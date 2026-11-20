"""Hand-derived phase sequences and cash ledgers."""

import math
from fractions import Fraction

import pytest
from test_golden import FIX, META, scenario

from tradelang.data import load_dataset
from tradelang.engine import execute

BUY = [
    (7, 0, "signal", "buy", "close"),
    (7, 0, "order_queued", "buy", "close"),
    (3, 1, "fill", "entry", "open"),
]
SELL = [
    (7, 1, "signal", "entry_ignored_holding", "close"),
    (7, 1, "signal", "sell", "close"),
    (7, 1, "order_queued", "sell", "close"),
]
EXPIRE = [
    (7, 2, "signal", "buy", "close"),
    (8, 2, "order_expired_end", "end_of_window", "close"),
]


@pytest.mark.parametrize(
    ("file", "options", "expected", "cash"),
    [
        (
            "core",
            {"exit": "close >= 112 price"},
            BUY + SELL + [(2, 2, "fill", "signal_exit", "open")],
            Fraction(12000, 11),
        ),
        (
            "gap-stop",
            {
                "exit": "volume == 20 volume",
                "risk": "risk: stop loss 10% take profit 10%",
            },
            BUY
            + SELL
            + [
                (1, 2, "fill", "stop_gap", "open"),
                (1, 2, "order_cancelled", "gap_protection", "open"),
            ],
            800,
        ),
        (
            "dual-touch",
            {"risk": "risk: stop loss 10% take profit 10%"},
            BUY
            + [
                (5, 1, "warning", "both_levels_touched", "bar"),
                (5, 1, "fill", "stop_dual_touch", "bar"),
            ]
            + EXPIRE,
            900,
        ),
        (
            "dual-touch",
            {"slip": 1000, "risk": "risk: stop loss 1%"},
            BUY + [(4, 1, "fill", "stop_entry_open", "open")] + EXPIRE,
            Fraction(9000, 11),
        ),
        ("core", {"entry": "volume == 30 volume"}, EXPIRE, 1000),
    ],
)
def test_phases_and_order_links(file, options, expected, cash):
    result = execute(*scenario(file, **options))
    events = result["events"]
    keys = ("phase", "bar_index", "kind", "reason", "time_precision")
    assert [tuple(e[key] for key in keys) for e in events] == expected
    assert [e["sequence"] for e in events] == list(range(1, len(events) + 1))
    orders = {
        e["order_id"]: e for e in events if e["kind"] == "signal" and e["order_id"]
    }
    for row in events:
        if row["kind"] in {"order_queued", "order_expired_end"}:
            assert row["linked_event_id"] == orders[row["order_id"]]["event_id"]
        if row["kind"] == "fill" and row["order_id"]:
            signal = orders[row["order_id"]]
            assert signal["observed_at"] == row["observed_at"]
            assert signal["sequence"] < row["sequence"]
    fills = [e for e in events if e["kind"] == "fill"]
    assert [e["fill_id"] for e in fills] == [
        f"F{i:08}" for i in range(1, len(fills) + 1)
    ]
    if fills:
        (trade,) = result["trades"]
        assert all(e["trade_id"] == trade["trade_id"] for e in fills)
        assert float(cash) - 1000 == pytest.approx(trade["net_pnl"])
        assert fills[-1]["quantity_after"] == 0
    assert all(e["cash_after"] >= 0 and e["quantity_after"] >= 0 for e in events)
    assert result["summary"]["final_cash"] == pytest.approx(float(cash))
    assert result["summary"]["benchmark_entry_at"] == "2024-01-02T00:00:00Z"


def test_fee_inclusive_ledger_uses_adverse_prices():
    result = execute(*scenario(exit="close >= 112 price", fee=100, slip=1000))
    buy, sell = [e for e in result["events"] if e["kind"] == "fill"]
    qty = Fraction(1000, 1) / (121 * Fraction(101, 100))
    entry_fee, exit_fee = (qty * price / 100 for price in (121, 108))
    assert [e["reference_price"] for e in (buy, sell)] == [110, 120]
    assert [e["fill_price"] for e in (buy, sell)] == pytest.approx([121, 108])
    assert buy["quantity"] == sell["quantity"] == pytest.approx(float(qty))
    assert [e["fee"] for e in (buy, sell)] == pytest.approx(
        [float(entry_fee), float(exit_fee)]
    )
    assert result["summary"]["final_equity"] == pytest.approx(
        float(108 * qty - exit_fee)
    )
    middle = list(result["equity"])[2]
    assert middle["equity"] == pytest.approx(float(112 * qty))
    assert middle["phase"] == "close"


def test_rounding_uses_adjacent_binary64_quantity(tmp_path):
    strategy, data = scenario(
        entry="volume == 10 volume",
        size="1 USDT",
        fee=10,
        rows={1: "3,5,2,3,20"},
        tmp_path=tmp_path,
    )
    result = execute(strategy, data)
    (buy,) = [e for e in result["events"] if e["kind"] == "fill"]
    # With an unadjusted quantity, rounded gross plus fee exceeds the one-dollar budget.
    nominal = 1 / (3 * 1.001)
    gross = nominal * 3
    assert gross + gross * 0.001 > 1
    assert buy["quantity"] == math.nextafter(nominal, 0)
    assert 0 < -buy["cash_delta"] <= 1


def test_frozen_atr_and_perturbed_fill_bar(tmp_path):
    args = dict(
        entry="volume == 20 volume",
        risk="risk: stop loss 2 * ATR(2) take profit 4 * ATR(2)",
    )
    dataset_options = [None, {2: "100,117,96,112,30"}, {2: "102,117,96,112,30"}]
    fills = []
    for rows in dataset_options:
        strategy, data = scenario("frozen-atr", rows=rows, tmp_path=tmp_path, **args)
        result = execute(strategy, data)
        fills.append(next(e for e in result["events"] if e["reason"] == "entry"))
    # The signal bar has a range of 6 and its predecessor a range of 4.
    # Wilder's initial average is 5, giving distances 10 and 20.
    for fill, anchor in zip(fills, [100, 100, 102]):
        assert fill["protection"] == {
            name: {
                "node_id": f"risk.{name}.expression",
                "sampled_bar": 1,
                "sampled_at": "2024-01-03T00:00:00Z",
                "expression_value": distance,
                "unit": "price",
                "entry_anchor": anchor,
                "distance": distance,
                "trigger_price": anchor + sign * distance,
            }
            for name, distance, sign in (("stop", 10, -1), ("target", 20, 1))
        }
    assert fills[0]["trace"] == fills[1]["trace"] == fills[2]["trace"]


def test_gaps_use_next_observed_open_and_terminal_mark(tmp_path):
    source, _ = scenario(exit="false")
    original = (FIX / "core.csv").read_text().splitlines()
    path = tmp_path / "gap.csv"
    path.write_text("\n".join([original[0], original[1], original[3]]) + "\n")
    dataset = load_dataset(path, {**META, "gap_policy": "allow"})
    result = execute(source, dataset)
    (fill,) = [e for e in result["events"] if e["kind"] == "fill"]
    assert fill["observed_at"] == "2024-01-03T00:00:00Z"
    assert fill["bar_index"] == 1 and fill["fill_price"] == 120
    assert result["summary"]["benchmark_entry_at"] == fill["observed_at"]
    assert result["summary"]["final_equity"] == pytest.approx(1000)
    assert result["summary"]["open_position"]["quantity"] == pytest.approx(1000 / 120)
    assert result["trades"] == []
