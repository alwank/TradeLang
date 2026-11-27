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
from tradelang.api.contracts import (
    AST_SCHEMA,
    AST_SCHEMA_V2,
    AST_SCHEMA_V3,
    AST_SCHEMA_V4,
    AST_SCHEMA_V5,
    AST_SCHEMA_V6,
    AST_SCHEMA_V7,
    ErrorEnvelope,
)
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
    "prefix,version",
    [
        ("", 1),
        ("dsl 1\n", 1),
        ("tradelang 1\n", 1),
        ("tradelang 2\n", 2),
        ("tradelang 3\n", 3),
        ("tradelang 4\n", 4),
        ("tradelang 5\n", 5),
        ("tradelang 6\n", 6),
        ("tradelang 7\n", 7),
        ("tradelang 8\n", 8),
        ("tradelang 9\n", None),
    ],
)
def test_version_directive_api_cli_parity(tmp_path, command, prefix, version):
    source = prefix + CORE
    path = tmp_path / "version.trade"
    path.write_text(source)
    code, response = cli(command, path)
    http = request(create_app(), command, headers=ORIGIN, json={"source": source})
    assert code == (0 if version is not None else 2) and http.status_code == 200
    body = http.json()
    assert body["valid"] == response["ok"] == (version is not None)
    assert body["diagnostics"] == response["diagnostics"]
    if version is not None:
        assert body["diagnostics"] == []
        assert response["result"] == {key: body[key] for key in response["result"]}
        if command == "validate":
            assert (
                body["spec"]["dsl_version"] == body["spec"]["schema_version"] == version
            )
    else:
        assert body["diagnostics"][0]["code"] == "E101_SYNTAX"
        assert body["spec_hash"] is None and response["result"] is None


@pytest.mark.parametrize("market", [None, "TESTUSDT"])
@pytest.mark.parametrize("timeframe", [None, "24h"])
def test_optional_dataset_declarations(tmp_path, market, timeframe):
    source = CORE.replace("market TESTUSDT\n", f"market {market}\n" if market else "")
    source = source.replace(
        "timeframe 1d\n", f"timeframe {timeframe}\n" if timeframe else ""
    )
    dataset_id = uuid4()
    app = create_app({dataset_id: load_dataset(FIX / "core.csv", META)}.get)
    body = {"source": source}
    selected = {**body, "dataset_id": str(dataset_id)}

    source_only = request(app, headers=ORIGIN, json=body).json()
    with_data = request(app, headers=ORIGIN, json=selected).json()
    assert source_only["valid"] and with_data["valid"]
    assert source_only["data_compatible"] is None
    assert with_data["data_compatible"] is True
    assert source_only["spec_hash"] == with_data["spec_hash"]
    assert source_only["spec"] == with_data["spec"]
    assert with_data["spec"]["symbol"] == market
    assert with_data["spec"]["timeframe_seconds"] == (86400 if timeframe else None)

    explanation = request(app, "explain", headers=ORIGIN, json=body).json()["text"]
    assert ("Market from selected dataset" in explanation) == (market is None)
    assert ("timeframe from selected dataset" in explanation) == (timeframe is None)
    explanation = request(app, "explain", headers=ORIGIN, json=selected).json()
    assert "TESTUSDT, 86400 seconds per UTC bar" in explanation["text"]

    path = tmp_path / "optional.trade"
    path.write_text(source)
    code, response = cli(
        "validate",
        path,
        "--data",
        FIX / "core.csv",
        "--metadata",
        FIX / "metadata.json",
    )
    assert code == 0
    assert response["result"] == {key: with_data[key] for key in response["result"]}


@pytest.mark.parametrize(
    "declaration,currency,field",
    [
        ("market OTHERUSDT\n", "USDT", "market"),
        ("timeframe 1h\n", "USDT", "timeframe"),
        ("", "USD", "quote currency"),
    ],
)
def test_optional_dataset_declaration_mismatches(declaration, currency, field):
    source = CORE.replace("market TESTUSDT\ntimeframe 1d\n", declaration)
    source = source.replace("capital 1000 USDT", f"capital 1000 {currency}")
    dataset_id = uuid4()
    app = create_app({dataset_id: load_dataset(FIX / "core.csv", META)}.get)
    result = request(
        app, headers=ORIGIN, json={"source": source, "dataset_id": str(dataset_id)}
    ).json()
    assert not result["valid"] and result["data_compatible"] is False
    assert result["diagnostics"][0]["code"] == "E402_WINDOW"
    assert f"requires {field}" in result["diagnostics"][0]["message"]


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
    assert set(doc["paths"]) == {
        PREFIX + "validate",
        PREFIX + "explain",
        PREFIX + "draft-check",
        "/health",
    }
    schemas = doc["components"]["schemas"]
    assert schemas["SourceRequest"]["additionalProperties"] is False
    assert schemas["CompilationResponse"]["properties"]["spec"]["anyOf"][0][
        "$ref"
    ].endswith("/StrategySpec")
    assert schemas["StrategySpec"]["oneOf"] == [
        {"$ref": f"#/components/schemas/StrategySpecV{version}"}
        for version in (1, 2, 3, 4, 5, 6, 7, 8, 9)
    ]
    assert all(
        schemas[f"StrategySpecV{version}"]["additionalProperties"] is False
        for version in (1, 2, 3, 4, 5, 6, 7, 8, 9)
    )
    assert AST_SCHEMA == json.loads(
        Path("docs/schemas/strategy.schema.json").read_text()
    )
    assert AST_SCHEMA_V2 == json.loads(
        Path("docs/schemas/strategy-v2.schema.json").read_text()
    )

    assert AST_SCHEMA_V3 == json.loads(
        Path("docs/schemas/strategy-v3.schema.json").read_text()
    )
    assert AST_SCHEMA_V4 == json.loads(
        Path("docs/schemas/strategy-v4.schema.json").read_text()
    )
    assert AST_SCHEMA_V5 == json.loads(
        Path("docs/schemas/strategy-v5.schema.json").read_text()
    )
    assert AST_SCHEMA_V6 == json.loads(
        Path("docs/schemas/strategy-v6.schema.json").read_text()
    )
    assert AST_SCHEMA_V7 == json.loads(
        Path("docs/schemas/strategy-v7.schema.json").read_text()
    )


def test_http_rejects_duplicate_parameter_overrides():
    source = json.dumps(
        "tradelang 2\n" + CORE.replace("entry:", "param enabled: bool = true\nentry:")
    )
    response = request(
        create_app(),
        headers={**ORIGIN, "Content-Type": "application/json"},
        content='{"source":'
        + source
        + ',"parameters":{"enabled":true,"enabled":false}}',
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "E_JSON"


def test_portfolio_source_uses_the_same_typed_contract_in_cli_and_api(tmp_path):
    source = Path("docs/fixtures/portfolio/priority.trade").read_text()
    path = tmp_path / "portfolio.trade"
    path.write_text(source)
    code, cli_result = cli("validate", path)
    assert code == 0
    app = create_app()
    checked = request(app, "validate", headers=ORIGIN, json={"source": source})
    assert checked.status_code == 200
    assert checked.json()["valid"]
    assert checked.json()["spec"] == cli_result["result"]["spec"]
    assert checked.json()["spec"]["assets"] == ["alpha", "beta"]
    explained = request(app, "explain", headers=ORIGIN, json={"source": source})
    assert explained.status_code == 200
    assert "alpha, beta" in explained.json()["text"]
    draft = request(app, "draft-check", headers=ORIGIN, json={"source": source})
    assert draft.status_code == 200
    assert draft.json()["records"] == []


def test_draft_check_recovers_source_spans_without_a_compiled_spec(tmp_path):
    from language_cases import strategy_text

    body = (
        strategy_text(
            lets="let broken = ema(2)\nlet cascades = broken + 1\nlet period = SMA(0)",
            entry="cascades > 0",
            exit="clsoe > 0",
        )
        .replace("Golden next-open ledger", "Café 🧪")
        .replace("\n", "\r\n")
    )
    source = "\ufeff# 🧪\r\n" + body
    app = create_app()
    strict = request(app, headers=ORIGIN, json={"source": source}).json()
    assert [row["code"] for row in strict["diagnostics"]] == ["E101_SYNTAX"]
    draft = request(app, "draft-check", headers=ORIGIN, json={"source": source}).json()
    assert draft["source_hash"] == strict["source_hash"]
    assert (
        draft["valid"] is False and draft["spec"] is None and draft["spec_hash"] is None
    )
    assert draft["data_compatible"] is None
    assert [row["code"] for row in draft["diagnostics"]] == [
        "E101_SYNTAX",
        "E202_PERIOD",
        "E102_UNKNOWN_NAME",
    ]
    extracted = [
        source.encode()[row["span"]["start_byte"] : row["span"]["end_byte"]]
        for row in draft["diagnostics"]
    ]
    assert extracted == [b"ema", b"0", b"clsoe"]
    assert draft["diagnostics"][0]["details"] == {
        "original": "ema",
        "replacement": "EMA",
    }
    assert draft["diagnostics"][2]["details"] == {
        "original": "clsoe",
        "replacement": "close",
    }
    file = tmp_path / "exact.trade"
    file.write_bytes(source.encode())
    code, wire = cli("validate", file)
    assert code == 2 and wire["diagnostics"] == strict["diagnostics"]


def test_draft_check_limits_independent_diagnostics():
    from language_cases import strategy_text

    source = strategy_text(
        lets="\n".join(f"let binding{i} = SMA(0)" for i in range(129))
    )
    draft = request(
        create_app(), "draft-check", headers=ORIGIN, json={"source": source}
    ).json()
    assert draft["valid"] is False
    assert draft["spec"] is None
    assert [row["code"] for row in draft["diagnostics"]] == ["E202_PERIOD"] * 8


def test_draft_check_offers_a_literal_scale_fix():
    from language_cases import strategy_text

    source = "tradelang 2\n" + strategy_text(entry="RSI(2) < 30%")
    draft = request(
        create_app(), "draft-check", headers=ORIGIN, json={"source": source}
    ).json()
    assert draft["valid"] and draft["spec"]["dsl_version"] == 2
    (warning,) = draft["diagnostics"]
    assert warning["code"] == "W_POINT_SCALE"
    assert warning["details"] == {"original": "30%", "replacement": "30"}


def test_draft_check_retains_record_fields_from_valid_declarations():
    from language_cases import strategy_text

    source = "tradelang 2\n" + strategy_text(
        lets="let trend = DMI(2, 3)\nlet saved = trend",
        entry="saved.",
    )
    response = request(
        create_app(), "draft-check", headers=ORIGIN, json={"source": source}
    )
    assert response.status_code == 200, response.text
    draft = response.json()
    assert draft["spec"] is None and not draft["valid"]
    assert [record["name"] for record in draft["records"]] == ["trend", "saved"]
    assert all(
        record["fields"] == {"adx": "points", "plus_di": "points", "minus_di": "points"}
        for record in draft["records"]
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
