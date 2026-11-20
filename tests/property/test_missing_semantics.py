"""Availability truth tables and causal crossing comparisons."""

from itertools import product

import numpy as np
import pytest
from hypothesis import given
from hypothesis import strategies as st
from language_cases import CLOCK, FIXTURES, METADATA, strategy_text

from tradelang.compiler import compile_source
from tradelang.data import load_dataset
from tradelang.evaluator import Evaluator

DATA = load_dataset(FIXTURES / "indicators.csv", METADATA, as_of_utc=CLOCK)
UNKNOWN = "close / (high-low) > 0"


def spell(value):
    return UNKNOWN if value is None else str(value).lower()


@pytest.mark.parametrize("a,b", list(product([True, False, None], repeat=2)))
@pytest.mark.parametrize("operation", ["and", "or"])
def test_boolean_binary_truth_table(operation, a, b):
    strategy = compile_source(
        strategy_text(
            lets=f"let left = {spell(a)}\nlet right = {spell(b)}",
            entry=f"left {operation} right",
        )
    )
    expected = (
        None if None in (a, b) else ((a and b) if operation == "and" else (a or b))
    )
    assert Evaluator(strategy, DATA, 2).value(strategy.entry, 2) == expected


@pytest.mark.parametrize("a", [True, False, None])
def test_boolean_not_truth_table(a):
    strategy = compile_source(strategy_text(entry=f"not ({spell(a)})"))
    expected = None if a is None else not a
    assert Evaluator(strategy, DATA, 2).value(strategy.entry, 2) == expected


@pytest.mark.parametrize("at", [2, 3])
@pytest.mark.parametrize("swap", [False, True])
def test_cross_needs_four_available_samples(at, swap):
    # The unavailable sample is current at row 2 and previous at row 3.
    x = "(close/(high-low))"
    left, right = (x, "10") if not swap else ("10", x)
    strategy = compile_source(strategy_text(entry=f"{left} crosses above {right}"))
    assert Evaluator(strategy, DATA, at).value(strategy.entry, at) is None


@pytest.mark.parametrize(
    ("text", "reason"),
    [
        ("close/(high-low)", "zero_denominator"),
        ("(-close / 1 price)**0.5", "domain"),
        ("(close * 1e308) / 1 price", "overflow"),
    ],
)
def test_runtime_failures_are_unavailable_and_counted(text, reason):
    strategy = compile_source(strategy_text(lets=f"let v = {text}"))
    evaluator = Evaluator(strategy, DATA, 2)
    assert evaluator.value(strategy.bindings[0][1], 2) is None
    assert evaluator.invalid[reason] >= 1


LEAVES = st.sampled_from(
    [
        ("true", True, ("literal", True)),
        ("false", False, ("literal", False)),
        ("(volume > 0)", True, (">", "volume", 0)),
        ("(volume is below 0)", False, ("<", "volume", 0)),
    ]
)


def combine(item):
    left, operator, right = item
    if operator == "not":
        return f"(not {left[0]})", not left[1], ("not", left[2])
    value = (left[1] and right[1]) if operator == "and" else (left[1] or right[1])
    return f"({left[0]} {operator} {right[0]})", value, (operator, left[2], right[2])


def shape(node):
    if node.op == "literal":
        return ("literal", node.value)
    if node.op == "compare":
        return (node.value, node.args[0].value, node.args[1].value)
    return (node.value, *(shape(child) for child in node.args))


@given(
    tree=st.recursive(
        LEAVES,
        lambda inner: st.tuples(
            inner,
            st.sampled_from(["not", "and", "or"]),
            inner,
        ).map(combine),
        max_leaves=8,
    )
)
def test_generated_boolean_source_compiles_and_evaluates(tree):
    text, expected, tree_shape = tree
    strategy = compile_source(strategy_text(entry=text))
    assert shape(strategy.entry) == tree_shape
    available = Evaluator(strategy, DATA, 0).value(strategy.entry, 0)
    assert available is not None
    np.testing.assert_equal(available, float(expected))


@pytest.mark.parametrize(
    ("condition", "expected"),
    [
        ("close crosses above 12 price", [np.nan, 0, 1, 0, 0, 0, 0, 0]),
        ("close crosses below 17 price", [np.nan, 0, 0, 0, 0, 0, 1, 0]),
    ],
)
def test_cross_uses_previous_equality_and_strict_current_threshold(condition, expected):
    strategy = compile_source(strategy_text(entry=condition))
    np.testing.assert_equal(
        Evaluator(strategy, DATA, 7).evaluate(strategy.entry), expected
    )
