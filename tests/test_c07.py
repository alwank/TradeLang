import csv
import json
import math
import subprocess
import zipfile
from importlib.metadata import version

import pyarrow.parquet as pq
import pytest
from test_contracts import cli
from test_golden import FIX, META, scenario

from tradelang.data import digest, hash_json
from tradelang.engine import execute
from tradelang.report import package_revision


def test_timeframe_alias_cli(tmp_path):
    signatures = []
    for alias in ("1d", "24h", "1440m"):
        meta = tmp_path / "meta.json"
        meta.write_text(json.dumps({**META, "timeframe": alias}))
        out = tmp_path / alias
        code, response = cli(
            "backtest",
            FIX / "core.trade",
            "--data",
            FIX / "core.csv",
            "--metadata",
            meta,
            "--out",
            out,
        )
        assert code == 0, response
        manifest = json.loads((out / "manifest.json").read_text())
        assert manifest["dataset_metadata"]["timeframe"] == alias
        assert response["result"]["summary"]["timeframe"] == "1d"
        fills = [
            event
            for line in (out / "events.jsonl").read_text().splitlines()
            if (event := json.loads(line))["fill_id"] is not None
        ]
        assert fills
        signatures.append(
            (
                manifest["dataset_hash"],
                manifest["run_fingerprint"],
                manifest["result_digest"],
                fills,
                (out / "trades.csv").read_bytes(),
                (out / "equity.csv").read_bytes(),
            )
        )
    assert all(signature == signatures[0] for signature in signatures)


def test_explain_precise_cli(tmp_path):
    path = tmp_path / "price.trade"
    next_value = math.nextafter(100.00004, math.inf)
    source = (
        (FIX / "core.trade")
        .read_text()
        .replace("when true", "when close > 100.00004 price")
        .replace(
            "close >= 112 price",
            f"SMA(1) > {next_value} price and close / open < 98.7654321%",
        )
        .replace("100% of equity", "12.3456789% of equity")
        .replace("1000 USDT", "1000.00004 USDT")
        .replace("fee 0", "fee 0.1234567")
        .replace("slippage 0", "slippage 1.234567")
    )
    path.write_text(source)
    code, r = cli("explain", path)
    assert code == 0, r
    text = r["result"]["text"]
    for fragment in (
        "100.00004 price",
        f"{next_value} price",
        "SMA(close, 1)",
        repr(12.3456789 / 100),
        f"(close / open) < {98.7654321 / 100!r}",
        "1000.00004 USDT",
        "0.1234567 bps",
        "1.234567 bps",
    ):
        assert fragment in text
    candles = tmp_path / "candles.csv"
    candles.write_text(
        (FIX / "core.csv").read_text().replace(",100,10\n", ",100.00002,10\n")
    )
    code, r = cli(
        "backtest",
        path,
        "--data",
        candles,
        "--metadata",
        FIX / "metadata.json",
        "--out",
        tmp_path / "run",
    )
    assert code == 0, r
    events = [
        json.loads(line)
        for line in (tmp_path / "run/events.jsonl").read_text().splitlines()
    ]
    assert not any(e["side"] == "buy" and e["bar_index"] == 0 for e in events)
    assert any(e["side"] == "buy" and e["reason"] == "buy" for e in events)


@pytest.mark.parametrize("reason", ["signal_exit", "stop_gap"])
def test_exit_underflow_fails_atomically(tmp_path, reason):
    strategy = tmp_path / "tiny.trade"
    source = (FIX / "core.trade").read_text().replace("capital 1000", "capital 1e-100")
    if reason == "stop_gap":
        source = source.replace("close >= 112 price", "false").replace(
            "backtest:", "risk: stop loss 10%\nbacktest:"
        )
    strategy.write_text(source)
    data = tmp_path / "tiny.csv"
    candles = (FIX / "core.csv").read_text()
    data.write_text(
        candles.replace("120,125,115,120,30", ",".join(["1e-250"] * 4 + ["30"]))
    )
    out = tmp_path / "run"
    args = (
        "backtest",
        strategy,
        "--data",
        data,
        "--metadata",
        FIX / "metadata.json",
        "--out",
        out,
    )
    code, response = cli(*args)
    assert code == 4, response
    assert response["ok"] is False and response["result"] is None
    diagnostic = response["diagnostics"][0]
    assert diagnostic["code"] == "E_NUMERIC_EXECUTION"
    assert diagnostic["details"] == {"bar_index": 2, "exit_reason": reason}
    assert not out.exists()
    failures = list(tmp_path.glob(".run-*/failure.json"))
    assert failures and not (failures[0].parent / "manifest.json").exists()
    data.write_text(
        candles.replace("120,125,115,120,30", ",".join(["1e-215"] * 4 + ["30"]))
    )
    code, response = cli(*args)
    assert code == 0, response
    assert 0 < response["result"]["summary"]["final_equity"] < 2.2250738585072014e-308


def test_roc_counts_zero_once_through_cli(tmp_path):
    source = (
        (FIX / "core.trade")
        .read_text()
        .replace("entry:", "let z = (close - close) / close\nlet r = ROC(z,1)\nentry:")
        .replace("when true", "when r > 0 or not (r > 0)")
    )
    path = tmp_path / "roc.trade"
    path.write_text(source)
    code, response = cli(
        "backtest",
        path,
        "--data",
        FIX / "core.csv",
        "--metadata",
        FIX / "metadata.json",
        "--out",
        tmp_path / "run",
    )
    assert code == 0, response
    counts = response["result"]["summary"]["counts"]
    assert counts["unavailable_by_reason"]["zero_denominator"] == 2
    assert counts["signals"] == 0


def test_roc_reports_only_valid_window_zero_bases():
    result = execute(*scenario(entry="ROC(volume / 10 volume - 1,1) > 0", exit="false"))
    assert result["summary"]["counts"]["unavailable_by_reason"]["zero_denominator"] == 1
    assert result["summary"]["counts"]["expired_orders"] == 1
    result = execute(*scenario("invalid", entry="ROC(close / (high - low),2) > 0"))
    assert result["summary"]["counts"]["unavailable_by_reason"]["zero_denominator"] == 2
    assert result["summary"]["counts"]["signals"] == 0


@pytest.mark.parametrize(
    "args",
    [
        ("validate",),
        ("validate", FIX / "core.trade", "--no-such-option"),
        ("backtest", FIX / "core.trade"),
    ],
)
def test_cli_usage_error_envelope(args):
    code, response = cli(*args)
    assert code == 3 and response["ok"] is False and response["result"] is None
    assert (
        response["command"] == args[0]
        and response["diagnostics"][0]["code"] == "E_USAGE"
    )


def test_cli_human_data_row_and_version(tmp_path):
    candles = tmp_path / "invalid.csv"
    candles.write_text((FIX / "core.csv").read_text().replace(",102,", ",99,", 1))
    args = (
        "validate",
        FIX / "core.trade",
        "--data",
        candles,
        "--metadata",
        FIX / "metadata.json",
    )
    code, response = cli(*args)
    assert code == 2 and response["diagnostics"][0]["data_row"] == 1
    p = subprocess.run(["tradelang", *map(str, args)], capture_output=True, text=True)
    assert p.returncode == 2 and "E401_DATA at data row 1" in p.stderr
    p = subprocess.run(
        ["tradelang", "--version"], capture_output=True, text=True, check=True
    )
    assert p.stdout.strip() == version("tradelang")


def test_equity_exports_and_archive_version(tmp_path):
    strategy = tmp_path / "dual.trade"
    strategy.write_bytes(
        scenario("dual-touch", risk="risk: stop loss 10% take profit 10%")[0].source
    )
    out = tmp_path / "run"
    code, response = cli(
        "backtest",
        strategy,
        "--data",
        FIX / "dual-touch.csv",
        "--metadata",
        FIX / "metadata.json",
        "--out",
        out,
    )
    assert code == 0, response
    table = pq.read_table(out / "equity.parquet")
    assert str(table.schema.field("exposed").type) == "bool"
    assert str(table.schema.field("cumulative_return").type) == "double"
    rows = table.to_pylist()
    assert [row["exposed"] for row in rows] == [False, False, True, False]
    assert rows[2]["quantity"] == 0 and rows[2]["cumulative_return"] == pytest.approx(
        -0.1
    )
    summary = response["result"]["summary"]
    assert summary["metrics"]["exposure_fraction"] == 1 / 3
    assert rows[-1]["cumulative_return"] == summary["metrics"]["total_return"]
    with (out / "equity.csv").open() as handle:
        csv_rows = list(csv.DictReader(handle))
    assert [r["exposed"] for r in csv_rows] == ["false", "false", "true", "false"]
    assert [float(r["cumulative_return"]) for r in csv_rows] == table[
        "cumulative_return"
    ].to_pylist()
    manifest = json.loads((out / "manifest.json").read_text())
    assert manifest["schema_version"] == 2
    assert manifest["dsl_version"] == 1
    assert manifest["semantics_version"] == "1.1.0"
    with zipfile.ZipFile(out / "source-package.zip") as archive:
        names = archive.namelist()
        assert "tradelang/api/strategy.schema.json" in names
        assert not any("__pycache__" in n for n in names)
        assert manifest["code_revision"] == hash_json(
            {n.removeprefix("tradelang/"): digest(archive.read(n)) for n in names}
        )
    if manifest["release_lock_hash"] is not None:
        assert manifest["release_lock_hash"] == digest((out / "uv.lock").read_bytes())


def test_exposure_counts_opening_gap_liquidation_and_cash_only_bars():
    source, data = scenario("gap-stop", risk="risk: stop loss 10%")
    result = execute(source, data)
    assert [row["exposed"] for row in result["equity"]] == [False, False, True, True]
    assert result["equity"][-1]["quantity"] == 0
    assert result["summary"]["metrics"]["exposure_fraction"] == 2 / 3
    result = execute(*scenario(entry="false"))
    assert not any(row["exposed"] for row in result["equity"])
    assert result["summary"]["metrics"]["exposure_fraction"] == 0


def test_nested_package_resource_changes_code_revision(tmp_path):
    package = tmp_path / "tradelang"
    nested = package / "api"
    nested.mkdir(parents=True)
    resource = nested / "strategy.schema.json"
    resource.write_bytes(b"{}")
    archive = tmp_path / "source-package.zip"
    before = package_revision(package, archive)
    resource.write_bytes(b"{}\n")
    after = package_revision(package, archive)
    assert before != after
    assert after == hash_json({"api/strategy.schema.json": digest(b"{}\n")})
