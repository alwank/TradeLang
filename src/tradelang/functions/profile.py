"""Admission and rolling calculations for volume by price."""

from dataclasses import dataclass

import numpy as np

from ..model import Problem
from .rolling import binary64_units, complete, count, extreme

MAX_PROFILE_CALLS = 4
MAX_PROFILE_WORK = 30_000_000
MAX_PROFILE_WINDOW = 256
MAX_PROFILE_SPAN = 256
MAX_BIN = 2**52 - 1
ProfileKey = tuple[int, float, float]


def profile_key(arguments) -> ProfileKey:
    period, width, fraction = arguments
    return int(period), float(width), float(fraction)


@dataclass(frozen=True)
class ProfileWindow:
    offsets: np.ndarray
    volumes: np.ndarray
    bins: np.ndarray
    lowest: np.ndarray
    highest: np.ndarray
    eligible: np.ndarray
    work_units: int


def prepare_profiles(
    primary_times, width_us, child_times, child_width_us, prices, volumes, keys
):
    """Map completed child intervals and bound the work for each unique profile."""
    initial, count_rows = primary_times[0], len(primary_times)
    first, end = child_times.searchsorted([initial, primary_times[-1] + width_us])
    times = child_times[first:end]
    groups = primary_times.searchsorted(times, side="right") - 1
    mapped = times + child_width_us <= primary_times[groups] + width_us
    coverage = (
        np.bincount(groups[mapped], minlength=count_rows) == width_us // child_width_us
    )
    positive = mapped & (volumes[first:end] > 0)
    owners = groups[positive]
    prices = prices[first:end][positive]
    weights = volumes[first:end][positive]
    offsets = np.r_[0, np.cumsum(np.bincount(owners, minlength=count_rows))]
    prepared = {}
    work = 0
    for key in keys:
        period, bin_width, _ = key
        with np.errstate(over="ignore", invalid="ignore"):
            indexes = np.floor(prices / bin_width)
        good = np.isfinite(indexes) & (indexes <= MAX_BIN)
        bins = np.where(good, indexes, -1).astype(np.int64)
        low = np.full(count_rows, MAX_BIN + 1, dtype=np.int64)
        high = np.full(count_rows, -1, dtype=np.int64)
        np.minimum.at(low, owners[good], bins[good])
        np.maximum.at(high, owners[good], bins[good])
        valid = coverage.copy()
        valid[owners[~good]] = False
        window = complete(np.where(valid, 0.0, np.nan), period - 1)
        lowest = extreme(low, period, high=False)
        highest = extreme(high, period, high=True)
        span = highest - lowest + 1
        eligible = window & (span > 0) & (span <= MAX_PROFILE_SPAN)
        work_units = 2 * (len(owners) + int(np.sum(span[eligible])))
        work += work_units
        if work > MAX_PROFILE_WORK:
            raise Problem("E_DATA_LIMIT", "Volume Profile exceeds the workload limit")
        for array in (bins, lowest, highest, eligible):
            array.flags.writeable = False
        prepared[key] = ProfileWindow(
            offsets, weights, bins, lowest, highest, eligible, work_units
        )
    offsets.flags.writeable = False
    weights.flags.writeable = False
    return prepared


def _value_area(histogram, first, last, point, target_numerator, target_denominator):
    left = right = point
    included = histogram[point]
    while included * target_denominator < target_numerator and (
        left > first or right < last
    ):
        lower = histogram.get(left - 1, 0) if left > first else -1
        upper = histogram.get(right + 1, 0) if right < last else -1
        if lower >= upper:
            left -= 1
            included += lower
        else:
            right += 1
            included += upper
    return left, right


def vprofile(args, context):
    period, width, fraction = profile_key(args)
    window = context.profile
    if window is None:
        raise AssertionError("Volume Profile requires prepared candle data")
    poc, val, vah = (np.full(len(window.eligible), np.nan) for _ in range(3))
    histogram: dict[int, int] = {}
    total = 0
    numerator, denominator = fraction.as_integer_ratio()

    def update(row, sign):
        delta = 0
        for entry in range(window.offsets[row], window.offsets[row + 1]):
            bin_index = int(window.bins[entry])
            if bin_index < 0:
                continue
            change = sign * binary64_units(window.volumes[entry])
            balance = histogram.get(bin_index, 0) + change
            if balance:
                histogram[bin_index] = balance
            else:
                histogram.pop(bin_index)
            delta += change
        return delta

    for row, eligible in enumerate(window.eligible):
        total += update(row, 1)
        if row >= period:
            total += update(row - period, -1)
        if not eligible:
            continue
        first, last = int(window.lowest[row]), int(window.highest[row])
        point = max(range(first, last + 1), key=lambda level: histogram.get(level, 0))
        left, right = (
            (first, last)
            if numerator == denominator
            else _value_area(
                histogram, first, last, point, total * numerator, denominator
            )
        )
        poc[row] = (point + 0.5) * width
        val[row] = left * width
        vah[row] = (right + 1) * width
    for values in (poc, val, vah):
        count(context, "overflow", np.isinf(values))
        values[np.isinf(values)] = np.nan
    return dict(poc=poc, val=val, vah=vah)
