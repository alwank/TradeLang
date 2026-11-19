# Example strategies

Start with six synthetic candles to see how an indicator produces a signal. Once you can trace that trade, use the larger examples to explore moving averages, breakouts, and named conditions.

## Inspect six candles by hand

Run these commands from the checkout root after [installing TradeLang](quickstart.md#install). Open the [bundled RSI strategy](https://github.com/alwank/TradeLang/blob/main/examples/quick/rsi.trade) in an editor. Its entry rule uses `RSI(2) crosses above 30`. The relative strength index (RSI) measures recent price momentum on a 0–100 scale. The crossing requires a previous RSI at or below 30 and a current RSI above 30. The exit rule queues a sale when the completed close is at least `13 price`.

```sh
uv run --no-sync tradelang explain examples/quick/rsi.trade --data examples/quick/recovery.csv --metadata docs/fixtures/metadata.json
uv run --no-sync tradelang backtest examples/quick/rsi.trade --data examples/quick/recovery.csv --metadata docs/fixtures/metadata.json --out runs/quick-rsi
```

`explain` shows that `RSI(2)` uses the closing price by default and that the crossing can first be evaluated on the fourth candle, at warmup index 3. Trace the two signals and fills in `runs/quick-rsi/events.jsonl`.

| Signal (by UTC candle opening date) | Fill at next open |
| --- | --- |
| Jan 4 · RSI reaches 73.33, triggering a buy | Jan 5 · **13 USDT** |
| Jan 5 · Close reaches 13 USDT, triggering a sell | Jan 6 · **14 USDT** |

The run starts with 1,000 USDT and ends with **1,076.92 USDT**. Check `trades.csv` for the prices and `summary.json` for final equity.

To isolate the effect of sizing on this strategy, save a copy as `rsi-quarter.trade` in the checkout root and change `buy using 100% of equity` to `buy using 25% of equity`. Run it into a fresh folder.

```sh
uv run --no-sync tradelang backtest rsi-quarter.trade --data examples/quick/recovery.csv --metadata docs/fixtures/metadata.json --out runs/quick-rsi-quarter
```

The fill prices stay the same and final equity is **1,019.23 USDT**. Compare the quantities in the two trade files. Both runs use synthetic candles with zero fees and slippage.

For a different entry signal on the same candles, use `examples/quick/ema.trade` or `examples/quick/breakout.trade` in the backtest command with a fresh output path. Both variants buy and sell on the same dates and at the same prices as the RSI strategy. Compare the entry rationale in each `trades.csv` to see what triggered the buy.

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

Check `summary.json` for the outcome and `trades.csv` for the completed trades. On this synthetic series, the full RSI strategy generates no entry signals. The [six-candle RSI exercise](#inspect-six-candles-by-hand) shows a recovery signal and its fill. Each output path must be new or empty.
