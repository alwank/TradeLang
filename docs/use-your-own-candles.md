# Use your own candle data

Run a TradeLang strategy on a historical candle export. Before you begin, [install TradeLang](quickstart.md#install) and have a strategy, a CSV or Parquet export, and the export's market, quote currency, and candle interval. Run the commands from the repository root.

## Prepare the candles

1. Export completed spot candles with the `timestamp`, `open`, `high`, `low`, `close`, and `volume` columns. Save the file as `candles.csv` in the checkout for the commands on this page. For Parquet, use `candles.parquet` and substitute that name in both commands.
2. Use UTC-aligned candle opening times. Sort the rows from earliest to latest, remove duplicates, and ensure the requested dates include a complete first and last candle. Supply earlier candles if the strategy needs history to initialize its indicators.
3. Copy the [sample metadata](fixtures/metadata.json) to `metadata.json`. Change `symbol`, `quote_currency`, and `timeframe` to match your export and the strategy's `market`, `capital` currency, and `timeframe`. The template expects raw spot prices priced in the quote currency, base-asset volume, and a 24/7 calendar.

The default gap policy rejects missing candles. Check the [file and metadata requirements](candle-data.md#file-formats) for timestamp formats, limits, and supported values.

## Check compatibility

Save your strategy as `my-strategy.trade` in the checkout or substitute its path. Ask TradeLang to explain it with the dataset.

```sh
tradelang explain my-strategy.trade --data candles.csv --metadata metadata.json
```

Confirm that the explanation lists a first eligible close and first executable open within the date range you intend to test. If validation fails, use the diagnostic message to [check metadata, dates, gaps, or warmup](troubleshoot-backtests.md).

To rehearse the steps on sample data, copy [the fixture strategy](fixtures/core.trade), [candles](fixtures/core.csv), and [metadata](fixtures/metadata.json) to the three paths shown. The first eligible close and executable open are both `2024-01-02T00:00:00Z`.

## Run the backtest

Use the same files and choose a new or empty output directory.

```sh
tradelang backtest my-strategy.trade --data candles.csv --metadata metadata.json --out runs/my-backtest
```

The CLI prints final equity and the output directory. With the sample files, expect about **1,090.91 USDT**. With your data, open `summary.json` for the final equity and `diagnostics.json` for warnings about the run. See [Inspect and compare backtests](inspect-backtest-results.md) to trace fills and read the results.
