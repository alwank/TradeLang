"""Adaptive smoothers, regime measures, and regression indicators."""

import numpy as np

from .extended import checked_atr, trange
from .kernels import lag
from .rolling import count, divide, extreme, smooth_checked, totals


def alma(args, context):
    source, period, offset, sigma = args
    period = int(period)
    result = np.full(len(source), np.nan)
    if period > len(source):
        return result
    if period == 1:
        return np.where(np.isfinite(source), source, np.nan)
    positions = np.arange(period) - offset * (period - 1)
    weights = np.exp(-0.5 * (positions * (sigma / period)) ** 2)
    weights /= weights.sum()
    windows = np.lib.stride_tricks.sliding_window_view(source, period)
    batch_size = max(1, 262_144 // period)
    for start in range(0, len(windows), batch_size):
        batch = windows[start : start + batch_size]
        result[start + period - 1 : start + period - 1 + len(batch)] = np.sum(
            batch * weights, axis=1
        )
    count(context, "overflow", np.isinf(result))
    result[np.isinf(result)] = np.nan
    return result


def kama(args, context):
    source, period, fast, slow = args
    period = int(period)
    fast_alpha = 2 / (fast + 1)
    slow_alpha = 2 / (slow + 1)
    change = abs(source - lag(source, period))
    distance = totals(abs(source - lag(source, 1)), period)
    valid = np.isfinite(distance) & np.isfinite(change)
    efficiency = np.divide(
        change, distance, out=np.zeros(len(source)), where=valid & (distance > 0)
    )
    alpha = (slow_alpha + np.clip(efficiency, 0, 1) * (fast_alpha - slow_alpha)) ** 2
    result = np.full(len(source), np.nan)
    previous = None
    failures = 0
    for row, sample in enumerate(source):
        if not valid[row]:
            previous = None
            continue
        if previous is None:
            previous = source[row - 1]
        weight = alpha[row]
        previous = (1 - weight) * previous + weight * sample
        if np.isfinite(previous):
            result[row] = previous
        else:
            failures += 1
            previous = None
    if failures:
        context.invalid_counts["overflow"] = (
            context.invalid_counts.get("overflow", 0) + failures
        )
    return result


def ao(args, context):
    fast, slow = map(int, args)
    high, low = (context.columns[name] for name in ("high", "low"))
    midpoint = high / 2 + low / 2
    values = totals(midpoint, fast) / fast - totals(midpoint, slow) / slow
    count(context, "overflow", np.isinf(values))
    values[np.isinf(values)] = np.nan
    return values


def chop(args, context):
    period = int(args[0])
    high, low = (context.columns[name] for name in ("high", "low"))
    span = extreme(high, period, high=True) - extreme(low, period, high=False)
    relative = divide(totals(trange((), context), period), span, context)
    bad = np.isfinite(relative) & (relative <= 0)
    count(context, "domain", bad)
    return np.where(bad, np.nan, 100 * np.log10(relative) / np.log10(period))


def ultosc(args, context):
    high, low, close = (context.columns[name] for name in ("high", "low", "close"))
    previous = lag(close, 1)
    valid = np.isfinite(high) & np.isfinite(low) & np.isfinite(close)
    adjacent = valid & (lag(valid, 1) == 1)
    floor = np.minimum(low, previous)
    ceiling = np.maximum(high, previous)
    pressure = np.where(adjacent, close - floor, np.nan)
    ranges = np.where(adjacent, ceiling - floor, np.nan)
    numerators = [totals(pressure, int(period)) for period in args]
    denominators = [totals(ranges, int(period)) for period in args]
    complete = np.all(np.isfinite([*numerators, *denominators]), axis=0)
    zeros = complete & np.any(np.array(denominators) == 0, axis=0)
    count(context, "zero_denominator", zeros)
    available = complete & ~zeros
    value = np.zeros(len(close))
    for weight, numerator, denominator in zip(
        (4, 2, 1), numerators, denominators, strict=True
    ):
        value += weight * np.divide(
            numerator, denominator, out=np.zeros(len(close)), where=available
        )
    return np.where(available, 100 * value / 7, np.nan)


def tsi(args, context):
    source, slow, fast = args
    change = source - lag(source, 1)
    slow, fast = int(slow), int(fast)
    signed = smooth_checked(smooth_checked(change, slow, context), fast, context)
    magnitude = smooth_checked(
        smooth_checked(abs(change), slow, context), fast, context
    )
    ready = np.isfinite(signed) & np.isfinite(magnitude)
    output = np.full(len(source), np.nan)
    output[ready & (magnitude == 0)] = 0
    np.divide(signed, magnitude, out=output, where=ready & (magnitude != 0))
    count(context, "overflow", np.isinf(signed) | np.isinf(magnitude))
    return 100 * output


def lsma(args, context):
    source, period = args
    period = int(period)
    result = np.full(len(source), np.nan)
    if period > len(source):
        return result
    windows = np.lib.stride_tricks.sliding_window_view(source, period)
    batch_size = max(1, 262_144 // period)
    predictor = np.arange(period) - (period - 1) / 2
    weights = predictor * predictor[-1] / np.sum(predictor**2) + 1 / period
    for start in range(0, len(windows), batch_size):
        batch = windows[start : start + batch_size]
        # Shifting the intercept preserves small slopes on large price levels.
        origin = batch[:, -1]
        result[start + period - 1 : start + period - 1 + len(batch)] = origin + np.sum(
            (batch - origin[:, None]) * weights, axis=1
        )
    count(context, "overflow", np.isinf(result))
    result[np.isinf(result)] = np.nan
    return result


def chandelier(args, context):
    period, atr_period, factor = args
    period = int(period)
    high, low = (context.columns[name] for name in ("high", "low"))
    distance = factor * checked_atr(int(atr_period), context)
    long_exit = extreme(high, period, high=True) - distance
    short_exit = extreme(low, period, high=False) + distance
    count(context, "overflow", np.isinf(long_exit))
    count(context, "overflow", np.isinf(short_exit))
    return dict(long_exit=long_exit, short_exit=short_exit)
