"""Independent typed arithmetic trees using exact fractions in bounded cases."""

from dataclasses import dataclass
from fractions import Fraction

import pytest
from hypothesis import given
from hypothesis import strategies as st
from language_cases import CLOCK, FIXTURES, METADATA, expression_text

from tradelang.compiler import compile_source
from tradelang.data import load_dataset
from tradelang.evaluator import Evaluator
from tradelang.model import Problem


@dataclass(frozen=True)
class Tree:
    source: str
    value: Fraction
    unit: tuple[int, int]
    shape: tuple


def constant(item):
    value, (suffix, dimension) = item
    return Tree(f"{value}{suffix}", Fraction(value), dimension, ("literal",))


UNITS = [("", (0, 0)), (" price", (1, -1)), (" volume", (0, 1)), (" money", (1, 0))]
leaves = st.tuples(st.integers(1, 4), st.sampled_from(UNITS)).map(constant)


def combine(item):
    a, op, b = item
    match op:
        case "+":
            value, unit = a.value + b.value, a.unit
        case "-":
            value, unit = a.value - b.value, a.unit
        case "*":
            value, unit = (
                a.value * b.value,
                tuple(x + y for x, y in zip(a.unit, b.unit)),
            )
        case "/":
            value, unit = (
                a.value / b.value,
                tuple(x - y for x, y in zip(a.unit, b.unit)),
            )
        case "**":
            exponent = int(b.value)
            value, unit = a.value**exponent, tuple(x * exponent for x in a.unit)
    return Tree(f"({a.source} {op} {b.source})", value, unit, (op, a.shape, b.shape))


def branch(child):
    # Division always uses positive power-of-two denominators and bounded dimensions.
    denominator = st.tuples(st.sampled_from([1, 2, 4]), st.sampled_from(UNITS)).map(
        constant
    )
    factors = st.tuples(child, st.just("*"), leaves)
    quotients = st.tuples(child, st.just("/"), denominator)
    powers = st.tuples(
        child,
        st.just("**"),
        st.sampled_from([constant((1, UNITS[0])), constant((2, UNITS[0]))]),
    )
    additive = child.flatmap(
        lambda a: (
            st.tuples(
                st.just(a),
                st.sampled_from(["+", "-"]),
                st.integers(1, 4).map(
                    lambda v: constant(
                        (v, next(unit for unit in UNITS if unit[1] == a.unit))
                    )
                ),
            )
            if a.unit in {unit[1] for unit in UNITS}
            else st.just((a, "+", a))
        )
    )
    return (
        st.one_of(factors, quotients, powers, additive)
        .map(combine)
        .filter(
            lambda a: (
                max(map(abs, a.unit)) <= 8
                and abs(a.value.numerator) < 2**30
                and a.value.denominator < 2**30
            )
        )
    )


def compiled_shape(node):
    if node.op == "literal":
        return (node.op,)
    return (node.value, *(compiled_shape(child) for child in node.args))


@given(
    tree=st.recursive(leaves, branch, max_leaves=8),
    sign=st.sampled_from(["+", "-"]),
)
def test_typed_arithmetic(tree, sign):
    strategy = compile_source(expression_text(f"{sign}({tree.source})"))
    node = strategy.bindings[0][1]
    assert compiled_shape(node) == (sign, tree.shape)
    assert node.type.unit == tree.unit
    assert node.type.series is False
    assert node.ready == 0
    assert node.constant == float(tree.value) * (-1 if sign == "-" else 1)


@given(
    pair=st.sampled_from([(a, b) for a in UNITS for b in UNITS if a != b]),
    op=st.sampled_from(["+", "-", ">", "<", ">=", "<=", "==", "!="]),
    x=st.integers(1, 50),
    y=st.integers(1, 50),
)
def test_incompatible_units_reject(pair, op, x, y):
    (left, _), (right, _) = pair
    source = expression_text(f"{x}{left} {op} {y}{right}")
    with pytest.raises(Problem) as trouble:
        compile_source(source)
    assert trouble.value.diagnostic["code"] == "E201_UNIT"


@pytest.mark.parametrize(
    ("text", "answer"),
    [
        ("-2 ** 2", -4),
        ("2 ** -2", 0.25),
        ("2 ** 3 ** 2", 512),
        ("(2 ** 3) ** 2", 64),
        ("20 - 6 / 2 * 3 + 1", 12),
        ("not false and true or false", 1.0),
        ("true or false and false", 1.0),
        ("2 count * 3", 6),
        ("3 * 2 count", 6),
        ("2 count / 4 count", 0.5),
        ("8 count / 4", 2),
    ],
)
def test_precedence_and_nominal_counts(text, answer):
    strategy = compile_source(expression_text(text))
    data = load_dataset(FIXTURES / "indicators.csv", METADATA, as_of_utc=CLOCK)
    evaluator = Evaluator(strategy, data, 0)
    assert evaluator.value(strategy.bindings[0][1], 0) == answer


@given(
    column=st.sampled_from([("close", "price", (1, -1)), ("volume", "volume", (0, 1))]),
    coefficient=st.integers(-8, 8),
    shift=st.integers(-10, 10),
)
def test_series_broadcast_uses_same_dimensions_and_exact_values(
    column, coefficient, shift
):
    name, suffix, dimension = column
    strategy = compile_source(
        expression_text(f"{coefficient} / 4 * {name} + {shift} {suffix}")
    )
    node = strategy.bindings[0][1]
    data = load_dataset(FIXTURES / "indicators.csv", METADATA, as_of_utc=CLOCK)
    evaluator = Evaluator(strategy, data, 7)
    assert node.type.unit == dimension and node.type.series
    assert node.ready == 0
    assert list(evaluator.evaluate(node)) == [
        float(Fraction(coefficient, 4) * int(sample) + shift)
        for sample in data.column(name)
    ]
