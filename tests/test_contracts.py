import csv
import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path

import jsonschema
import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
import pytest
from test_golden import FIX, META, scenario

from tradelang.compiler import compile_source
from tradelang.data import digest, load_dataset
from tradelang.engine import execute
from tradelang.evaluator import Evaluator
from tradelang.model import Problem
from tradelang.report import identity


def cli(*args):
    proc = subprocess.run(
        ["tradelang", *map(str, args), "--json"], capture_output=True, text=True
    )
    return proc.returncode, json.loads(proc.stdout)


def parquet(csv_path, path):
    with csv_path.open() as f:
        rows = list(csv.DictReader(f))
    for row in rows:
        row["timestamp"] = datetime.fromisoformat(row["timestamp"]).astimezone(UTC)
        for k in ["open", "high", "low", "close", "volume"]:
            row[k] = float(row[k])
    pq.write_table(pa.Table.from_pylist(rows), path)


def test_cli_roundtrip(tmp_path):
    path = tmp_path / "d.parquet"
    parquet(FIX / "core.csv", path)
    outputs = []
    for i, data in enumerate([path, FIX / "core.csv", path]):
        out = tmp_path / str(i)
        code, response = cli(
            "backtest",
            FIX / "core.trade",
            "--metadata",
            FIX / "metadata.json",
            "--data",
            data,
            "--out",
            out,
        )
        assert code == 0, response
        outputs.append(response["result"])
        manifest = json.loads((out / "manifest.json").read_text())
        for file in manifest["artifact_files"]:
            assert digest((out / file["name"]).read_bytes()) == file["sha256"]
        assert pq.read_table(out / "equity.parquet").num_rows == 4
        assert len((out / "trades.csv").read_text().splitlines()) == 2
    assert len({o["run_fingerprint"] for o in outputs}) == 1
    assert len({o["result_digest"] for o in outputs}) == 1
    assert len({o["run_id"] for o in outputs}) == 3
    code, r = cli(
        "backtest",
        FIX / "core.trade",
        "--metadata",
        FIX / "metadata.json",
        "--data",
        path,
        "--out",
        tmp_path / "0",
    )
    assert code == 3 and not r["ok"]


def test_schemas():
    schema = json.loads(Path("docs/schemas/strategy.schema.json").read_text())
    for path in Path("docs").rglob("*.trade"):
        s = compile_source(path.read_bytes())
        jsonschema.validate(s.public(), schema)
        decorated = compile_source("# comment\r\n" + s.source.decode())
        assert identity(s)["spec_hash"] == identity(decorated)["spec_hash"]
        assert identity(s)["source_hash"] != identity(decorated)["source_hash"]


def test_cli_explain_and_error(tmp_path):
    code, r = cli("explain", FIX / "core.trade")
    assert code == 0 and "next open" in r["result"]["text"]
    bad = tmp_path / "bad.trade"
    bad.write_text(
        (FIX / "core.trade").read_text().replace("when true", "when close + 2% > close")
    )
    code, r = cli("validate", bad)
    assert code == 2 and r["diagnostics"][0]["span"]["start_line"] == 5


def test_no_future_and_boolean_unavailable():
    s, d = scenario(
        "invalid", lets="let z = close / (high-low)", entry="true or not (z > 0)"
    )
    full = Evaluator(s, d, len(d.times) - 1).evaluate(s.entry)
    assert np.isnan(full[0]) and np.isnan(full[2])
    for k in range(len(full)):
        np.testing.assert_equal(Evaluator(s, d, k).evaluate(s.entry), full[: k + 1])
    for path in Path("docs/examples").glob("*.trade"):
        s = compile_source(path.read_bytes())
        # Complement entire strategy prefix tests with recursive kernels past seed.
        x = np.tile(d.values, (80, 1))
        from dataclasses import replace

        ds = replace(d, values=x)
        full = Evaluator(s, ds, len(x) - 1)
        for end in [31, 205, 234]:
            prefix = Evaluator(s, ds, end)
            for e in (s.entry, s.exit):
                np.testing.assert_equal(prefix.evaluate(e), full.evaluate(e)[: end + 1])


@pytest.mark.parametrize(
    "expression,valid_value",
    [("not positive", 0), ("false and positive", 0), ("true or positive", 1)],
)
def test_named_conditions_preserve_unavailable_and_prefix(expression, valid_value):
    strategy, data = scenario(
        "invalid",
        lets=f"let positive = close / (high - low) > 0\nlet condition = {expression}",
        entry="condition and (positive or positive)",
    )
    definition = strategy.bindings[1][1]
    full = Evaluator(strategy, data, len(data.times) - 1)
    expected = [np.nan, valid_value, np.nan, valid_value]
    np.testing.assert_equal(full.evaluate(definition), expected)
    np.testing.assert_equal(full.evaluate(strategy.entry), expected)
    for end in range(len(data.times)):
        prefix = Evaluator(strategy, data, end)
        for expression_node in (definition, strategy.entry):
            np.testing.assert_equal(
                prefix.evaluate(expression_node),
                full.evaluate(expression_node)[: end + 1],
            )

    result = execute(strategy, data)
    assert result["summary"]["counts"]["unavailable_by_reason"]["zero_denominator"] == 2
    assert [
        e["bar_index"] for e in result["events"] if e["kind"] == "order_queued"
    ] == ([1] if valid_value else [])
    assert all(
        e["bar_index"] in {1, 3} for e in result["events"] if e["kind"] == "signal"
    )


def test_allowed_missing_bar(tmp_path):
    path = tmp_path / "gap.csv"
    lines = (FIX / "core.csv").read_text().splitlines()
    path.write_text("\n".join([lines[0], lines[1], lines[3]]))
    with pytest.raises(Problem):
        load_dataset(path, META)
    d = load_dataset(path, {**META, "gap_policy": "allow"})
    assert d.missing == 1
    s = compile_source((FIX / "core.trade").read_bytes())
    r = execute(s, d)["summary"]
    assert r["final_equity"] == 1000 and r["metrics"]["sharpe"] is None


@pytest.mark.parametrize(
    "before,after",
    [
        ("2024-01-01T00:00:00Z", "2024-01-01"),
        ("100,102,98,100,10", "100,99,98,100,10"),
        ("100,102,98,100,10", "NaN,102,98,100,10"),
        ("2024-01-02", "2024-01-01"),
    ],
)
def test_bad_inputs(tmp_path, before, after):
    p = tmp_path / "bad.csv"
    p.write_text((FIX / "core.csv").read_text().replace(before, after))
    with pytest.raises(Problem):
        load_dataset(p, META)


@pytest.mark.parametrize("strategy", ["rsi", "ema", "breakout"])
def test_short_indicator_trades(tmp_path, strategy):
    code, r = cli(
        "backtest",
        f"examples/quick/{strategy}.trade",
        "--data",
        "examples/quick/recovery.csv",
        "--metadata",
        FIX / "metadata.json",
        "--out",
        tmp_path / "run",
    )
    assert code == 0, r
    assert r["result"]["summary"]["metrics"]["closed_trades"] == 1
    assert r["result"]["summary"]["final_equity"] == pytest.approx(1000 * 14 / 13)


def test_window_prefix_and_metrics():
    from tradelang.engine import costs, metrics

    s, d = scenario("indicators", lets="let m = SMA(3)", entry="m > 0")
    narrowed = compile_source(s.source.replace(b"from 2024-01-01", b"from 2024-01-03"))
    assert execute(narrowed, d)["summary"]["final_equity"] == 1125
    m = metrics([1000, 900, 990], [], costs(), 0, 86400, 172800, False)
    assert m["max_drawdown"] == pytest.approx(0.1)
    assert m["sharpe"] == pytest.approx(0, abs=1e-12)
    assert m["win_rate"] is None
    assert metrics([1000, 1100], [], costs(), 1, 86400, 31557600, False)[
        "cagr"
    ] == pytest.approx(0.1)


@pytest.mark.parametrize(
    "source,code",
    [
        ("let x = y\nlet y = close", "E104_FORWARD_REFERENCE"),
        ("let y = close\nlet y = volume", "E103_DUPLICATE_BINDING"),
        ("let open = close", "E103_DUPLICATE_BINDING"),
        ("let y = close + volume", "E201_UNIT"),
        ("let z = 0 ** 0", "E206_CONSTANT_INVALID"),
        ("let v = MACD(12,26,9).typo", "E204_SELECTOR"),
        ("let v = (1 + 2)[1]", "E205_OFFSET"),
    ],
)
def test_static_diagnostics(source, code):
    with pytest.raises(Problem) as exc:
        scenario(lets=source)
    assert exc.value.diagnostic["code"] == code
    assert exc.value.diagnostic["span"]["start_line"] >= 4


def test_boolean_scalar_binding_broadcasts():
    strategy, data = scenario(
        lets="let enabled = true\nlet disabled = not enabled",
        entry="enabled",
        exit="disabled",
    )
    spec = strategy.public()
    scalar = {"kind": "boolean", "shape": "scalar"}
    assert [binding["expression"]["inferred_type"] for binding in spec["bindings"]] == [
        scalar,
        scalar,
    ]
    for rule, name in (("entry", "enabled"), ("exit", "disabled")):
        reference = spec[rule]["condition"]
        assert reference["kind"] == "Reference"
        assert reference["binding_kind"] == "let"
        assert reference["name"] == name
        assert reference["inferred_type"] == scalar
    schema = json.loads(Path("docs/schemas/strategy.schema.json").read_text())
    jsonschema.validate(spec, schema)

    rows = len(data.times)
    evaluator = Evaluator(strategy, data, rows - 1)
    np.testing.assert_equal(
        evaluator.array(evaluator.evaluate(strategy.entry)), [1] * rows
    )
    np.testing.assert_equal(
        evaluator.array(evaluator.evaluate(strategy.exit)), [0] * rows
    )
    result = execute(strategy, data)
    assert [
        (e["bar_index"], e["side"]) for e in result["events"] if e["kind"] == "fill"
    ] == [(1, "buy")]


@pytest.mark.parametrize(
    "before,after,code,highlight",
    [
        (
            "let confirmed = close > 0",
            "let confirmed = later\nlet later = true",
            "E104_FORWARD_REFERENCE",
            "later",
        ),
        (
            "let confirmed = close > 0",
            "let confirmed = true\nlet confirmed = false",
            "E103_DUPLICATE_BINDING",
            "let confirmed = false",
        ),
        (
            "let confirmed = close > 0",
            "let confirmed = MACD(12, 26, 9)",
            "E203_TYPE",
            "let confirmed = MACD(12, 26, 9)",
        ),
        ("when true", "when confirmed + 1 > 0", "E203_TYPE", "confirmed + 1"),
        ("when true", "when confirmed == true", "E203_TYPE", "confirmed == true"),
        (
            "when true",
            "when confirmed crosses above 0",
            "E203_TYPE",
            "confirmed crosses above 0",
        ),
        ("when true", "when SMA(confirmed, 3) > 0", "E203_TYPE", "SMA(confirmed, 3)"),
        ("when true", "when SMA(confirmed) > 0", "E202_PERIOD", "confirmed"),
        ("when true", "when confirmed[1]", "E205_OFFSET", "[1]"),
        ("100% of equity", "confirmed of equity", "E302_SIZING", "confirmed of equity"),
        ("100% of equity", "confirmed USDT", "E302_SIZING", "confirmed USDT"),
        (
            "backtest:",
            "risk: stop loss confirmed\nbacktest:",
            "E303_RISK",
            "stop loss confirmed",
        ),
        (
            "backtest:",
            "risk: take profit confirmed\nbacktest:",
            "E303_RISK",
            "take profit confirmed",
        ),
    ],
)
def test_boolean_binding_diagnostics(before, after, code, highlight):
    source = (
        (FIX / "core.trade")
        .read_text()
        .replace("entry:", "let confirmed = close > 0\nentry:")
        .replace(before, after)
        .encode()
    )
    with pytest.raises(Problem) as exc:
        compile_source(source)
    diagnostic = exc.value.diagnostic
    assert diagnostic["code"] == code
    span = diagnostic["span"]
    assert source[span["start_byte"] : span["end_byte"]].decode() == highlight
    if after == "let confirmed = MACD(12, 26, 9)":
        assert diagnostic["message"] == "let requires a numeric or Boolean expression"


def test_signal_invalid_protection_and_no_cash_mutation():
    s, d = scenario(
        "gap-stop", risk="risk: stop loss (high-low) / (high-low) * 200 price"
    )
    r = execute(s, d)
    assert (
        r["summary"]["final_cash"] == 1000 and r["summary"]["costs"]["total_fees"] == 0
    )
    assert not [e for e in r["events"] if e["kind"] == "fill"]


def test_runtime_power_and_scalar_boolean_trace():
    s, d = scenario(entry="(1 == 1) and close > 0", size="(2 ** -1) of equity")
    assert execute(s, d)["summary"]["final_equity"] == pytest.approx(
        500 + 500 * 120 / 110
    )
    s, d = scenario(lets="let v = (low-high) / close", entry="v ** 0.5 > 0")
    r = execute(s, d)["summary"]
    assert (
        r["final_cash"] == 1000 and r["counts"]["unavailable_by_reason"]["domain"] == 3
    )


def test_canonical_bytes_and_full_ast():
    import hashlib

    # Cross-format content-addressing protocol: little-endian u32 header length,
    # UTC microsecond int64 followed by O,H,L,C,V as five little-endian doubles.
    import struct

    from tradelang.data import canonical

    header = b'{"calendar":"24x7","price_basis":"raw_spot","quote_currency":"USDT","symbol":"TESTUSDT","timeframe":86400,"timestamp_convention":"bar_open","volume_unit":"base_quantity"}'
    raw = b"tradelang.dataset.v1\n" + struct.pack("<I", len(header)) + header
    for i, values in enumerate(
        [(100, 102, 98, 100, 10), (110, 115, 108, 112, 20), (120, 125, 115, 120, 30)]
    ):
        raw += struct.pack("<q5d", 1704067200000000 + 86400000000 * i, *values)
    assert (
        hashlib.sha256(raw).hexdigest()
        == load_dataset(FIX / "core.csv", META).dataset_hash
    )
    assert canonical({"z": 1e-7, "a": [1.0, -0.0, 1e20]}) == '{"a":[1,0,1e20],"z":1e-7}'
    assert compile_source((FIX / "core.trade").read_bytes()).public() == json.loads(
        Path("docs/schemas/strategy.example.json").read_text()
    )


def test_unicode_byte_spans_and_postfix_depth():
    src = b"# \xf0\x9f\x98\x80\r\n" + (FIX / "core.trade").read_bytes()
    entry = compile_source(src).entry
    assert src[entry.span.start_byte : entry.span.end_byte] == b"true"
    with pytest.raises(Problem, match="chain exceeds"):
        scenario(lets="let a = close" + "[0]" * 70)


def test_grammar_copy_and_complete_reference_sources():
    from lark import Lark

    from tradelang.compiler import GRAMMAR

    assert GRAMMAR == Path("docs/grammar-v1.lark").read_text()
    parser = Lark(GRAMMAR, parser="lalr", lexer="contextual", strict=True)
    for source in Path("docs/examples").glob("*.trade"):
        parser.parse(source.read_text())
