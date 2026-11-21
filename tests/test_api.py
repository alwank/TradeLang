import asyncio
import json
import subprocess
import sys
from pathlib import Path
from threading import Event
from uuid import UUID, uuid4

import httpx
import pytest
from openapi_spec_validator import validate
from test_contracts import cli
from test_golden import FIX, META

from tradelang.api import create_app
from tradelang.api.contracts import AST_SCHEMA, ErrorEnvelope
from tradelang.data import load_dataset

BASE = "http://127.0.0.1:8000"
ORIGIN = {"origin": "http://127.0.0.1:3000"}
PREFIX = "/api/v1/strategies/"
CORE = (FIX / "core.trade").read_text()


def request(app, command="validate", peer="127.0.0.1", **options):
    async def send():
        transport = httpx.ASGITransport(app=app, client=(peer, 1234))
        async with httpx.AsyncClient(transport=transport, base_url=BASE) as client:
            return await client.post(PREFIX + command, **options)

    return asyncio.run(send())


@pytest.fixture(scope="module")
def example_data(tmp_path_factory):
    directory = tmp_path_factory.mktemp("reference-candles")
    subprocess.run(
        [sys.executable, "scripts/example_data.py", str(directory)], check=True
    )
    candles, metadata = directory / "example.csv", directory / "metadata.json"
    return candles, metadata, load_dataset(candles, json.loads(metadata.read_text()))


@pytest.mark.parametrize("command", ["explain", "validate"])
def test_api_cli_parity(tmp_path, command, example_data):
    candles, metadata, dataset = example_data
    example_id, golden_id = uuid4(), uuid4()
    store = {example_id: dataset, golden_id: load_dataset(FIX / "core.csv", META)}
    app = create_app(store.get)
    threshold = tmp_path / "threshold.trade"
    threshold.write_text(CORE.replace("when true", "when close > 100.00004 price"))
    examples = sorted(Path("docs/examples").glob("*.trade"))
    assert len(examples) == 5
    boolean_names = ["volume_confirmed", "entry_ready", "exit_ready"]
    cases = [(path, candles, metadata, example_id) for path in examples]
    cases.append((threshold, FIX / "core.csv", FIX / "metadata.json", golden_id))
    for path, data, meta, key in cases:
        code, r = cli(command, path, "--data", data, "--metadata", meta)
        resp = request(
            app,
            command,
            headers=ORIGIN,
            json={"source": path.read_text(), "dataset_id": str(key)},
        )
        assert resp.status_code == 200 and code == 0
        body = resp.json()
        assert body["valid"] and body["resolved_window"] is not None
        assert r["diagnostics"] == body["diagnostics"]
        assert r["result"] == {k: body[k] for k in r["result"]}
        if path.name == "04-math.trade":
            if command == "validate":
                spec = body["spec"]
                assert spec["dsl_version"] == spec["schema_version"] == 1
                series = {"kind": "boolean", "shape": "series"}
                assert [
                    (binding["name"], binding["expression"]["inferred_type"])
                    for binding in spec["bindings"][-3:]
                ] == [(name, series) for name in boolean_names]
                for rule in ("entry", "exit"):
                    condition = spec[rule]["condition"]
                    assert condition["name"] == f"{rule}_ready"
                    assert condition["binding_kind"] == "let"
                    assert condition["inferred_type"] == series
            else:
                lines = body["text"].splitlines()
                definitions = [
                    line.removeprefix("let ").split(" = ", 1)[0]
                    for line in lines
                    if line.startswith("let ")
                ]
                assert definitions[-3:] == boolean_names
                assert "At close, enter when entry_ready." in lines
                assert "Exit all at the next open after exit_ready." in lines


@pytest.mark.parametrize("command", ["validate", "explain"])
@pytest.mark.parametrize(
    "prefix,expected_code",
    [("", 0), ("dsl 1\n", 0), ("tradelang 1\n", 0), ("tradelang 2\n", 2)],
)
def test_version_directive_api_cli_parity(tmp_path, command, prefix, expected_code):
    source = prefix + CORE
    path = tmp_path / "version.trade"
    path.write_text(source)
    code, response = cli(command, path)
    http = request(create_app(), command, headers=ORIGIN, json={"source": source})
    assert code == expected_code and http.status_code == 200
    body = http.json()
    assert body["valid"] == response["ok"] == (expected_code == 0)
    assert body["diagnostics"] == response["diagnostics"]
    if expected_code == 0:
        assert body["diagnostics"] == []
        assert response["result"] == {key: body[key] for key in response["result"]}
        if command == "validate":
            assert body["spec"]["dsl_version"] == 1
    else:
        assert body["diagnostics"][0]["code"] == "E101_SYNTAX"
        assert body["spec_hash"] is None and response["result"] is None


@pytest.mark.parametrize("command", ["explain", "validate"])
def test_import_resolver_and_invalid_source(tmp_path, command):
    good, bad = uuid4(), uuid4()
    store = {
        good: load_dataset(FIX / "core.csv", META),
        bad: load_dataset(FIX / "core.csv", {**META, "symbol": "OTHER"}),
    }
    app = create_app(store.get)
    code, r = cli(
        command,
        FIX / "core.trade",
        "--metadata",
        FIX / "metadata.json",
        "--data",
        FIX / "core.csv",
    )

    def inspect(source, key=None):
        response = request(
            app,
            command,
            headers=ORIGIN,
            json={"source": source, "dataset_id": str(key) if key else None},
        )
        assert response.status_code == 200
        return response.json()

    body = inspect(CORE, good)
    assert body["valid"] and code == 0
    assert all(body[k] == v for k, v in r["result"].items())
    assert body["resolved_window"]["first_execution_at"] == "2024-01-02T00:00:00Z"
    source_only = inspect(CORE)
    assert source_only["valid"] and source_only["resolved_window"] is None
    assert source_only.get("data_compatible") is None
    invalid = inspect(CORE, bad)
    assert not invalid["valid"] and invalid["resolved_window"] is None
    assert invalid.get("spec") is None and invalid.get("text") is None
    if command == "validate":
        assert invalid["data_compatible"] is False
    path = tmp_path / "bad.trade"
    path.write_text(CORE.replace("when true", "when close + 2% > close"))
    code, error = cli(command, path)
    invalid = inspect(path.read_text(), good)
    assert code == 2 and invalid["diagnostics"] == error["diagnostics"]
    assert invalid["spec_hash"] is None and invalid.get("data_compatible") is None
    assert invalid["diagnostics"][0]["span"]["start_line"] == 5
    assert (
        request(
            app,
            command,
            headers=ORIGIN,
            json={"source": CORE, "dataset_id": str(uuid4())},
        ).status_code
        == 404
    )


@pytest.mark.parametrize(
    "options,status",
    [
        ({"headers": ORIGIN, "json": {"source": 123}}, 422),
        ({"headers": ORIGIN, "json": {"source": CORE, "dataset_id": "some/path"}}, 422),
        ({"headers": ORIGIN, "json": {"source": CORE, "extra": True}}, 422),
        (
            {"headers": {**ORIGIN, "Content-Type": "application/json"}, "content": "{"},
            400,
        ),
        (
            {"headers": {**ORIGIN, "Content-Type": "application/json"}, "content": ""},
            400,
        ),
        (
            {
                "headers": {**ORIGIN, "Content-Type": "application/json"},
                "content": b'{"source":NaN}',
            },
            400,
        ),
        (
            {
                "headers": {**ORIGIN, "Content-Type": "application/json"},
                "content": b'{"source":"\xff"}',
            },
            400,
        ),
        ({"headers": ORIGIN, "json": {"source": "é" * 32769}}, 413),
        (
            {
                "headers": {**ORIGIN, "Content-Type": "application/json"},
                "content": b" " * 131073,
            },
            413,
        ),
        ({"headers": ORIGIN, "content": "source"}, 415),
        ({"headers": {**ORIGIN, "host": "other.test"}, "json": {"source": CORE}}, 403),
        (
            {"headers": {"origin": "http://localhost:3000"}, "json": {"source": CORE}},
            403,
        ),
        ({"headers": {}, "json": {"source": CORE}}, 403),
        ({"headers": ORIGIN, "peer": "192.0.2.1", "json": {"source": CORE}}, 403),
    ],
)
def test_errors(options, status):
    resp = request(create_app(), **options)
    assert resp.status_code == status
    UUID(ErrorEnvelope.model_validate(resp.json()).request_id)


def test_rate_limit_and_default_resolver():
    app = create_app()
    for _ in range(30):
        assert (
            request(
                app, headers=ORIGIN, json={"source": CORE, "dataset_id": str(uuid4())}
            ).status_code
            == 404
        )
    resp = request(app, headers=ORIGIN, json={"source": CORE})
    assert resp.status_code == 429 and int(resp.headers["Retry-After"]) >= 1


def test_four_concurrent_inspections():
    all_entered = asyncio.Event()
    release = Event()

    async def exercise():
        loop = asyncio.get_running_loop()
        arrived = []

        def resolve(key):
            arrived.append(key)
            if len(arrived) == 4:
                loop.call_soon_threadsafe(all_entered.set)
            release.wait(10)
            return None

        transport = httpx.ASGITransport(app=create_app(resolve))
        async with httpx.AsyncClient(transport=transport, base_url=BASE) as client:

            def post():
                return client.post(
                    PREFIX + "validate",
                    headers=ORIGIN,
                    json={"source": CORE, "dataset_id": str(uuid4())},
                )

            pending = [asyncio.create_task(post()) for _ in range(4)]
            try:
                await asyncio.wait_for(all_entered.wait(), 5)
                assert (await post()).status_code == 429
            finally:
                release.set()
                await asyncio.gather(*pending)
            assert (await post()).status_code == 404

    asyncio.run(exercise())


def test_openapi_matches_contract():
    doc = create_app().openapi()
    validate(doc)
    assert set(doc["paths"]) == {PREFIX + "validate", PREFIX + "explain", "/health"}
    schemas = doc["components"]["schemas"]
    assert schemas["SourceRequest"]["additionalProperties"] is False
    assert schemas["CompilationResponse"]["properties"]["spec"]["anyOf"][0][
        "$ref"
    ].endswith("/StrategySpec")
    assert schemas["StrategySpec"]["additionalProperties"] is False
    assert AST_SCHEMA == json.loads(
        Path("docs/schemas/strategy.schema.json").read_text()
    )


@pytest.mark.parametrize("command", ["validate", "explain"])
@pytest.mark.parametrize("valid", [True, False])
def test_registry_catalog_api_cli_parity(tmp_path, command, valid):
    from language_cases import FIXTURES

    source = (FIXTURES / "catalog.trade").read_text()
    if not valid:
        source = source.replace("BBANDS(source,2,2).upper", "BBANDS(source,0,0).upper")
    path = tmp_path / "catalog.trade"
    path.write_text(source)
    code, response = cli(command, path)
    http = request(create_app(), command, headers=ORIGIN, json={"source": source})
    assert http.status_code == 200
    body = http.json()
    assert body["valid"] == response["ok"] == valid
    assert body["diagnostics"] == response["diagnostics"]
    if valid:
        assert code == 0
        assert response["result"] == {key: body[key] for key in response["result"]}
    else:
        assert code == 2
        assert response["result"] is None
        assert body["spec_hash"] is None
        assert body["diagnostics"][0]["code"] == "E202_PERIOD"
