"""Causal indicator kernels with chronological binary64 operations."""

import numpy as np


def lag(a, n):
    if n == 0:
        return a
    out = np.full(len(a), np.nan)
    if n < len(a):
        out[n:] = a[:-n]
    return out


def rolling(x, n, fn):
    out = np.full(len(x), np.nan)
    if n <= len(x):
        windows = np.lib.stride_tricks.sliding_window_view(x, n)
        # Bound work buffers for two-pass standard deviation.
        step = max(1, 1000000 // n)
        for i in range(0, len(windows), step):
            block = windows[i : i + step]
            if fn in (np.mean, np.std):
                # accumulate follows the time axis in order for each reference window.
                mean = np.add.accumulate(block, axis=1)[:, -1] / n
                result = (
                    mean
                    if fn is np.mean
                    else np.sqrt(
                        np.add.accumulate((block - mean[:, None]) ** 2, axis=1)[:, -1]
                        / n
                    )
                )
            else:
                result = fn(block, axis=1)
            out[n - 1 + i : n - 1 + i + len(block)] = result
    return out


def smooth(x, n, wilder=False):
    out = np.full(len(x), np.nan)
    seen = 0
    total = 0.0
    prev = 0.0
    alpha = 2 / (n + 1)
    for i, v in enumerate(x):
        if not np.isfinite(v):
            seen = 0
            total = 0.0
            continue
        if seen < n:
            total += v
            seen += 1
            if seen < n:
                continue
            prev = total / n
        elif wilder:
            prev = (prev * (n - 1) + v) / n
        else:
            prev = alpha * v + (1 - alpha) * prev
        out[i] = prev
    return out


def atr(args, context):
    columns = context.columns
    h, low, c = (columns[k] for k in ("high", "low", "close"))
    tr = h - low
    tr[1:] = np.maximum(tr[1:], np.maximum(abs(h[1:] - c[:-1]), abs(low[1:] - c[:-1])))
    return smooth(tr, int(args[0]), True)


def ema(args, _context):
    x, n = args[0], int(args[1])
    return smooth(x, n)


def rsi(args, _context):
    x, n = args[0], int(args[1])
    delta = x - lag(x, 1)
    g = smooth(np.maximum(0, delta), n, True)
    loss = smooth(np.maximum(0, -delta), n, True)
    return np.where(
        loss == 0, np.where(g == 0, 50.0, 100.0), 100 - 100 / (1 + g / loss)
    )


def macd(args, _context):
    x, n = args[0], int(args[1])
    line = smooth(x, n) - smooth(x, int(args[2]))
    signal = smooth(line, int(args[3]))
    return dict(line=line, signal=signal, histogram=line - signal)


def roc(args, context):
    x, n = args[0], int(args[1])
    invalid_counts = context.invalid_counts
    prior = lag(x, n)
    missing = np.cumsum(~np.isfinite(x))
    invalid = missing - np.pad(missing, (n + 1, 0))[: len(x)]
    complete = (np.arange(len(x)) >= n) & (invalid == 0)
    zeros = complete & (prior == 0)
    usable = complete & ~zeros
    values = np.divide(x, prior, out=np.full(len(x), np.nan), where=usable) - 1
    overflow = usable & ~np.isfinite(values)
    for reason, mask in (("zero_denominator", zeros), ("overflow", overflow)):
        count = int(np.count_nonzero(mask))
        if count:
            invalid_counts[reason] = invalid_counts.get(reason, 0) + count
    values[overflow] = np.nan
    return values


def bbands(args, _context):
    x, n = args[0], int(args[1])
    mid = rolling(x, n, np.mean)
    width = rolling(x, n, np.std) * args[2]
    return dict(middle=mid, upper=mid + width, lower=mid - width)


def rolling_kernel(reduce):
    def evaluate(args, _context):
        return rolling(args[0], int(args[1]), reduce)

    return evaluate
