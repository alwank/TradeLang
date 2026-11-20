# Command-line reference

Use `validate` to check inputs, `explain` to inspect rules and timing, and `backtest` to simulate trades. Run `tradelang --version` for the installed package version or `tradelang COMMAND --help` for a command’s options. See [Run your first backtest](quickstart.md) for installation and an end-to-end example.

## Validate

```text
tradelang validate STRATEGY [--data FILE --metadata FILE] [--json]
```

Compile syntax, types, and constant constraints. With data, also check the dataset and its compatibility with the strategy's market, currency, timeframe, and execution window. JSON success returns `source_hash`, `spec_hash`, the typed `spec`, `warmup_index`, and `data_compatible`. The last field is null for source-only validation.

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

## Data options

For any command with `--data`, choose a [metadata JSON file](candle-data.md#declare-metadata) or supply metadata as flags. This example uses a POSIX shell.

```sh
tradelang backtest docs/fixtures/core.trade --data docs/fixtures/core.csv \
  --symbol TESTUSDT --quote-currency USDT --timeframe 1d \
  --calendar 24x7 --timestamp-convention bar_open \
  --volume-unit base_quantity --price-basis raw_spot --gap-policy reject \
  --out runs/with-flags
```

All the metadata flags shown are required in flag mode except `--gap-policy`, which defaults to `reject`.

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

The object above illustrates the shape. A failure carries diagnostic entries. Each includes a code, severity, message, and applicable source span or one-based data row. Successful inspection and backtest responses can also carry warnings. See the [language diagnostics](language-spec.md#diagnostics-and-explanation) for the fields and [Troubleshoot a backtest](troubleshoot-backtests.md) for example fixes.

| Exit status | Meaning |
| --- | --- |
| `0` | Success. Warnings may be present. |
| `2` | Invalid strategy source, data, or configuration. |
| `3` | Command usage error (`E_USAGE`) or I/O failure (`E_IO`). I/O failures include malformed metadata JSON and an occupied output directory. |
| `4` | Numerical or resource failure during execution. |
| `130` | Interrupted. |

When using `--metadata`, a file containing just `{` is malformed JSON and returns `E_IO` with exit status `3`. A file containing `{}` parses successfully but lacks required metadata fields, so it returns `E401_DATA` with exit status `2`. Both codes appear in `diagnostics` with `--json`.
