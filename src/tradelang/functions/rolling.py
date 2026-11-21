"""Bounded, causal rolling operations for the expanded catalog."""

from collections import deque
from math import inf, isfinite

import numpy as np

_BINARY64_SCALE = 1 << 1074


def binary64_units(value):
    numerator, denominator = float(value).as_integer_ratio()
    return numerator << (1075 - denominator.bit_length())


def _from_units(value):
    try:
        return value / _BINARY64_SCALE
    except OverflowError:
        return inf if value > 0 else -inf


def _exact_totals(samples, period, weighted):
    units = [binary64_units(sample) for sample in samples]
    total = sum(units[:period])
    moment = (
        sum(weight * value for weight, value in enumerate(units[:period], 1))
        if weighted
        else 0
    )
    out = [_from_units(moment if weighted else total)]
    for index in range(period, len(units)):
        newest = units[index]
        if weighted:
            moment += period * newest - total
        total += newest - units[index - period]
        out.append(_from_units(moment if weighted else total))
    return out


def totals(values, period, *, weighted=False):
    """Return trailing sums, or sums with weights from one through period."""
    if period == 1:
        return np.where(np.isfinite(values), values, np.nan)
    result = np.full(len(values), np.nan)
    block_size = max(128 if weighted else 2048, period)
    for start in range(period - 1, len(values), block_size):
        end = min(len(values), start + block_size)
        samples = values[start - period + 1 : end]
        finite = np.isfinite(samples)
        active = np.where(finite, samples, 0.0)
        sums = np.r_[0.0, np.cumsum(active)]
        missing = np.r_[0, np.cumsum(~finite)]
        nonzero = np.r_[0, np.cumsum(active != 0)]
        magnitudes = np.r_[0.0, np.cumsum(abs(active))]
        output = sums[period:] - sums[:-period]
        risk = magnitudes[period:]
        if weighted:
            positions = np.arange(1, len(samples) + 1)
            moment = np.r_[0.0, np.cumsum(active * positions)]
            output = (
                moment[period:] - moment[:-period] - np.arange(len(output)) * output
            )
            risk = risk * np.arange(period, len(active) + 1)
        complete = missing[period:] == missing[:-period]
        populated = nonzero[period:] != nonzero[:-period]
        # Recover tiny windows after a large observation leaves the prefix.
        unstable = ~np.isfinite(output) | (abs(output) <= 1e-6 * risk)
        repair = complete & populated & unstable
        if np.any(repair):
            np.copyto(
                output,
                np.asarray(_exact_totals(active, period, weighted)),
                where=repair,
            )
        output[~populated] = 0
        result[start:end] = np.where(complete, output, np.nan)
    return result


def count(context, reason, mask):
    total = int(np.count_nonzero(mask))
    if total:
        context.invalid_counts[reason] = context.invalid_counts.get(reason, 0) + total


def smooth_checked(source, period, context, *, wilder=False):
    """Seed from consecutive samples and clear a failed recursive state."""
    if period == 1:
        return np.where(np.isfinite(source), source, np.nan)
    result = np.full(len(source), np.nan)
    overflow = np.zeros(len(source), dtype=bool)
    alpha = 2 / (period + 1)
    seen = 0
    total = previous = 0.0
    for row, raw in enumerate(source):
        sample = float(raw)
        if not isfinite(sample):
            seen = 0
            total = 0.0
            continue
        if seen < period:
            seen += 1
            total += sample
            previous = total / period
        elif wilder:
            previous = (previous * (period - 1) + sample) / period
        else:
            previous = alpha * sample + (1 - alpha) * previous
        if not isfinite(previous):
            overflow[row] = True
            seen = 0
            total = 0.0
        elif seen == period:
            result[row] = previous
    count(context, "overflow", overflow)
    return result


def extreme(source, period, *, high, age=False):
    """Return the trailing extreme or its age, keeping the newest equal value."""
    queue: deque[int] = deque()
    run = 0
    result = np.full(len(source), np.nan)
    for row, sample in enumerate(source):
        if not np.isfinite(sample):
            queue.clear()
            run = 0
            continue
        run += 1
        if queue and queue[0] <= row - period:
            queue.popleft()
        while queue and (
            sample >= source[queue[-1]] if high else sample <= source[queue[-1]]
        ):
            queue.pop()
        queue.append(row)
        if run >= period:
            result[row] = row - queue[0] if age else source[queue[0]]
    return result


def complete(source, lookback):
    missing = np.r_[0, np.cumsum(~np.isfinite(source))]
    valid = np.zeros(len(source), dtype=bool)
    if lookback < len(source):
        valid[lookback:] = missing[lookback + 1 :] == missing[: -lookback - 1]
    return valid


def divide(numerator, denominator, context):
    complete = np.isfinite(numerator) & np.isfinite(denominator)
    zeros = complete & (denominator == 0)
    usable = complete & ~zeros
    values = np.divide(
        numerator, denominator, out=np.full(len(numerator), np.nan), where=usable
    )
    count(context, "zero_denominator", zeros)
    overflow = usable & ~np.isfinite(values)
    count(context, "overflow", overflow | np.isinf(numerator) | np.isinf(denominator))
    values[overflow] = np.nan
    return values
