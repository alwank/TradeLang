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

Unavailable metrics use JSON null. If a valid ledger produces a statistic outside the supported numeric range, `diagnostics.json` reports the affected metric with reason `numeric_range`. Treat a short-window annualized value as a mathematical extrapolation of that window.

The run's missing-bar warning counts gaps inside the execution window. In `dataset-summary.json`, `missing_bar_count` covers the full primary input. `pre_window_missing_bar_count` covers the history up to the first in-window open. `execution_window_missing_bar_count` covers gaps between the first and last in-window opens.

### Compare a common-start benchmark

Compare can calculate a shared buy-and-hold reference for runs that use the same primary candles, market, calendar, timeframe, execution semantics, gap policy, fees, and slippage. The reference starts at the latest first executable open in the group and ends at the earliest terminal close. It starts at index 100, buys at the selected open with entry costs, and marks the holding through the common end.

Strategy returns over that interval start at index 100 using equity immediately before orders execute at the common open. Cash and quantity come from the last preceding ledger row. Any existing quantity is valued at the common open, then carried into the interval. The comparison reports excess return in percentage points by subtracting the reference return from each strategy's return on those same candles. Full-run metrics use their original windows.

The API derives this view from recorded inputs using policy `common_start_hold_v1`. It retains each run's warmup-aligned benchmark in the saved bundle. A run with incompatible inputs or a disjoint window receives an eligibility reason. Compatible groups remain available.

## Artifact files

| File | Contents |
| --- | --- |
| `summary.json` | Schema version 1. Final cash and equity, open position, metrics, benchmark, costs, counts, and warnings. |
| `equity.csv`, `equity.parquet` | The same full-resolution strategy and benchmark curves, with `cumulative_return` and Boolean `exposed` fields. |
| `trades.csv` | One row per closed trade, with reference and fill prices, fees, net P&L, rationale, and exit reason. Nested fields contain JSON. |
| `events.jsonl` | Ordered signal, order, fill, rejection, expiry, and warning events. Sort by `sequence` when timestamps coincide. For an intrabar event, `time_precision: "bar"` identifies the containing candle. |
| `decisions.parquet` | Version 1 decision record for each observed candle in the execution window. Records rule outcomes, event byte ranges, and fill-time sizing inputs. |
| `diagnostics.json` | Run diagnostics, also surfaced in the JSON CLI response. |
| `source.trade`, `strategy-spec.json` | Exact submitted source bytes and the compiler's typed strategy. Omitted market and timeframe declarations appear as `null` in the typed strategy. The run's effective values appear in `summary.json` and `metadata.json`. |
| `input.csv` or `input.parquet`, `metadata.json`, `dataset-summary.json` | Exact submitted dataset, validated settings, and quality summary. |
| `environment.json`, `dependency-lock.txt`, `source-package.zip` | Runtime build identity, installed package versions, and executing TradeLang source. Bundles may also contain the release build inputs `uv.lock` and `pyproject.toml`. |
| `manifest.json` | Schema version 2. Version identifiers, resolved window, policy, fingerprints, and SHA-256 checksums and sizes for the other bundle files. |

The CLI stages files in a sibling directory and publishes a successful bundle at the requested path at the end. A single-input run that fails after staging begins can leave a staging directory containing `failure.json`. Volume Profile runs remove their staging directory on failure.

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

### Review workload

Dataset-aware validation reports the version 1 `workload` record before a run. The manifest saves the same estimate. Evaluated rows include the history preceding execution. Execution rows count the observed candles inside the requested window.

| Field | Meaning |
| --- | --- |
| `minimum_resident_bytes` | Lower bound from input arrays, resident profile data, required calculated arrays, and the equity curve. Admission compares this bound with `memory_limit_bytes`, which is 1 GiB. |
| `retained_series`, `kernel_calls` | Estimates for cached series and indicator evaluations. References to the same binding and equivalent indicator inputs receive credit for cache reuse. |
| `dominant_expression`, `dominant_component` | Expression contributing the most estimated series and the largest estimated allocation category. |
| `event_count_ceiling`, `event_memory_allowance_bytes` | A per-bar bound on event count and a planning allowance for events and traces. Actual values depend on signals and orders. |
| `profile_work_units`, `profile_bytes`, `decision_bytes` | Prepared Volume Profile work and storage, and estimated base storage for candle decisions. |

Transient kernel buffers, process overhead, and actual events can push an admitted run past the budget. The supervised worker still enforces its measured memory and time limits and accepts cancellation.

### Inspect a candle decision

Use the [browser workspace](browser.md#inspect-a-candle) or the [bar inspection route](local-api.md#inspect-a-candle) to inspect one observed candle by its zero-based primary dataset index. A rule's predicate can be true, false, or unavailable. The outcome explains what happened to the rule in the ledger, such as an entry blocked by a true exit or a rule skipped after an intrabar exit.

The manifest identifies decision evidence in `decision_inspection`. Its `decision_counts` totals true, false, and unavailable predicates for evaluated candles and counts skipped warmup and post-exit candles separately. These counts use observed candles as the unit. The decision file participates in the artifact checksum inventory. The logical result digest covers summary, trades, equity, events, and diagnostics as before.

Ordered exits use decision file schema 2, which records completed holding candles for exit rule inspection. The signal, queued order, and fill events identify the rule under `trace.exit_rule`. Trailing events record the sampled close, previous and new triggers, and the effective open when activated. [Ordered exits](language-v5.md)

Quantity-changing runs record `position_ledger` schema 1 in the manifest. Every fill in `events.jsonl` includes remaining quantity and basis, the basis and entry fee released on that leg, and realized gross and net P&L. Filter the events by `trade_id` to obtain one position's ordered fills. A closed-trade CSV row aggregates all fills in a finished cycle. `summary.position_accounting` includes realized P&L from open and closed cycles. [Position accounting](execution-semantics.md#position-accounting-in-semantics-600)

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
- **V1-ID01.** `spec_hash` identifies the normalized typed strategy. Formatting and source spans are excluded. Declaration names and order are retained.
- **V1-ID02.** `dataset_hash` identifies the normalized candles and semantic market metadata. CSV and Parquet encodings can share it when their normalized rows and metadata match. The raw file hash is recorded separately as `import_source_hash`.
- **V1-ID03.** `run_fingerprint` identifies the versioned strategy, dataset, resolved configuration, and runtime environment. Keep the code, interpreter, and dependency inventory fixed when comparing fingerprints.
- `result_digest` identifies the logical summary, trades, equity, events, and diagnostics. It excludes the run ID, artifact paths, and physical Parquet encoding.

JSON used for identity is UTF-8 with sorted object keys, compact separators, normalized finite decimal exponents, and both signs of zero written as `0`. The dataset byte stream starts with `tradelang.dataset.v1\n`, a little-endian unsigned 32-bit metadata-header length, and the canonical metadata bytes. Each row then contributes a little-endian signed 64-bit opening time in UTC microseconds and five binary64 OHLCV values. Gap policy belongs in configuration identity. Timeframe is normalized to seconds.

The run fingerprint hashes the canonical object with `dsl_version`, `semantics_version`, `spec_hash`, `dataset_hash`, `environment_hash`, and `config_hash`. For the result digest, hash the stream of summary, trades, equity, events, and diagnostics in that order. Each section starts with its name and a newline, followed by its canonical JSON records, each terminated by a newline. Diagnostic spans are omitted from the digest, including spans in summary warnings.

| Version | Scope |
| --- | --- |
| DSL 1 and typed strategy schema 1 | Accepted source and serialized compiler output |
| Semantics 1.1.0 | Evaluation, clock, order phases, and accounting |
| DSL 2 and typed strategy schema 2 | Opt-in source syntax, effective parameters, and record typing |
| Semantics 2.0.0 | DSL 2 expression evaluation and reachable warmup |
| DSL 3, typed strategy schema 3, and semantics 3.0.0 | Named secondary feeds, separate evaluation clocks, and completed-close alignment |
| DSL 4, typed strategy schema 4, and semantics 4.0.0 | Stop-based sizing for one long, with optional allocation limits and entry trace evidence |
| DSL 5, typed strategy schema 5, and semantics 5.0.0 | First-match exits, completed holding candles, trailing stops, and optional signal-order expiry |
| DSL 6, typed strategy schema 6, and semantics 6.0.0 | Partial exits, scaling in, quantity steps, and weighted-average position accounting |
| DSL 7, typed strategy schema 7, and semantics 7.0.0 | Recorded exchange sessions and split-reference pricing |
| DSL 8, typed strategy schema 8, and semantics 8.0.0 | Borrowed-asset shorts with explicit collateral, financing, and liquidation |
| DSL 9, typed portfolio schema 9, and semantics 9.0.0 | Independent asset clocks and shared capital in a portfolio |
| Artifact schema 2 | Published bundle and manifest structure |
| Artifact schema 3 | Volume Profile runs with a secondary dataset in the manifest |
| Artifact schema 4 | Runs with a named higher-timeframe feed and captured alignment inputs |
| Metadata, summary, and inspection envelopes 1 | Independently versioned JSON payloads |
| Package version and code revision | Executing source and reproducibility evidence |

A code-only migration can preserve the source, normalized spec, dataset, configuration, and result digest while changing the environment hash and run fingerprint. Two runs in the same recorded environment have distinct run IDs.

To reproduce a bundle, use its source, dataset copy, and metadata with the recorded package and dependencies. Write to a fresh directory, then compare the fingerprints and result digests. Generated run bundles contain the original submitted data and strategy, so review both before sharing one.

For [DSL 2](language-v2.md), pass each entry in the manifest's `parameter_overrides` as `--param NAME=VALUE`. The typed strategy records the default and effective value of each parameter. The spec hash uses effective values in canonical name order. An omitted override and an explicit override equal to the default produce the same spec hash and fingerprint for the same data and runtime.

### Replay configured runs

The bundle includes `run-config.json` for a portfolio, or when a single-market run uses a preset, explicit run settings, parameter overrides, a named feed, session data, or a borrowed-asset short. The file points to the saved inputs in the same bundle and contains the applied overrides. Run the bundled source in the recorded environment. [Named feeds](language-v3.md) · [Exchange sessions](language-v7.md) · [Borrowed-asset shorts](language-v8.md) · [Portfolios](language-v9.md)

```sh
tradelang backtest BUNDLE/source.trade \
  --run-config BUNDLE/run-config.json --out REPLAY_DIRECTORY
```

Replace `BUNDLE` with the saved run directory and `REPLAY_DIRECTORY` with a new output path. Compare the run fingerprint and result digest. The manifest records the resolved values in `effective_configuration`. Effective run settings contribute to configuration identity. Preset names, revision labels, and value origins are provenance fields.

### Replay a Volume Profile run

Supply the bundle's primary input and metadata through `--data` and `--metadata`. Pass the file named by `profile_input.data_file` through `--profile-data` and `profile_input.metadata_file` through `--profile-metadata`. Profile inputs are named `profile-input.csv` or `profile-input.parquet` and `profile-metadata.json`. Match the recorded hashes for both input files against the artifact inventory before replay.

The schema 3 manifest carries `profile_dataset` with `role: "volume_profile"` and the secondary dataset's canonical `dataset_hash`. Include this object as an additional member of the run signature when recomputing the fingerprint. The configuration identity includes the same object with its `gap_policy` added. The `profile_input` manifest object records the role, canonical and source hashes, gap policy, and both file names. The raw file hash belongs to the artifact inventory, allowing equivalent CSV and Parquet data to share a fingerprint when the canonical inputs and environment match.
