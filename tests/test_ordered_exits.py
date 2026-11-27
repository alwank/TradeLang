"""Causal trails, first-match exit ordering, and pending signal lifetimes."""

import json
from dataclasses import replace
from pathlib import Path

import pyarrow.parquet as pq
import pytest

from tradelang.api.contracts import AST_VALIDATOR_V5
from tradelang.compiler import compile_source
from tradelang.data import load_dataset
from tradelang.engine import execute
from tradelang.model import Problem
from tradelang.report import explain, publish

FIXTURES = Path("docs/fixtures")
FILE = FIXTURES / "ordered-exits/ordered.csv"
SOURCE = FILE.with_suffix(".trade").read_text()
META = json.loads((FIXTURES / "metadata.json").read_text())
DAY_US = 86_400_000_000
PROFIT = "rule profit when close >= 120 price sell all"
TIMER = "rule timeout after hold_bars bars sell all"
EXPIRY = " expire after 1d"


def events(result, kind):
    return [event for event in result["events"] if event["kind"] == kind]


def run(source=SOURCE, data=None, parameters=None):
    return execute(
        compile_source(source, parameters=parameters),
        data if data is not None else load_dataset(FILE, META),
    )


def test_first_true_exit_and_trails_start_at_next_open(tmp_path):
    strategy = compile_source(SOURCE)
    AST_VALIDATOR_V5.validate(strategy.public())
    assert strategy.warmup == 0
    assert "first true rule in source order" in explain(strategy)["text"]
    assert [rule.name for rule in strategy.exit_rules] == [
        "slow_confirmation",
        "profit",
        "timeout",
    ]
    data = load_dataset(FILE, META)
    result = execute(strategy, data)
    entry, exit = events(result, "fill")
    assert (entry["bar_index"], entry["fill_price"], entry["quantity"]) == (1, 100, 5)
    assert entry["protection"]["stop"]["trigger_price"] == 90
    assert (exit["bar_index"], exit["phase"], exit["fill_price"]) == (3, 2, 122)
    assert result["summary"]["final_equity"] == 1110
    for close, active in zip(
        events(result, "trail_queued"), events(result, "trail_activated"), strict=True
    ):
        assert close["phase"] == 7 and active["phase"] == 1
        assert active["bar_index"] == close["bar_index"] + 1
        assert active["trail"]["sampled_bar"] == close["bar_index"]
        assert active["trail"]["trigger_price"] == close["trail"]["trigger_price"]
        assert active["trail"]["effective_open_at"] == active["bar_open_at"]
    assert [
        event["trail"]["trigger_price"] for event in events(result, "trail_activated")
    ] == [110, 120]
    assert (
        events(result, "trail_queued")[0]["trail"]["trigger_price"]
        > data.column("low")[1]
    )
    queued = events(result, "order_queued")[-1]
    trigger = {"name": "profit", "order": 2, "holding_closes": 2, "after_bars": None}
    assert queued["trace"]["exit_rule"] == exit["trace"]["exit_rule"] == trigger
    assert queued["order_id"] == exit["order_id"]

    output = tmp_path / "bundle"
    publish(strategy, data, output)
    manifest = json.loads((output / "manifest.json").read_text())
    assert manifest["semantics_version"] == "5.0.0"
    assert manifest["decision_inspection"]["schema_version"] == 2
    rows = pq.read_table(output / "decisions.parquet")
    assert rows["holding_closes"].to_pylist() == [0, 1, 2, 0]


def test_timeout_counts_observed_holding_closes_and_fills_at_next_open():
    source = SOURCE.replace(f"{PROFIT}\n  {TIMER}", f"{TIMER}\n  {PROFIT}").replace(
        EXPIRY, ""
    )
    data = load_dataset(FILE, META)
    times = data.times.copy()
    times[2:] += DAY_US
    data = replace(
        data,
        times=times,
        missing=1,
        meta=data.meta.model_copy(update={"gap_policy": "allow"}),
    )
    result = run(source.replace("to 2024-01-04", "to 2024-01-05"), data)
    entry, exit = events(result, "fill")
    assert entry["bar_index"] == 1
    assert exit["bar_open_at"] == "2024-01-05T00:00:00Z"
    assert exit["trace"]["exit_rule"] == {
        "name": "timeout",
        "order": 2,
        "holding_closes": 2,
        "after_bars": 2,
    }


def test_unavailable_trail_retains_initial_stop_and_does_not_delay_entry():
    result = run(SOURCE.replace("trailing stop 5 price", "trailing stop ATR(20)"))
    assert not events(result, "trail_queued")
    entry, exit = events(result, "fill")
    assert entry["bar_index"] == 1
    assert exit["protection"]["stop"] == entry["protection"]["stop"]


def test_trail_only_tightens():
    data = load_dataset(FILE, META)
    values = data.values.copy()
    values[2, 3] = 112
    values[3, :4] = [110, 126, 108, 123]
    result = run(data=replace(data, values=values), parameters={"hold_bars": 99})
    assert [
        row["trail"]["trigger_price"] for row in events(result, "trail_queued")
    ] == [110]
    assert events(result, "fill")[-1]["reason"] == "stop_gap"
    assert events(result, "fill")[-1]["fill_price"] == 110


@pytest.mark.parametrize("missing_candle", [False, True])
def test_trail_activation_and_gap_stop_precede_queued_sell(missing_candle):
    baseline = run()
    data = load_dataset(FILE, META)
    values = data.values.copy()
    values[-1, :4] = [119, 126, 118, 123]
    source = SOURCE
    if missing_candle:
        times = data.times.copy()
        times[-1] += DAY_US
        data = replace(
            data,
            times=times,
            missing=1,
            meta=data.meta.model_copy(update={"gap_policy": "allow"}),
        )
        source = source.replace("to 2024-01-04", "to 2024-01-05")
    result = run(source, replace(data, values=values))
    assert [event for event in result["events"] if event["bar_index"] < 3] == [
        event for event in baseline["events"] if event["bar_index"] < 3
    ]
    last = [event for event in result["events"] if event["bar_index"] == 3]
    assert [event["kind"] for event in last] == [
        "trail_activated",
        "fill",
        "order_cancelled",
    ]
    assert last[1]["reason"] == "stop_gap"
    assert last[1]["fill_price"] == 119
    assert last[2]["order_id"] == events(result, "order_queued")[-1]["order_id"]


def test_time_exit_on_final_close_expires_with_no_fill_open():
    result = run(
        SOURCE.replace("close >= 120 price", "close >= 130 price"),
        parameters={"hold_bars": 3},
    )
    assert len(events(result, "fill")) == 1
    (expiry,) = events(result, "order_expired_end")
    assert (expiry["bar_index"], expiry["phase"], expiry["reason"]) == (
        3,
        8,
        "end_of_window",
    )
    assert expiry["trace"]["exit_rule"]["name"] == "timeout"
    assert expiry["trace"]["exit_rule"]["holding_closes"] == 3
    assert result["summary"]["open_position"]["quantity"] == 5


def test_active_trail_wins_intrabar_dual_touch():
    data = load_dataset(FILE, META)
    values = data.values.copy()
    values[-1, :4] = [122, 155, 119, 123]
    result = run(
        SOURCE.replace("close >= 120 price", "close >= 145 price"),
        replace(data, values=values),
        parameters={"hold_bars": 99},
    )
    exit = events(result, "fill")[-1]
    assert (exit["phase"], exit["reason"], exit["fill_price"]) == (
        5,
        "stop_dual_touch",
        120,
    )
    assert result["summary"]["counts"]["dual_touches"] == 1


@pytest.mark.parametrize("side", ["buy", "sell"])
def test_expiry_at_age_boundary_after_gap_respects_order_phase(side):
    data = load_dataset(FILE, META)
    times = data.times.copy()
    times[1 if side == "buy" else 3 :] += DAY_US
    data = replace(
        data,
        times=times,
        missing=1,
        meta=data.meta.model_copy(update={"gap_policy": "allow"}),
    )
    source = SOURCE.replace("to 2024-01-04", "to 2024-01-05")
    result = run(source, data)
    (stale,) = events(result, "order_expired_stale")
    assert stale["side"] == side
    assert stale["phase"] == (3 if side == "buy" else 2)
    assert stale["age_seconds"] == stale["max_age_seconds"] == 86400
    assert not any(
        fill["order_id"] == stale["order_id"] for fill in events(result, "fill")
    )
    if side == "sell":
        assert stale["trace"]["exit_rule"]["name"] == "profit"
        assert (
            events(result, "order_expired_end")[-1]["trace"]["exit_rule"]["name"]
            == "profit"
        )
        assert result["summary"]["open_position"] is not None
    with_no_limit = run(source.replace(EXPIRY, ""), data)
    assert (
        events(with_no_limit, "fill")[1 if side == "sell" else 0]["bar_open_at"]
        == stale["bar_open_at"]
    )


@pytest.mark.parametrize(
    "old,new,match",
    [
        ("rule timeout", "rule profit", "Duplicate exit rule name profit"),
        ("after hold_bars", "after close", "static count"),
        ("after hold_bars", "after 0", "static count"),
        ("after hold_bars", "after 1.5", "static count"),
        ("  stop loss 10%\n", "", "requires an initial stop loss"),
        ("trailing stop 5 price", "trailing stop 100%", "Invalid risk distance"),
        ("expire after 1d", "expire after 8d", "at most seven days"),
    ],
)
def test_rejects_invalid_rules_and_protection(old, new, match):
    with pytest.raises(Problem, match=match):
        compile_source(SOURCE.replace(old, new))


def test_single_rule_preserves_legacy_equity_trades_and_event_sequence():
    text = (FIXTURES / "core.trade").read_text()
    data = load_dataset(FIXTURES / "core.csv", META)
    original = run(text, data)
    modern = run("tradelang 5\n" + text, data)
    assert modern["summary"] == original["summary"]
    assert modern["events"] == original["events"]
    assert modern["trades"] == original["trades"]
