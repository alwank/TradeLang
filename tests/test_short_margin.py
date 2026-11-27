"""Hand-calculated short, financing, protection, and replay contracts."""

import json
from pathlib import Path

import pytest

from tradelang.api.contracts import AST_VALIDATOR_V8
from tradelang.compiler import compile_source
from tradelang.data import load_dataset
from tradelang.engine import execute
from tradelang.model import Problem
from tradelang.report import publish

FIXTURE = Path("docs/fixtures/short/round-trip.csv")
SOURCE = FIXTURE.with_suffix(".trade").read_text()
METADATA = json.loads(FIXTURE.with_suffix(".json").read_text())
HEADER = "timestamp,open,high,low,close,volume\n"


def run(source=SOURCE, candles=FIXTURE):
    return execute(compile_source(source), load_dataset(candles, METADATA))


def candles(tmp_path, replacement, *, day=3):
    path = tmp_path / "candles.csv"
    lines = FIXTURE.read_text().splitlines()
    lines[day] = f"2024-01-{day:02d}T00:00:00Z," + replacement
    path.write_text("\n".join(lines) + "\n")
    return path


def fills(result):
    return [item for item in result["events"] if item["kind"] == "fill"]


def test_short_round_trip_and_replay_reconcile_cash_collateral_and_borrow(tmp_path):
    strategy = compile_source(SOURCE)
    AST_VALIDATOR_V8.validate(strategy.public())
    data = load_dataset(FIXTURE, METADATA)
    result = execute(strategy, data)
    entry, cover = fills(result)
    assert (entry["side"], entry["quantity_after"], entry["cash_after"]) == (
        "short",
        -5,
        1495,
    )
    assert entry["margin"] == dict(
        initial_margin=250,
        restricted_proceeds=500,
        reserved_cash=750,
        available_cash=745,
    )
    assert (result["equity"][2]["quantity"], result["equity"][2]["equity"]) == (
        -5,
        1015,
    )
    borrow = next(e for e in result["events"] if e["kind"] == "borrow_charged")
    assert (borrow["cash_after"], borrow["elapsed_seconds"], borrow["borrow_cost"]) == (
        1490,
        86400,
        5,
    )
    assert (cover["side"], cover["cash_delta"], cover["cash_after"]) == (
        "cover",
        -454.5,
        1035.5,
    )
    assert cover["ledger"]["borrow_cost_released"] == 5
    assert cover["ledger"]["realized_net_pnl"] == 35.5
    assert cover["margin"]["reserved_cash"] == 0
    (trade,) = result["trades"]
    assert (trade["direction"], trade["initial_collateral"], trade["borrow_cost"]) == (
        "short",
        250,
        5,
    )
    assert trade["return_fraction"] == pytest.approx(35.5 / 255)
    assert result["summary"]["final_equity"] == 1035.5
    assert result["summary"]["costs"]["total_fees"] == 9.5
    assert result["summary"]["costs"]["total_borrow_cost"] == 5

    bundle = tmp_path / "bundle"
    original = publish(strategy, data, bundle)
    manifest = json.loads((bundle / "manifest.json").read_text())
    assert manifest["position_ledger"]["schema_version"] == 2
    assert manifest["resolved_policy"]["short_margin"]["model"] == "borrowed_asset_v1"
    assert "initial_collateral,borrow_cost" in (bundle / "trades.csv").read_text()
    reloaded = load_dataset(bundle / "input.csv", manifest["dataset_metadata"])
    replay = publish(strategy, reloaded, tmp_path / "replay")
    assert replay["run_fingerprint"] == original["run_fingerprint"]
    assert replay["result_digest"] == original["result_digest"]


@pytest.mark.parametrize(
    "open_price,reason,final,insolvent",
    [
        (125, "stop_gap", 858.75, False),
        (320, "liquidation_gap", -126.0, True),
    ],
)
def test_adverse_gap_preempts_signal_and_reconciles_deficit(
    tmp_path, open_price, reason, final, insolvent
):
    path = candles(tmp_path, f"{open_price},{open_price},{open_price},{open_price},1")
    result = run(candles=path)
    _, cover = fills(result)
    assert (cover["reason"], cover["fill_price"], cover["phase"]) == (
        reason,
        open_price,
        1,
    )
    assert result["summary"]["final_cash"] == final
    assert result["summary"]["short_accounting"]["insolvent"] is insolvent
    assert result["summary"]["short_accounting"]["liquidations"] == int(insolvent)
    assert result["trades"][0]["net_pnl"] == final - 1000
    assert any(e["kind"] == "order_cancelled" for e in result["events"])
    if insolvent:
        assert cover["maintenance_trigger"] == pytest.approx(1490 / (5 * 1.26))
        assert result["summary"]["metrics"]["max_drawdown"] > 1
        assert result["summary"]["metrics"]["sharpe"] is None
        assert result["summary"]["metrics"]["cagr"] is None


@pytest.mark.parametrize(
    "stop,reason,reference",
    [
        ("20%", "stop_touch", 120),
        ("200 price", "liquidation_touch", 1495 / (5 * 1.26)),
    ],
)
def test_short_intrabar_adverse_priority(tmp_path, stop, reason, reference):
    path = candles(tmp_path, "100,250,95,95,100", day=2)
    result = run(SOURCE.replace("20%", stop), path)
    _, cover = fills(result)
    assert cover["reason"] == reason
    assert cover["time_precision"] == "bar"
    assert cover["fill_price"] == pytest.approx(reference)
    assert result["summary"]["costs"]["total_borrow_cost"] == 0


def test_borrow_can_trigger_liquidation_at_close_without_earlier_touch(tmp_path):
    source = (
        SOURCE.replace("255 USD", "100% of equity")
        .replace("maintenance margin 25%", "maintenance margin 49%")
        .replace("fee 100 bps", "fee 0 bps")
        .replace("borrow 100 bps", "borrow 1000 bps")
    )
    result = run(source, candles(tmp_path, "100,100,100,100,100", day=2))
    _, cover = fills(result)
    assert cover["reason"] == "liquidation_close"
    assert cover["maintenance_trigger"] == pytest.approx(2800 / (20 * 1.49))
    assert cover["time_precision"] == "close"
    assert cover["observed_at"] == "2024-01-03T00:00:00Z"
    assert result["trades"][0]["exit_at"] == cover["observed_at"]
    assert result["summary"]["final_equity"] == 800


def test_partial_cover_releases_borrow_and_collateral_then_accrues_on_remainder(
    tmp_path,
):
    path = tmp_path / "candles.csv"
    path.write_text(FIXTURE.read_text() + "2024-01-04T00:00:00Z,90,91,89,90,100\n")
    source = SOURCE.replace(
        "when close == 95 price\n  cover all",
        "rule timer after 2 bars cover all\n  rule trim when close == 95 price cover 50% of position",
    ).replace("to 2024-01-03", "to 2024-01-04")
    result = run(source, path)
    _, partial, closed = fills(result)
    assert partial["quantity_after"] == -2.5
    assert partial["margin"]["reserved_cash"] == 375
    assert partial["ledger"]["borrow_cost_released"] == 2.5
    assert closed["ledger"]["borrow_cost_released"] == 5
    assert result["summary"]["costs"]["total_borrow_cost"] == 7.5
    assert result["summary"]["final_cash"] == 1033
    assert result["trades"][0]["net_pnl"] == 33


def test_adverse_slippage_and_lot_rounding(tmp_path):
    source = SOURCE.replace("slippage 0 bps", "slippage 100 bps").replace(
        "stop loss 20%", "stop loss 20%\n  quantity step 1 units"
    )
    result = run(source)
    short, cover = fills(result)
    assert short["quantity_after"] == -5
    assert short["fill_price"] == 99
    assert cover["fill_price"] == pytest.approx(90.9)
    assert cover["quantity_after"] == 0
    assert result["summary"]["final_cash"] == pytest.approx(1026.055)


def test_open_short_marks_borrow_and_locked_cash_through_final_close():
    result = run(SOURCE.replace("to 2024-01-03", "to 2024-01-02"))
    summary = result["summary"]
    assert summary["final_cash"] == 1490
    assert summary["final_equity"] == 1015
    assert summary["short_accounting"]["available_cash"] == 740
    assert summary["short_accounting"]["reserved_cash"] == 750
    holding = summary["open_position"]
    assert holding["quantity"] == -5
    assert holding["remaining_borrow_cost"] == 5
    assert holding["unrealized_net"] == 15
    assert not result["trades"]


def test_short_trail_moves_down_at_next_open_and_wins_dual_touch(tmp_path):
    before = candles(tmp_path, "100,110,95,95,100", day=2)
    path = tmp_path / "touch.csv"
    path.write_text(
        "\n".join(before.read_text().splitlines()[:3])
        + "\n2024-01-03T00:00:00Z,100,110,80,100,100\n"
    )
    source = SOURCE.replace("when close == 95 price", "when false").replace(
        "stop loss 20%", "stop loss 20%\n  trailing stop 10 price\n  take profit 15%"
    )
    result = run(source, path)
    trail = next(e for e in result["events"] if e["kind"] == "trail_queued")
    assert trail["reason"] == "lower_stop"
    assert trail["trail"]["trigger_price"] == 105
    cover = fills(result)[-1]
    assert cover["reason"] == "stop_dual_touch"
    assert cover["observed_at"] == "2024-01-03T00:00:00Z"
    assert cover["fill_price"] == 105


def test_scheduled_split_and_closure_accrue_actual_utc_duration():
    session = Path("docs/fixtures/exchange/session.csv")
    source = (
        SOURCE.replace("when close == 95 price", "when close >= 110 price")
        .replace("calendar 24x7", "calendar session")
        .replace("2024-01-01 to 2024-01-03", "2024-11-27 to 2024-12-03")
        .replace("stop loss 20%", "stop loss 30%")
    )
    data = load_dataset(session, json.loads(session.with_suffix(".json").read_text()))
    result = execute(compile_source(source), data)
    short, cover = fills(result)
    assert short["observed_at"] == "2024-11-29T14:30:00Z"
    assert cover["reason"] == "signal_exit"
    assert cover["split_factor"] == 2
    assert cover["fill_price"] == 120
    assert sum(e.get("elapsed_seconds", 0) for e in result["events"]) == 4 * 86400
    assert result["summary"]["costs"]["total_borrow_cost"] == pytest.approx(20)
    assert result["summary"]["final_cash"] == pytest.approx(869)


@pytest.mark.parametrize(
    "old,new",
    [
        ("cover all", "sell all"),
        ("short using", "buy using"),
        ("maintenance margin 25%", "maintenance margin 50%"),
        ("borrow 100 bps", "borrow 10000 bps"),
        ("initial margin 50%\n  maintenance margin 25%\n  borrow 100 bps per day", ""),
    ],
)
def test_short_side_and_terms_have_source_diagnostics(old, new):
    with pytest.raises(Problem) as caught:
        compile_source(SOURCE.replace(old, new))
    assert caught.value.diagnostic["code"] == "E304_MARGIN"
    assert caught.value.diagnostic["span"]["start_byte"] > 0
