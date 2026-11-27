"""Derive common-window comparisons from recorded run artifacts."""

import itertools
import math
from dataclasses import dataclass

import numpy as np
import pyarrow.parquet as pq

from ..data import Dataset, instant, load_dataset, timestamp
from ..engine import purchase
from ..persistence import LibraryError

POLICY = "common_start_hold_v1"
MARKET_FIELDS = (
    "market",
    "currency",
    "timeframe_seconds",
    "calendar",
    "semantics_version",
)
COST_FIELDS = ("fee_rate", "slippage_rate")


@dataclass(frozen=True)
class ComparisonInput:
    result: object
    ident: str
    config: dict
    start: int
    end: int

    @classmethod
    def from_result(cls, result):
        row = result.row
        config = row["snapshot"]["configuration"]
        return cls(
            result,
            row["id"],
            config,
            timestamp(row["summary"]["benchmark_entry_at"]),
            timestamp(config["last_close_at"]),
        )


def incompatible(inputs):
    first = inputs[0].config
    if any(item.config.get("calendar") == "portfolio" for item in inputs):
        return "portfolio_reference_unavailable"
    for other in inputs[1:]:
        if any(first[field] != other.config[field] for field in MARKET_FIELDS):
            return "market_or_semantics_mismatch"
        if any(
            first[field] != other.config[field]
            for field in ("dataset_hash", "gap_policy")
        ):
            return "primary_data_mismatch"
        if any(first[field] != other.config[field] for field in COST_FIELDS):
            return "cost_mismatch"
    if max(item.start for item in inputs) >= min(item.end for item in inputs):
        return "no_overlap"
    return None


def saved_input(item):
    result = item.result
    files = [name for name in ("input.csv", "input.parquet") if name in result.files]
    if len(files) != 1:
        raise ValueError("Expected one primary input")
    dataset = load_dataset(result.file(files[0]), result.manifest["dataset_metadata"])
    if dataset.dataset_hash != item.config["dataset_hash"]:
        raise ValueError("Saved primary data does not match the run")
    return dataset


def strategy_window(item, rows, open_price):
    table = pq.read_table(
        item.result.file("equity.parquet"),
        columns=["bar_index", "cash", "quantity", "equity"],
    )
    # A bundle stores one initial row followed by consecutive observed close rows.
    first = table["bar_index"][1].as_py()
    a, b = int(rows.start) - first + 1, int(rows.stop) - first + 1
    if (
        a < 1
        or b > table.num_rows
        or not np.array_equal(
            table["bar_index"].slice(a, b - a).to_numpy(),
            np.arange(rows.start, rows.stop),
        )
    ):
        raise ValueError("Common interval is outside the recorded ledger")
    cash = table["cash"][a - 1].as_py()
    quantity = table["quantity"][a - 1].as_py()
    basis = cash + quantity * open_price
    if not math.isfinite(basis) or basis <= 0:
        return dict(
            run_id=item.ident,
            open_equity=None,
            open_quantity=quantity,
            values=None,
            reason="invalid_open_mark",
        )
    with np.errstate(over="ignore", invalid="ignore"):
        equity = 100 * (table["equity"].slice(a, b - a).to_numpy() / basis)
    if not np.isfinite(equity).all():
        return dict(
            run_id=item.ident,
            open_equity=basis,
            open_quantity=quantity,
            values=None,
            reason="invalid_index_value",
        )
    return dict(
        run_id=item.ident,
        open_equity=basis,
        open_quantity=quantity,
        values=equity,
        reason=None,
    )


def cohort(inputs, dataset, sample):
    start = max(item.start for item in inputs)
    end = min(item.end for item in inputs)
    delta = dataset.timeframe_seconds * 1_000_000
    closes = dataset.session_rows.close if dataset.session_rows is not None else None

    def bounds(a, b):
        first = int(dataset.times.searchsorted(a))
        last = int(
            closes.searchsorted(b)
            if closes is not None
            else dataset.times.searchsorted(b - delta)
        )
        return first, last

    for item in inputs:
        left, right = bounds(item.start, item.end)
        if (
            right >= len(dataset.times)
            or left > right
            or dataset.times[left] != item.start
            or dataset.close_at(right) != item.end
        ):
            raise ValueError("A run window does not match the primary candles")
    first, last = bounds(start, end)
    rows = range(first, last + 1)
    reference = float(dataset.column("open")[first])
    fees, slippage = (inputs[0].config[field] for field in COST_FIELDS)
    quantity, fill, fee = purchase(100, reference, fees, slippage)
    cash = 100 - (quantity * fill + fee)
    with np.errstate(over="ignore", invalid="ignore"):
        benchmark = cash + quantity * dataset.column("close")[first : last + 1]
    if not np.isfinite(benchmark).all():
        raise ArithmeticError("Benchmark values exceed the numeric range")
    strategies = [strategy_window(item, rows, reference) for item in inputs]
    series = [np.concatenate(([100.0], benchmark))]
    series.extend(
        np.concatenate(([100.0], strategy["values"]))
        for strategy in strategies
        if strategy["values"] is not None
    )
    indices, _ = sample(
        len(benchmark) + 1,
        1000,
        [(values, pick) for values in series for pick in (np.argmin, np.argmax)],
    )
    for strategy in strategies:
        equity = strategy.pop("values")
        strategy["total_return"] = (
            float(equity[-1] / 100 - 1) if equity is not None else None
        )
        strategy["excess_return"] = (
            float(equity[-1] / 100 - benchmark[-1] / 100)
            if equity is not None
            else None
        )
    points = []
    for row in indices:
        index = int(row)
        values = iter(float(values[index]) for values in series[1:])
        points.append(
            dict(
                timestamp=instant(dataset.close_at(first + index - 1))
                if index
                else instant(start),
                phase="close" if index else "initial",
                benchmark=float(series[0][index]),
                strategies={
                    s["run_id"]: next(values) for s in strategies if s["reason"] is None
                },
            )
        )
    return dict(
        run_ids=[item.ident for item in inputs],
        start_at=instant(start),
        end_at=instant(end),
        reference_price=reference,
        entry_price=fill,
        entry_fee=fee,
        fee_rate=fees,
        slippage_rate=slippage,
        total_return=float(benchmark[-1] / 100 - 1),
        strategies=strategies,
        points=points,
    )


def common_benchmark(results, sample):
    inputs = [ComparisonInput.from_result(result) for result in results]
    datasets: dict[str, Dataset] = {}
    cohorts: list[dict] = []
    settled: list[frozenset[str]] = []
    reasons = {}
    for size in range(len(inputs), 1, -1):
        for group in itertools.combinations(inputs, size):
            identifiers = frozenset(item.ident for item in group)
            if any(identifiers <= previous for previous in settled):
                continue
            reason = incompatible(group)
            if reason is None:
                try:
                    key = group[0].config["dataset_hash"]
                    if key not in datasets:
                        datasets[key] = saved_input(group[0])
                    cohorts.append(cohort(group, datasets[key], sample))
                    settled.append(identifiers)
                except ArithmeticError:
                    reason = "numeric_range"
                except (
                    AttributeError,
                    IndexError,
                    KeyError,
                    TypeError,
                    ValueError,
                    OSError,
                    LibraryError,
                ):
                    reason = "recorded_input_unavailable"
            if reason is not None and size == 2:
                reasons[identifiers] = reason
    pairs = [
        dict(
            run_ids=[first.ident, second.ident],
            reason=reasons.get(frozenset({first.ident, second.ident})),
        )
        for first, second in itertools.combinations(inputs, 2)
    ]
    return dict(policy=POLICY, cohorts=cohorts, pairs=pairs)
