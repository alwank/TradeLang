"""Higher-timeframe selection, clocks, causal execution, and replay."""

import json
from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest

from tradelang.api.contracts import AST_VALIDATOR_V3
from tradelang.compiler import compile_source
from tradelang.data import load_dataset, prepare_window
from tradelang.decision import Samples
from tradelang.engine import execute
from tradelang.evaluator import Evaluator
from tradelang.model import Problem

FIXTURES = Path("docs/fixtures/feeds")
SOURCE = (FIXTURES / "trend.trade").read_text()


def load(name):
    return load_dataset(
        FIXTURES / f"{name}.csv", json.loads((FIXTURES / f"{name}.json").read_text())
    )


def entries(strategy, primary, secondary, *, end=23):
    prepared = prepare_window(
        strategy, primary, profile_end=end, feeds={"trend": secondary}
    )
    return Evaluator(strategy, primary, end, feeds=prepared.feeds)


def test_clock_alignment_selects_only_completed_native_values_and_primary_fills():
    strategy = compile_source(SOURCE)
    spec = strategy.public()
    AST_VALIDATOR_V3.validate(spec)
    assert spec["required_feeds"] == ["trend"]
    assert spec["bindings"][0]["expression"]["inferred_type"]["clock"] == "trend"
    primary, secondary = load("primary"), load("trend")
    evaluator = entries(strategy, primary, secondary)
    assert evaluator.value(strategy.entry, 6) is None
    assert evaluator.value(strategy.entry, 7) == 1
    execution = execute(strategy, primary, feeds={"trend": secondary})
    fills = [
        (event["bar_index"], event["side"])
        for event in execution["events"]
        if event["kind"] == "fill"
    ]
    assert fills[0] == (8, "buy")
    assert fills[1] == (16, "sell")
    evidence = Samples(strategy, evaluator).trace(strategy.entry, "entry.condition", 7)
    native = [
        sample for sample in evidence["samples"] if sample.get("clock") == "trend"
    ]
    assert any(
        sample["observed_at"] == "2024-01-01T08:00:00Z" and sample["value"] == 105
        for sample in native
    )
    for row, reason in (
        (2, "feed_no_completed_candle"),
        (6, "feed_insufficient_history"),
    ):
        result = Samples(strategy, evaluator).trace(
            strategy.entry, "entry.condition", row
        )
        assert reason in [sample["unavailable_reason"] for sample in result["samples"]]


def test_native_and_primary_lookbacks_and_future_perturbations():
    source = SOURCE.replace(
        "let regime = align(average)",
        "let regime = align(average)\nlet native_previous = align(average[1])\nlet primary_previous = regime[1]",
    )
    strategy = compile_source(source)
    primary, secondary = load("primary"), load("trend")
    full = entries(strategy, primary, secondary)
    expressions = dict((name, expression) for name, expression, _ in strategy.bindings)
    assert full.value(expressions["native_previous"], 8) is None
    assert full.value(expressions["primary_previous"], 8) == 105
    changed = secondary.values.copy()
    changed[2:, :4] *= 10
    prefix = replace(secondary, times=secondary.times[:2], values=secondary.values[:2])
    perturbed = replace(secondary, values=changed)
    short = entries(strategy, primary, prefix, end=10)
    future = entries(strategy, primary, perturbed)
    for expression in (expressions["regime"], strategy.entry, strategy.exit):
        expected = full.evaluate(expression)[:11]
        np.testing.assert_equal(expected, short.evaluate(expression))
        np.testing.assert_equal(expected, future.evaluate(expression)[:11])

    expected = execute(strategy, primary, feeds={"trend": secondary})
    prefix_fills = [
        event
        for event in expected["events"]
        if event["kind"] == "fill" and event["bar_index"] <= 10
    ]
    assert len(prefix_fills) == 1
    for dataset in (prefix, perturbed):
        result = execute(strategy, primary, feeds={"trend": dataset})
        assert [
            event
            for event in result["events"]
            if event["kind"] == "fill" and event["bar_index"] <= 10
        ] == prefix_fills
        assert list(result["equity"])[:12] == list(expected["equity"])[:12]


def test_gap_and_staleness_return_distinct_reasons():
    primary, secondary = load("primary"), load("trend")
    positions = np.array([0, 1, 3, 4, 5])
    gapped = replace(
        secondary, times=secondary.times[positions], values=secondary.values[positions]
    )
    strategy = compile_source(SOURCE)
    for spec, data, row, expected in (
        (strategy, gapped, 11, "feed_gap"),
        (
            compile_source(SOURCE.replace("max_age 8h", "max_age 1h")),
            secondary,
            8,
            "feed_stale",
        ),
    ):
        ev = entries(spec, primary, data)
        evidence = Samples(spec, ev).trace(spec.entry, "entry.condition", row)
        sample = next(
            item for item in evidence["samples"] if item.get("clock") == "primary"
        )
        assert sample["feed"] == "trend" and sample["unavailable_reason"] == expected


def test_mixed_clocks_and_missing_or_conflicting_selection_are_rejected():
    with pytest.raises(Problem, match="different candle clocks"):
        compile_source(SOURCE.replace("regime > 100 price", "average > close"))
    with pytest.raises(Problem, match="Align a secondary series"):
        compile_source(SOURCE.replace("regime > 100 price", "average > 100 price"))
    strategy = compile_source(SOURCE)
    primary = load("primary")
    with pytest.raises(Problem, match="secondary feed trend"):
        prepare_window(strategy, primary)
    with pytest.raises(Problem, match="Feed trend requires"):
        prepare_window(strategy, primary, feeds={"trend": primary})
