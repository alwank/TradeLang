# Troubleshoot a backtest

Use the CLI diagnostic to find the first thing to fix. Before you begin, [install TradeLang](quickstart.md#install). Run the examples from the repository root. The examples use the bundled strategy and candles, so you can compare their behavior with your own run.

## Fix a unit error

If `validate` reports `E201_UNIT`, check the expression at the reported source location. For example, a comparison between `close` and a nonzero price needs a price threshold. Change `close >= 112` to `close >= 112 price`.

To reproduce the error, save a copy of [the fixture strategy](fixtures/core.trade) as `my-strategy.trade` and remove `price` from its exit condition. Run the validator before and after restoring the suffix.

```sh
tradelang validate my-strategy.trade
```

Expect `E201_UNIT` before the correction and `Warmup index 0` after it. See [unit comparisons](strategy-patterns.md#choose-the-right-units) for more examples.

## Check metadata and date coverage

If `explain` reports `E402_WINDOW` with `Strategy and dataset metadata differ`, compare the strategy's market, timeframe duration, and capital currency with the metadata. If the message is `Missing complete edge coverage`, check that the dataset includes the first and last complete candles on the requested UTC grid.

Rerun `explain` after the correction. Use the bundled files as a known-good comparison.

```sh
tradelang explain docs/fixtures/core.trade --data docs/fixtures/core.csv --metadata docs/fixtures/metadata.json
```

The example reports a first eligible close and executable open at `2024-01-02T00:00:00Z`. See [date coverage rules](candle-data.md#cover-the-dates-and-supply-warmup) for intervals that straddle a date boundary.

## Allow enough history for warmup

If `explain` reports `E_NO_EXECUTION_WINDOW`, supply earlier candles, extend the date range with complete candles, or review your indicator periods and lookbacks. The run needs an eligible close and a later observed open within the requested window.

For a reproducible check, insert `let average = EMA(3)` before `entry:` in your copy of the restored fixture strategy.

```sh
tradelang explain my-strategy.trade --data docs/fixtures/core.csv --metadata docs/fixtures/metadata.json
```

With three candles, the first ready close is on the last candle, so the command reports `E_NO_EXECUTION_WINDOW`. Change the example to `EMA(2)` and rerun the command. The explanation now gives a warmup index of 1 and a first executable open at `2024-01-03T00:00:00Z`. See [structural warmup and availability](language-spec.md#unavailable-and-bounded-computation).

## Diagnose missing or duplicate candles

If `E401_DATA` reports `Unsorted, duplicate or missing candle`, check the reported data row and the row before it. The diagnostic counts from the first candle, excluding the CSV header. Sort by opening time, remove duplicates, and fill accidental holes using complete candles from the source.

To see how a gap affects execution, copy [the three-candle fixture](fixtures/core.csv) to `gapped.csv` and remove the January 2 candle. Save a copy of [the sample metadata](fixtures/metadata.json) as `gapped-metadata.json`.

```sh
tradelang explain docs/fixtures/core.trade --data gapped.csv --metadata gapped-metadata.json
```

Expect `E401_DATA` on data row 2 with the default `reject` policy. If the missing candle is intentional, set `"gap_policy": "allow"` in your metadata copy and rerun. The first eligible close stays at `2024-01-02T00:00:00Z` and the first executable open moves to `2024-01-03T00:00:00Z`. [Gap handling](candle-data.md#choose-a-gap-policy) explains the effects on fills, lookbacks, and metrics.

## Choose a fresh output directory

If a run reports `E_IO` with `Output directory must be new or empty`, change `--out` to a new or empty directory. For example, after completing the [first backtest](quickstart.md), rerun it with a different output path.

```sh
tradelang backtest docs/fixtures/core.trade --data docs/fixtures/core.csv --metadata docs/fixtures/metadata.json --out runs/first-again
```

The new directory contains its own `manifest.json` and result files. Use the [CLI exit codes](cli.md#json-and-exit-status) if you need to handle failures in a script.
