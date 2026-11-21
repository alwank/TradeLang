"""Measure indicator workloads on reproducible completed candle data."""

import argparse
import json
import platform
import resource
import statistics
import sys
import tempfile
import time
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from pathlib import Path

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq

from tradelang.compiler import compile_source
from tradelang.data import load_dataset, prepare_window
from tradelang.engine import execute_prepared
from tradelang.evaluator import Evaluator

ROOT = Path(__file__).resolve().parents[1]
START = datetime(2022, 1, 1, tzinfo=UTC)
FIRST_RELEASE = [
    "DMI(4, 4).adx",
    "STOCH(4, 2, 2).d",
    "VWAP()",
    "SUPERTREND(4, 2).line",
    "DONCHIAN(4).upper",
    "KELTNER(4, 4, 2).lower",
    "STOCHRSI(4, 4, 2, 2).d",
    "OBV()",
    "MFI(4)",
    "CCI(4)",
    "WILLR(4)",
    "SAR(0.02, 0.2)",
    "WMA(4)",
    "RMA(4)",
    "VWMA(4)",
    "CMF(4)",
]
MIXED = [
    "HMA(RMA(10), 20)",
    "TSI(WMA(close, 5), 12, 5)",
    "KAMA(VWMA(10), 12, 2, 15)",
    "SUPERTREND(20, 2).line",
    "SUPERTREND(20, 2).direction",
    "ICHIMOKU(9, 26, 52).span_a[26]",
    "ICHIMOKU(9, 26, 52).span_b[26]",
    "LSMA(ALMA(close, 20, 0.5, 6), 20)",
    "ZIGZAG(3, 3, 0.05).last_high",
]
PROFILE = ["VPROFILE(128, 1 price, 0.7).poc", "VPROFILE(128, 1 price, 0.7).vah"]
WORKLOADS = (
    "first-release",
    "mixed",
    "cci",
    "alma",
    "wide",
    "profile-sparse",
    "profile-dense",
)


def candles(path, rows, minutes, spread):
    position = np.arange(rows)
    times = int(START.timestamp()) * 1_000_000 + position * minutes * 60_000_000
    close = 100 + (position % spread) + 0.11 * np.sin(position)
    table = pa.table(
        {
            "timestamp": pa.array(times, type=pa.timestamp("us", "UTC")),
            "open": close,
            "high": close + 1,
            "low": close - 1,
            "close": close,
            "volume": position % 23 + 1,
        }
    )
    pq.write_table(table, path)


def strategy_source(rows, minutes, expressions):
    template = (ROOT / "docs/fixtures/core.trade").read_text()
    start = START.date().isoformat()
    end = (START + timedelta(days=rows * minutes // 1440 - 1)).date().isoformat()
    bindings = "\n".join(
        f"let value{i} = {value}" for i, value in enumerate(expressions)
    )
    return (
        template.replace("1d", f"{minutes}m")
        .replace("2024-01-01", start)
        .replace("2024-01-03", end)
        .replace("entry:", bindings + "\nentry:")
        .replace("when true", "when close > 1000 price")
    )


def benchmark(workload, rows, repeats, period):
    paired = workload.startswith("profile-")
    minutes = 2 if paired else 1
    if rows * minutes % 1440 or rows * minutes > 1_000_000:
        raise ValueError(
            "Choose complete UTC days under one million underlying minute rows"
        )
    expressions = {
        "first-release": FIRST_RELEASE,
        "mixed": MIXED,
        "cci": [f"CCI({period})"],
        "alma": [f"ALMA(close, {period}, 0.32, 6)"],
        "wide": [f"WMA({period})", f"CCI({period})", f"ALMA(close, {period}, 0.32, 6)"],
        "profile-sparse": PROFILE,
        "profile-dense": PROFILE,
    }[workload]
    source = strategy_source(rows, minutes, expressions)
    metadata = json.loads((ROOT / "docs/fixtures/metadata.json").read_text())
    times = defaultdict(list)

    def measure(name, action, iteration):
        started = time.perf_counter()
        value = action()
        if iteration:
            times[name].append(time.perf_counter() - started)
        return value

    with tempfile.TemporaryDirectory() as directory:
        primary_file = Path(directory) / "primary.parquet"
        child_file = Path(directory) / "child.parquet"
        candles(primary_file, rows, minutes, 17)
        if paired:
            candles(
                child_file, rows * minutes, 1, 127 if workload == "profile-dense" else 4
            )
        for iteration in range(repeats + 1):
            strategy = measure("compile", lambda: compile_source(source), iteration)
            primary = measure(
                "primary_import",
                lambda: load_dataset(
                    primary_file, {**metadata, "timeframe": f"{minutes}m"}
                ),
                iteration,
            )
            child = (
                measure(
                    "child_import",
                    lambda: load_dataset(child_file, {**metadata, "timeframe": "1m"}),
                    iteration,
                )
                if paired
                else None
            )
            prepared = measure(
                "prepare", lambda: prepare_window(strategy, primary, child), iteration
            )
            profile_work = sum(item.work_units for item in prepared.profiles.values())

            def evaluate():
                evaluator = Evaluator(
                    strategy, primary, prepared.last, profiles=prepared.profiles
                )
                for value in strategy.roots():
                    if value is not None and not value.account:
                        evaluator.evaluate(value)
                return len(evaluator.call_cache)

            calls = measure("evaluate", evaluate, iteration)
            result = measure(
                "execute",
                lambda: execute_prepared(strategy, primary, prepared),
                iteration,
            )
            assert result["summary"]["final_equity"] == 1000
            del result
            primary = child = prepared = None
    summaries = {
        name: {
            "median_seconds": statistics.median(samples),
            "p95_seconds": float(np.percentile(samples, 95)),
        }
        for name, samples in times.items()
    }
    rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / (
        1024**2 if sys.platform == "darwin" else 1024
    )
    return dict(
        workload=workload,
        rows=rows,
        child_rows=rows * minutes if paired else 0,
        profile_work_units=profile_work,
        period=period,
        calls=calls,
        repeats=repeats,
        peak_mib=rss,
        stages=summaries,
        platform=platform.platform(),
        python=platform.python_version(),
        numpy=np.__version__,
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workload", choices=WORKLOADS, required=True)
    parser.add_argument("--rows", type=int, required=True)
    parser.add_argument("--period", type=int, default=20)
    parser.add_argument("--repeats", type=int, default=5)
    args = parser.parse_args()
    if not 0 < args.rows or not 0 < args.repeats or not 1 <= args.period <= 10_000:
        parser.error("Use positive rows and repeats and a period from 1 through 10,000")
    print(json.dumps(benchmark(args.workload, args.rows, args.repeats, args.period)))
