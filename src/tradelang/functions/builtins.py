"""The ten indicator contracts and their numeric bindings."""

import numpy as np

from . import kernels
from .contracts import Field, Function, InvalidCall, Signature

EXPLICIT_WINDOW = Signature(("source", "period"))
CLOSE_WINDOW = Signature(("period",), implicit_close=True)
SOURCE_WINDOW = (EXPLICIT_WINDOW,)
OPTIONAL_CLOSE = (CLOSE_WINDOW, EXPLICIT_WINDOW)


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
        (Signature(("period",)),),
        "price",
        atr_ready,
        "reseed",
        kernels.atr,
        required_columns=("high", "low", "close"),
    ),
    Function(
        "BBANDS",
        (Signature(("source", "period", "multiplier")),),
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
)
