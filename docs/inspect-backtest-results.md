# Inspect and compare backtests

Use a run bundle to inspect the outcome, trace orders back to strategy decisions, and compare a replay with the original. Complete the [first backtest](quickstart.md) to get the example bundle at `runs/first`. Run the commands from the checkout root.

## Find the result and any warnings

1. Open `runs/first/summary.json`. Check `final_equity` for the strategy and `benchmark` for the buy-and-hold comparison. Final equity is about **1,090.91 USDT** for this fixture.
2. Open `runs/first/trades.csv` and check the entry and exit price, quantity, and exit reason. The example has one completed trade with a `signal_exit` at 120 USDT.
3. Open `runs/first/diagnostics.json` if a metric is missing or a result looks unexpected. For example, a metric with a JSON `null` value is unavailable. See [metric definitions](results.md#read-the-equity-and-benchmark) for its requirements.

## Trace the quickstart trade

Run the [quickstart backtest](quickstart.md#simulate-and-check-the-fills). In its `events.jsonl`, the six rows carrying an order ID show the two sides of the trade.

| `sequence` | `observed_at` (UTC) | `kind` / `reason` | `time_precision` | `order_id` | `fill_id` |
| ---: | --- | --- | --- | --- | --- |
| 1 | `2024-01-02T00:00:00Z` | `signal` / `buy` | `close` | `O00000001` | |
| 2 | `2024-01-02T00:00:00Z` | `order_queued` / `buy` | `close` | `O00000001` | |
| 3 | `2024-01-02T00:00:00Z` | `fill` / `entry` | `open` | `O00000001` | `F00000001` |
| 5 | `2024-01-03T00:00:00Z` | `signal` / `sell` | `close` | `O00000002` | |
| 6 | `2024-01-03T00:00:00Z` | `order_queued` / `sell` | `close` | `O00000002` | |
| 7 | `2024-01-03T00:00:00Z` | `fill` / `signal_exit` | `open` | `O00000002` | `F00000002` |

Each `order_queued` row links to its signal through `linked_event_id`. Each fill shares its order's `order_id`. The close and next open share a timestamp, so use `sequence` to see the order of operations. Both fills carry `trade_id` `T000001`, which matches the single row in `trades.csv`. That row records an entry price of 110, an exit price of 120, and an exit reason of `signal_exit`.

## Compare and replay runs

Replay the example using the strategy, candles, and metadata saved in its original bundle.

```sh
tradelang backtest runs/first/source.trade --data runs/first/input.csv --metadata runs/first/metadata.json --out runs/first-replay
```

Use `input.parquet` if the original bundle contains Parquet. For a historical bundle, use its recorded TradeLang build and dependencies.

Open `manifest.json` in both directories and compare these fields.

| Field | What to check |
| --- | --- |
| `result_digest` | Matching digests identify the same logical results. |
| `run_fingerprint` | Matching fingerprints identify the same versioned inputs, configuration, and recorded environment. |
| `run_id` | Each run has a distinct ID, including replays with matching fingerprints and results. |

For the quickstart replay with the same CLI and environment, expect matching result digests and run fingerprints and different run IDs. See the [run identity reference](results.md#compare-and-replay-runs) for the hashes that explain differences.

## Check a file checksum

Compute the SHA-256 checksum of a file in the bundle. This example uses the bundled `summary.json`.

```sh
uv run --no-project --python 3.12 python -c 'import hashlib, pathlib; print(hashlib.sha256(pathlib.Path("runs/first/summary.json").read_bytes()).hexdigest())'
```

In that bundle's `manifest.json`, find the entry with `name` set to `summary.json` in `artifact_files`. Its `sha256` should match the printed value. A run bundle also includes the submitted strategy and dataset. Review both before sharing the bundle.
