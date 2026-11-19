# Results and artifacts

A successful `tradelang backtest` writes a bundle to `--out`. Start with `summary.json` to read the result, `trades.csv` to inspect completed round trips, and `events.jsonl` to trace a decision through a fill, rejection, or expiry.

## Read the equity and benchmark

Both equity curves start at the first in-window open with the starting capital. Subsequent rows record each observed in-window close, including warmup bars. Strategy equity is cash plus quantity times the raw close. Open holdings remain marked at the final close and appear in `summary.open_position`. Closed-trade statistics use completed round trips only.

The benchmark spends 100% of starting capital, including the entry fee, at the first open after the strategy's first eligible signal bar. It uses the same buy slippage and keeps the position through the final close. Compare `benchmark_entry_at` when comparing runs with different warmups or input history.

| Metric | Interpretation |
| --- | --- |
| `total_return` | Ending equity divided by starting equity, minus one. |
| `max_drawdown` | Largest fractional decline from a prior equity peak, as a nonnegative magnitude. The curve stores drawdowns as nonpositive fractions. |
| `cagr` | Annualized equity growth using elapsed UTC time and a 365.25-day year. Requires positive ending equity, at least one day, and a representable result. |
| `sharpe` | Mean bar return divided by sample standard deviation, annualized using the fixed bar duration and zero risk-free rate. Requires two or more returns, at least one day, positive volatility, and contiguous in-window candles. |
| `win_rate` | Winning closed trades divided by all closed trades, including breakeven trades. |
| `profit_factor` | Sum of positive net trade P&L divided by the magnitude of negative net trade P&L. When there are no losses, the value is null and `profit_factor_status` explains why. |
| `exposure_fraction` | Fraction of observed in-window bars with a holding at any phase. An opening exit or an entry and exit on the same bar counts as exposure. |

Unavailable metrics use JSON null. Treat a short-window annualized value as a mathematical extrapolation of that window. Use `diagnostics.json` for warnings such as delayed warmup, missing bars, and unavailable metrics.

## Artifact files

| File | Contents |
| --- | --- |
| `summary.json` | Schema version 1. Final cash and equity, open position, metrics, benchmark, costs, counts, and warnings. |
| `equity.csv`, `equity.parquet` | The same full-resolution strategy and benchmark curves, with `cumulative_return` and Boolean `exposed` fields. |
| `trades.csv` | One row per closed trade, with reference and fill prices, fees, net P&L, rationale, and exit reason. Nested fields contain JSON. |
| `events.jsonl` | Ordered signal, order, fill, rejection, expiry, and warning events. Sort by `sequence` when timestamps coincide. For an intrabar event, `time_precision: "bar"` identifies the containing candle. |
| `diagnostics.json` | Run diagnostics, also surfaced in the JSON CLI response. |
| `source.trade`, `strategy-spec.json` | Exact submitted source bytes and the compiler's typed strategy. |
| `input.csv` or `input.parquet`, `metadata.json`, `dataset-summary.json` | Exact submitted dataset, validated settings, and quality summary. |
| `environment.json`, `dependency-lock.txt`, `source-package.zip` | Runtime build identity, installed package versions, and executing TradeLang source. Bundles may also contain the release build inputs `uv.lock` and `pyproject.toml`. |
| `manifest.json` | Schema version 2. Version identifiers, resolved window, policy, fingerprints, and SHA-256 checksums and sizes for the other bundle files. |

The CLI stages files in a sibling directory and publishes a successful bundle at the requested path at the end. A run that fails after staging begins can leave a staging directory containing `failure.json`.

## Read the artifact fields

| File and fields | How to read them |
| --- | --- |
| Manifest `run_id`, `run_fingerprint`, `result_digest` | Use `run_id` to identify this run instance. Use the fingerprint and digest to [compare or replay](#compare-and-replay-runs). |
| Manifest `requested_window`, `resolved_window`, `resolved_policy` | Read the requested UTC dates, actual opening and closing timestamps, warmup and first execution times, and policies used for the run. |
| Manifest `artifact_files` | Each item gives the file `name`, `sha256`, and size in `bytes`. The manifest describes the other files in the bundle. |
| Summary `starting_capital`, `final_cash`, `final_equity`, `quote_currency` | These monetary values use the declared quote currency. Final equity includes any position marked at the last close. |
| Summary `open_position`, `metrics`, `benchmark`, `costs`, `counts`, `warnings` | `open_position` is null when the strategy ends flat. `metrics` describes the strategy and `benchmark.metrics` describes buy-and-hold. `counts.unavailable_by_reason` records runtime calculation failures, such as a zero denominator. |
| Equity `index`, `timestamp`, `phase`, `bar_index`, `mark_price` | `index` starts at 0. The first row has `phase` set to `initial` and its timestamp is the first in-window open. Its `bar_index` and `mark_price` are blank in CSV and null in Parquet. Subsequent `close` rows give the close time, zero-based dataset row, and raw close price. |
| Equity `equity`, `benchmark_equity`, `drawdown`, `benchmark_drawdown`, `cumulative_return`, `exposed` | Return and drawdown use fractions, so a cumulative return of `0.09` means 9%. `exposed` is a Boolean in Parquet and `true` or `false` in CSV. It records whether the strategy held a position at any point in that bar and is false on the initial row. |
| Trade `trade_id`, `entry_reference`, `entry_price`, `exit_reference`, `exit_price`, `net_pnl`, `return_fraction` | Match the trade to its fill events by `trade_id`. Reference prices precede slippage. Entry and exit prices include it. Net P&L is in quote currency, and `return_fraction` expresses return on the entry debit. |
| Trade `entry_rationale`, `exit_rationale`, `protection` | Parse the CSV row first, then JSON-decode populated cells in these columns. A missing value is an empty CSV cell. A protective exit can have an empty `exit_rationale` because it has no exit signal. |
| Event `sequence`, `observed_at`, `time_precision`, `bar_open_at` | Read events in `sequence` order. `time_precision` identifies a close, an open, or the containing interval for an intrabar event. `bar_open_at` identifies the candle in all three cases. |
| Event `event_id`, `linked_event_id`, `order_id`, `fill_id`, `trade_id` | `event_id` identifies a row and `linked_event_id` points to a related event when present. Follow the same `order_id` from signal to fill, then match fill events to `trades.csv` by `trade_id`. A protective exit can have a fill ID and trade ID with a null order ID. |

### Trace the quickstart trade

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

- `source_hash` identifies exact strategy bytes. A whitespace or comment edit changes it.
- `spec_hash` identifies the normalized typed strategy. Formatting and source spans are excluded. Declaration names and order are retained.
- `dataset_hash` identifies the normalized candles and semantic market metadata. CSV and Parquet encodings can share it when their normalized rows and metadata match. The raw file hash is recorded separately as `import_source_hash`.
- `run_fingerprint` identifies the versioned strategy, dataset, resolved configuration, and runtime environment. Keep the code, interpreter, and dependency inventory fixed when comparing fingerprints.
- `result_digest` identifies the logical summary, trades, equity, events, and diagnostics. It excludes the run ID, artifact paths, and physical Parquet encoding.

To reproduce a bundle, use its source, dataset copy, and metadata with the recorded package and dependencies. Write to a fresh directory, then compare the fingerprints and result digests. Generated run bundles contain the original submitted data and strategy, so review both before sharing one.
