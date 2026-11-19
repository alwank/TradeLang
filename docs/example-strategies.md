# Example strategies

The repository includes synthetic data for two ways to try the language.

## Run the full examples

| Source | What to look for |
| --- | --- |
| [RSI trend recovery](examples/01-rsi.trade) | An RSI recovery signal with a trend filter and percent-based protection. |
| [EMA crossover](examples/02-ema.trade) | Two moving averages with crossings in both directions. |
| [Previous-high breakout](examples/03-breakout.trade) | A lagged rolling high and ATR-based price distances. |
| [Arithmetic deviation](examples/04-math.trade) | Named Boolean conditions, dimensionless deviation, and series-based sizing. |

From the repository root, after [installing TradeLang](quickstart.md#install), generate the hourly dataset offline. The generator writes 35,064 synthetic candles.

```sh
uv run --no-sync python scripts/example_data.py runs/example-data
```

In a POSIX shell, backtest all four source files against that dataset.

```sh
for strategy in docs/examples/*.trade; do
  uv run --no-sync tradelang backtest "$strategy" \
    --data runs/example-data/example.csv \
    --metadata runs/example-data/metadata.json \
    --out "runs/$(basename "$strategy" .trade)"
done
```

To run a single example on any shell, including PowerShell, pass the file explicitly.

```sh
uv run --no-sync tradelang backtest docs/examples/02-ema.trade --data runs/example-data/example.csv --metadata runs/example-data/metadata.json --out runs/ema-example
```

Check `summary.json` for the outcome and `trades.csv` for the completed trades. The full RSI example has no entry signals on this synthetic series. Use the six-candle RSI example below to see a recovery signal and its fill. Each output path must be new or empty.

## Inspect six candles by hand

The three strategies in `examples/quick/` share `recovery.csv`. Try the EMA example, then substitute `rsi.trade` or `breakout.trade` and a fresh output directory.

```sh
uv run --no-sync tradelang backtest examples/quick/ema.trade --data examples/quick/recovery.csv --metadata docs/fixtures/metadata.json --out runs/quick-ema
```

All three variants signal entry on the January 4 candle's close, buy at the January 5 open for 13, and sell at the January 6 open for 14. Compare the entry rationale in each `trades.csv` to see how the same price sequence produced different signals.
