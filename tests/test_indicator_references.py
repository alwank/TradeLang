"""Replay pinned TA-Lib outputs and source-derived chart comparisons offline."""

import hashlib
import json
import math
from pathlib import Path

import numpy as np
import pytest

from tradelang.functions.contracts import KernelContext
from tradelang.functions.registry import FUNCTIONS

FIXTURE = (
    Path(__file__).parent / "fixtures" / "indicator-expansion" / "vendor-reference.json"
)
REFERENCE = json.loads(FIXTURE.read_text())
CANDLES = {key: np.array(values) for key, values in REFERENCE["columns"].items()}


def evaluate(name, arguments):
    inputs = [
        CANDLES[value[1:]] if isinstance(value, str) else value for value in arguments
    ]
    result = FUNCTIONS[name].kernel(inputs, KernelContext(CANDLES, {}))
    return result if isinstance(result, dict) else {"value": result}


def test_fixture_preserves_the_reference_inputs():
    payload = json.dumps(
        REFERENCE["columns"], sort_keys=True, separators=(",", ":")
    ).encode()
    assert (
        hashlib.sha256(payload).hexdigest() == REFERENCE["reference"]["columns_sha256"]
    )


@pytest.mark.parametrize("name", REFERENCE["comparisons"])
def test_talib_reference(name):
    fixture = REFERENCE["comparisons"][name]
    outputs = evaluate(name, fixture["arguments"])
    for field, values in fixture["outputs"].items():
        expected = np.asarray(values, dtype=float)
        actual = outputs[field]
        if name == "OBV":
            expected -= expected[0]
        if name == "STOCH" and field == "k":
            assert np.flatnonzero(np.isfinite(actual))[0] == 4
            assert np.flatnonzero(np.isfinite(expected))[0] == 6
            actual = np.where(np.isfinite(expected), actual, np.nan)
        if name == "ALMA":
            assert np.isfinite(actual[4]) and not np.isclose(actual[4], expected[4])
            # TA-Lib floors the Gaussian center to bar 1 with these arguments.
            weights = [
                math.exp(-0.5 * ((index - 1) * 6 / 5) ** 2) for index in range(5)
            ]
            close = CANDLES["close"]
            actual = np.array(
                [
                    np.nan
                    if index < 4
                    else math.fsum(
                        value * weight
                        for value, weight in zip(close[index - 4 : index + 1], weights)
                    )
                    / sum(weights)
                    for index in range(len(close))
                ]
            )
        np.testing.assert_allclose(actual, expected, rtol=1e-10, atol=1e-10)


def test_lean_formula_scales_for_positive_price_bollinger_metrics():
    fixture = REFERENCE["formula_outputs"]["LEAN"]
    args = ["$close", fixture["period"], fixture["multiplier"]]
    np.testing.assert_allclose(
        evaluate("BBWIDTH", args)["value"],
        np.asarray(fixture["width_points"], dtype=float) / 100,
        rtol=1e-10,
        atol=1e-10,
    )
    np.testing.assert_allclose(
        evaluate("BBPCTB", args)["value"],
        np.asarray(fixture["percent_b"], dtype=float),
        rtol=1e-10,
        atol=1e-10,
    )


def test_tradingview_prior_volume_baseline_on_synthetic_candles():
    fixture = REFERENCE["formula_outputs"]["TradingView"]
    np.testing.assert_allclose(
        evaluate("RVOL", [fixture["period"]])["value"],
        np.asarray(fixture["relative_volume"], dtype=float),
        rtol=1e-10,
        atol=1e-10,
    )
