"""One cash account over ordered, independently observed candles."""

import json
from dataclasses import replace
from pathlib import Path

import pyarrow.parquet as pq
import pytest

from tradelang.compiler import compile_source
from tradelang.data import load_dataset
from tradelang.model import Problem
from tradelang.portfolio import (
    AssetInputs,
    compile_portfolio,
    execute_portfolio,
    prepare_portfolio,
)
from tradelang.portfolio_report import load_portfolio_inputs, publish_portfolio

HEADER = "timestamp,open,high,low,close,volume\n"
SOURCE = """tradelang 9
portfolio "Shared cash"
asset alpha
asset beta
capital 1000 USD
max open positions 2
"""
STRATEGY = """tradelang 8
strategy "One asset"
market {market}
timeframe {timeframe}
entry:
  when {entry}
  buy using {budget} USD
exit:
  when {exit}
  sell all
{risk}
backtest:
  from 2024-01-01 to 2024-01-03
  capital 1000 USD
  fee 0 bps per side
  slippage 0 bps per side
  execute at next bar open
  calendar 24x7
"""


def data(tmp_path, market, rows, timeframe="1d"):
    path = tmp_path / f"{market}.csv"
    path.write_text(
        HEADER + "".join(f"{timestamp},{prices},100\n" for timestamp, prices in rows)
    )
    return load_dataset(
        path,
        {
            "symbol": market,
            "quote_currency": "USD",
            "timeframe": timeframe,
            "calendar": "24x7",
            "timestamp_convention": "bar_open",
            "price_basis": "raw_spot",
            "volume_unit": "base_quantity",
        },
    )


def daily(tmp_path, market, closes=(100, 100, 120)):
    return data(
        tmp_path,
        market,
        [
            (
                f"2024-01-0{i}T00:00:00Z",
                f"100,{max(100, close)},{min(100, close)},{close}",
            )
            for i, close in enumerate(closes, 1)
        ],
    )


def asset(dataset, *, budget=750, entry="close == 100 price", exit="false", risk=""):
    return AssetInputs(
        compile_source(
            STRATEGY.format(
                market=dataset.meta.symbol,
                timeframe=dataset.meta.timeframe,
                budget=budget,
                entry=entry,
                exit=exit,
                risk=risk,
            )
        ),
        dataset,
    )


def fills(result):
    return [e for e in result["events"] if e["kind"] == "fill"]


def test_shared_cash_reconciles_and_declaration_order_changes_winner(tmp_path):
    inputs = {
        "beta": asset(daily(tmp_path, "BETA", (100, 100, 80))),
        "alpha": asset(daily(tmp_path, "ALPHA")),
    }
    spec = compile_portfolio(SOURCE)
    result = execute_portfolio(spec, inputs)
    (fill,) = fills(result)
    assert (fill["asset"], fill["quantity"], fill["cash_after"]) == ("alpha", 7.5, 250)
    denied = next(e for e in result["events"] if e["kind"] == "entry_rejected")
    assert (denied["asset"], denied["reason"]) == ("beta", "insufficient_cash")
    assert denied["trace"]["capital"]["available_cash"] == 250
    assert result["summary"]["final_equity"] == 1150
    assert result["summary"]["assets"][0]["market_value"] == 900
    assert result["summary"]["assets"][0]["mark_at"] == "2024-01-04T00:00:00Z"
    assert (
        result["equity"][-1]["cash"] + result["equity"][-1]["net_market_value"] == 1150
    )
    assert result == execute_portfolio(spec, inputs)

    reversed_spec = compile_portfolio(
        SOURCE.replace("asset alpha\nasset beta", "asset beta\nasset alpha")
    )
    reversed_result = execute_portfolio(reversed_spec, inputs)
    assert fills(reversed_result)[0]["asset"] == "beta"
    assert reversed_result["summary"]["final_equity"] == 850


def test_aggregate_mark_overflow_reports_a_numerical_execution_error(tmp_path):
    inputs = {
        name: asset(daily(tmp_path, name.upper(), (100, 100, 200)), budget="5e307")
        for name in ("alpha", "beta")
    }
    spec = compile_portfolio(SOURCE.replace("1000 USD", "1e308 USD"))
    prepared = prepare_portfolio(spec, inputs)
    out = tmp_path / "overflow"

    with pytest.raises(Problem, match="Nonfinite portfolio ledger total") as error:
        publish_portfolio(prepared, out)

    assert error.value.diagnostic["code"] == "E_NUMERIC_EXECUTION"
    assert not out.exists()


def test_cross_asset_order_cannot_spend_intrabar_exit_before_containing_close(tmp_path):
    primary = data(
        tmp_path,
        "ALPHA",
        [
            ("2024-01-01T00:00:00Z", "100,100,100,100"),
            ("2024-01-02T00:00:00Z", "100,120,95,115"),
            ("2024-01-03T00:00:00Z", "100,100,100,100"),
        ],
    )
    secondary = data(
        tmp_path,
        "BETA",
        [
            (f"2024-01-0{day}T{hour}:00:00Z", f"100,100,{close},{close}")
            for day, hour, close in [
                (1, "00", 100),
                (1, "12", 100),
                (2, "00", 90),
                (2, "12", 90),
                (3, "00", 100),
                (3, "12", 100),
            ]
        ],
        "12h",
    )
    result = execute_portfolio(
        compile_portfolio(SOURCE),
        {
            "alpha": asset(primary, budget=1000, risk="risk:\n  take profit 20%"),
            "beta": asset(secondary, entry="close == 90 price"),
        },
    )
    buy, touch, beta = fills(result)
    assert buy["asset"] == "alpha"
    rejection = next(e for e in result["events"] if e["kind"] == "entry_rejected")
    assert (rejection["asset"], rejection["observed_at"], rejection["reason"]) == (
        "beta",
        "2024-01-02T12:00:00Z",
        "insufficient_cash",
    )
    assert (touch["reason"], touch["time_precision"], touch["observed_at"]) == (
        "target_touch",
        "bar",
        "2024-01-03T00:00:00Z",
    )
    assert touch["bar_open_at"] < touch["observed_at"]
    assert (beta["asset"], beta["observed_at"], beta["cash_after"]) == (
        "beta",
        touch["observed_at"],
        450,
    )
    assert touch["sequence"] < beta["sequence"]
    assert result["summary"]["final_equity"] == 1200


def test_simultaneous_reduction_frees_cash_before_earlier_declared_entry(tmp_path):
    result = execute_portfolio(
        compile_portfolio(
            SOURCE.replace("asset alpha\nasset beta", "asset beta\nasset alpha")
        ),
        {
            "alpha": asset(
                daily(tmp_path, "ALPHA", (100, 105, 120)),
                budget=1000,
                exit="close == 105 price",
            ),
            "beta": asset(
                daily(tmp_path, "BETA", (100, 105, 120)), entry="close == 105 price"
            ),
        },
    )
    _, sale, new_entry = fills(result)
    assert (sale["asset"], sale["reason"], sale["cash_after"]) == (
        "alpha",
        "signal_exit",
        1000,
    )
    assert (new_entry["asset"], new_entry["cash_after"]) == ("beta", 250)
    assert sale["observed_at"] == new_entry["observed_at"]
    assert sale["sequence"] < new_entry["sequence"]


def test_short_reserves_sale_proceeds_and_initial_collateral(tmp_path):
    path = Path("docs/fixtures/short/round-trip.csv")
    primary = load_dataset(path, json.loads(path.with_suffix(".json").read_text()))
    portfolio = execute_portfolio(
        compile_portfolio(SOURCE),
        {
            "alpha": AssetInputs(
                compile_source(path.with_suffix(".trade").read_bytes()), primary
            ),
            "beta": asset(daily(tmp_path, "BETA", (100, 101, 120))),
        },
    )
    short, cover = fills(portfolio)
    assert (
        short["side"],
        short["quantity_after"],
        short["margin"]["available_cash"],
    ) == (
        "short",
        -5,
        745,
    )
    rejection = next(e for e in portfolio["events"] if e["kind"] == "entry_rejected")
    assert rejection["trace"]["capital"]["available_cash"] == 745
    assert cover["side"] == "cover"
    assert portfolio["summary"]["reserved_cash"] == 0
    assert portfolio["summary"]["final_equity"] == 1035.5


def test_position_limit_and_currency_checks(tmp_path):
    inputs = {
        "alpha": asset(daily(tmp_path, "ALPHA"), budget=250),
        "beta": asset(daily(tmp_path, "BETA"), budget=250),
    }
    result = execute_portfolio(
        compile_portfolio(SOURCE.replace("positions 2", "positions 1")), inputs
    )
    assert len(fills(result)) == 1
    assert any(
        event["reason"] == "portfolio_position_limit" for event in result["events"]
    )
    with pytest.raises(Problem, match="currency EUR"):
        execute_portfolio(compile_portfolio(SOURCE.replace("USD", "EUR")), inputs)


def test_exchange_closure_does_not_block_or_move_other_market_opens(tmp_path):
    path = Path("docs/fixtures/exchange/session.csv")
    equity = load_dataset(path, json.loads(path.with_suffix(".json").read_text()))
    continuous = data(
        tmp_path,
        "BETA",
        [(f"2024-11-{day}T00:00:00Z", "100,100,100,100") for day in (27, 28, 29, 30)],
    )
    beta = STRATEGY.format(
        market="BETA",
        timeframe="1d",
        budget=1000,
        entry="close == 100 price",
        exit="false",
        risk="",
    )
    beta = beta.replace("2024-01-01 to 2024-01-03", "2024-11-27 to 2024-11-30")
    result = execute_portfolio(
        compile_portfolio(SOURCE),
        {
            "alpha": AssetInputs(
                compile_source(path.with_suffix(".trade").read_bytes()), equity
            ),
            "beta": AssetInputs(compile_source(beta), continuous),
        },
    )
    (winner,) = fills(result)
    assert (winner["asset"], winner["observed_at"]) == ("beta", "2024-11-28T00:00:00Z")
    denied = next(e for e in result["events"] if e["kind"] == "entry_rejected")
    assert (denied["asset"], denied["observed_at"]) == ("alpha", "2024-11-29T14:30:00Z")
    assert (
        result["summary"]["assets"][0]["warning_counts"].get("W_MISSING_BARS", 0) == 0
    )


def test_portfolio_bundle_preserves_order_inputs_fingerprint_and_replay(tmp_path):
    fixture = Path("docs/fixtures/portfolio")
    spec = compile_portfolio((fixture / "priority.trade").read_bytes())
    inputs = load_portfolio_inputs(spec, fixture / "inputs.json")
    bundle = tmp_path / "bundle"
    original = publish_portfolio(prepare_portfolio(spec, inputs), bundle)
    replay_spec = compile_portfolio((bundle / "source.trade").read_bytes())
    replayed = load_portfolio_inputs(replay_spec, bundle / "run-config.json")
    replay = publish_portfolio(
        prepare_portfolio(replay_spec, replayed), tmp_path / "replay"
    )
    assert replay["run_fingerprint"] == original["run_fingerprint"]
    assert replay["result_digest"] == original["result_digest"]
    manifest = json.loads((bundle / "manifest.json").read_text())
    assert manifest["semantics_version"] == "9.0.0"
    assert [entry["asset"] for entry in manifest["assets"]] == ["alpha", "beta"]
    evidence = manifest["assets"][1]["decision_inspection"]
    rows = pq.read_table(bundle / evidence["artifact"]).to_pylist()
    row = rows[1]
    assert (row["fill_cash"], row["entry_equity"], row["budget"]) == (250, 1000, 750)
    journal = (bundle / evidence["events_artifact"]).read_bytes()
    events = [
        json.loads(line)
        for line in journal[row["event_offset"] : row["event_end"]].splitlines()
    ]
    assert all(event["asset"] == "beta" for event in events)
    assert any(event["reason"] == "insufficient_cash" for event in events)
    reversed_spec = compile_portfolio(
        SOURCE.replace("asset alpha\nasset beta", "asset beta\nasset alpha")
    )
    reversed_run = publish_portfolio(
        prepare_portfolio(reversed_spec, inputs), tmp_path / "reversed"
    )
    assert reversed_run["run_fingerprint"] != original["run_fingerprint"]
    changed = daily(tmp_path, "BETA", (100, 100, 90))
    inputs["beta"] = replace(inputs["beta"], primary=changed)
    changed_run = publish_portfolio(
        prepare_portfolio(spec, inputs), tmp_path / "changed"
    )
    assert changed_run["run_fingerprint"] != original["run_fingerprint"]


def test_portfolio_named_feed_keeps_native_close_and_replays(tmp_path):
    fixture = Path("docs/fixtures/feeds")
    primary = load_dataset(
        fixture / "primary.csv", json.loads((fixture / "primary.json").read_text())
    )
    feed = load_dataset(
        fixture / "trend.csv", json.loads((fixture / "trend.json").read_text())
    )
    source = (fixture / "trend.trade").read_text()
    beta_source = source.replace(primary.meta.symbol, "BETA").replace(
        "when close crosses above regime", "when false"
    )
    beta_path = tmp_path / "beta.csv"
    beta_path.write_bytes((fixture / "primary.csv").read_bytes())
    beta_meta = primary.meta.model_dump()
    beta_meta["symbol"] = "BETA"
    beta = load_dataset(beta_path, beta_meta)
    beta_feed_path = tmp_path / "beta-feed.csv"
    beta_feed_path.write_bytes((fixture / "trend.csv").read_bytes())
    beta_feed_meta = feed.meta.model_dump()
    beta_feed_meta["symbol"] = "BETA"
    beta_feed = load_dataset(beta_feed_path, beta_feed_meta)
    spec = compile_portfolio(SOURCE.replace("USD", primary.meta.quote_currency))
    inputs = {
        "alpha": AssetInputs(compile_source(source), primary, feeds={"trend": feed}),
        "beta": AssetInputs(
            compile_source(beta_source), beta, feeds={"trend": beta_feed}
        ),
    }
    result = execute_portfolio(spec, inputs)
    first = next(
        event
        for event in result["events"]
        if event["kind"] == "fill" and event["asset"] == "alpha"
    )
    assert first["bar_index"] == 8
    bundle = tmp_path / "feed-bundle"
    original = publish_portfolio(prepare_portfolio(spec, inputs), bundle)
    reloaded = load_portfolio_inputs(spec, bundle / "run-config.json")
    replay = publish_portfolio(
        prepare_portfolio(spec, reloaded), tmp_path / "feed-replay"
    )
    assert replay["run_fingerprint"] == original["run_fingerprint"]
    assert replay["result_digest"] == original["result_digest"]
