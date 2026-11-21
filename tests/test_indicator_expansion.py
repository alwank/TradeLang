"""Independent numeric and language checks for the expanded indicators."""

import math

import numpy as np
import pytest
from jsonschema import Draft202012Validator
from language_cases import CLOCK, METADATA, expression_text, strategy_text

from tradelang.api.contracts import AST_SCHEMA
from tradelang.compiler import compile_source
from tradelang.data import load_dataset, validate_indicator_data
from tradelang.engine import execute
from tradelang.evaluator import Evaluator
from tradelang.functions.contracts import KernelContext
from tradelang.functions.registry import FUNCTIONS
from tradelang.model import PRICE, RATIO, VOLUME, Problem

EXPANSION_CALLS = {
    "DMI": "DMI(3, 2).adx",
    "STOCH": "STOCH(3, 2, 3).d",
    "VWAP": "VWAP()",
    "SUPERTREND": "SUPERTREND(3, 2).direction",
    "DONCHIAN": "DONCHIAN(5).upper",
    "KELTNER": "KELTNER(EMA(2), 3, 6, 2).middle",
    "STOCHRSI": "STOCHRSI(2, 3, 2, 3).d",
    "OBV": "OBV()",
    "MFI": "MFI(3)",
    "CCI": "CCI(4)",
    "WILLR": "WILLR(3)",
    "SAR": "SAR(0.02, 0.2)",
    "WMA": "WMA(volume, 4)",
    "RMA": "RMA(close / WMA(2), 4)",
    "VWMA": "VWMA(4)",
    "CMF": "CMF(4)",
    "HMA": "HMA(volume, 5)",
    "ICHIMOKU": "ICHIMOKU(2, 3, 5).span_a[1]",
    "AROON": "AROON(4).oscillator",
    "MOM": "MOM(volume, 3)",
    "TRANGE": "TRANGE()",
    "NATR": "NATR(4)",
    "BBPCTB": "BBPCTB(close, 4, 2)",
    "BBWIDTH": "BBWIDTH(close, 4, 2)",
    "ADL": "ADL()",
    "RVOL": "RVOL(4)",
    "DEMA": "DEMA(close, 3)",
    "TEMA": "TEMA(close, 3)",
    "ALMA": "ALMA(volume, 5, 0.32, 3)",
    "KAMA": "KAMA(close, 4, 2, 5)",
    "AO": "AO(2, 4)",
    "CHOP": "CHOP(4)",
    "ULTOSC": "ULTOSC(1, 3, 5)",
    "TSI": "TSI(close, 5, 3)",
    "LSMA": "LSMA(volume, 4)",
    "CHANDELIER": "CHANDELIER(4, 3, 2).short_exit",
    "ZIGZAG": "ZIGZAG(2, 3, 0.05).last_high",
    "VPROFILE": "VPROFILE(5, 1 price, 0.7).poc",
}


class MarketSeries:
    def __init__(self, *, suffix=0):
        rows = np.arange(48)
        self.times = rows * 3_600_000_000
        price = 100 + rows / 10 + 10 * np.sin(rows)
        volume = (rows % 11).astype(float)
        price[23:] += suffix
        self.columns = {
            "open": price,
            "high": price + 2,
            "low": price - 1,
            "close": price,
            "volume": volume,
        }

    def column(self, key):
        return self.columns[key]


def test_every_expansion_call_validates_against_the_public_schema():
    validator = Draft202012Validator(AST_SCHEMA)
    bindings = "\n".join(
        f"let indicator_{rank} = {call}"
        for rank, call in enumerate(EXPANSION_CALLS.values(), 1)
    )
    assert len(EXPANSION_CALLS) == 38
    strategy = compile_source(strategy_text(lets=bindings))
    validator.validate(strategy.public())
    assert all(next(strategy.calls(name), None) is not None for name in EXPANSION_CALLS)


def test_rsi_scale_warning_does_not_spread_to_other_point_indicators():
    strategy = compile_source(strategy_text(entry="CCI(3) > 2%"))
    assert all(warning["code"] != "W_RSI_SCALE" for warning in strategy.warnings)


@pytest.mark.parametrize(
    "name", [name for name in EXPANSION_CALLS if name != "VPROFILE"]
)
def test_compiled_indicators_are_exactly_invariant_under_suffix_changes(name):
    source = expression_text(EXPANSION_CALLS[name]).replace("1d", "1h")
    strategy = compile_source(source)
    call = next(strategy.calls(name))
    data = MarketSeries()
    earlier = Evaluator(strategy, data, 22)
    later = Evaluator(strategy, data, 47)
    perturbed = Evaluator(strategy, MarketSeries(suffix=340), 47)
    reference = earlier.evaluate(call)
    full = later.evaluate(call)
    changed = perturbed.evaluate(call)
    if isinstance(reference, dict):
        assert reference.keys() == full.keys() == changed.keys()
        for field, values in reference.items():
            assert np.isnan(
                values[: FUNCTIONS[name].field_ready(field, call.args)]
            ).all()
            np.testing.assert_equal(values, full[field][:23])
            np.testing.assert_equal(values, changed[field][:23])
    else:
        assert np.isnan(reference[: call.ready]).all()
        np.testing.assert_equal(reference, full[:23])
        np.testing.assert_equal(reference, changed[:23])


def calculate(name, args, *, times=None, **columns):
    context = KernelContext(
        {key: np.array(value) for key, value in columns.items()},
        {},
        times=None if times is None else np.array(times, dtype=np.int64),
    )
    with np.errstate(all="ignore"):
        output = FUNCTIONS[name].kernel(args, context)
    return output, context.invalid_counts


@pytest.mark.parametrize("name", ["WMA", "RMA", "VWMA"])
def test_source_overload_preserves_units_and_readiness(name):
    expr = compile_source(expression_text(f"{name}(EMA(volume, 3), 4)[1]")).bindings[0][
        1
    ]
    assert expr.type.unit == VOLUME
    assert expr.ready == 6
    implicit = compile_source(expression_text(f"{name}(3)")).bindings[0][1]
    explicit = compile_source(expression_text(f"{name}(close, 3)")).bindings[0][1]
    assert implicit.args[0].value == explicit.args[0].value == "close"
    assert implicit.ready == explicit.ready == 2


@pytest.mark.parametrize("period", [1, 3, 10000])
def test_weighted_average_against_direct_windows(period):
    source = 100 + np.sin(np.arange(10150) / 10)
    source[53] = np.nan
    weights = list(range(1, period + 1))
    out, invalid = calculate("WMA", [source, period])
    assert invalid == {}
    weight_sum = sum(weights)
    for row in range(period - 1, len(source)):
        window = source[row - period + 1 : row + 1]
        expected = (
            sum(weight * value for weight, value in zip(weights, window)) / weight_sum
        )
        if math.isnan(expected):
            assert math.isnan(out[row])
        else:
            assert out[row] == pytest.approx(expected, rel=1e-10)
    prefix, _ = calculate("WMA", [source[:10077], period])
    np.testing.assert_equal(prefix, out[:10077])


def test_wilder_reseeds_after_a_hole():
    source = np.array([3.0, 9.0, 12.0, np.nan, 10.0, 14.0, 20.0])
    out, _ = calculate("RMA", [source, 2])
    np.testing.assert_allclose(out, [np.nan, 6, 9, np.nan, np.nan, 12, 16])
    identity, _ = calculate("RMA", [source, 1])
    np.testing.assert_equal(identity, source)


def test_vwma_zero_volume_and_missing_source_are_distinct():
    source = np.array([10.0, 20.0, 30.0, np.nan, 50.0, 60.0])
    out, invalid = calculate("VWMA", [source, 2], volume=[0, 0, 3, 0, 1, 3])
    np.testing.assert_equal(out, [np.nan, np.nan, 30, np.nan, np.nan, 57.5])
    assert invalid == {"zero_denominator": 1}


def test_cmf_price_extremes_and_flat_candles():
    out, invalid = calculate(
        "CMF",
        [2],
        high=[12, 12, 10, 12, 12, 12],
        low=[8, 8, 10, 8, 8, 8],
        close=[12, 8, 10, 12, 8, 12],
        volume=[2, 1, 1, 0, 0, 2],
    )
    np.testing.assert_allclose(out, [np.nan, 1 / 3, -0.5, 0, np.nan, 1])
    assert invalid == {"zero_denominator": 1}


def test_obv_has_volume_units_and_resets():
    compiled = compile_source(expression_text("OBV()[1]")).bindings[0][1]
    assert compiled.ready == 1
    assert compiled.type.unit == VOLUME
    out, invalid = calculate(
        "OBV",
        [],
        close=[100, 110, 110, 90, 100, np.nan, 75],
        volume=[9, 5, 7, 3, 0, 12, 4],
    )
    np.testing.assert_equal(out, [0, 5, 5, 2, 2, np.nan, 0])
    assert invalid == {}


def test_vwap_anchor_at_midnight_and_across_skipped_days():
    minute = 60_000_000
    day = 1440 * minute
    prices = [100, 110, 120, 105, 200, 220]
    out, invalid = calculate(
        "VWAP",
        [],
        times=[
            day - minute,
            day,
            day + minute,
            day + 2 * minute,
            3 * day,
            3 * day + minute,
        ],
        high=prices,
        low=prices,
        close=prices,
        volume=[1, 0, 2, 1, 0, 4],
    )
    np.testing.assert_allclose(out, [100, np.nan, 120, 115, np.nan, 220])
    assert invalid == {}


def test_vwap_requires_whole_intraday_sessions():
    source = expression_text("VWAP()")
    with pytest.raises(Problem, match="intraday") as err:
        validate_indicator_data(compile_source(source))
    assert err.value.diagnostic["code"] == "E402_WINDOW"
    validate_indicator_data(compile_source(source.replace("1d", "1h")))
    with pytest.raises(Problem, match="intraday"):
        validate_indicator_data(compile_source(source.replace("1d", "7m")))


def test_donchian_fields_have_independent_masks():
    out, _ = calculate(
        "DONCHIAN", [2], high=[14, 12, np.nan, 16, 16], low=[9, 8, 10, 7, 6]
    )
    np.testing.assert_equal(out["upper"], [np.nan, 14, np.nan, np.nan, 16])
    np.testing.assert_equal(out["lower"], [np.nan, 8, 8, 7, 6])
    np.testing.assert_equal(out["middle"], [np.nan, 11, np.nan, np.nan, 11])


def test_keltner_middle_readiness_and_price_only_source():
    middle = compile_source(expression_text("KELTNER(2, 4, 2).middle")).bindings[0][1]
    upper = compile_source(expression_text("KELTNER(EMA(5), 2, 4, 2).upper")).bindings[
        0
    ][1]
    assert middle.ready == 1
    assert upper.ready == 5
    with pytest.raises(Problem, match="price series"):
        compile_source(expression_text("KELTNER(volume, 2, 4, 2).upper"))
    prices = np.array([10.0, 12.0, 14.0, 16.0])
    out, _ = calculate(
        "KELTNER", [prices, 2, 3, 1], high=prices + 1, low=prices - 1, close=prices
    )
    np.testing.assert_allclose(out["middle"], [np.nan, 11, 13, 15])
    np.testing.assert_allclose(out["upper"], [np.nan, np.nan, 15 + 2 / 3, 17 + 7 / 9])


def test_keltner_reseeds_its_ema_after_numeric_overflow():
    source = np.array([1e308, 1e308, 10, 14, 16])
    ohlc = [10] * len(source)
    result, diagnostics = calculate(
        "KELTNER",
        [source, 2, 1, 2],
        high=ohlc,
        low=ohlc,
        close=ohlc,
    )
    np.testing.assert_allclose(result["middle"], [np.nan, np.nan, np.nan, 12, 44 / 3])
    assert diagnostics == {"overflow": 1}


def test_donchian_volume_breakout_fills_at_the_next_open(tmp_path):
    candle_path = tmp_path / "breakout.csv"
    prices = [100, 100, 100, 110, 120, 114]
    volumes = [1, 1, 1, 20, 1, 1]
    rows = ["timestamp,open,high,low,close,volume"]
    rows.extend(
        f"2024-01-{day:02}T00:00:00Z,{price},{price + 1},{price - 1},{price},{volume}"
        for day, (price, volume) in enumerate(zip(prices, volumes), 1)
    )
    candle_path.write_text("\n".join(rows) + "\n")
    data = load_dataset(candle_path, METADATA, as_of_utc=CLOCK)
    source = strategy_text(
        lets="let band = DONCHIAN(2).upper[1]\nlet volume_spike = RVOL(2) > 1.2",
        entry="(close crosses above band) and volume_spike",
        exit="close > 200 price",
        end="2024-01-06",
    )
    events = execute(compile_source(source), data)["events"]
    [fill] = [event for event in events if event["kind"] == "fill"]
    assert fill["observed_at"] == "2024-01-05T00:00:00Z"
    assert fill["fill_price"] == 120


def test_supertrend_mixed_units_both_flips_and_contextual_field_names():
    source = strategy_text(
        lets="let direction = SUPERTREND(1, 1).direction\nlet level = SUPERTREND(1, 1).line"
    )
    strategy = compile_source(source)
    side, line = (binding[1] for binding in strategy.bindings)
    assert side.type.unit == RATIO
    assert line.type.unit == PRICE
    fields = side.args[0].type.public()["fields"]
    assert fields["line"]["dimension"] == line.type.public()["dimension"]
    assert fields["direction"]["dimension"] == side.type.public()["dimension"]
    prices = [10, 12, 9, 9, 13]
    out, _ = calculate("SUPERTREND", [1, 1], high=prices, low=prices, close=prices)
    np.testing.assert_equal(out["direction"], [-1, 1, -1, -1, 1])
    np.testing.assert_equal(out["line"], [10, 10, 12, 9, 9])


def test_dmi_uses_independent_periods_and_zero_for_a_tie():
    source = expression_text("DMI(2, 3).plus_di")
    di = compile_source(source).bindings[0][1]
    assert di.ready == 2
    assert di.args[0].ready == 4
    out, _ = calculate(
        "DMI",
        [1, 2],
        high=[12, 13, 14, 15, 15],
        low=[10, 11, 10, 11, 11],
        close=[11, 12, 12, 13, 13],
    )
    np.testing.assert_allclose(out["plus_di"], [np.nan, 50, 0, 25, 0])
    np.testing.assert_equal(out["minus_di"], [np.nan, 0, 0, 0, 0])
    np.testing.assert_equal(out["adx"], [np.nan, np.nan, 50, 75, 37.5])


def test_stochastic_smoothing_has_distinct_k_and_d_windows():
    out, _ = calculate(
        "STOCH",
        [2, 2, 2],
        high=[20, 20, 20, 20, 20],
        low=[10, 10, 10, 10, 10],
        close=[10, 20, 10, 15, 15],
    )
    np.testing.assert_equal(out["k"], [np.nan, np.nan, 50, 25, 50])
    np.testing.assert_equal(out["d"], [np.nan, np.nan, np.nan, 37.5, 37.5])
    expression = compile_source(expression_text("STOCH(2, 2, 2).k[1]")).bindings[0][1]
    assert expression.ready == 3


def test_stochastic_rsi_on_a_flat_seed():
    out, _ = calculate("STOCHRSI", [2, 3, 2, 2], close=np.full(10, 10.0))
    np.testing.assert_equal(out["k"], [np.nan] * 5 + [0] * 5)
    np.testing.assert_equal(out["d"], [np.nan] * 6 + [0] * 4)


def test_money_flow_all_positive_negative_and_zero():
    prices = [10, 11, 12, 11, 10, 10, 10]
    out, _ = calculate(
        "MFI", [2], high=prices, low=prices, close=prices, volume=[1] * 7
    )
    np.testing.assert_allclose(out, [np.nan, np.nan, 100, 100 * 12 / 23, 0, 0, 50])


def test_commodity_channel_index_mean_absolute_deviation_and_flat():
    prices = [10.0, 11.0, 12.0, 12.0, 12.0]
    out, _ = calculate("CCI", [3], high=prices, low=prices, close=prices)
    np.testing.assert_allclose(out, [np.nan, np.nan, 100, 50, 0], atol=1e-12)


def test_wide_cci_uses_online_absolute_deviation_through_holes():
    source = 1000 + np.sin(np.arange(4400))
    source[2100] = np.nan
    period = 2048
    out, _ = calculate("CCI", [period], high=source, low=source, close=source)
    for index in (period - 1, 2099, 2100, 4150, 4399):
        samples = source[index - period + 1 : index + 1]
        center = math.fsum(samples) / period
        mad = math.fsum(abs(sample - center) for sample in samples) / period
        expected = (samples[-1] - center) / (0.015 * mad)
        np.testing.assert_allclose(out[index], expected, atol=1e-10)


def test_volume_mean_recovers_after_large_prefix_leaves_window():
    out, invalid = calculate(
        "VWMA", [np.array([10.0, 10, 20, 30]), 2], volume=[1e30, 1, 1, 1]
    )
    np.testing.assert_allclose(out, [np.nan, 10, 15, 25])
    assert invalid == {}


def test_williams_range_uses_point_scale_and_zero_on_flat():
    out, _ = calculate(
        "WILLR",
        [1],
        high=[20, 20, 20, 20],
        low=[10, 10, 10, 20],
        close=[10, 15, 20, 20],
    )
    np.testing.assert_equal(out, [-100, -50, 0, 0])


def test_parabolic_sar_reverses_on_equality_then_reseeds():
    out, _ = calculate(
        "SAR",
        [0.2, 0.4],
        high=[12, 13, 14, 14, np.nan, 12, 11],
        low=[10, 11, 10, 9, np.nan, 10, 9],
    )
    np.testing.assert_allclose(out, [np.nan, 10, 14, 9, np.nan, np.nan, 12])
    for expression in ("SAR(0.3, 0.2)", "SAR(2%, 0.2)", "SAR(0, 0.2)"):
        with pytest.raises(Problem) as err:
            compile_source(expression_text(expression))
        assert err.value.diagnostic["code"] == "E203_TYPE"


def moving_average(values, period, weights=None):
    out = [math.nan] * len(values)
    weights = [1] * period if weights is None else weights
    for row in range(period - 1, len(values)):
        trailing = values[row + 1 - period : row + 1]
        out[row] = math.fsum(
            value * weight for value, weight in zip(trailing, weights)
        ) / sum(weights)
    return out


def scalar_ema(values, period):
    result = []
    seed = []
    state = None
    decay = 2 / (period + 1)
    for sample in values:
        if not math.isfinite(sample):
            state = None
            seed.clear()
        elif state is None:
            seed.append(sample)
            if len(seed) == period:
                state = math.fsum(seed) / period
        else:
            state = decay * sample + (1 - decay) * state
        result.append(math.nan if state is None else state)
    return result


def test_hull_odd_period_and_floor_of_square_root():
    source = [10, 10, 12, 8, 11, 14, 7, 12, 11, 20, 8]
    long = moving_average(source, 5, [1, 2, 3, 4, 5])
    short = moving_average(source, 2, [1, 2])
    expected = moving_average(
        [2 * fast - slow for fast, slow in zip(short, long)], 2, [1, 2]
    )
    out, _ = calculate("HMA", [np.array(source), 5])
    np.testing.assert_allclose(out, expected)


def test_ichimoku_calculation_time_and_explicit_displacement():
    out, _ = calculate(
        "ICHIMOKU", [1, 2, 3], high=[11, 13, 12, 18, 14], low=[9, 7, 10, 14, 12]
    )
    np.testing.assert_allclose(out["conversion"], [10, 10, 11, 16, 13])
    np.testing.assert_allclose(out["base"], [np.nan, 10, 10, 14, 15])
    np.testing.assert_allclose(out["span_a"], [np.nan, 10, 10.5, 15, 14])
    np.testing.assert_allclose(out["span_b"], [np.nan, np.nan, 10, 12.5, 14])
    span = compile_source(expression_text("ICHIMOKU(9, 26, 52).span_a[26]")).bindings[
        0
    ][1]
    assert span.ready == 51


def test_aroon_selects_the_most_recent_equal_extreme():
    out, _ = calculate("AROON", [2], high=[15, 10, 15, 12], low=[8, 6, 6, 7])
    np.testing.assert_allclose(out["up"], [np.nan, np.nan, 100, 50])
    np.testing.assert_allclose(out["down"], [np.nan, np.nan, 100, 50])
    np.testing.assert_allclose(out["oscillator"], [np.nan, np.nan, 0, 0])


def test_momentum_requires_the_full_interval():
    source = np.array([3, 8, np.nan, 20, 11, 1])
    out, _ = calculate("MOM", [source, 2])
    np.testing.assert_equal(out, [np.nan] * 5 + [-19])


def test_true_range_and_normalized_atr():
    ohlc = {"high": [11, 13, 16, 15], "low": [9, 11, 14, 11], "close": [10, 12, 15, 13]}
    true, _ = calculate("TRANGE", [], **ohlc)
    np.testing.assert_equal(true, [2, 3, 4, 4])
    normalized, _ = calculate("NATR", [2], **ohlc)
    np.testing.assert_allclose(normalized, [np.nan, 2.5 / 12, 3.25 / 15, 3.625 / 13])


@pytest.mark.parametrize(
    "name, source, expected, failures",
    [
        ("BBPCTB", [1, 3, 3], [np.nan, 1, np.nan], 1),
        ("BBWIDTH", [-1, -3, 3], [np.nan, 1, np.nan], 1),
    ],
)
def test_band_ratios_and_zero_denominators(name, source, expected, failures):
    out, invalid = calculate(name, [np.array(source), 2, 1])
    np.testing.assert_equal(out, expected)
    assert invalid == {"zero_denominator": failures}


def test_accumulation_distribution_starts_with_the_first_candle():
    out, _ = calculate(
        "ADL",
        [],
        high=[13, 12, 10, 15, 12],
        low=[9, 8, 10, 9, 8],
        close=[13, 8, 10, 9, 10],
        volume=[3, 2, 8, 0, 2],
    )
    np.testing.assert_equal(out, [3, 1, 1, 1, 1])


def test_relative_volume_excludes_the_current_candle():
    out, invalid = calculate("RVOL", [2], volume=[0, 0, 3, 3, 30, 3])
    np.testing.assert_allclose(out, [np.nan, np.nan, np.nan, 2, 10, 2 / 11])
    assert invalid == {"zero_denominator": 1}


@pytest.mark.parametrize("name", ["DEMA", "TEMA"])
def test_ema_cascades_against_scalar_seeds(name):
    source = [3, 8, 12, 1, 0, 2, 3, np.nan, 8, 9, 8, 10, 11, 5, 12, 1, -6]
    first = scalar_ema(source, 3)
    second = scalar_ema(first, 3)
    if name == "DEMA":
        expected = [2 * a - b for a, b in zip(first, second)]
    else:
        third = scalar_ema(second, 3)
        expected = [3 * a - 3 * b + c for a, b, c in zip(first, second, third)]
    out, _ = calculate(name, [np.array(source), 3])
    np.testing.assert_allclose(out, expected, atol=1e-12)


def test_alma_fractional_center_against_scalar_weights():
    source = [2, 3, 8, 5, 5, 7, 8]
    weights = [math.exp(-0.5 * ((n - 0.37 * 3) * 4 / 4) ** 2) for n in range(4)]
    out, _ = calculate("ALMA", [np.array(source), 4, 0.37, 4])
    np.testing.assert_allclose(out, moving_average(source, 4, weights))


def test_kama_seed_and_reset_are_sampled_at_the_first_eligible_row():
    source = np.array([10, 11, 12, 12, np.nan, 9, 8, 7, 7])
    out, _ = calculate("KAMA", [source, 2, 1, 5])
    np.testing.assert_allclose(
        out, [np.nan, np.nan, 12, 12, np.nan, np.nan, np.nan, 7, 7]
    )


def test_awesome_oscillator_uses_candle_midpoint():
    out, _ = calculate("AO", [1, 3], high=[13, 15, 17, 16], low=[9, 9, 13, 10])
    np.testing.assert_allclose(out, [np.nan, np.nan, 15 - 38 / 3, 13 - 40 / 3])


def test_choppiness_gap_and_flat():
    out, invalid = calculate(
        "CHOP", [2], high=[1, 11, 12, 12], low=[1, 11, 12, 12], close=[1, 11, 12, 12]
    )
    np.testing.assert_allclose(out, [np.nan, 0, 100 * math.log2(11), np.nan])
    assert invalid == {"zero_denominator": 1}


def test_ultimate_oscillator_horizons_and_flat_range():
    close = [10, 11, 12, 13, 13, 13, 13]
    out, invalid = calculate("ULTOSC", [1, 2, 3], high=close, low=close, close=close)
    np.testing.assert_equal(out, [np.nan, np.nan, np.nan, 100, np.nan, np.nan, np.nan])
    assert invalid == {"zero_denominator": 3}


def test_true_strength_on_monotone_and_flat_paths():
    for source, expected in (
        (np.arange(10), 100),
        (np.arange(10)[::-1], -100),
        (np.ones(10), 0),
    ):
        out, _ = calculate("TSI", [source, 3, 2])
        np.testing.assert_allclose(out, [np.nan] * 4 + [expected] * 6)


def test_lsma_preserves_small_slopes_at_large_price_levels():
    source = 10**14 + np.arange(30) * 0.25
    out, _ = calculate("LSMA", [source, 15])
    np.testing.assert_equal(out, [np.nan] * 14 + list(source[14:]))


def test_chandelier_uses_independent_price_and_atr_windows():
    out, _ = calculate(
        "CHANDELIER",
        [2, 1, 2],
        high=[11, 12, 13],
        low=[9, 10, 11],
        close=[10, 11, 12],
    )
    np.testing.assert_equal(out["long_exit"], [np.nan, 8, 9])
    np.testing.assert_equal(out["short_exit"], [np.nan, 13, 14])


def test_zigzag_flips_only_when_confirmed_and_keeps_previous_extremes():
    source = [90, 100, 93, 90, 91, 99, 98, 90]
    out, _ = calculate("ZIGZAG", [1, 1, 0.1], high=source, low=source)
    np.testing.assert_equal(
        out["pivot"], [np.nan, np.nan, 100, np.nan, 90, np.nan, 99, np.nan]
    )
    np.testing.assert_equal(
        out["last_high"], [np.nan, np.nan, 100, 100, 100, 100, 99, 99]
    )
    np.testing.assert_equal(
        out["last_low"], [np.nan, np.nan, np.nan, np.nan, 90, 90, 90, 90]
    )
    np.testing.assert_equal(out["direction"], [np.nan, np.nan, 1, 1, -1, -1, 1, 1])
