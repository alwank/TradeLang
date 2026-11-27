"""Exercise the supervised worker and the API's durable run boundaries."""

import json
import subprocess
import time
from pathlib import Path
from uuid import uuid4

import httpx
import pyarrow as pa
import pyarrow.parquet as pq
import pytest
from fastapi.testclient import TestClient
from test_library import BASE, CORE, META, ORIGIN, SOURCE
from test_supervisor import local_app

from tradelang.api import create_app
from tradelang.api.run_results import comparison
from tradelang.persistence import Library
from tradelang.persistence.runs import Runs

RUNS = "/api/v1/backtests"


def test_portfolio_queue_pins_asset_revisions_and_replays(tmp_path):
    root = tmp_path / "library"
    fixture = Path("docs/fixtures/portfolio")
    library = Library(root)
    with TestClient(
        create_app(library=library, worker_available=lambda: True),
        base_url=BASE,
        client=("127.0.0.1", 1234),
    ) as client:
        selections = {}
        for name in ("alpha", "beta"):
            imported = client.post(
                "/api/v1/datasets/import",
                headers=ORIGIN,
                files={
                    "file": (f"{name}.csv", (fixture / f"{name}.csv").read_bytes()),
                    "metadata": (None, (fixture / f"{name}-metadata.json").read_text()),
                },
            )
            assert imported.status_code in (200, 201), imported.text
            strategy = client.post(
                "/api/v1/strategies",
                headers=ORIGIN,
                json={
                    "name": name,
                    "source": (fixture / f"{name}.trade").read_text(),
                },
            )
            assert strategy.status_code == 201
            selections[name] = {
                "strategy_id": strategy.json()["id"],
                "strategy_revision": 1,
                "dataset_id": imported.json()["dataset"]["id"],
            }
        portfolio = client.post(
            "/api/v1/strategies",
            headers=ORIGIN,
            json={
                "name": "Portfolio",
                "source": (fixture / "priority.trade").read_text(),
            },
        )
        body = {
            "strategy_id": portfolio.json()["id"],
            "strategy_revision": 1,
            "portfolio_assets": selections,
        }
        validated = client.post(
            "/api/v1/strategies/validate",
            headers=ORIGIN,
            json={
                "source": portfolio.json()["current_source"],
                "portfolio_assets": selections,
            },
        )
        assert (
            validated.status_code == 200 and validated.json()["data_compatible"] is True
        ), validated.text
        submitted = client.post(RUNS, headers=ORIGIN, json=body)
        assert submitted.status_code == 202, submitted.text
        run = submitted.json()
        url = submitted.headers["Location"]
        alpha = client.get(f"/api/v1/strategies/{selections['alpha']['strategy_id']}")
        updated = client.put(
            f"/api/v1/strategies/{selections['alpha']['strategy_id']}",
            headers={**ORIGIN, "If-Match": alpha.headers["ETag"]},
            json={
                "name": "alpha",
                "expected_revision": 1,
                "source": (fixture / "alpha.trade")
                .read_text()
                .replace("750 USD", "100 USD"),
            },
        )
        assert updated.status_code == 200, updated.text
        selections["alpha"]["strategy_revision"] = 2
        second = client.post(RUNS, headers=ORIGIN, json=body)
        assert second.status_code == 202, second.text
        second_url = second.headers["Location"]
        listed = client.get(
            RUNS, params={"dataset_id": selections["beta"]["dataset_id"]}
        )
        assert run["id"] in [item["id"] for item in listed.json()["items"]]
    library.db.dispose()
    with (
        local_app(root, tmp_path / "portfolio-worker.log") as service,
        httpx.Client(base_url=service.url) as client,
    ):
        finished = finish(client, url)
        assert finished["status"] == "succeeded", finished
        assert finished["summary"]["final_equity"] == 1150
        equity = client.get(f"{url}/equity")
        assert equity.status_code == 200, equity.text
        assert equity.json()["items"][-1]["equity"] == 1150
        assert client.get(f"{url}/trades").status_code == 200
        assert (
            finished["configuration"]["portfolio_assets"][0]["strategy_revision"] == 1
        )
        second_finished = finish(client, second_url)
        assert second_finished["status"] == "succeeded", second_finished
        compared = client.get(
            f"{RUNS}/compare",
            params={"ids": f"{run['id']},{second.json()['id']}"},
        )
        assert compared.status_code == 200, compared.text
        comparison_result = compared.json()
        assert comparison_result["alignment"] == "exact"
        assert [point["phase"] for point in comparison_result["runs"][0]["curve"]][
            :2
        ] == ["initial", "mark"]
        assert comparison_result["runs"][0]["curve"][-1]["value"] == pytest.approx(115)
        assert (
            comparison_result["common_benchmark"]["pairs"][0]["reason"]
            == "portfolio_reference_unavailable"
        )
        bar = client.get(f"{url}/bars/1", params={"asset": "beta"})
        assert bar.status_code == 200 and bar.json()["available"], bar.text
        assert any(
            item["reason"] == "insufficient_cash" for item in bar.json()["events"]
        )
    bundle = root / "runs" / run["id"]
    replay = subprocess.run(
        [
            "tradelang",
            "backtest",
            str(bundle / "source.trade"),
            "--run-config",
            str(bundle / "run-config.json"),
            "--out",
            str(tmp_path / "replay"),
            "--json",
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    result = json.loads(replay.stdout)["result"]
    assert result["run_fingerprint"] == finished["run_fingerprint"]
    assert result["result_digest"] == finished["result_digest"]


def request_data(client, source=SOURCE):
    dataset = client.post(
        "/api/v1/datasets/import",
        headers=ORIGIN,
        files={"file": ("core.csv", CORE), "metadata": (None, json.dumps(META))},
    )
    assert dataset.status_code in (200, 201), dataset.text
    entry = client.post(
        "/api/v1/strategies", headers=ORIGIN, json={"name": "Ledger", "source": source}
    )
    assert entry.status_code == 201, entry.text
    return entry.json(), dataset.json()["dataset"], entry.headers["ETag"]


def submit(client, strategy, dataset, key=None, *, parameters=None):
    body = {
        "strategy_id": strategy["id"],
        "dataset_id": dataset["id"],
        "strategy_revision": strategy["current_revision"],
    }
    if parameters is not None:
        body["parameters"] = parameters
    return client.post(
        RUNS, headers={**ORIGIN, "Idempotency-Key": key or str(uuid4())}, json=body
    )


def finish(client, url):
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        response = client.get(url)
        assert response.status_code == 200, response.text
        row = response.json()
        if row["status"] not in {"queued", "running"}:
            return row
        time.sleep(0.05)
    raise AssertionError(f"Run did not finish: {url}")


def test_preset_snapshot_survives_edit_and_replays_in_cli(tmp_path):
    library_root = tmp_path / "library"
    library = Library(library_root)
    source = "tradelang 2\n" + SOURCE.replace(
        "entry:", "param period: count = 2 range [1 count, 3 count]\nentry:"
    ).replace("when true", "when close >= SMA(period)").replace(
        "close >= 112 price", "false"
    )
    with TestClient(
        create_app(library=library, worker_available=lambda: True),
        base_url=BASE,
        client=("127.0.0.1", 1234),
    ) as client:
        strategy, dataset, _ = request_data(client, source)
        fields = dict(
            name="Fee experiment",
            dataset_id=dataset["id"],
            settings={
                "capital": 2000,
                "from_date": "2024-01-02",
                "fee_bps": 5,
                "parameters": {"period": 2},
            },
        )
        created = client.post("/api/v1/run-presets", headers=ORIGIN, json=fields)
        assert created.status_code == 201, created.text
        preset = created.json()
        override = dict(fee_bps=15, slippage_bps=4, parameters={"period": 1})
        selected = dict(preset_id=preset["id"], preset_revision=1, settings=override)
        checked = client.post(
            "/api/v1/strategies/validate",
            headers=ORIGIN,
            json={"source": source, **selected},
        )
        assert checked.status_code == 200, checked.text
        validation = checked.json()
        assert validation["data_compatible"] is True
        assert validation["spec"]["backtest"]["capital"] == 1000
        effective = validation["run_configuration"]
        assert effective["capital"] == 2000
        assert (
            effective["from_date"] == "2024-01-02"
            and effective["to_date"] == "2024-01-03"
        )
        assert effective["fee_rate"] == 0.0015 and effective["slippage_rate"] == 0.0004
        assert effective["parameters"] == {"period": 1}
        assert effective["origins"] == {
            "from_date": "preset",
            "to_date": "source",
            "capital": "preset",
            "fee_bps": "override",
            "slippage_bps": "override",
            "dataset_id": "preset",
            "gap_policy": "dataset",
            "parameters.period": "override",
        }
        body = {"strategy_id": strategy["id"], "strategy_revision": 1, **selected}
        invalid_date = {**body, "settings": {"to_date": "2024-01-01"}}
        before = client.post(RUNS, headers=ORIGIN, json=invalid_date)
        assert (
            before.status_code == 422
            and before.json()["error"]["code"] == "E209_RUN_CONFIG"
        )
        invalid_fee = {**body, "settings": {"fee_bps": 10000}}
        assert (
            client.post(RUNS, headers=ORIGIN, json=invalid_fee).json()["error"]["code"]
            == "E209_RUN_CONFIG"
        )
        key = str(uuid4())
        headers = {**ORIGIN, "Idempotency-Key": key}
        submitted = client.post(RUNS, headers=headers, json=body)
        assert submitted.status_code == 202, submitted.text
        queued = submitted.json()
        url = submitted.headers["Location"]
        assert queued["dataset_id"] == dataset["id"]
        assert queued["configuration"]["effective"] == effective
        assert queued["status"] == "queued"
        update = {**fields, "settings": {"capital": 4000}, "expected_revision": 1}
        revised = client.put(created.headers["Location"], headers=ORIGIN, json=update)
        assert revised.status_code == 200 and revised.json()["revision"] == 2
        assert (
            client.put(
                created.headers["Location"], headers=ORIGIN, json=update
            ).status_code
            == 409
        )
        assert client.post(RUNS, headers=ORIGIN, json=body).status_code == 409
        repeated = client.post(RUNS, headers=headers, json=body)
        assert repeated.status_code == 202 and repeated.headers["Location"] == url
    library.db.dispose()

    with (
        local_app(library_root, tmp_path / "worker.log") as service,
        httpx.Client(base_url=service.url) as client,
    ):
        completed = finish(client, url)
        assert completed["status"] == "succeeded", completed.get("error")
        assert completed["configuration"]["preset"]["revision"] == 1
        assert completed["configuration"]["effective"] == effective
        assert completed["summary"]["metrics"]["total_fees"] > 0
        decision = client.get(f"{url}/bars/1").json()
        assert decision["available"] and decision["entry"]["predicate"] is True
        exported = client.get(f"{url}/artifacts/run-config.json")
        assert (
            exported.status_code == 200
            and exported.json()["settings"]["capital"] == 2000
        )

    bundle = library_root / "runs" / queued["id"]
    manifest = json.loads((bundle / "manifest.json").read_text())
    assert (
        manifest["effective_configuration"] == effective
        and manifest["run_settings"]["fee_bps"] == 15
    )
    cli = subprocess.run(
        [
            "tradelang",
            "validate",
            str(bundle / "source.trade"),
            "--data",
            str(bundle / exported.json()["data"]),
            "--metadata",
            str(bundle / "metadata.json"),
            "--from-date",
            "2024-01-02",
            "--capital",
            "2000",
            "--fee-bps",
            "15",
            "--slippage-bps",
            "4",
            "--param",
            "period=1",
            "--json",
        ],
        check=True,
        timeout=15,
        capture_output=True,
        text=True,
    )
    checked_cli = json.loads(cli.stdout)["result"]
    assert checked_cli["spec_hash"] == validation["spec_hash"]
    assert {
        key: val
        for key, val in checked_cli["run_configuration"].items()
        if key != "origins"
    } == {key: val for key, val in effective.items() if key != "origins"}
    replay = tmp_path / "replay"
    subprocess.run(
        [
            "tradelang",
            "backtest",
            str(bundle / "source.trade"),
            "--run-config",
            str(bundle / "run-config.json"),
            "--out",
            str(replay),
        ],
        check=True,
        timeout=15,
    )
    repeated_manifest = json.loads((replay / "manifest.json").read_text())
    assert repeated_manifest["run_fingerprint"] == completed["run_fingerprint"]
    assert repeated_manifest["result_digest"] == completed["result_digest"]


def test_v2_worker_and_bundle_replay_resolve_same_parameters(tmp_path):
    source = "tradelang 2\n" + SOURCE.replace(
        "entry:", "param limit: price = 115 price range [100 price, 130 price]\nentry:"
    ).replace("close >= 112 price", "close >= limit")
    library = tmp_path / "library"
    with (
        local_app(library, tmp_path / "worker.log") as service,
        httpx.Client(base_url=service.url) as client,
    ):
        strategy, dataset, _ = request_data(client, source)
        invalid = submit(client, strategy, dataset, parameters={"limit": 90})
        assert (
            invalid.status_code == 422
            and invalid.json()["error"]["code"] == "E208_PARAMETER"
        )
        accepted = submit(client, strategy, dataset, parameters={"limit": 110})
        assert accepted.status_code == 202, accepted.text
        url = accepted.headers["Location"]
        run = finish(client, url)
        assert run["status"] == "succeeded", run.get("error")
        assert run["configuration"]["parameters"] == {"limit": 110}
        assert run["configuration"]["semantics_version"] == "2.0.0"
        assert client.get(f"{url}/bars/1").json()["exit"]["predicate"] is True
        assert len(client.get(f"{url}/trades").json()["items"]) == 1

    bundle = library / "runs" / run["id"]
    manifest = json.loads((bundle / "manifest.json").read_text())
    assert (bundle / "source.trade").read_bytes() == source.encode()
    assert manifest["parameter_overrides"] == {"limit": 110}
    output = tmp_path / "replay"
    subprocess.run(
        [
            "tradelang",
            "backtest",
            str(bundle / "source.trade"),
            "--data",
            str(next(bundle.glob("input.*"))),
            "--metadata",
            str(bundle / "metadata.json"),
            "--param",
            f"limit={manifest['parameter_overrides']['limit']}",
            "--out",
            str(output),
        ],
        check=True,
        timeout=15,
    )
    replayed = json.loads((output / "manifest.json").read_text())
    assert (
        replayed["result_digest"] == manifest["result_digest"] == run["result_digest"]
    )
    assert (
        replayed["run_fingerprint"]
        == manifest["run_fingerprint"]
        == run["run_fingerprint"]
    )


def test_run_snapshot_results_and_parity_survive_restart(tmp_path):
    library = tmp_path / "library"
    key = str(uuid4())
    with (
        local_app(library, tmp_path / "worker.log") as service,
        httpx.Client(base_url=service.url) as client,
    ):
        strategy, dataset, etag = request_data(client)
        accepted = submit(client, strategy, dataset, key)
        assert accepted.status_code == 202, accepted.text
        url = accepted.headers["Location"]
        edited = client.put(
            f"/api/v1/strategies/{strategy['id']}",
            headers={**ORIGIN, "If-Match": etag},
            json={"name": "Renamed", "source": "invalid draft", "expected_revision": 1},
        )
        assert edited.status_code == 200
        retry = submit(client, strategy, dataset, key)
        assert retry.status_code == 202 and retry.headers["Location"] == url
        assert submit(client, strategy, dataset).status_code == 409
        assert submit(client, edited.json(), dataset).status_code == 422

        run = finish(client, url)
        assert run["status"] == "succeeded", run.get("error")
        assert run["strategy_revision"] == 1 and run["strategy_name"] == "Ledger"
        assert run["source_hash"] == strategy["source_hash"]
        assert run["progress"]["completed_bars"] == run["progress"]["total_bars"] == 3
        assert client.get(f"{url}/artifacts/source.trade").content == SOURCE.encode()
        assert client.get(f"{url}/artifacts/input.parquet").status_code == 404
        decision = client.get(f"{url}/bars/0").json()
        assert decision["available"]
        assert decision["entry"]["predicate"] is True
        assert decision["entry"]["outcome"] == "order_queued"
        assert decision["exit"]["outcome"] == "false"
        assert decision["entry"]["expression"]["samples"][0]["value"] is True
        assert decision["events"][0]["order_id"] == "O00000001"
        fill = client.get(f"{url}/bars/1").json()
        assert fill["entry"]["outcome"] == "holding"
        assert fill["entry_fill"]["cash"] == 1000
        assert fill["entry_fill"]["signal_bar"] == 0
        assert fill["entry_fill"]["expression"]["samples"][0]["bar_index"] == 0
        assert fill["events"][0]["fill_id"] == "F00000001"
        after_exit = client.get(f"{url}/bars/2").json()
        assert after_exit["entry"]["outcome"] == "post_exit"
        assert after_exit["entry"]["evaluated"] is False
        assert after_exit["exit"]["predicate"] is None
        assert client.get(f"{url}/bars/3").status_code == 422
        manifest_path = library / "runs" / run["id"] / "manifest.json"
        saved_manifest = manifest_path.read_text()
        historical = json.loads(saved_manifest)
        assert historical["decision_counts"]["post_exit"] == 1
        try:
            manifest_path.write_text(
                json.dumps({**historical, "environment_hash": "0" * 64})
            )
            evidence = client.get(f"{url}/bars/0").json()
            assert evidence["reason"] == "inspection_runtime_mismatch"
            assert evidence["entry"]["outcome"] == "order_queued"
            assert evidence["entry"]["expression"] is None
            historical.pop("decision_inspection")
            manifest_path.write_text(json.dumps(historical))
            assert (
                client.get(f"{url}/bars/0").json()["reason"]
                == "inspection_not_recorded"
            )
            assert client.get(f"{url}/equity").status_code == 200
        finally:
            manifest_path.write_text(saved_manifest)

        original = client.get(f"{url}/equity", params={"mode": "full", "limit": 2})
        equity = original.json()
        assert (
            client.get(
                f"{url}/equity",
                params={"mode": "full", "limit": 2},
                headers={"If-None-Match": original.headers["ETag"]},
            ).status_code
            == 304
        )
        assert [item["phase"] for item in equity["items"]] == ["initial", "close"]
        cursor = equity["next_cursor"]
        sequel = client.get(
            f"{url}/equity", params={"cursor": cursor, "limit": 2}
        ).json()
        assert [item["index"] for item in sequel["items"]] == [2, 3]
        assert (
            client.get(
                f"{url}/equity", params={"cursor": cursor, "from_index": 1}
            ).status_code
            == 400
        )
        trade = client.get(f"{url}/trades").json()["items"][0]
        assert trade["entry_price"] == 110 and trade["exit_price"] == 120
        events = client.get(
            f"{url}/events", params={"trade_id": trade["trade_id"]}
        ).json()["items"]
        assert [
            event["time_precision"] for event in events if event["kind"] == "fill"
        ] == ["open", "open"]

        other, _, _ = request_data(client, SOURCE.replace("when true", "when false"))
        second = submit(client, other, dataset)
        second_url = second.headers["Location"]
        assert finish(client, second_url)["status"] == "succeeded"
        compare = client.get(
            RUNS + "/compare", params={"ids": f"{run['id']},{second.json()['id']}"}
        ).json()
        assert compare["alignment"] == "exact"
        assert all(item["curve"][0]["value"] == 100 for item in compare["runs"])
        assert compare["runs"][1]["metrics"]["closed_trades"] == 0
        quiet = client.get(f"{second_url}/bars/0").json()
        assert quiet["entry"]["outcome"] == "false"
        assert quiet["events"] == []

        rejected, _, _ = request_data(
            client, SOURCE.replace("100% of equity", "5000 USDT")
        )
        rejected_run = submit(client, rejected, dataset).headers["Location"]
        assert finish(client, rejected_run)["status"] == "succeeded"
        rejected_bar = client.get(f"{rejected_run}/bars/1").json()
        assert rejected_bar["entry_fill"]["budget"] == 5000
        assert rejected_bar["entry_fill"]["cash"] == 1000
        assert rejected_bar["events"][0]["reason"] == "invalid_budget"

        blocked, _, _ = request_data(
            client, SOURCE.replace("close >= 112 price", "true", 1)
        )
        blocked_run = submit(client, blocked, dataset).headers["Location"]
        assert finish(client, blocked_run)["status"] == "succeeded"
        blocked_bar = client.get(f"{blocked_run}/bars/0").json()
        assert blocked_bar["entry"]["predicate"] is True
        assert blocked_bar["entry"]["outcome"] == "exit_priority"

    output = tmp_path / "cli"
    source = tmp_path / "cli.trade"
    source.write_text(SOURCE)
    candles = tmp_path / "cli.csv"
    candles.write_bytes(CORE)
    metadata = tmp_path / "cli.json"
    metadata.write_text(json.dumps(META))
    subprocess.run(
        [
            "tradelang",
            "backtest",
            str(source),
            "--data",
            str(candles),
            "--metadata",
            str(metadata),
            "--out",
            str(output),
        ],
        check=True,
        timeout=15,
    )
    manifest = json.loads((output / "manifest.json").read_text())
    assert run["result_digest"] == manifest["result_digest"]
    assert run["run_fingerprint"] == manifest["run_fingerprint"]
    with (
        local_app(library, tmp_path / "restart.log") as service,
        httpx.Client(base_url=service.url) as client,
    ):
        assert client.get(url).json() == run
        assert (
            client.get(f"{url}/artifacts/manifest.json").json()["run_id"] == run["id"]
        )
        assert (
            client.get(f"{url}/artifacts/manifest.json").json()["result_digest"]
            == manifest["result_digest"]
        )


def test_cancelled_jobs_and_orphaned_artifacts_remain_terminal(tmp_path):
    library = Library(tmp_path)
    runs = Runs(library)
    with TestClient(
        create_app(library=library, worker_available=lambda: True),
        base_url=BASE,
        client=("127.0.0.1", 1234),
    ) as client:
        strategy, dataset, _ = request_data(client)
        queued = submit(client, strategy, dataset)
        url = queued.headers["Location"]
        assert client.get("/health").json()["queue_depth"] == 1
        assert (
            client.post(url + "/cancel", headers=ORIGIN, json={}).json()["status"]
            == "cancelled"
        )
        assert runs.claim() is None

        active = submit(client, strategy, dataset)
        url = active.headers["Location"]
        row = runs.claim()
        assert row["status"] == "running"
        assert client.post(url + "/cancel", headers=ORIGIN, json={}).status_code == 202
        with library.writer() as connection:
            runs.finish(
                connection, runs.row(row["id"], connection), result={"summary": {}}
            )
        assert client.get(url).json()["status"] == "cancelled"
        assert client.get(url + "/equity").status_code == 409

        interrupted = submit(client, strategy, dataset)
        url = interrupted.headers["Location"]
        row = runs.claim()
        orphan = runs.directory(row["id"])
        orphan.mkdir()
        (orphan / "manifest.json").write_text("{}")
        with library.writer() as connection:
            connection.execute(
                runs.table.update()
                .where(runs.table.c.id == row["id"])
                .values(worker_pid=None)
            )
        assert runs.claim() is None
        assert not orphan.exists()
        assert client.get(url).json()["error"]["code"] == "E_INTERRUPTED"


def test_comparison_uses_original_capital_and_exact_time_and_phase(tmp_path):
    class FixtureResult:
        def __init__(self, name, first, capital, equities):
            configuration = dict(
                market="TESTUSDT",
                currency="USDT",
                timeframe_seconds=86400,
                calendar="24x7",
                semantics_version="1.1.0",
                dataset_hash="a" * 64,
                profile_dataset_hash=None,
                first_open=f"2024-01-{first:02}T00:00:00Z",
                last_close_at=f"2024-01-{first + len(equities) - 1:02}T00:00:00Z",
                capital=capital,
                fee_rate=0,
                slippage_rate=0,
                gap_policy="reject",
                engine_version="0.1.0",
            )
            self.row = {
                "id": str(uuid4()),
                "strategy_id": str(uuid4()),
                "snapshot": {
                    "configuration": configuration,
                    "strategy_name": name,
                    "strategy_revision": 1,
                    "source_hash": "b" * 64,
                    "dataset_hash": "a" * 64,
                },
                "summary": {
                    "metrics": {"closed_trades": 1},
                    "final_equity": equities[-1],
                    "benchmark_entry_at": configuration["first_open"],
                },
            }
            self.path = tmp_path / f"{name}.parquet"
            pq.write_table(
                pa.table(
                    {
                        "index": range(len(equities)),
                        "timestamp": [
                            f"2024-01-{first + offset:02}T00:00:00Z"
                            for offset in range(len(equities))
                        ],
                        "phase": ["initial"] + ["close"] * (len(equities) - 1),
                        "equity": equities,
                        "drawdown": [0.0] * len(equities),
                    }
                ),
                self.path,
            )

        def file(self, name):
            assert name == "equity.parquet"
            return self.path

    first = FixtureResult("first", 1, 1000, [1000, 1000, 1100, 1200])
    second = FixtureResult("second", 2, 2000, [2000, 3000, 4000])
    overlapping = comparison([first, second])
    assert overlapping["alignment"] == "intersection"
    assert overlapping["display_window"]["from"] == "2024-01-03T00:00:00Z"
    for run, expected in zip(overlapping["runs"], [[110, 120], [150, 200]]):
        assert [point["value"] for point in run["curve"]] == pytest.approx(expected)
        assert run["metrics"]["closed_trades"] == 1

    remote = FixtureResult("later", 10, 1000, [1000, 1100])
    disjoint = comparison([first, remote])
    assert disjoint["alignment"] == "unavailable" and not disjoint["runs"][0]["curve"]
    assert disjoint["common_benchmark"]["pairs"][0]["reason"] == "no_overlap"
    second.row["snapshot"]["configuration"]["currency"] = "USD"
    incompatible = comparison([first, second])
    assert incompatible["alignment"] == "unavailable"
    assert any(
        record["field"] == "currency" and record["severity"] == "incompatible"
        for record in incompatible["differences"]
    )


def test_common_start_benchmark_preserves_compatible_pair_and_marks_open_holdings(
    tmp_path,
):
    with (
        local_app(tmp_path / "library", tmp_path / "worker.log") as service,
        httpx.Client(base_url=service.url) as client,
    ):
        source = SOURCE.replace("when close >= 112 price", "when false").replace(
            "fee 0 bps", "fee 10 bps"
        )
        quick, dataset, _ = request_data(client, source)
        slow_source = (
            source.replace("entry:", "let mean = SMA(2)\nentry:")
            .replace("when true", "when close >= mean")
            .replace("capital 1000", "capital 2000")
        )
        slow, _, _ = request_data(client, slow_source)
        costly, _, _ = request_data(client, source.replace("fee 10 bps", "fee 20 bps"))
        different = client.post(
            "/api/v1/datasets/import",
            headers=ORIGIN,
            files={
                "file": ("different.csv", CORE.replace(b"100,10", b"100,91")),
                "metadata": (None, json.dumps(META)),
            },
        ).json()["dataset"]
        runs = []
        for strategy, selected in (
            (quick, dataset),
            (slow, dataset),
            (costly, dataset),
            (quick, different),
        ):
            accepted = submit(client, strategy, selected)
            assert accepted.status_code == 202, accepted.text
            row = finish(client, accepted.headers["Location"])
            assert row["status"] == "succeeded", row["error"]
            runs.append(row)
        response = client.get(
            RUNS + "/compare", params={"ids": ",".join(row["id"] for row in runs)}
        )
        assert response.status_code == 200, response.text
        results = response.json()
        assert [row["benchmark_entry_at"] for row in results["runs"][:2]] == [
            "2024-01-02T00:00:00Z",
            "2024-01-03T00:00:00Z",
        ]
        benchmark = results["common_benchmark"]
        assert benchmark["policy"] == "common_start_hold_v1"
        (group,) = benchmark["cohorts"]
        assert group["run_ids"] == [row["id"] for row in runs[:2]]
        assert group["start_at"] == "2024-01-03T00:00:00Z"
        assert group["end_at"] == "2024-01-04T00:00:00Z"
        assert group["reference_price"] == group["entry_price"] == 120
        assert group["entry_fee"] == pytest.approx(100 / 1.001 * 0.001)
        assert group["total_return"] == pytest.approx(1 / 1.001 - 1)
        assert [point["phase"] for point in group["points"]] == ["initial", "close"]
        assert group["points"][0]["benchmark"] == 100
        early, late = group["strategies"]
        assert early["open_quantity"] == pytest.approx(1000 / (110 * 1.001))
        assert early["open_equity"] == pytest.approx(early["open_quantity"] * 120)
        assert early["total_return"] == pytest.approx(0)
        assert early["excess_return"] == pytest.approx(-group["total_return"])
        assert late["open_equity"] == 2000
        assert late["open_quantity"] == 0
        assert late["excess_return"] == pytest.approx(0)
        reasons = {
            tuple(pair["run_ids"]): pair["reason"] for pair in benchmark["pairs"]
        }
        assert reasons[(runs[0]["id"], runs[2]["id"])] == "cost_mismatch"
        assert reasons[(runs[0]["id"], runs[3]["id"])] == "primary_data_mismatch"
