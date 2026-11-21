"""Indicator contracts and their numeric bindings."""

from math import isqrt

import numpy as np

from ..model import PRICE
from . import additional, extended, kernels, momentum, profile, trend, volume
from .contracts import Field, Function, InvalidCall, Signature

EXPLICIT_WINDOW = Signature(("source", "period"))
CLOSE_WINDOW = Signature(("period",), implicit_close=True)
SOURCE_WINDOW = (EXPLICIT_WINDOW,)
OPTIONAL_CLOSE = (CLOSE_WINDOW, EXPLICIT_WINDOW)
PERIOD = (Signature(("period",)),)
OHLC = ("high", "low", "close")
OHLCV = (*OHLC, "volume")
NO_ARGUMENTS = (Signature(()),)
BANDS = (Signature(("source", "period", "multiplier")),)


def trailing(arguments):
    source, period, *_ = arguments
    return source.ready + int(period.value) - 1


def changes(arguments):
    return trailing(arguments) + 1


def atr_ready(arguments):
    return int(arguments[0].value) - 1


def macd_line(arguments):
    source, _, slow, _ = arguments
    return source.ready + int(slow.value) - 1


def macd_ready(arguments):
    return macd_line(arguments) + int(arguments[3].value) - 1


def validate_macd(arguments):
    _, fast, slow, _ = arguments
    if fast.value >= slow.value:
        raise InvalidCall("E202_PERIOD", "Fast period must be below slow period")


def immediate(_arguments):
    return 0


def di_ready(arguments):
    return int(arguments[0].value)


def dmi_ready(arguments):
    return di_ready(arguments) + int(arguments[1].value) - 1


def keltner_ready(arguments):
    return max(trailing(arguments), int(arguments[2].value) - 1)


def validate_keltner(arguments):
    if arguments[0].type.unit != PRICE:
        raise InvalidCall("E203_TYPE", "Keltner source must be a price series")


def stoch_k(arguments):
    period, k_period, _ = arguments
    return int(period.value + k_period.value) - 2


def stoch_ready(arguments):
    return stoch_k(arguments) + int(arguments[-1].value) - 1


def stochrsi_k(arguments):
    return int(arguments[0].value) + stoch_k(arguments[1:])


def stochrsi_ready(arguments):
    return stochrsi_k(arguments) + int(arguments[-1].value) - 1


def sar_ready(_arguments):
    return 1


def validate_sar(arguments):
    step, maximum = (argument.value for argument in arguments)
    if not 0 < step <= maximum <= 1:
        raise InvalidCall("E203_TYPE", "SAR requires 0 < step <= maximum <= 1")


def hma_ready(arguments):
    return trailing(arguments) + isqrt(int(arguments[1].value)) - 1


def ichimoku_conversion(arguments):
    return int(arguments[0].value) - 1


def ichimoku_base(arguments):
    return int(arguments[1].value) - 1


def ichimoku_ready(arguments):
    return int(arguments[2].value) - 1


def validate_ichimoku(arguments):
    conversion, base, span = (argument.value for argument in arguments)
    if not conversion <= base <= span:
        raise InvalidCall(
            "E202_PERIOD", "Ichimoku requires conversion <= base <= span B"
        )


def dema_ready(arguments):
    return trailing(arguments) + int(arguments[1].value) - 1


def tema_ready(arguments):
    return dema_ready(arguments) + int(arguments[1].value) - 1


def validate_alma(arguments):
    _, _, offset, sigma = (argument.value for argument in arguments)
    if not (0 <= offset <= 1 and 0 < sigma <= 100):
        raise InvalidCall(
            "E203_TYPE", "ALMA requires offset in 0..1 and sigma in (0, 100]"
        )


def validate_fast_slow(arguments):
    fast, slow = (argument.value for argument in arguments[-2:])
    if fast >= slow:
        raise InvalidCall("E202_PERIOD", "Fast period must be below slow period")


def ao_ready(arguments):
    return int(arguments[1].value) - 1


def validate_minimum_two(arguments):
    if arguments[-1].value < 2:
        raise InvalidCall("E202_PERIOD", "Period must be at least two")


def validate_ultosc(arguments):
    short, middle, long = (argument.value for argument in arguments)
    if not short < middle < long:
        raise InvalidCall(
            "E202_PERIOD", "Ultimate Oscillator requires short < medium < long"
        )


def ultosc_ready(arguments):
    return int(arguments[2].value)


def tsi_ready(arguments):
    return trailing(arguments) + int(arguments[2].value)


def validate_tsi(arguments):
    validate_fast_slow((arguments[2], arguments[1]))


def chandelier_ready(arguments):
    return int(max(arguments[0].value, arguments[1].value)) - 1


def zigzag_ready(arguments):
    return int(arguments[0].value + arguments[1].value)


def validate_zigzag(arguments):
    left, right, reversal = (argument.value for argument in arguments)
    if max(left, right) > 1000:
        raise InvalidCall("E202_PERIOD", "Zig Zag leg lengths must be at most 1000")
    if not 0 < reversal <= 1:
        raise InvalidCall("E203_TYPE", "Zig Zag reversal must be a fraction in (0, 1]")


def validate_vprofile(arguments):
    period, _, fraction = (argument.value for argument in arguments)
    if period > profile.MAX_PROFILE_WINDOW:
        raise InvalidCall("E202_PERIOD", "Volume Profile period must be at most 256")
    if not 0 < fraction <= 1:
        raise InvalidCall("E203_TYPE", "Value area must be a fraction in (0, 1]")


BUILTINS = (
    Function(
        "SMA",
        OPTIONAL_CLOSE,
        "source",
        trailing,
        "window",
        kernels.rolling_kernel(np.mean),
    ),
    Function("EMA", OPTIONAL_CLOSE, "source", trailing, "reseed", kernels.ema),
    Function(
        "RSI", (CLOSE_WINDOW,), "ratio", changes, "reseed", kernels.rsi, scale="points"
    ),
    Function(
        "MACD",
        (Signature(("period", "period", "period"), implicit_close=True),),
        "source",
        macd_ready,
        "reseed",
        kernels.macd,
        fields=(Field("line", macd_line), Field("signal"), Field("histogram")),
        validate=validate_macd,
    ),
    Function(
        "ATR",
        PERIOD,
        "price",
        atr_ready,
        "reseed",
        kernels.atr,
        required_columns=OHLC,
    ),
    Function(
        "BBANDS",
        BANDS,
        "source",
        trailing,
        "window",
        kernels.bbands,
        fields=(Field("upper"), Field("middle"), Field("lower")),
    ),
    Function(
        "HIGHEST",
        SOURCE_WINDOW,
        "source",
        trailing,
        "window",
        kernels.rolling_kernel(np.max),
    ),
    Function(
        "LOWEST",
        SOURCE_WINDOW,
        "source",
        trailing,
        "window",
        kernels.rolling_kernel(np.min),
    ),
    Function(
        "ROC",
        SOURCE_WINDOW,
        "ratio",
        changes,
        "interval",
        kernels.roc,
        scale="fraction",
    ),
    Function(
        "STDDEV",
        SOURCE_WINDOW,
        "source",
        trailing,
        "window",
        kernels.rolling_kernel(np.std),
    ),
    Function("WMA", OPTIONAL_CLOSE, "source", trailing, "window", volume.wma),
    Function("RMA", OPTIONAL_CLOSE, "source", trailing, "reseed", volume.rma),
    Function(
        "VWMA",
        OPTIONAL_CLOSE,
        "source",
        trailing,
        "window",
        volume.vwma,
        required_columns=("volume",),
    ),
    Function(
        "CMF",
        PERIOD,
        "ratio",
        atr_ready,
        "window",
        volume.cmf,
        required_columns=OHLCV,
        scale="fraction",
    ),
    Function(
        "OBV",
        NO_ARGUMENTS,
        "volume",
        immediate,
        "reseed",
        volume.obv,
        required_columns=("close", "volume"),
    ),
    Function(
        "VWAP",
        NO_ARGUMENTS,
        "price",
        immediate,
        "reseed",
        volume.vwap,
        required_columns=OHLCV,
        requires_clock=True,
    ),
    Function(
        "DONCHIAN",
        PERIOD,
        "price",
        atr_ready,
        "window",
        trend.donchian,
        fields=(Field("upper"), Field("middle"), Field("lower")),
        required_columns=("high", "low"),
    ),
    Function(
        "KELTNER",
        (
            Signature(("period", "period", "multiplier"), implicit_close=True),
            Signature(("source", "period", "period", "multiplier")),
        ),
        "price",
        keltner_ready,
        "reseed",
        trend.keltner,
        fields=(Field("upper"), Field("middle", trailing), Field("lower")),
        required_columns=OHLC,
        validate=validate_keltner,
    ),
    Function(
        "SUPERTREND",
        (Signature(("period", "multiplier")),),
        "price",
        atr_ready,
        "reseed",
        trend.supertrend,
        fields=(Field("line"), Field("direction", unit="ratio")),
        required_columns=OHLC,
    ),
    Function(
        "DMI",
        (Signature(("period", "period")),),
        "ratio",
        dmi_ready,
        "reseed",
        trend.dmi,
        fields=(Field("plus_di", di_ready), Field("minus_di", di_ready), Field("adx")),
        required_columns=OHLC,
        scale="points",
    ),
    Function(
        "STOCH",
        (Signature(("period", "period", "period")),),
        "ratio",
        stoch_ready,
        "window",
        momentum.stoch,
        fields=(Field("k", stoch_k), Field("d")),
        required_columns=OHLC,
        scale="points",
    ),
    Function(
        "STOCHRSI",
        (Signature(("period", "period", "period", "period")),),
        "ratio",
        stochrsi_ready,
        "reseed",
        momentum.stochrsi,
        fields=(Field("k", stochrsi_k), Field("d")),
        required_columns=("close",),
        scale="points",
    ),
    Function(
        "MFI",
        PERIOD,
        "ratio",
        di_ready,
        "window",
        momentum.mfi,
        required_columns=OHLCV,
        scale="points",
    ),
    Function(
        "CCI",
        PERIOD,
        "ratio",
        atr_ready,
        "window",
        momentum.cci,
        required_columns=OHLC,
        scale="points",
    ),
    Function(
        "WILLR",
        PERIOD,
        "ratio",
        atr_ready,
        "window",
        momentum.willr,
        required_columns=OHLC,
        scale="points",
    ),
    Function(
        "SAR",
        (Signature(("number", "number")),),
        "price",
        sar_ready,
        "reseed",
        trend.sar,
        required_columns=("high", "low"),
        validate=validate_sar,
    ),
    Function("HMA", OPTIONAL_CLOSE, "source", hma_ready, "window", extended.hma),
    Function(
        "ICHIMOKU",
        (Signature(("period", "period", "period")),),
        "price",
        ichimoku_ready,
        "window",
        extended.ichimoku,
        fields=(
            Field("conversion", ichimoku_conversion),
            Field("base", ichimoku_base),
            Field("span_a", ichimoku_base),
            Field("span_b"),
        ),
        required_columns=("high", "low"),
        validate=validate_ichimoku,
    ),
    Function(
        "AROON",
        PERIOD,
        "ratio",
        di_ready,
        "window",
        extended.aroon,
        fields=(Field("up"), Field("down"), Field("oscillator")),
        required_columns=("high", "low"),
        scale="points",
    ),
    Function("MOM", OPTIONAL_CLOSE, "source", changes, "interval", extended.mom),
    Function(
        "TRANGE",
        NO_ARGUMENTS,
        "price",
        immediate,
        "interval",
        extended.trange,
        required_columns=OHLC,
    ),
    Function(
        "NATR",
        PERIOD,
        "ratio",
        atr_ready,
        "reseed",
        extended.natr,
        required_columns=OHLC,
        scale="fraction",
    ),
    Function(
        "BBPCTB", BANDS, "ratio", trailing, "window", extended.bbpctb, scale="fraction"
    ),
    Function(
        "BBWIDTH",
        BANDS,
        "ratio",
        trailing,
        "window",
        extended.bbwidth,
        scale="fraction",
    ),
    Function(
        "ADL",
        NO_ARGUMENTS,
        "volume",
        immediate,
        "reseed",
        volume.adl,
        required_columns=OHLCV,
    ),
    Function(
        "RVOL",
        PERIOD,
        "ratio",
        di_ready,
        "interval",
        volume.rvol,
        required_columns=("volume",),
        scale="fraction",
    ),
    Function("DEMA", OPTIONAL_CLOSE, "source", dema_ready, "reseed", extended.dema),
    Function("TEMA", OPTIONAL_CLOSE, "source", tema_ready, "reseed", extended.tema),
    Function(
        "ALMA",
        (
            Signature(("period", "number", "number"), implicit_close=True),
            Signature(("source", "period", "number", "number")),
        ),
        "source",
        trailing,
        "window",
        additional.alma,
        validate=validate_alma,
    ),
    Function(
        "KAMA",
        (
            Signature(("period", "period", "period"), implicit_close=True),
            Signature(("source", "period", "period", "period")),
        ),
        "source",
        changes,
        "reseed",
        additional.kama,
        validate=validate_fast_slow,
    ),
    Function(
        "AO",
        (Signature(("period", "period")),),
        "price",
        ao_ready,
        "window",
        additional.ao,
        required_columns=("high", "low"),
        validate=validate_fast_slow,
    ),
    Function(
        "CHOP",
        PERIOD,
        "ratio",
        atr_ready,
        "window",
        additional.chop,
        required_columns=OHLC,
        validate=validate_minimum_two,
        scale="points",
    ),
    Function(
        "ULTOSC",
        (Signature(("period", "period", "period")),),
        "ratio",
        ultosc_ready,
        "window",
        additional.ultosc,
        required_columns=OHLC,
        validate=validate_ultosc,
        scale="points",
    ),
    Function(
        "TSI",
        (
            Signature(("period", "period"), implicit_close=True),
            Signature(("source", "period", "period")),
        ),
        "ratio",
        tsi_ready,
        "reseed",
        additional.tsi,
        validate=validate_tsi,
        scale="points",
    ),
    Function(
        "LSMA",
        OPTIONAL_CLOSE,
        "source",
        trailing,
        "window",
        additional.lsma,
        validate=validate_minimum_two,
    ),
    Function(
        "CHANDELIER",
        (Signature(("period", "period", "multiplier")),),
        "price",
        chandelier_ready,
        "reseed",
        additional.chandelier,
        fields=(Field("long_exit"), Field("short_exit")),
        required_columns=OHLC,
    ),
    Function(
        "ZIGZAG",
        (Signature(("period", "period", "number")),),
        "price",
        zigzag_ready,
        "reseed",
        trend.zigzag,
        fields=(
            Field("pivot"),
            Field("last_high"),
            Field("last_low"),
            Field("direction", unit="ratio"),
        ),
        required_columns=("high", "low"),
        validate=validate_zigzag,
    ),
    Function(
        "VPROFILE",
        (Signature(("period", "price_literal", "number")),),
        "price",
        atr_ready,
        "window",
        profile.vprofile,
        fields=(Field("poc"), Field("vah"), Field("val")),
        validate=validate_vprofile,
        requires_profile=True,
    ),
)
