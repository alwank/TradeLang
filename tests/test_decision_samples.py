"""Sample provenance and compact decision evidence."""

import json
from pathlib import Path

from language_cases import CLOCK, METADATA, strategy_text
from test_volume_profile import candle_file

from tradelang.compiler import compile_source
from tradelang.data import load_dataset, prepare_window
from tradelang.decision import Samples
from tradelang.evaluator import Evaluator


def test_cross_samples_include_alias_and_shifted_history_across_a_gap(tmp_path):
    fixture = Path("docs/fixtures/core.csv").read_text()
    candles = tmp_path / "shifted.csv"
    candles.write_text(
        fixture.replace("2024-01-03", "2024-01-05").replace("2024-01-02", "2024-01-03")
    )
    dataset = load_dataset(
        candles, {**METADATA, "gap_policy": "allow"}, as_of_utc=CLOCK
    )
    strategy = compile_source(
        strategy_text(
            lets="let delayed = close[1][0]",
            entry="delayed crosses above 105 price",
            end="2024-01-05",
        )
    )
    out = Samples(strategy, Evaluator(strategy, dataset, 2)).trace(
        strategy.entry, "entry.condition", 2
    )
    assert out["value"] is True
    samples = {(row["node_id"], row["bar_index"]): row for row in out["samples"]}
    base = "bindings.0.expression.base.base"
    assert (
        samples[("entry.condition.left", 2)]["definition_node_id"]
        == "bindings.0.expression"
    )
    assert samples[("entry.condition.left", 1)]["value"] == 100
    assert samples[("entry.condition.right", 1)]["value"] == 105
    assert samples[(base, 1)]["value"] == 112
    assert samples[(base, 1)]["observed_at"] == "2024-01-04T00:00:00Z"
    assert samples[(base, 0)]["value"] == 100
    assert samples[(base, 0)]["observed_at"] == "2024-01-02T00:00:00Z"
    assert not out["truncated"]


def test_empty_profile_and_zero_division_report_source_reasons(tmp_path):
    primary = candle_file(
        tmp_path / "parent.csv", [0, 8, 16], [102, 110, 109], [9, 3, 4], timeframe="8h"
    )
    child = candle_file(
        tmp_path / "child.csv",
        [0, 4, 8, 12, 16, 20],
        [100] * 6,
        [0] * 6,
        timeframe="4h",
    )
    strategy = compile_source(
        strategy_text(
            entry="VPROFILE(1, 1 price, 0.7).poc > 0 or high / (close - open) > 1",
            end="2024-01-01",
        ).replace("1d", "8h")
    )
    prepared = prepare_window(strategy, primary, child, profile_end=1)
    trace = Samples(
        strategy, Evaluator(strategy, primary, 1, profiles=prepared.profiles)
    )
    out = trace.trace(strategy.entry, "entry.condition", 1)
    reasons = {part["unavailable_reason"] for part in out["samples"]}
    assert out["value"] is None
    assert "profile_empty_distribution" in reasons
    assert "zero_denominator" in reasons
    assert "upstream_unavailable" in reasons
    json.dumps(out, allow_nan=False)


def test_trace_bounds_a_long_binding_chain():
    dataset = load_dataset(Path("docs/fixtures/core.csv"), METADATA, as_of_utc=CLOCK)
    lets = "\n".join(
        ["let a0 = close", *[f"let a{i} = a{i - 1}" for i in range(1, 65)]]
    )
    strategy = compile_source(strategy_text(lets=lets, entry="a64 > 99 price"))
    out = Samples(strategy, Evaluator(strategy, dataset, 0)).trace(
        strategy.entry, "entry.condition", 0
    )
    assert out["value"] is True
    assert out["truncated"]
    assert len(out["samples"]) <= 34
