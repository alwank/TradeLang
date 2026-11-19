import json
from pathlib import Path

import numpy as np
import pytest

from tradelang.compiler import compile_source
from tradelang.data import load_dataset
from tradelang.engine import execute
from tradelang.evaluator import Evaluator
from tradelang.model import Problem
from tradelang.report import resolved

FIX = Path("docs/fixtures")
META = json.loads((FIX / "metadata.json").read_text())


def scenario(
    file="core",
    entry="true",
    exit="false",
    risk="",
    lets="",
    size="100% of equity",
    fee=0,
    slip=0,
    rows=None,
    tmp_path=None,
):
    path = FIX / (file + ".csv")
    if rows:
        lines = path.read_text().splitlines()
        for i, vals in rows.items():
            lines[i + 1] = lines[i + 1].split(",")[0] + "," + vals
        path = tmp_path / "variant.csv"
        path.write_text("\n".join(lines) + "\n")
    end = path.read_text().splitlines()[-1][:10]
    src = (
        (FIX / "core.trade")
        .read_text()
        .replace("entry:", lets + "\nentry:")
        .replace("when true", "when " + entry)
        .replace("close >= 112 price", exit)
        .replace("100% of equity", size)
        .replace("backtest:", risk + "\nbacktest:")
        .replace("2024-01-03", end)
        .replace("fee 0", f"fee {fee}")
        .replace("slippage 0", f"slippage {slip}")
    )
    return compile_source(src), load_dataset(path, META)


@pytest.mark.parametrize(
    "file,options,final,reason",
    [
        ("core", dict(exit="close >= 112 price"), 12000 / 11, "signal_exit"),
        (
            "core",
            dict(exit="close >= 112 price", fee=100, slip=1000),
            10692000 / 12221,
            "signal_exit",
        ),
        (
            "dual-touch",
            dict(risk="risk: stop loss 10% take profit 10%"),
            900,
            "stop_dual_touch",
        ),
        ("gap-stop", dict(risk="risk: stop loss 10% take profit 10%"), 800, "stop_gap"),
        (
            "gap-stop",
            dict(exit="volume == 20 volume", risk="risk: stop loss 10%"),
            800,
            "stop_gap",
        ),
        (
            "dual-touch",
            dict(slip=1000, risk="risk: stop loss 1%"),
            9000 / 11,
            "stop_entry_open",
        ),
        (
            "frozen-atr",
            dict(
                entry="volume == 20 volume",
                risk="risk: stop loss 2 * ATR(2) take profit 4 * ATR(2)",
            ),
            1200,
            "target_touch",
        ),
        (
            "invalid",
            dict(lets="let z = close / (high - low)", entry="z crosses above 0"),
            1000,
            None,
        ),
        ("cross", dict(entry="close crosses above 100 price"), 20000 / 21, None),
        ("core", dict(entry="volume == 30 volume"), 1000, None),
        ("indicators", dict(lets="let m = SMA(3)", entry="m > 0"), 1125, None),
        (
            "core",
            dict(size="500 USDT", exit="close >= 112 price"),
            11500 / 11,
            "signal_exit",
        ),
        ("core", dict(exit="true"), 1000, None),
        (
            "frozen-atr",
            dict(entry="volume == 20 volume", risk="risk: stop loss -2 * ATR(2)"),
            1000,
            None,
        ),
        (
            "core",
            dict(size="equity USDT", exit="close >= 112 price"),
            12000 / 11,
            "signal_exit",
        ),
        (
            "core",
            dict(size="(close / 100 price) * 50% of equity", exit="close >= 112 price"),
            11500 / 11,
            "signal_exit",
        ),
    ],
)
def test_goldens(file, options, final, reason):
    s, d = scenario(file, **options)
    result = execute(s, d)
    summary = result["summary"]
    trades = result["trades"]
    assert summary["final_equity"] == pytest.approx(final)
    assert [t["exit_reason"] for t in trades] == ([reason] if reason else [])
    holding = summary["open_position"]
    assert final - 1000 == pytest.approx(
        sum(t["net_pnl"] for t in trades)
        + (holding["unrealized_gross"] - holding["entry_fee"] if holding else 0)
    )
    if reason == "target_touch":
        assert trades[0]["protection"]["stop"]["distance"] == 10
        assert trades[0]["protection"]["target"]["distance"] == 20
    if file == "invalid":
        assert summary["counts"]["unavailable_by_reason"]["zero_denominator"] == 2
    if options.get("fee"):
        assert summary["benchmark"]["final_equity"] == pytest.approx(12000000 / 12221)
        assert trades[0]["exit_fee"] == pytest.approx(108000 / 12221)
    if file == "cross":
        assert summary["benchmark"]["final_equity"] == pytest.approx(100000 / 101)
    if options.get("entry") == "volume == 30 volume":
        assert summary["counts"]["expired_orders"] == 1


@pytest.mark.parametrize(
    "row,exit,expected,reason",
    [
        ("100,115,85,100,30", "volume == 20 volume", 1000, "signal_exit"),
        ("100,115,85,100,30", "false", 900, "stop_dual_touch"),
        ("120,122,90,105,30", "false", 1200, "target_gap"),
    ],
)
def test_priority(tmp_path, row, exit, expected, reason):
    result = execute(
        *scenario(
            "gap-stop",
            exit=exit,
            risk="risk: stop loss 10% take profit 10%",
            rows={2: row},
            tmp_path=tmp_path,
        )
    )
    assert result["summary"]["final_equity"] == expected
    assert result["trades"][0]["exit_reason"] == reason


def test_unready():
    with pytest.raises(Problem, match="Insufficient"):
        execute(*scenario(lets="let unused = SMA(10)"))


def test_named_conditions_match_inline_trading():
    inline, data = scenario(
        "indicators",
        entry="close > SMA(3) and close crosses above 12 price and not (close >= 16 price)",
        exit="close >= 16 price",
    )
    named, _ = scenario(
        "indicators",
        lets=(
            "let trend_confirmed = close > SMA(3)\n"
            "let exit_ready = close >= 16 price\n"
            "let entry_ready = trend_confirmed and close crosses above 12 price"
            " and not exit_ready"
        ),
        entry="entry_ready",
        exit="exit_ready",
    )
    assert named.warmup == inline.warmup == 2
    assert resolved(named, data) == resolved(inline, data)
    expected, actual = (execute(s, data) for s in (inline, named))
    anchor = "2024-01-04T00:00:00Z"
    assert actual["summary"]["benchmark_entry_at"] == anchor
    assert expected["summary"]["benchmark_entry_at"] == anchor
    assert (
        actual["summary"]["final_equity"] == expected["summary"]["final_equity"] == 1125
    )
    assert list(actual["equity"]) == list(expected["equity"])

    trading_kinds = {"signal", "order_queued", "fill"}
    inline_events, named_events = (
        [e for e in result["events"] if e["kind"] in trading_kinds]
        for result in (expected, actual)
    )
    assert [{k: v for k, v in e.items() if k != "trace"} for e in named_events] == [
        {k: v for k, v in e.items() if k != "trace"} for e in inline_events
    ]
    assert [(e["bar_index"], e["kind"], e["reason"]) for e in named_events] == [
        (2, "signal", "buy"),
        (2, "order_queued", "buy"),
        (3, "fill", "entry"),
        (3, "signal", "sell"),
        (3, "order_queued", "sell"),
        (4, "fill", "signal_exit"),
    ]
    assert [e["fill_price"] for e in named_events if e["kind"] == "fill"] == [16, 18]
    spec = named.public()
    for signal, rule in zip(
        (e for e in named_events if e["kind"] == "signal"),
        ("entry", "exit"),
        strict=True,
    ):
        condition = spec[rule]["condition"]
        assert condition["name"] == f"{rule}_ready"
        assert signal["trace"]["root_node_id"] == condition["node_id"]
        assert signal["trace"]["operands"] == [
            {
                "node_id": condition["node_id"],
                "value": 1,
                "unit": "boolean",
                "valid": True,
            }
        ]


def test_unused_boolean_binding_counts_toward_warmup():
    strategy, data = scenario(lets="let unused = close > SMA(10)", entry="false")
    assert strategy.warmup == 9
    assert [warning["code"] for warning in strategy.warnings] == ["W_UNUSED_LET"]
    with pytest.raises(Problem) as exc:
        execute(strategy, data)
    assert exc.value.diagnostic["code"] == "E_NO_EXECUTION_WINDOW"


@pytest.mark.parametrize(
    "expr,expected",
    [
        ("SMA(3)", [None, None, 12, 14, 16]),
        ("EMA(2)", [None, 11, 13, 15, 17]),
        ("RSI(2)", [None, None, 100, 100, 100]),
        ("MACD(2,3,2).line", [None, None, 1, 1, 1]),
        ("MACD(2,3,2).histogram", [None, None, None, 0, 0]),
        ("ATR(2)", [None, 2.5, 2.75, 2.875, 2.9375]),
        (
            "BBANDS(close,3,2).upper",
            [
                None,
                None,
                12 + 2 * np.sqrt(8 / 3),
                14 + 2 * np.sqrt(8 / 3),
                16 + 2 * np.sqrt(8 / 3),
            ],
        ),
        ("HIGHEST(high,3)[1]", [None, None, None, 15, 17]),
        ("LOWEST(low,3)", [None, None, 9, 11, 13]),
        ("ROC(close,2)", [None, None, 0.4, 1 / 3, 2 / 7]),
        ("STDDEV(close,3)", [None, None, *[np.sqrt(8 / 3)] * 3]),
    ],
)
def test_indicator_values(expr, expected):
    s, d = scenario("indicators", lets="let v = " + expr)
    out = Evaluator(s, d, 4).evaluate(s.bindings[0][1])
    np.testing.assert_allclose(out, np.array(expected, dtype=float), atol=1e-12)


@pytest.mark.parametrize(
    "expr",
    [
        "close + 2%",
        "10 / 0",
        "RSI(0)",
        "MACD(2,3,2) + close",
        "close[-1]",
        "equity",
        "2 ** 17",
        "close > 30",
        "(-1) ** 0.5",
        "1e999",
    ],
)
def test_reject(expr):
    with pytest.raises(Problem):
        scenario(lets="let v = " + expr)


@pytest.mark.parametrize(
    "expr,val",
    [("-2 ** 2", -4), ("2 ** 3 ** 2", 512), ("2 ** -2", 0.25), ("(1+2)*3", 9)],
)
def test_precedence(expr, val):
    s, d = scenario(lets="let v = " + expr)
    assert Evaluator(s, d, 2).evaluate(s.bindings[0][1]) == val


def test_invalid_power_zero_does_not_become_one():
    s, d = scenario("invalid", lets="let x = close / (high-low)", entry="x ** 0 == 1")
    out = Evaluator(s, d, 3).evaluate(s.entry)
    np.testing.assert_equal(out, [np.nan, 1, np.nan, 1])


def test_entry_bar_immediate_exit_no_duplicate_or_reopen():
    s, d = scenario("dual-touch", risk="risk: stop loss 10% take profit 10%")
    events = execute(s, d)["events"]
    assert [
        (x["side"], x["phase"], x["bar_index"]) for x in events if x["kind"] == "fill"
    ] == [("buy", 3, 1), ("sell", 5, 1)]
    assert not [
        x for x in events if x["kind"] == "order_queued" and x["bar_index"] == 1
    ]


def test_constant_overbudget_rejects_at_open():
    r = execute(*scenario(size="1001 USDT"))
    assert all(e["phase"] == 3 for e in r["events"] if e["kind"] == "entry_rejected")
    assert r["summary"]["counts"]["entry_rejections"] == 2
    assert r["summary"]["final_cash"] == 1000
