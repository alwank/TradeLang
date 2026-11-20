"""Scalar references, generated vectors, and causality across the catalog."""

import math
from dataclasses import replace

import numpy as np
import pytest
from hypothesis import given
from hypothesis import strategies as st
from language_cases import CLOCK, FIXTURES, METADATA, strategy_text
from test_release import average, rolling, smooth

from tradelang.compiler import compile_source
from tradelang.data import load_dataset
from tradelang.evaluator import Evaluator

BASE = load_dataset(FIXTURES / "indicators.csv", METADATA, as_of_utc=CLOCK)


def reference(name, xs, period, *, edition=None):
    def std(samples):
        mean = average(samples)
        return math.sqrt(average([(x - mean) ** 2 for x in samples]))

    if name in {"SMA", "HIGHEST", "LOWEST", "STDDEV"}:
        return rolling(
            xs,
            period,
            {"SMA": average, "HIGHEST": max, "LOWEST": min, "STDDEV": std}[name],
        )
    if name == "EMA":
        return smooth(xs, period, 2 / (period + 1))
    if name == "RSI":
        delta = [math.nan, *(b - a for a, b in zip(xs, xs[1:]))]
        gain = smooth([max(v, 0) for v in delta], period, 1 / period)
        loss = smooth([max(-v, 0) for v in delta], period, 1 / period)
        return [
            100 * g / (g + loss_) if g + loss_ else 50 for g, loss_ in zip(gain, loss)
        ]
    if name == "ATR":
        highs, lows = edition
        spreads = [highs[0] - lows[0]]
        spreads += [
            max(h, p) - min(low, p) for h, low, p in zip(highs[1:], lows[1:], xs)
        ]
        return smooth(spreads, period, 1 / period)
    if name == "ROC":
        result = [math.nan] * len(xs)
        for i in range(period, len(xs)):
            interval = xs[i - period : i + 1]
            if interval[0] and all(map(math.isfinite, interval)):
                result[i] = interval[-1] / interval[0] - 1
        return result
    if name == "BBANDS":
        mid = rolling(xs, period, average)
        spread = rolling(xs, period, std)
        k, field = edition
        weight = {"lower": -k, "middle": 0, "upper": k}[field]
        return [m + weight * s for m, s in zip(mid, spread)]
    assert name == "MACD"
    slow, signal, field = edition
    ema_fast = smooth(xs, period, 2 / (period + 1))
    ema_slow = smooth(xs, slow, 2 / (slow + 1))
    line = [a - b for a, b in zip(ema_fast, ema_slow)]
    trigger = smooth(line, signal, 2 / (signal + 1))
    return {
        "line": line,
        "signal": trigger,
        "histogram": [a - b for a, b in zip(line, trigger)],
    }[field]


def samples(closes, spreads, volumes):
    return np.array(
        [[c, c + w, c - w, c, v] for c, w, v in zip(closes, spreads, volumes)],
        dtype="float64",
    )


def call_cases(period, closes, spreads, volumes):
    highs = [a + b for a, b in zip(closes, spreads)]
    lows = [a - b for a, b in zip(closes, spreads)]
    ratios = [a / (2 * b) if b else math.nan for a, b in zip(closes, spreads)]
    for name in ("SMA", "EMA", "HIGHEST", "LOWEST", "ROC", "STDDEV", "BBANDS"):
        for text, xs in (
            ("close", closes),
            ("volume", volumes),
            ("close/(high-low)", ratios),
        ):
            for field in ("lower", "middle", "upper") if name == "BBANDS" else (None,):
                edition = (2, field) if field else None
                expression = (
                    f"{name}({text},{period},2).{field}"
                    if field
                    else f"{name}({text},{period})"
                )
                ready = period if name == "ROC" else period - 1
                yield expression, ready, reference(name, xs, period, edition=edition)
    for name in ("SMA", "EMA", "RSI", "ATR"):
        ready = period if name == "RSI" else period - 1
        edition = (highs, lows) if name == "ATR" else None
        yield (
            f"{name}({period})",
            ready,
            reference(name, closes, period, edition=edition),
        )
    slow = min(period + 1, 10000)
    fast = min(period, slow - 1)
    for field in ("line", "signal", "histogram"):
        ready = slow - 1 if field == "line" else slow + period - 2
        yield (
            f"MACD({fast},{slow},{period}).{field}",
            ready,
            reference(
                "MACD",
                closes,
                fast,
                edition=(slow, period, field),
            ),
        )


@given(
    bars=st.lists(
        st.tuples(st.integers(10, 500), st.integers(0, 6), st.integers(0, 20)),
        min_size=2,
        max_size=32,
    ),
    period=st.integers(1, 9),
)
def test_catalog_against_independent_scalar_references(bars, period):
    closes, spreads, volumes = zip(*bars)
    cases = list(call_cases(period, closes, spreads, volumes))
    source = strategy_text(
        lets="\n".join(f"let v{i} = {expr}" for i, (expr, _, _) in enumerate(cases))
    )
    strategy = compile_source(source)
    data = replace(BASE, values=samples(closes, spreads, volumes))
    full = Evaluator(strategy, data, len(bars) - 1)
    for (_, node, _), (expr, ready, expected) in zip(strategy.bindings, cases):
        assert node.ready == ready, expr
        np.testing.assert_allclose(
            full.evaluate(node), expected, rtol=1e-12, atol=1e-12, err_msg=expr
        )


@pytest.mark.parametrize("period", [1, 2, 10000])
def test_window_boundaries_with_constant_inputs(period):
    # The exact answers follow from a constant market and constant dispersion zero.
    length = 2 * period + 1
    values = np.tile([12.0, 15.0, 10.0, 12.0, 6.0], (length, 1))
    fast, slow = (1, 2) if period == 1 else (period - 1, period)
    cases = [
        (f"SMA({period})", period - 1, 12),
        (f"EMA({period})", period - 1, 12),
        (f"RSI({period})", period, 50),
        (f"ATR({period})", period - 1, 5),
        (f"ROC(volume,{period})", period, 0),
        (f"STDDEV(close,{period})", period - 1, 0),
        (f"HIGHEST(high,{period})", period - 1, 15),
        (f"LOWEST(low,{period})", period - 1, 10),
        *[
            (f"BBANDS(close,{period},10).{field}", period - 1, 12)
            for field in ("upper", "middle", "lower")
        ],
        *[
            (
                f"MACD({fast},{slow},{period}).{field}",
                slow - 1 if field == "line" else slow + period - 2,
                0,
            )
            for field in ("line", "signal", "histogram")
        ],
    ]
    strategy = compile_source(
        strategy_text(
            lets="\n".join(f"let v{i} = {expr}" for i, (expr, _, _) in enumerate(cases))
        )
    )
    evaluator = Evaluator(strategy, replace(BASE, values=values), length - 1)
    for (_, node, _), (expr, ready, expected) in zip(strategy.bindings, cases):
        vector = evaluator.evaluate(node)
        assert node.ready == ready, expr
        assert np.isnan(vector[:ready]).all(), expr
        np.testing.assert_allclose(
            vector[ready:], expected, rtol=0, atol=1e-12, err_msg=expr
        )


@given(
    field=st.sampled_from(
        [
            "BBANDS(close/(high-low),2,1).upper",
            "BBANDS(close/(high-low),2,1).middle",
            "BBANDS(close/(high-low),2,1).lower",
            "MACD(1,2,2).line",
            "MACD(1,2,2).signal",
            "MACD(1,2,2).histogram",
        ]
    ),
    offset=st.integers(0, 3),
    prices=st.lists(st.integers(8, 90), min_size=2, max_size=15),
)
def test_graph_prefix_and_perturbation(field, offset, prices):
    direction = "above" if offset % 2 else "below"
    strategy = compile_source(
        strategy_text(
            lets=f"let level = EMA({field}[{offset}],2)\n"
            f"let crossed = level crosses {direction} 0",
            entry="crossed and not (volume < 0)",
            sizing="SMA(volume,2) / 10 volume of equity",
            risk="risk: stop loss ATR(2)",
        )
    )
    values = samples(prices, [i % 4 for i in range(len(prices))], range(len(prices)))
    data = replace(BASE, values=values)
    full = Evaluator(strategy, data, len(prices) - 1)
    for end in range(len(prices)):
        prefix = Evaluator(strategy, data, end)
        later = values.copy()
        later[end + 1 :] *= 3
        extended = np.concatenate([later, values])
        changed = Evaluator(strategy, replace(data, values=extended), len(extended) - 1)
        assert all(len(col) == end + 1 for col in prefix.columns.values())
        for node in (*strategy.roots()[:4], strategy.stop):
            if node is None:
                continue
            a = prefix.array(prefix.evaluate(node))
            np.testing.assert_equal(full.array(full.evaluate(node))[: end + 1], a)
            np.testing.assert_equal(changed.array(changed.evaluate(node))[: end + 1], a)
