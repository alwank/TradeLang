"""Oscillators over trailing price and volume windows."""

import numpy as np

from .kernels import lag
from .order_statistics import cci_wide
from .rolling import count, extreme, smooth_checked, totals
from .volume import typical_price


def stochastic(source, high, low, periods, context):
    period, k_period, d_period = map(int, periods)
    ceiling = extreme(high, period, high=True)
    floor = extreme(low, period, high=False)
    span = ceiling - floor
    ready = np.isfinite(source) & np.isfinite(ceiling) & np.isfinite(floor)
    raw = np.full(len(source), np.nan)
    raw[ready & (span == 0)] = 0
    np.divide(source - floor, span, out=raw, where=ready & (span != 0))
    k = totals(100 * raw, k_period) / k_period
    d = totals(k, d_period) / d_period
    count(context, "overflow", np.isinf(k))
    count(context, "overflow", np.isinf(d))
    return dict(k=k, d=d)


def stoch(args, context):
    high, low, close = (context.columns[key] for key in ("high", "low", "close"))
    return stochastic(close, high, low, args, context)


def stochrsi(args, context):
    rsi_period, *periods = args
    close = context.columns["close"]
    change = close - lag(close, 1)
    gain = smooth_checked(np.maximum(0, change), int(rsi_period), context, wilder=True)
    loss = smooth_checked(np.maximum(0, -change), int(rsi_period), context, wilder=True)
    values = np.where(
        loss == 0, np.where(gain == 0, 50.0, 100.0), 100 - 100 / (1 + gain / loss)
    )
    values[~(np.isfinite(gain) & np.isfinite(loss))] = np.nan
    return stochastic(values, values, values, periods, context)


def mfi(args, context):
    period = int(args[0])
    high, low, close, volume = (
        context.columns[key] for key in ("high", "low", "close", "volume")
    )
    typical = typical_price(high, low, close)
    difference = typical - lag(typical, 1)
    flow = typical * volume
    valid = np.isfinite(typical) & np.isfinite(volume)
    ready = valid & (lag(valid, 1) == 1) & np.isfinite(difference)
    count(context, "overflow", ready & np.isinf(flow) & (difference != 0))
    gain = totals(np.where(ready, np.where(difference > 0, flow, 0), np.nan), period)
    loss = totals(np.where(ready, np.where(difference < 0, flow, 0), np.nan), period)
    total = gain + loss
    result = np.full(len(close), np.nan)
    complete = np.isfinite(total)
    result[complete & (total == 0)] = 0.5
    np.divide(gain, total, out=result, where=complete & (total != 0))
    count(context, "overflow", np.isinf(total))
    return 100 * result


def willr(args, context):
    period = int(args[0])
    high, low, close = (context.columns[key] for key in ("high", "low", "close"))
    ceiling = extreme(high, period, high=True)
    floor = extreme(low, period, high=False)
    span = ceiling - floor
    ready = np.isfinite(close) & np.isfinite(span)
    result = np.full(len(close), np.nan)
    result[ready & (span == 0)] = 0
    np.divide(close - ceiling, span, out=result, where=ready & (span != 0))
    return 100 * result


def cci(args, context):
    period = int(args[0])
    high, low, close = (context.columns[key] for key in ("high", "low", "close"))
    typical = typical_price(high, low, close)
    if period >= 2048:
        return cci_wide(typical, period)
    result = np.full(len(close), np.nan)
    if period > len(close):
        return result
    windows = np.lib.stride_tricks.sliding_window_view(typical, period)
    batch_size = max(1, 262_144 // period)
    for start in range(0, len(windows), batch_size):
        batch = windows[start : start + batch_size]
        # Center each window before summing to retain small deviations from a
        # large common price level.
        centered = batch - batch[:, :1]
        mean = np.mean(centered, axis=1)
        deviations = centered - mean[:, None]
        mad = np.mean(abs(deviations), axis=1)
        selected = result[start + period - 1 : start + period - 1 + len(batch)]
        selected[mad == 0] = 0
        np.divide(deviations[:, -1], 0.015 * mad, out=selected, where=mad > 0)
    overflow = np.isinf(result)
    count(context, "overflow", overflow)
    result[overflow] = np.nan
    return result
