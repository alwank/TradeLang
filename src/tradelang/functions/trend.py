"""Channels and trend indicators with per-field availability."""

import numpy as np

from .extended import checked_atr
from .kernels import lag
from .rolling import complete, count, extreme, smooth_checked
from .volume import rma_values


def donchian(args, context):
    period = int(args[0])
    upper = extreme(context.columns["high"], period, high=True)
    lower = extreme(context.columns["low"], period, high=False)
    return dict(upper=upper, middle=upper / 2 + lower / 2, lower=lower)


def keltner(args, context):
    source, ema_period, atr_period, factor = args
    middle = smooth_checked(source, int(ema_period), context)
    width = factor * checked_atr(int(atr_period), context)
    upper, lower = middle + width, middle - width
    count(context, "overflow", np.isinf(middle))
    count(context, "overflow", np.isinf(upper))
    count(context, "overflow", np.isinf(lower))
    return dict(upper=upper, middle=middle, lower=lower)


def supertrend(args, context):
    period, factor = args
    high, low, close = (context.columns[key] for key in ("high", "low", "close"))
    center = high / 2 + low / 2
    width = factor * checked_atr(int(period), context)
    basic_upper = center + width
    basic_lower = center - width
    line = np.full(len(close), np.nan)
    direction = line.copy()
    valid = np.isfinite(basic_upper) & np.isfinite(basic_lower) & np.isfinite(close)
    count(context, "overflow", np.isinf(basic_upper) | np.isinf(basic_lower))
    side = 0
    upper = lower = 0.0
    for row in range(len(close)):
        if not valid[row]:
            side = 0
            continue
        if side == 0:
            upper, lower = basic_upper[row], basic_lower[row]
            side = -1
        else:
            if basic_upper[row] < upper or close[row - 1] > upper:
                upper = basic_upper[row]
            if basic_lower[row] > lower or close[row - 1] < lower:
                lower = basic_lower[row]
            if side == -1 and close[row] > upper:
                side = 1
            elif side == 1 and close[row] < lower:
                side = -1
        line[row] = lower if side == 1 else upper
        direction[row] = side
    return dict(line=line, direction=direction)


def dmi(args, context):
    period, adx_period = map(int, args)
    high, low, close = (context.columns[key] for key in ("high", "low", "close"))
    valid = np.isfinite(high) & np.isfinite(low) & np.isfinite(close)
    plus, minus, true_range = (np.full(len(close), np.nan) for _ in range(3))
    adjacent = valid[1:] & valid[:-1]
    up = high[1:] - high[:-1]
    down = low[:-1] - low[1:]
    plus[1:] = np.where(adjacent, np.where((up > 0) & (up > down), up, 0), np.nan)
    minus[1:] = np.where(adjacent, np.where((down > 0) & (down > up), down, 0), np.nan)
    ranges = np.maximum(
        high[1:] - low[1:],
        np.maximum(abs(high[1:] - close[:-1]), abs(low[1:] - close[:-1])),
    )
    true_range[1:] = np.where(adjacent, ranges, np.nan)
    gain, _ = rma_values(plus, period)
    loss, _ = rma_values(minus, period)
    range_mean, _ = rma_values(true_range, period)

    def directional(numerator, denominator):
        out = np.full(len(close), np.nan)
        ready = np.isfinite(numerator) & np.isfinite(denominator)
        out[ready & (denominator == 0)] = 0
        np.divide(numerator, denominator, out=out, where=ready & (denominator != 0))
        return 100 * out

    plus_di = directional(gain, range_mean)
    minus_di = directional(loss, range_mean)
    dx = directional(abs(plus_di - minus_di), plus_di + minus_di)
    adx, _ = rma_values(dx, adx_period)
    return dict(plus_di=plus_di, minus_di=minus_di, adx=adx)


def sar(args, context):
    step, maximum = args
    high, low = (context.columns[key] for key in ("high", "low"))
    valid = np.isfinite(high) & np.isfinite(low)
    values = np.full(len(high), np.nan)
    prior_rows = 0
    level = extreme_price = acceleration = 0.0
    rising = True
    failures = 0
    for row, (top, bottom) in enumerate(zip(high, low, strict=True)):
        if not valid[row]:
            prior_rows = 0
            continue
        prior_rows += 1
        if prior_rows == 1:
            continue
        if prior_rows == 2:
            rising = low[row - 1] - bottom <= max(0.0, top - high[row - 1])
            if rising:
                level = min(low[row - 1], bottom)
                extreme_price = max(high[row - 1], top)
            else:
                level = max(high[row - 1], top)
                extreme_price = min(low[row - 1], bottom)
            acceleration = step
        else:
            projection = level + acceleration * (extreme_price - level)
            if rising:
                level = min(projection, low[row - 1], low[row - 2])
                if bottom <= level:
                    level = max(extreme_price, high[row - 1], top)
                    extreme_price, acceleration, rising = bottom, step, False
                elif top > extreme_price:
                    extreme_price = top
                    acceleration = min(maximum, acceleration + step)
            else:
                level = max(projection, high[row - 1], high[row - 2])
                if top >= level:
                    level = min(extreme_price, low[row - 1], bottom)
                    extreme_price, acceleration, rising = top, step, True
                elif bottom < extreme_price:
                    extreme_price = bottom
                    acceleration = min(maximum, acceleration + step)
        if np.isfinite(level):
            values[row] = level
        else:
            failures += 1
            prior_rows = 0
    if failures:
        context.invalid_counts["overflow"] = (
            context.invalid_counts.get("overflow", 0) + failures
        )
    return values


def zigzag(args, context):
    left, right = map(int, args[:2])
    reversal = args[2]
    highs, lows = (context.columns[key] for key in ("high", "low"))
    valid = np.isfinite(highs) & np.isfinite(lows)
    highs = np.where(valid, highs, np.nan)
    lows = np.where(valid, lows, np.nan)
    high_candidates = highs > lag(extreme(highs, left, high=True), 1)
    high_candidates = (lag(high_candidates, right) == 1) & (
        lag(highs, right) >= extreme(highs, right, high=True)
    )
    low_candidates = lows < lag(extreme(lows, left, high=False), 1)
    low_candidates = (lag(low_candidates, right) == 1) & (
        lag(lows, right) <= extreme(lows, right, high=False)
    )
    eligible = complete(highs, left + right)
    pivot, last_high, last_low, direction = (
        np.full(len(highs), np.nan) for _ in range(4)
    )
    high = low = np.nan
    side = 0
    for row in range(len(highs)):
        if not valid[row]:
            side = 0
            high = low = np.nan
        if not eligible[row]:
            continue
        center = row - right
        top, bottom = highs[center], lows[center]
        if high_candidates[row] and (
            side == 0 or (side == -1 and (top - low) / low >= reversal)
        ):
            side, high = 1, top
            pivot[row] = top
        elif low_candidates[row] and (
            side == 0 or (side == 1 and (high - bottom) / high >= reversal)
        ):
            side, low = -1, bottom
            pivot[row] = bottom
        if side:
            direction[row] = side
            last_high[row], last_low[row] = high, low
    return dict(
        pivot=pivot, last_high=last_high, last_low=last_low, direction=direction
    )
