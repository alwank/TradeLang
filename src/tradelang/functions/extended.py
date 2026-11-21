"""Derived moving averages, range indicators, and band measures."""

from math import isqrt

import numpy as np

from .kernels import bbands, lag
from .rolling import complete, count, divide, extreme, smooth_checked
from .volume import wma_values


def hma(args, context):
    source, period = args
    period = int(period)
    fast = wma_values(source, max(1, period // 2))
    combined = fast + (fast - wma_values(source, period))
    values = wma_values(combined, isqrt(period))
    count(context, "overflow", np.isinf(combined) | np.isinf(values))
    values[np.isinf(values)] = np.nan
    return values


def ichimoku(args, context):
    conversion, base, span_b = map(int, args)
    high, low = (context.columns[name] for name in ("high", "low"))

    def midpoint(period):
        return (
            extreme(high, period, high=True) / 2 + extreme(low, period, high=False) / 2
        )

    conversion_line = midpoint(conversion)
    base_line = midpoint(base)
    leading_a = conversion_line / 2 + base_line / 2
    return dict(
        conversion=conversion_line,
        base=base_line,
        span_a=leading_a,
        span_b=midpoint(span_b),
    )


def aroon(args, context):
    period = int(args[0])
    high, low = (context.columns[name] for name in ("high", "low"))
    up = 100 * (period - extreme(high, period + 1, high=True, age=True)) / period
    down = 100 * (period - extreme(low, period + 1, high=False, age=True)) / period
    return dict(up=up, down=down, oscillator=up - down)


def mom(args, context):
    source, period = args
    period = int(period)
    values = np.where(complete(source, period), source - lag(source, period), np.nan)
    count(context, "overflow", np.isinf(values))
    values[np.isinf(values)] = np.nan
    return values


def trange(_args, context):
    high, low, close = (context.columns[name] for name in ("high", "low", "close"))
    valid = np.isfinite(high) & np.isfinite(low) & np.isfinite(close)
    distance = high - low
    previous = close[:-1]
    distance[1:] = np.where(
        valid[:-1],
        np.maximum(
            distance[1:], np.maximum(abs(high[1:] - previous), abs(low[1:] - previous))
        ),
        distance[1:],
    )
    count(context, "overflow", valid & np.isinf(distance))
    return np.where(valid & np.isfinite(distance), distance, np.nan)


def natr(args, context):
    return divide(checked_atr(int(args[0]), context), context.columns["close"], context)


def checked_atr(period, context):
    return smooth_checked(trange((), context), period, context, wilder=True)


def bbpctb(args, context):
    bands = bbands(args, context)
    return divide(args[0] - bands["lower"], bands["upper"] - bands["lower"], context)


def bbwidth(args, context):
    bands = bbands(args, context)
    return divide(bands["upper"] - bands["lower"], abs(bands["middle"]), context)


def ema_cascade(args, context, *, triple):
    source, period = args
    period = int(period)
    if period == 1:
        return np.where(np.isfinite(source), source, np.nan)
    first = smooth_checked(source, period, context)
    second = smooth_checked(first, period, context)
    if triple:
        third = smooth_checked(second, period, context)
        values = 3 * (first - second) + third
    else:
        values = first + (first - second)
    count(context, "overflow", np.isinf(values))
    values[np.isinf(values)] = np.nan
    return values


def dema(args, context):
    return ema_cascade(args, context, triple=False)


def tema(args, context):
    return ema_cascade(args, context, triple=True)
