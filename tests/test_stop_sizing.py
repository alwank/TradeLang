"""Scope, order sizing, and cash ledger cases for a long with a protective stop."""

import json
import math
from dataclasses import replace
from pathlib import Path

import pytest

from tradelang.api.contracts import AST_VALIDATOR_V4
from tradelang.compiler import compile_source
from tradelang.data import load_dataset
from tradelang.engine import execute
from tradelang.model import Problem
from tradelang.report import explain

FIXTURES = Path("docs/fixtures")
DATA = FIXTURES / "risk-sizing" / "stop-risk.csv"
SOURCE = DATA.with_suffix(".trade").read_text()
META = json.loads((FIXTURES / "metadata.json").read_text())


def fills(result):
    return [event for event in result["events"] if event["kind"] == "fill"]


@pytest.mark.parametrize(
    "stop, distance, trigger, stop_fill, loss",
    [("10%", 10.1, 90.9, 89.991, 12.91891), ("2 * ATR(1)", 12, 89, 88.11, 14.7811)],
)
def test_percent_and_signal_close_atr_stop_touch(
    stop, distance, trigger, stop_fill, loss
):
    strategy = compile_source(SOURCE.replace("stop loss 10%", f"stop loss {stop}"))
    spec = strategy.public()
    AST_VALIDATOR_V4.validate(spec)
    assert spec["entry"]["sizing"]["kind"] == "stop_risk"
    assert "An opening gap can exceed the modeled loss" in explain(strategy)["text"]
    result = execute(strategy, load_dataset(DATA, META))
    entry, exit = fills(result)
    assert (entry["phase"], entry["bar_index"], entry["fill_price"]) == (3, 1, 101)
    stop = entry["protection"]["stop"]
    assert stop["sampled_bar"] == 0
    assert stop["distance"] == pytest.approx(distance)
    assert stop["trigger_price"] == pytest.approx(trigger)
    assert (exit["reason"], exit["bar_index"]) == ("stop_touch", 2)
    assert exit["fill_price"] == pytest.approx(stop_fill)
    sizing = entry["trace"]["risk_sizing"]
    quantity = 20 / loss
    assert sizing["loss_per_unit"] == pytest.approx(loss)
    assert sizing["entry_debit_per_unit"] == pytest.approx(102.01)
    assert sizing["modeled_loss"] == pytest.approx(20)
    assert sizing["risk_budget"] == 20
    assert sizing["cash_available"] == 1000
    assert sizing["allocation_limit"] == 500
    assert sizing["binding_constraint"] == "risk_budget"
    assert sizing["quantity"] == entry["quantity"] == exit["quantity"]
    assert entry["quantity"] == pytest.approx(quantity)
    assert entry["fee"] == pytest.approx(quantity * 1.01)
    assert exit["fee"] == pytest.approx(quantity * stop_fill * 0.01)
    assert entry["cash_delta"] == pytest.approx(-quantity * 102.01)
    assert result["trades"][0]["net_pnl"] == pytest.approx(-20)
    assert result["trades"][0]["entry_rationale"]["risk_sizing"] == sizing
    assert result["summary"]["final_equity"] == pytest.approx(980)


def test_allocation_and_cash_limits_with_boundary_rounding():
    data = load_dataset(DATA, META)
    source = SOURCE.replace(
        "100 bps per side\n  slippage 100 bps", "200 bps per side\n  slippage 0 bps"
    )
    capped = compile_source(
        source, parameters={"risk_fraction": 0.01, "allocation_limit": 0.03}
    )
    result = execute(capped, data)
    entry = fills(result)[0]
    sizing = entry["trace"]["risk_sizing"]
    assert sizing["binding_constraint"] == "allocation"
    assert sizing["allocation_limit"] == 30
    unit_debit = 100 + 100 * 0.02
    assert sizing["rounded_down"]
    assert sizing["quantity"] == math.nextafter(30 / unit_debit, 0)
    assert -entry["cash_delta"] <= 30
    assert sizing["modeled_loss"] <= 10

    uncapped = compile_source(
        SOURCE.replace(" max allocation allocation_limit of equity", ""),
        parameters={"risk_fraction": 0.5},
    )
    entry = fills(execute(uncapped, data))[0]
    sizing = entry["trace"]["risk_sizing"]
    assert sizing["binding_constraint"] == "cash"
    assert sizing["allocation_limit"] == sizing["cash_available"] == 1000
    assert sizing["quantity"] == pytest.approx(1000 / 102.01)
    assert 0 <= entry["cash_after"] < 1e-10


def test_capped_size_combines_signal_close_with_fill_cash_and_proposed_open():
    source = SOURCE.replace(
        "allocation allocation_limit", "allocation (close * 1 volume / equity)"
    )
    dataset = load_dataset(DATA, META)
    values = dataset.values.copy()
    values[1, :4] = [110, 116, 105, 111]
    result = execute(compile_source(source), replace(dataset, values=values))
    entry = fills(result)[0]
    sizing = entry["trace"]["risk_sizing"]
    assert sizing["allocation_limit"] == 100
    assert sizing["entry_open"] == 110
    assert sizing["entry_fill_price"] == pytest.approx(111.1)
    assert sizing["stop_trigger_price"] == pytest.approx(99.99)
    assert sizing["quantity"] == pytest.approx(100 / (111.1 * 1.01))


@pytest.mark.parametrize(
    "old,new,message",
    [
        ("risk:\n  stop loss 10%\n", "", "requires a stop loss"),
        ("stop loss 10%", "stop loss 100%", "Invalid risk distance"),
        ("risking risk_fraction", "risking 101%", "Invalid risk fraction amount"),
        (
            "allocation allocation_limit",
            "allocation 50 price",
            "Invalid allocation cap dimension",
        ),
    ],
)
def test_invalid_contracts(old, new, message):
    with pytest.raises(Problem, match=message):
        compile_source(SOURCE.replace(old, new))


@pytest.mark.parametrize(
    "old,new,reason,phase",
    [
        ("stop loss 10%", "stop loss close - close", "invalid_stop", 7),
        ("stop loss 10%", "stop loss 200 price", "invalid_protection", 3),
        ("risking risk_fraction", "risking 200 price / close", "invalid_sizing", 7),
        (
            "allocation allocation_limit",
            "allocation 200 price / close",
            "invalid_allocation_cap",
            7,
        ),
        (
            "allocation allocation_limit",
            "allocation (2000 money / equity)",
            "invalid_allocation_cap",
            3,
        ),
    ],
)
def test_invalid_proposals_leave_cash_and_position_unchanged(old, new, reason, phase):
    result = execute(compile_source(SOURCE.replace(old, new)), load_dataset(DATA, META))
    assert not fills(result)
    assert result["summary"]["final_equity"] == 1000
    assert all(
        point["quantity"] == 0 and point["cash"] == 1000 for point in result["equity"]
    )
    rejected = [
        event for event in result["events"] if event["kind"] == "entry_rejected"
    ]
    assert (rejected[0]["reason"], rejected[0]["phase"]) == (reason, phase)


def test_entry_open_stop_and_later_gap_can_exceed_the_modeled_loss():
    dataset = load_dataset(DATA, META)
    strategy = compile_source(
        SOURCE.replace("when close >= 100 price", "when close == 100 price")
    )
    entry_open = compile_source(
        strategy.source.decode().replace("stop loss 10%", "stop loss 0.5%")
    )
    result = execute(entry_open, dataset)
    entry, exit, *_ = fills(result)
    assert exit["phase"] == 4 and exit["reason"] == "stop_entry_open"
    assert exit["bar_index"] == entry["bar_index"]
    assert exit["reference_price"] == 100
    assert (
        result["trades"][0]["net_pnl"] < -entry["trace"]["risk_sizing"]["modeled_loss"]
    )

    values = dataset.values.copy()
    values[2, :4] = [70, 96, 68, 95]
    result = execute(strategy, replace(dataset, values=values))
    entry, exit = fills(result)
    assert exit["phase"] == 1 and exit["reason"] == "stop_gap"
    assert exit["fill_price"] == pytest.approx(69.3)
    assert (
        result["trades"][0]["net_pnl"] < -entry["trace"]["risk_sizing"]["modeled_loss"]
    )


@pytest.mark.parametrize("sizing", ["100% of equity", "1000 USDT"])
def test_legacy_sizing_preserves_the_golden_fills_in_dsl4(sizing):
    source = (FIXTURES / "core.trade").read_text().replace("100% of equity", sizing)
    dataset = load_dataset(FIXTURES / "core.csv", META)
    original = execute(compile_source(source), dataset)
    updated = execute(compile_source("tradelang 4\n" + source), dataset)
    assert original["events"] == updated["events"]
    assert original["trades"] == updated["trades"]
    assert updated["summary"]["final_equity"] == pytest.approx(1090.909090909091)
