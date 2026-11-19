"""Measure import plus execution on reproducible minute candles with ten indicators."""

import argparse
import json
import platform
import resource
import statistics
import sys
import tempfile
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq

from tradelang.compiler import compile_source
from tradelang.data import load_dataset
from tradelang.engine import execute


def benchmark(rows, repeats):
    start = datetime(2022, 1, 1, tzinfo=UTC)
    dates = (
        np.arange(rows, dtype=np.int64) * 60_000_000
        + int(start.timestamp()) * 1_000_000
    )
    close = 100 + np.arange(rows) % 7
    table = pa.table(
        dict(
            timestamp=pa.array(dates, type=pa.timestamp("us", "UTC")),
            open=close,
            high=close + 1,
            low=close - 1,
            close=close,
            volume=close,
        )
    )
    names = [
        "SMA(4)",
        "EMA(4)",
        "RSI(4)",
        "MACD(2,4,2).line",
        "ATR(4)",
        "BBANDS(close,4,2).upper",
        "HIGHEST(high,4)",
        "LOWEST(low,4)",
        "ROC(close,4)",
        "STDDEV(close,4)",
    ]
    original = Path("docs/fixtures/core.trade").read_text()
    end = (start + timedelta(days=rows // 1440 - 1)).date().isoformat()
    source = (
        original.replace("1d", "1m")
        .replace("2024-01-01", start.date().isoformat())
        .replace("2024-01-03", end)
        .replace(
            "entry:",
            "\n".join(f"let v{i} = {expr}" for i, expr in enumerate(names))
            + "\nentry:",
        )
        .replace("when true", "when close > 200 price")
    )
    meta = json.loads(Path("docs/fixtures/metadata.json").read_text())
    meta["timeframe"] = "1m"
    times = []
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "candles.parquet"
        pq.write_table(table, path)
        del table, close, dates
        for _ in range(repeats):
            begin = time.perf_counter()
            s = compile_source(source)
            d = load_dataset(path, meta)
            r = execute(s, d)
            assert r["summary"]["final_equity"] == 1000
            times.append(time.perf_counter() - begin)
            del r, d
    rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * (
        1 if sys.platform == "darwin" else 1024
    )
    return dict(
        rows=rows,
        runs=times,
        median_seconds=statistics.median(times),
        p95_seconds=float(np.percentile(times, 95)),
        peak_mib=rss / 2**20,
        platform=platform.platform(),
        python=platform.python_version(),
    )


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--rows", type=int, required=True)
    p.add_argument("--repeats", type=int, default=5)
    a = p.parse_args()
    print(json.dumps(benchmark(a.rows, a.repeats)))
