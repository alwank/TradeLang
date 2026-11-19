"""Write the deterministic hourly dataset shared by the four reference strategies."""

import argparse
import csv
import json
import math
from datetime import UTC, datetime, timedelta
from pathlib import Path


def generate(directory):
    directory.mkdir(parents=True, exist_ok=True)
    start = datetime(2022, 1, 1, tzinfo=UTC)
    stop = datetime(2026, 1, 1, tzinfo=UTC)
    previous = 100.0
    with (directory / "example.csv").open("x", newline="") as f:
        w = csv.writer(f)
        w.writerow(["timestamp", "open", "high", "low", "close", "volume"])
        for i in range(int((stop - start).total_seconds() / 3600)):
            close = round(
                100 + 0.001 * i + 6 * math.sin(i / 10) + 3 * math.sin(i / 90), 4
            )
            high = round(max(previous, close) + 0.05, 4)
            low = round(min(previous, close) - 0.05, 4)
            w.writerow(
                [
                    (start + timedelta(hours=i)).isoformat(),
                    previous,
                    high,
                    low,
                    close,
                    250 if i % 9 == 0 else 100,
                ]
            )
            previous = close
    meta = dict(
        symbol="BTCUSDT",
        quote_currency="USDT",
        timeframe="1h",
        calendar="24x7",
        timestamp_convention="bar_open",
        price_basis="raw_spot",
        volume_unit="base_quantity",
    )
    (directory / "metadata.json").write_text(json.dumps(meta, indent=2) + "\n")


if __name__ == "__main__":
    args = argparse.ArgumentParser()
    args.add_argument("directory", type=Path)
    generate(args.parse_args().directory)
