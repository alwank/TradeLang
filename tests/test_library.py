import asyncio
import json
import shutil
import threading
from pathlib import Path
from tempfile import mkdtemp
from uuid import uuid4

import httpx
import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient
from openapi_spec_validator import validate
from test_contracts import parquet
from test_golden import FIX, META

from tradelang import data as candle_reader
from tradelang.api import create_app
from tradelang.api import upload as wire_upload
from tradelang.data import digest, hash_json
from tradelang.persistence import Library

BASE = "http://127.0.0.1:8000"
ORIGIN = {"Origin": "http://127.0.0.1:3000"}
STRATEGIES = "/api/v1/strategies"
DATASETS = "/api/v1/datasets"
UPLOAD = DATASETS + "/import"
CORE = (FIX / "core.csv").read_bytes()
SOURCE = (FIX / "core.trade").read_text()


def client(library, *, raise_errors=True):
    return TestClient(
        create_app(library=library),
        base_url=BASE,
        client=("127.0.0.1", 1234),
        raise_server_exceptions=raise_errors,
    )


def upload(http, raw=CORE, metadata=META, filename="core.csv", headers=ORIGIN):
    return http.post(
        UPLOAD,
        data={"metadata": json.dumps(metadata)},
        files={"file": (filename, raw)},
        headers=headers,
    )


def counts(library):
    with library.db.connect() as conn:
        return tuple(
            conn.execute(sa.select(sa.func.count()).select_from(table)).scalar_one()
            for table in (library.imports, library.contents)
        )


@pytest.fixture
def library(tmp_path):
    return Library(tmp_path / "app")


def test_strategy_revisions_soft_delete_and_reopen(library):
    legacy_source = "dsl 1\r\n" + SOURCE.replace("\n", "\r\n")
    with client(library) as c:
        rejected = c.post(STRATEGIES, json={"name": "Research", "source": "draft"})
        assert rejected.status_code == 403
        initial = c.post(
            STRATEGIES,
            json={"name": "Älpha 100%", "source": "draft\r\n"},
            headers=ORIGIN,
        )
        assert initial.status_code == 201
        path = initial.headers["Location"]
        tag = initial.headers["ETag"]
        assert initial.json()["source_hash"] == digest(b"draft\r\n")
        assert (
            c.get(STRATEGIES, params={"q": "ÄLPHA 100%"}).json()["items"][0]
            == initial.json()
        )
        assert c.get(STRATEGIES, params={"q": "%_"}).json()["items"] == []
        body = dict(name="Renamed", source="draft\r\n", expected_revision=1)
        assert c.put(path, json=body, headers=ORIGIN).status_code == 428
        renamed = c.put(path, json=body, headers={**ORIGIN, "If-Match": tag})
        assert renamed.status_code == 200 and renamed.json()["current_revision"] == 1
        renamed_tag = renamed.headers["ETag"]
        assert renamed_tag != tag
        assert (
            c.put(
                path,
                json={**body, "source": legacy_source},
                headers={**ORIGIN, "If-Match": tag},
            ).status_code
            == 409
        )
        assert (
            c.put(
                path,
                json={**body, "expected_revision": 2},
                headers={**ORIGIN, "If-Match": renamed_tag},
            ).status_code
            == 409
        )
        revised = c.put(
            path,
            json={**body, "source": legacy_source},
            headers={**ORIGIN, "If-Match": renamed_tag},
        )
        assert revised.status_code == 200 and revised.json()["current_revision"] == 2
        tag = revised.headers["ETag"]
        current_revision = c.get(path + "/revisions/2").json()
        assert current_revision["source"] == legacy_source
        assert current_revision["source_hash"] == digest(legacy_source.encode())
        revs = c.get(path + "/revisions", params={"limit": 1}).json()
        assert revs["items"] == [current_revision]
        older = c.get(
            path + "/revisions", params={"cursor": revs["next_cursor"]}
        ).json()
        assert (
            older["items"][0]["source"] == "draft\r\n"
            and older["snapshot"] == revs["snapshot"]
        )
        assert (
            c.get(STRATEGIES, params={"cursor": revs["next_cursor"]}).status_code == 400
        )
        assert c.delete(path, headers=ORIGIN).status_code == 428
        assert (
            c.delete(path, headers={**ORIGIN, "If-Match": renamed_tag}).status_code
            == 409
        )
        assert c.delete(path, headers={**ORIGIN, "If-Match": tag}).status_code == 204
    reopened = Library(library.root)
    with client(reopened) as c:
        assert c.get(path).status_code == 404
        stored_revision = c.get(path + "/revisions/2").json()
        assert stored_revision == current_revision
        response = c.post(
            STRATEGIES + "/validate",
            json={"source": stored_revision["source"]},
            headers=ORIGIN,
        )
        assert response.status_code == 200
        validation = response.json()
        assert validation["valid"]
        assert validation["source_hash"] == stored_revision["source_hash"]
        assert c.get(STRATEGIES).json()["items"] == []
    with reopened.db.connect() as conn:
        assert conn.exec_driver_sql("PRAGMA foreign_keys").scalar_one() == 1
        assert conn.exec_driver_sql("PRAGMA journal_mode").scalar_one() == "wal"
        assert (
            conn.exec_driver_sql("SELECT version_num FROM alembic_version").scalar_one()
            == "003_run_presets"
        )


@pytest.mark.parametrize("first_edit", ["rename", "source"])
def test_simultaneous_strategy_updates_are_compare_and_swap(library, first_edit):
    with client(library) as c:
        initial = c.post(
            STRATEGIES, json={"name": "Research", "source": "draft"}, headers=ORIGIN
        )
    path, tag = initial.headers["Location"], initial.headers["ETag"]
    app = create_app(library=library)

    async def race():
        transport = httpx.ASGITransport(app=app, client=("127.0.0.1", 1234))
        async with httpx.AsyncClient(
            transport=transport, base_url=BASE, headers={**ORIGIN, "If-Match": tag}
        ) as c:
            bodies = [
                dict(name="Named", source="draft", expected_revision=1),
                dict(name="Research", source=SOURCE, expected_revision=1),
            ]
            if first_edit == "source":
                bodies.reverse()
            return await asyncio.gather(*(c.put(path, json=b) for b in bodies))

    result = asyncio.run(race())
    assert sorted(r.status_code for r in result) == [200, 409]
    assert library.strategy(path.rsplit("/", 1)[-1]) == next(
        r.json() for r in result if r.status_code == 200
    )


def test_import_exact_aliases_formats_and_validation(library, tmp_path):
    formatted = tmp_path / "core.parquet"
    parquet(FIX / "core.csv", formatted)
    with client(library) as c:
        first = upload(c)
        assert first.status_code == 201 and first.json()["deduplicated"] is False
        original = first.json()["dataset"]
        assert counts(library) == (1, 1)
        defaults = {
            k: META[k]
            for k in reversed(META)
            if k not in {"gap_policy", "schema_version"}
        }
        exact = upload(c, metadata=defaults, filename="../renamed.csv")
        assert exact.status_code == 200 and exact.json() == {
            "dataset": original,
            "deduplicated": True,
        }
        variants = [upload(c, formatted.read_bytes(), filename="core.parquet")]
        for alias in ("24h", "1440m"):
            variants.append(upload(c, metadata={**META, "timeframe": alias}))
        equivalent = [r.json()["dataset"] for r in variants]
        assert all(
            r.status_code == 201 and r.json()["deduplicated"] is False for r in variants
        )
        assert counts(library) == (4, 1)
        assert len({d["id"] for d in [original, *equivalent]}) == 4
        assert {d["dataset_hash"] for d in equivalent} == {original["dataset_hash"]}
        assert {d["metadata"]["timeframe"] for d in equivalent} == {
            "1d",
            "24h",
            "1440m",
        }
        assert [row["row"] for row in original["preview"]] == [1, 2, 3]
        changed = upload(c, CORE.replace(b",120,30", b",121,30"))
        assert changed.status_code == 201 and counts(library) == (5, 2)
        assert len(list(library.datasets.glob("*/candles.parquet"))) == 2
        for selected in (original, equivalent[-1]):
            found = c.post(
                STRATEGIES + "/validate",
                json={"source": SOURCE, "dataset_id": selected["id"]},
                headers=ORIGIN,
            )
            assert found.status_code == 200 and found.json()["data_compatible"]
            assert (
                found.json()["resolved_window"]["first_execution_at"]
                == "2024-01-02T00:00:00Z"
            )
        incompatible = c.post(
            STRATEGIES + "/explain",
            json={
                "source": SOURCE.replace("TESTUSDT", "OTHERUSDT"),
                "dataset_id": original["id"],
            },
            headers=ORIGIN,
        )
        assert incompatible.status_code == 200 and incompatible.json()["valid"] is False
        assert (
            c.post(
                STRATEGIES + "/explain",
                json={"source": SOURCE, "dataset_id": str(uuid4())},
                headers=ORIGIN,
            ).status_code
            == 404
        )
        without = c.post(
            STRATEGIES + "/explain", json={"source": SOURCE}, headers=ORIGIN
        )
        assert without.json()["valid"] and without.json()["resolved_window"] is None
        listing = c.get(DATASETS).json()["items"]
        assert len(listing) == 5 and all("preview" not in d for d in listing)
        validate(c.get("/openapi.json").json())
    with library.db.connect() as conn:
        record = (
            conn.execute(
                sa.select(library.imports).where(library.imports.c.id == original["id"])
            )
            .mappings()
            .one()
        )
        assert record["raw_source_hash"] == digest(CORE)
        assert record["import_key"] == hash_json(
            dict(
                dataset_hash=original["dataset_hash"],
                raw_source_hash=digest(CORE),
                metadata=META,
            )
        )
    with client(Library(library.root)) as c:
        assert c.get(DATASETS + "/" + original["id"]).json() == original


@pytest.mark.parametrize("first", ["allow", "reject"])
def test_gap_policy_import_order_and_failed_strict_retry(library, first):
    other = "reject" if first == "allow" else "allow"
    with client(library) as c:
        before = upload(c, metadata={**META, "gap_policy": first})
        after = upload(c, metadata={**META, "gap_policy": other})
        assert before.status_code == after.status_code == 201
        a, b = (r.json()["dataset"] for r in (before, after))
        assert a["id"] != b["id"] and a["dataset_hash"] == b["dataset_hash"]
        assert (a["metadata"]["gap_policy"], b["metadata"]["gap_policy"]) == (
            first,
            other,
        )
        assert counts(library) == (2, 1)
        gapped = b"\n".join(CORE.splitlines()[0:2] + CORE.splitlines()[3:])
        allowed = upload(c, gapped, metadata={**META, "gap_policy": "allow"})
        assert (
            allowed.status_code == 201
            and allowed.json()["dataset"]["quality"]["missing_bar_count"] == 1
        )
        invalid = upload(c, gapped)
        assert (
            invalid.status_code == 422
            and invalid.json()["error"]["diagnostics"][0]["data_row"] == 2
        )
        assert counts(library) == (3, 2)


def test_two_concurrent_first_imports_reuse_one_uuid(library, monkeypatch):
    app = create_app(library=library)
    manually_release = asyncio.Event()
    entered = asyncio.Event()
    from tradelang.api import library as transport

    real_receive = transport.receive_upload

    async def hold_first(*args):
        entered.set()
        await manually_release.wait()
        return await real_receive(*args)

    monkeypatch.setattr(transport, "receive_upload", hold_first)

    async def race():
        asgi = httpx.ASGITransport(app=app, client=("127.0.0.1", 1234))
        async with httpx.AsyncClient(transport=asgi, base_url=BASE) as c:
            one = asyncio.create_task(upload(c))
            await asyncio.wait_for(entered.wait(), 2)
            two = asyncio.create_task(upload(c))
            await asyncio.sleep(0)
            three = await upload(c)
            assert three.status_code == 429
            manually_release.set()
            return await asyncio.gather(one, two)

    first, second = asyncio.run(race())
    assert (first.status_code, second.status_code) == (201, 200)
    assert first.json()["dataset"] == second.json()["dataset"]
    assert second.json()["deduplicated"] is True and counts(library) == (1, 1)
    assert len(list(library.datasets.glob("*/candles.parquet"))) == 1


def test_import_validation_streaming_limits_and_cleanup(library, monkeypatch):
    with client(library) as c:
        assert upload(c, headers={}).status_code == 403
        assert upload(c, filename="wrong.parquet").status_code == 415
        assert (
            c.post(
                UPLOAD,
                content=b"--wrong",
                headers={**ORIGIN, "Content-Type": "multipart/form-data; boundary=abc"},
            ).status_code
            == 400
        )
        assert (
            c.post(
                UPLOAD,
                data={"metadata": "{"},
                files={"file": ("core.csv", CORE)},
                headers=ORIGIN,
            ).status_code
            == 400
        )
        assert upload(c, metadata={**META, "arbitrary": True}).status_code == 422
        with monkeypatch.context() as bounds:
            bounds.setattr(candle_reader, "MAX_ROWS", 2)
            assert upload(c).status_code == 413
        monkeypatch.setattr(wire_upload, "MAX_FILE", 10)
        assert upload(c).status_code == 413
        assert counts(library) == (0, 0) and not list(library.staging.iterdir())


def test_import_disconnect_leaves_no_stage_or_row(library):
    app = create_app(library=library)

    async def disconnected():
        messages = iter(
            [
                {
                    "type": "http.request",
                    "body": b'--abc\r\nContent-Disposition: form-data; name="file"; filename="partial.csv"\r\n\r\n123',
                    "more_body": True,
                },
                {"type": "http.disconnect"},
            ]
        )
        sent = []

        async def receive():
            return next(messages)

        async def send(message):
            sent.append(message)

        await app(
            {
                "type": "http",
                "scheme": "http",
                "http_version": "1.1",
                "method": "POST",
                "path": UPLOAD,
                "query_string": b"",
                "client": ("127.0.0.1", 1234),
                "headers": [
                    (b"host", b"127.0.0.1:8000"),
                    (b"origin", ORIGIN["Origin"].encode()),
                    (b"content-type", b"multipart/form-data; boundary=abc"),
                ],
            },
            receive,
            send,
        )
        assert sent[0]["status"] == 400

    asyncio.run(disconnected())
    assert counts(library) == (0, 0) and not list(library.staging.iterdir())


def test_total_import_timeout_during_normalization(library, monkeypatch):
    from tradelang.api import library as transport

    entered = threading.Event()
    resume = threading.Event()
    normalize = library.stage_content

    def blocked(*args):
        entered.set()
        assert resume.wait(3)
        return normalize(*args)

    monkeypatch.setattr(transport, "TOTAL_SECONDS", 0.15)
    monkeypatch.setattr(library, "stage_content", blocked)

    async def attempt():
        app = create_app(library=library)
        asgi = httpx.ASGITransport(app=app, client=("127.0.0.1", 1234))
        async with httpx.AsyncClient(transport=asgi, base_url=BASE) as c:
            try:
                response = await asyncio.wait_for(upload(c), 1)
                assert entered.is_set()
                assert response.status_code == 422
                assert response.json()["error"]["code"] == "E_IMPORT_TIMEOUT"
                assert counts(library) == (0, 0)
                assert list(library.staging.iterdir())
            finally:
                resume.set()
            await asyncio.wait_for(wait_for_cleanup(), 2)

    async def wait_for_cleanup():
        while list(library.staging.iterdir()):
            await asyncio.sleep(0.01)

    asyncio.run(attempt())
    assert counts(library) == (0, 0) and not list(
        library.datasets.glob("*/candles.parquet")
    )


def test_import_restart_rollback_and_post_commit_retry(library, monkeypatch):
    def fail_insert(conn, cursor, statement, parameters, context, executemany):
        if statement.startswith("INSERT INTO dataset_imports"):
            raise sa.exc.SQLAlchemyError("injected after rename")

    with client(library, raise_errors=False) as c:
        sa.event.listen(library.db, "before_cursor_execute", fail_insert)
        assert upload(c).status_code == 500
        sa.event.remove(library.db, "before_cursor_execute", fail_insert)
        assert counts(library) == (0, 0) and not list(
            library.datasets.glob("*/candles.parquet")
        )
        real_describe = library.describe_dataset

        def lost_response(*args, **kwargs):
            raise RuntimeError("injected after commit")

        monkeypatch.setattr(library, "describe_dataset", lost_response)
        assert upload(c).status_code == 500 and counts(library) == (1, 1)
        monkeypatch.setattr(library, "describe_dataset", real_describe)
        listed = c.get(DATASETS).json()["items"][0]

    path = library.content_path(listed["dataset_hash"])
    leftover = Path(mkdtemp(prefix="import-", dir=library.staging))
    (leftover / "partial").write_bytes(b"crash debris")
    orphan = library.content_path("e" * 64)
    orphan.parent.mkdir()
    shutil.copyfile(path, orphan)
    reopened = Library(library.root)
    reopened.recover()
    assert not orphan.exists() and path.is_file() and not leftover.exists()
    with client(reopened) as c:
        retry = upload(c)
        assert (
            retry.status_code == 200 and retry.json()["dataset"]["id"] == listed["id"]
        )
        assert retry.json()["deduplicated"] is True and counts(reopened) == (1, 1)
        backup = path.with_suffix(".backup")
        path.replace(backup)
        path.symlink_to(backup)
        assert c.get(DATASETS).json()["items"] == []
        unsafe = c.get(DATASETS + "/" + listed["id"])
        assert unsafe.status_code == 500 and str(backup) not in unsafe.text
