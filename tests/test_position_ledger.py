"""Fill-level cash, weighted-average basis, and causal quantity management."""

import json
from dataclasses import replace
from pathlib import Path

import pytest

from tradelang.api.contracts import AST_VALIDATOR_V6
from tradelang.compiler import compile_source
from tradelang.data import load_dataset
from tradelang.engine import execute
from tradelang.model import Problem
from tradelang.position_ledger import LotStep, PositionLedger
from tradelang.report import explain, publish

FIXTURES = Path("docs/fixtures")
DATA = FIXTURES / "position-ledger" / "position.csv"
SOURCE = DATA.with_suffix(".trade").read_text()
META = json.loads((FIXTURES / "metadata.json").read_text())
FIRST = "sell first_fraction of position"


def run(text=SOURCE, dataset=None):
    return execute(
        compile_source(text), load_dataset(DATA, META) if dataset is None else dataset
    )


def fills(run):
    return [event for event in run["events"] if event["kind"] == "fill"]


def test_two_partial_exits_mark_remaining_basis_and_realized_profit():
    result = run(SOURCE.replace("to 2024-01-06", "to 2024-01-04"))
    assert result["trades"] == []
    assert result["summary"]["final_equity"] == pytest.approx(2086.2)
    assert result["summary"]["position_accounting"][
        "realized_net_pnl"
    ] == pytest.approx(68.2)
    assert result["summary"]["metrics"]["total_fees"] == pytest.approx(16.3)
    holding = result["summary"]["open_position"]
    assert holding["quantity"] == 4.5
    assert holding["remaining_gross_basis"] == 450
    assert holding["remaining_entry_fees"] == 4.5
    assert holding["entry_fill_id"] == "F00000001"
    assert holding["unrealized_gross"] == 22.5
    assert holding["unrealized_net"] == 18


def test_weighted_average_cycle_reconciles_every_fill_and_bundle(tmp_path):
    strategy = compile_source(SOURCE)
    AST_VALIDATOR_V6.validate(strategy.public())
    assert "A matching exit takes priority" in explain(strategy)["text"]
    dataset = load_dataset(DATA, META)
    result = execute(strategy, dataset)
    assert result["summary"]["final_equity"] == pytest.approx(2101.225)
    assert result["summary"]["open_position"] is None
    assert result["summary"]["metrics"]["closed_trades"] == 1
    assert result["summary"]["position_accounting"][
        "realized_net_pnl"
    ] == pytest.approx(101.225)
    fill_rows = fills(result)
    assert [row["reason"] for row in fill_rows] == [
        "entry",
        "partial_exit",
        "partial_exit",
        "scale_in",
        "signal_exit",
    ]
    assert [row["order_id"] for row in fill_rows] == [
        f"O{index:08}" for index in range(1, 6)
    ]
    assert [row["fill_id"] for row in fill_rows] == [
        f"F{index:08}" for index in range(1, 6)
    ]
    assert {row["trade_id"] for row in fill_rows} == {"T000001"}
    assert [row["bar_index"] for row in fill_rows] == [1, 2, 3, 4, 5]
    assert [row["quantity"] for row in fill_rows] == [10, 2.5, 3, 2, 6.5]
    assert [row["cash_after"] for row in fill_rows] == pytest.approx(
        [990, 1287, 1613.7, 1361.2, 2101.225]
    )
    legs = [row["ledger"] for row in fill_rows]
    for field, expected in {
        "quantity_after": [10, 7.5, 4.5, 6.5, 0],
        "remaining_gross_basis": [1000, 750, 450, 700, 0],
        "remaining_entry_fees": [10, 7.5, 4.5, 7, 0],
        "realized_net_pnl": [0, 44.5, 23.7, 0, 33.025],
    }.items():
        assert [leg[field] for leg in legs] == pytest.approx(expected)
    assert [leg["leg"] for leg in legs] == list(range(1, 6))
    (trade,) = result["trades"]
    assert trade["net_pnl"] == pytest.approx(101.225)
    assert trade["quantity"] == 12
    assert trade["entry_price"] == pytest.approx(1250 / 12)
    assert trade["entry_fee"] + trade["exit_fee"] == pytest.approx(
        sum(fill["fee"] for fill in fill_rows)
    )
    assert result["summary"]["metrics"]["total_fees"] == pytest.approx(26.275)
    assert fill_rows[3]["protection"] == fill_rows[0]["protection"]
    assert trade["bars_held"] == 5

    output = tmp_path / "bundle"
    publish(strategy, dataset, output)
    manifest = json.loads((output / "manifest.json").read_text())
    assert manifest["semantics_version"] == "6.0.0"
    assert manifest["position_ledger"] == {
        "schema_version": 1,
        "artifact": "events.jsonl",
    }
    assert [
        json.loads(row)["fill_id"]
        for row in (output / "events.jsonl").read_text().splitlines()
        if json.loads(row)["kind"] == "fill"
    ] == [row["fill_id"] for row in fill_rows]


def test_partial_fill_preserves_protection_for_intrabar_remainder():
    dataset = load_dataset(DATA, META)
    values = dataset.values.copy()
    values[2, 2] = 79
    result = run(dataset=replace(dataset, values=values))
    first_sale, protective_sale = fills(result)[1:]
    assert (first_sale["bar_index"], first_sale["phase"], first_sale["quantity"]) == (
        2,
        2,
        2.5,
    )
    assert (
        protective_sale["bar_index"],
        protective_sale["phase"],
        protective_sale["quantity"],
    ) == (2, 5, 7.5)
    assert protective_sale["reason"] == "stop_touch"
    assert protective_sale["fill_price"] == 80
    assert protective_sale["ledger"]["remaining_entry_fees"] == 0
    assert result["summary"]["metrics"]["closed_trades"] == 1


def test_exit_precedes_add_and_open_protection_cancels_a_later_add():
    source = SOURCE.replace(
        "when close == 105 price", "when close == 105 price or close == 115 price"
    )
    assert [row["reason"] for row in fills(run(source))].count("scale_in") == 1
    dataset = load_dataset(DATA, META)
    values = dataset.values.copy()
    values[4, :4] = [75, 130, 75, 130]
    result = run(source, replace(dataset, values=values))
    stop = fills(result)[-1]
    assert (stop["reason"], stop["bar_index"], stop["quantity"]) == ("stop_gap", 4, 4.5)
    (cancellation,) = [
        event for event in result["events"] if event["kind"] == "order_cancelled"
    ]
    assert cancellation["reason"] == "gap_protection"
    assert not any(row["reason"] == "scale_in" for row in fills(result))


def test_add_can_use_free_cash_or_reject_an_oversized_debit():
    result = run(SOURCE.replace("252.5 USDT", "20% of cash"))
    add = fills(result)[3]
    assert add["reason"] == "scale_in"
    assert add["trace"]["add_budget"] == pytest.approx(322.74)
    assert add["quantity"] == 2.5

    result = run(SOURCE.replace("252.5 USDT", "2000 USDT"))
    (rejection,) = [
        event for event in result["events"] if event["kind"] == "add_rejected"
    ]
    assert rejection["cash_after"] == pytest.approx(1613.7)
    assert rejection["quantity_after"] == 4.5
    assert result["summary"]["metrics"]["total_fees"] == pytest.approx(
        sum(row["fee"] for row in fills(result))
    )


def test_units_and_lot_rounding_reject_zero_or_oversized_amounts():
    for expression in ("sell 0.1 units", "sell 11 units"):
        result = run(SOURCE.replace(FIRST, expression))
        (rejected,) = [
            event for event in result["events"] if event["kind"] == "exit_rejected"
        ]
        assert rejected["quantity_after"] == 10
        assert rejected["cash_after"] == 990
    result = run(SOURCE.replace(FIRST, "sell 2.79 units"))
    assert fills(result)[1]["quantity"] == 2.5


def test_lot_remainders_and_tiny_unrounded_positions_can_close_completely():
    ledger = PositionLedger(LotStep(0.1))
    ledger.enter(0.3, 100, 100, 0, 0)
    ledger.exit(0.1, 100, 100, 0, 0)
    assert ledger.quantity == 0.2
    assert ledger.exit_quantity("units", 0.2) == 0.2

    result = run(
        SOURCE.replace(FIRST, "sell 9.99999999 units")
        .replace("when close == 121 price", "when false")
        .replace("when close == 105 price", "when false")
        .replace("  quantity step 0.5 units\n", "")
    )
    initial, partial, terminal = fills(result)
    assert 0 < partial["ledger"]["remaining_gross_basis"] < 0.001
    assert 0 < terminal["quantity"] < 0.001
    assert terminal["ledger"]["quantity_after"] == 0
    assert terminal["ledger"]["remaining_gross_basis"] == 0
    assert terminal["ledger"]["remaining_entry_fees"] == 0
    assert sum(
        row["ledger"]["entry_fees_released"] for row in (partial, terminal)
    ) == pytest.approx(initial["fee"])


@pytest.mark.parametrize(
    "old,new,message",
    [
        (FIRST, "sell 101% of position", "Invalid exit quantity"),
        (FIRST, "sell close units", "base-unit quantity"),
        ("252.5 USDT", "252.5 USD", "currency differs"),
        ("0.5 units", "0 units", "positive and finite"),
    ],
)
def test_invalid_static_quantities_get_source_diagnostics(old, new, message):
    with pytest.raises(Problem, match=message):
        compile_source(SOURCE.replace(old, new))


def test_v6_sell_all_matches_legacy_fills_without_quantity_changes():
    source = (FIXTURES / "core.trade").read_text()
    data = load_dataset(FIXTURES / "core.csv", META)
    original = run(source, data)
    current = run("tradelang 6\n" + source, data)
    assert current["summary"] == original["summary"]
    assert current["trades"] == original["trades"]
    assert current["events"] == original["events"]
