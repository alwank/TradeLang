"""Moving averages and volume flow over completed bars."""

import numpy as np

from .kernels import lag
from .rolling import count, divide, totals

DAY_US = 86_400_000_000


def wma_values(source, period):
    return totals(source, period, weighted=True) / (period * (period + 1) / 2)


def wma(args, context):
    source, period = args
    values = wma_values(source, int(period))
    overflow = np.isinf(values)
    count(context, "overflow", overflow)
    values[overflow] = np.nan
    return values


def rma_values(source, period):
    values = np.full(len(source), np.nan)
    overflow = np.zeros(len(source), dtype=bool)
    if period == 1:
        return np.where(np.isfinite(source), source, np.nan), overflow
    seen = 0
    mean = 0.0
    for index, sample in enumerate(source):
        if not np.isfinite(sample):
            seen = 0
            mean = 0.0
            continue
        seen += 1
        weight = 1 / min(seen, period)
        mean = (1 - weight) * mean + weight * sample
        if not np.isfinite(mean):
            overflow[index] = True
            seen = 0
            mean = 0.0
        elif seen >= period:
            values[index] = mean
    return values, overflow


def rma(args, context):
    values, overflow = rma_values(args[0], int(args[1]))
    count(context, "overflow", overflow)
    return values


def vwma(args, context):
    source, period = args
    period = int(period)
    volume = context.columns["volume"]
    # A zero-volume row must still have a valid source value.
    products = np.where(np.isfinite(source), source * volume, np.nan)
    return divide(totals(products, period), totals(volume, period), context)


def location_flow(context):
    high, low, close, volume = (
        context.columns[name] for name in ("high", "low", "close", "volume")
    )
    valid = (
        np.isfinite(high) & np.isfinite(low) & np.isfinite(close) & np.isfinite(volume)
    )
    span = high - low
    multiplier = np.zeros(len(close))
    np.divide(
        (close - low) - (high - close), span, out=multiplier, where=valid & (span != 0)
    )
    return np.where(valid, multiplier * volume, np.nan)


def cmf(args, context):
    period = int(args[0])
    return divide(
        totals(location_flow(context), period),
        totals(context.columns["volume"], period),
        context,
    )


def typical_price(high, low, close):
    return high / 3 + low / 3 + close / 3


def vwap(_args, context):
    high, low, close, volume = (
        context.columns[name] for name in ("high", "low", "close", "volume")
    )
    typical = typical_price(high, low, close)
    days = context.times // DAY_US
    valid = np.isfinite(typical) & np.isfinite(volume)
    values = np.full(len(close), np.nan)
    active_day = None
    weight = dollars = 0.0
    failures = 0
    for row, day in enumerate(days):
        if day != active_day or not valid[row]:
            active_day = day
            weight = dollars = 0.0
        if not valid[row]:
            continue
        weight += volume[row]
        dollars += typical[row] * volume[row]
        if not (np.isfinite(weight) and np.isfinite(dollars)):
            failures += 1
            weight = dollars = 0.0
        elif weight > 0:
            values[row] = dollars / weight
    if failures:
        context.invalid_counts["overflow"] = (
            context.invalid_counts.get("overflow", 0) + failures
        )
    return values


def obv(_args, context):
    close, volume = (context.columns[name] for name in ("close", "volume"))
    valid = np.isfinite(close) & np.isfinite(volume)
    values = np.full(len(close), np.nan)
    previous = None
    total = 0.0
    failures = 0
    for row, price in enumerate(close):
        if not valid[row]:
            previous = None
            total = 0.0
            continue
        if previous is not None:
            if price > previous:
                total += volume[row]
            elif price < previous:
                total -= volume[row]
        if np.isfinite(total):
            values[row] = total
            previous = price
        else:
            failures += 1
            previous = None
            total = 0.0
    if failures:
        context.invalid_counts["overflow"] = (
            context.invalid_counts.get("overflow", 0) + failures
        )
    return values


def adl(_args, context):
    flow = location_flow(context)
    values = np.full(len(flow), np.nan)
    running = 0.0
    failures = 0
    for row, change in enumerate(flow):
        if not np.isfinite(change):
            running = 0.0
            continue
        running += change
        if np.isfinite(running):
            values[row] = running
        else:
            failures += 1
            running = 0.0
    if failures:
        context.invalid_counts["overflow"] = (
            context.invalid_counts.get("overflow", 0) + failures
        )
    return values


def rvol(args, context):
    period = int(args[0])
    volume = context.columns["volume"]
    average = totals(lag(volume, 1), period) / period
    return divide(volume, average, context)
