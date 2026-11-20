# Example strategies

Use six sample candles to see how an indicator triggers a trade. Then try the longer examples to explore moving averages, breakouts, and named conditions. Before you start, [install TradeLang](quickstart.md#install) and open a terminal in the checkout root.

## Inspect six candles by hand

Open the [bundled RSI strategy](https://github.com/alwank/TradeLang/blob/main/examples/quick/rsi.trade) in an editor. Its entry rule uses `RSI(2) crosses above 30`. The relative strength index (RSI) measures recent price momentum on a 0–100 scale. The crossing requires a previous RSI at or below 30 and a current RSI above 30. The exit rule queues a sale when the completed close is at least `13 price`. Explain the rules and run the example.

```sh
tradelang explain examples/quick/rsi.trade --data examples/quick/recovery.csv --metadata docs/fixtures/metadata.json
tradelang backtest examples/quick/rsi.trade --data examples/quick/recovery.csv --metadata docs/fixtures/metadata.json --out runs/quick-rsi
```

`explain` shows that `RSI(2)` uses the closing price by default and that the crossing can first be evaluated on the fourth candle, at warmup index 3. Open `runs/quick-rsi/events.jsonl` to trace the signals and fills. The table labels each candle by its UTC opening date.

| Signal (by UTC candle opening date) | Fill at next open |
| --- | --- |
| Jan 4 · RSI reaches 73.33, triggering a buy | Jan 5 · **13 USDT** |
| Jan 5 · Close reaches 13 USDT, triggering a sell | Jan 6 · **14 USDT** |

The run starts with 1,000 USDT and ends with **1,076.92 USDT**. Check `trades.csv` for the prices and `summary.json` for final equity.

To isolate the effect of sizing on this strategy, save a copy as `runs/rsi-quarter.trade` and change `buy using 100% of equity` to `buy using 25% of equity`. Run it into a fresh folder.

```sh
tradelang backtest runs/rsi-quarter.trade --data examples/quick/recovery.csv --metadata docs/fixtures/metadata.json --out runs/quick-rsi-quarter
```

The fill prices stay the same and final equity is **1,019.23 USDT**. Compare the quantities in the two trade files. Both runs use synthetic candles with zero fees and slippage.

For a different entry signal on the same candles, substitute `examples/quick/ema.trade` or `examples/quick/breakout.trade` in the original backtest command and choose a fresh output path. Both variants buy and sell on the same dates and at the same prices as the RSI strategy. Compare the entry rationale in each `trades.csv` to see what triggered the buy.

## Run the full examples

Choose an example to see how its rules use indicators, position sizing, or protection.

| Source | What to look for |
| --- | --- |
| [RSI trend recovery](examples/01-rsi.trade) | An RSI recovery signal with a trend filter and percent-based protection. |
| [EMA crossover](examples/02-ema.trade) | Two moving averages with crossings in both directions. |
| [Previous-high breakout](examples/03-breakout.trade) | A lagged rolling high and ATR-based price distances. |
| [Arithmetic deviation](examples/04-math.trade) | Named Boolean conditions, dimensionless deviation, and series-based sizing. |

Generate the hourly dataset offline. The generator writes 35,064 sample candles to `runs/example-data/example.csv` and the matching metadata to `runs/example-data/metadata.json`.

```sh
uv run --no-project --python 3.12 python scripts/example_data.py runs/example-data
```

Run the EMA example in a POSIX shell or PowerShell. Choose a new or empty output directory each time.

```sh
tradelang backtest docs/examples/02-ema.trade --data runs/example-data/example.csv --metadata runs/example-data/metadata.json --out runs/ema-example
```

To run all four in a POSIX shell, use a separate output path for each strategy.

```sh
for strategy in docs/examples/*.trade; do
  tradelang backtest "$strategy" \
    --data runs/example-data/example.csv \
    --metadata runs/example-data/metadata.json \
    --out "runs/$(basename "$strategy" .trade)"
done
```

Check `summary.json` for the outcome and `trades.csv` for the completed trades. On this synthetic series, the full RSI strategy generates no entry signals. The [six-candle RSI exercise](#inspect-six-candles-by-hand) shows a recovery signal and its fill.

Next, [apply these patterns to your own strategy](strategy-patterns.md).
