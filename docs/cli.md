# Command-line reference

After [installing TradeLang](quickstart.md#install), run `tradelang --version` for the installed package version or `tradelang COMMAND --help` for options.

## Validate

```text
tradelang validate STRATEGY [--data FILE --metadata FILE] [--json]
```

Compile syntax, types, and constant constraints. With data, also check that the dataset matches the strategy's capital currency, any declared market or timeframe, and the execution window. The primary dataset supplies omitted market and timeframe values for the run. JSON success returns `source_hash`, `spec_hash`, the typed `spec`, `warmup_index`, and `data_compatible`. The last field is null for source-only validation.

## Explain

```text
tradelang explain STRATEGY [--data FILE --metadata FILE] [--json]
```

Compile the same source and describe its normalized conditions, sizing, protection, and execution assumptions. JSON success returns `source_hash`, `spec_hash`, `text`, `assumptions`, `warmup_index`, and `resolved_window`. Supply data to resolve the window, first eligible signal close, and first execution open. A source-only explanation has a null `resolved_window`.

## Backtest

```text
tradelang backtest STRATEGY --data FILE --metadata FILE --out DIRECTORY [--json]
```

Run the strategy and write an auditable [artifact bundle](results.md#artifact-files). Dates, costs, and capital come from the strategy source. The output directory must be new or empty. JSON success returns `run_id`, `run_fingerprint`, `result_digest`, `artifact_directory`, and `summary`.

For DSL 4 stop-based sizing, `tradelang explain` describes the modeled loss and allocation cap. See the [runnable backtest and override](language-v4.md#run-and-inspect-the-example).

For DSL 5, `tradelang explain` lists exits in source order and describes the trailing stop and order expiry. See the [ordered exit example](language-v5.md#run-and-inspect-the-example).

For DSL 6, `tradelang explain` describes partial exits, the scale rule, and quantity increments. The [position example](language-v6.md#run-and-inspect-the-example) shows the fill ledger for a full cycle and an open position.

For DSL 7 exchange sessions, pass the [session metadata JSON](language-v7.md) with `--metadata`. Date overrides use the exchange's trading dates.

Declare the collateral and borrow terms for a [DSL 8 short](language-v8.md) in the strategy's `backtest` block. The bundle includes those terms and a replay configuration.

Pass `--run-config` with asset bindings when running a [DSL 9 portfolio](language-v9.md). The portfolio source declares shared capital. Set date, cost, and parameter overrides in each asset's settings.

## Parameter overrides

On any command, pass `--param NAME=VALUE` once per [DSL 2 parameter](language-v2.md#parameters-and-static-arguments) you want to override. Use a JSON number or Boolean, such as `--param fast=1` or `--param enabled=false`. Validation, explanation, and execution resolve the same values. Omit a parameter override to use the declared default.

## Reuse run settings

Pass `--run-config FILE` to apply a reusable JSON configuration. Relative candle and metadata paths resolve from that file. For example, save this run configuration as `docs/fixtures/macd-settings.json` in a checkout.

```json
{
  "schema_version": 1,
  "name": "MACD fee experiment",
  "data": "macd-v2.csv",
  "metadata": "metadata.json",
  "settings": {
    "capital": 2000,
    "fee_bps": 10,
    "parameters": {"fast": 1}
  }
}
```

Validate the selected inputs and override the fee for one run.

```sh
tradelang validate docs/fixtures/macd-v2.trade \
  --run-config docs/fixtures/macd-settings.json --fee-bps 15
```

The strategy supplies its date window. The file supplies the candles, capital, and fast period. The flag sets a fee of 15 basis points per side. You can also override other values directly with `--from-date`, `--to-date`, `--capital`, `--slippage-bps`, and `--run-gap-policy`. Use inclusive UTC dates in `YYYY-MM-DD` form and positive capital in the strategy's currency. Costs must be at least zero and below 10,000 basis points per side. The requested gap policy must match the candle metadata. Optional `profile_data` and `profile_metadata` select the lower-timeframe input.

The JSON output of `validate` and `explain` includes `run_configuration` when you use a configuration file or a run-setting flag. Inspect the effective values and `origins` before starting the backtest. [Replay a configured run](results.md#replay-configured-runs)

## Data options

For a [DSL 3 named feed](language-v3.md), bind the candle file with `--feed NAME=FILE` and the metadata with `--feed-metadata NAME=FILE`. Use the declared name in both options. A portable run configuration can instead map that name under `feeds` to an object with `data` and `metadata` paths.

For any command with `--data`, choose a [metadata JSON file](candle-data.md#declare-metadata) or supply the metadata flags as shown here.

```sh
tradelang backtest docs/fixtures/core.trade --data docs/fixtures/core.csv \
  --symbol TESTUSDT --quote-currency USDT --timeframe 1d \
  --calendar 24x7 --timestamp-convention bar_open \
  --volume-unit base_quantity --price-basis raw_spot --gap-policy reject \
  --out runs/with-flags
```

All the metadata flags shown are required in flag mode except `--gap-policy`, which defaults to `reject`.

For a strategy that uses `VPROFILE`, also pass `--profile-data FILE --profile-metadata FILE`. These select the [lower-timeframe candles and their own metadata](candle-data.md#pair-candles-for-volume-profile). Use both flags together on dataset-aware validation, explanation, and backtest. Source-only validation can compile a profile call before an input is selected. The engine reports `E402_WINDOW` when the required pairing is missing or incompatible and `E_DATA_LIMIT` when the estimated profile workload exceeds the execution limit.

## JSON and exit status

`--json` writes a single JSON object to stdout for a recognized subcommand.

```json
{
  "schema_version": 1,
  "command": "validate",
  "ok": false,
  "diagnostics": [],
  "result": null
}
```

The object above illustrates the shape. A failure carries diagnostic entries. Each includes a code, severity, message, and applicable source span or one-based data row. Successful inspection and backtest responses can also carry warnings. See the [language diagnostics](language-spec.md#diagnostics-and-explanation) for common codes.

Without `--json`, `validate` and `explain` print warnings to standard error, even when the strategy passes. Syntax errors can suggest a spelling or indicate the expected TradeLang constructs. Dataset-aware checks report required and observed window bounds when coverage is incomplete.

Dataset-aware `validate` and `explain` also report the workload before execution. Add `--json` to read the structured `workload` record with evaluated rows, series, and resource estimates. If the minimum resident storage exceeds the worker memory budget, the command exits with status 2 and `E_DATA_LIMIT`. Shorten the input history or reduce calculated series before starting the run. [Workload fields](results.md#review-workload)

| Exit status | Meaning |
| --- | --- |
| `0` | Success. Warnings may be present. |
| `2` | Invalid source, data, or configuration. |
| `3` | I/O, metadata JSON parsing, or command usage error, such as an occupied output directory. |
| `4` | Numerical or resource failure during execution. |
| `130` | Interrupted. |

When using `--metadata`, a file containing just `{` is malformed JSON and returns `E_IO` with exit status `3`. A file containing `{}` parses successfully but lacks required metadata fields, so it returns `E401_DATA` with exit status `2`. Both codes appear in `diagnostics` with `--json`.
