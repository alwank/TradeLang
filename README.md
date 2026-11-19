# TradeLang

TradeLang is a typed strategy language and deterministic local backtester for historical candles. Keep your entry, exit, position sizing, risk rules, and execution settings in one `.trade` file. The CLI checks and explains those rules before you run them, then saves the strategy, candles, and evidence behind each fill.

[Walkthrough](#walkthrough) · [Capabilities](#capabilities) · [Compare tools](#compare-tools) · [Docs](docs/index.md)

## Walkthrough

The example enters when the relative strength index (RSI) crosses above 30 and exits after a close of at least 13 USDT. With `uv` installed, run the walkthrough from the repository root. `uv` can fetch Python 3.12 if needed. [Install uv](https://docs.astral.sh/uv/getting-started/installation/)

```sh
uv sync --locked --no-dev --no-editable
```

### 1. Write the strategy

Save this complete strategy as `strategy.trade` in the repository root. [Bundled RSI strategy](examples/quick/rsi.trade)

```text
strategy "rsi recovery"
market TESTUSDT
timeframe 1d
entry:
  when RSI(2) crosses above 30
  buy using 100% of equity
exit:
  when close >= 13 price
  sell all

backtest:
  from 2024-01-01 to 2024-01-06
  capital 1000 USDT
  fee 0 bps per side
  slippage 0 bps per side
  execute at next bar open
  calendar 24x7
```

- `market TESTUSDT` and `timeframe 1d` match the sample market and daily candles.
- `13 price` tells the compiler that 13 is a price in the market’s quote currency. A bare `13` has a different unit and fails validation against `close`.
- `backtest` sets the inclusive date range, starting capital, per-side fees and slippage, next-open execution, and continuous calendar.

### 2. Check the rules

Use `explain` with the [six sample candles](examples/quick/recovery.csv) and their [metadata](docs/fixtures/metadata.json) to check how TradeLang will interpret the strategy.

```sh
uv run --no-sync tradelang explain strategy.trade --data examples/quick/recovery.csv --metadata docs/fixtures/metadata.json
```

Selected output shows that `RSI(2)` uses the closing price, the order fills at the next open, and signals can start on the fourth candle (zero-based index 3).

```text
At close, enter when (RSI(close, 2) crosses above 30).
At next open, allocate 1 of equity including entry fee.
Exit all at the next open after (close >= 13 price).
Warmup index 3. …
```

### 3. Backtest and inspect the result

Run the same strategy and candles through the simulator. Use a new or empty output directory for each run.

```sh
uv run --no-sync tradelang backtest strategy.trade --data examples/quick/recovery.csv --metadata docs/fixtures/metadata.json --out runs/rsi-100
```

The table labels each UTC candle by the date it opened.

| Signal at close (UTC) | Fill at next open (UTC) |
| --- | --- |
| Jan 4 · Buy | Jan 5 · **13 USDT** |
| Jan 5 · Sell | Jan 6 · **14 USDT** |

The first run ends with **1,076.92 USDT**. Open `runs/rsi-100` to see how it got there.

- `summary.json` shows final equity and the buy-and-hold benchmark.
- `trades.csv` shows entry and exit fills and net profit or loss.
- `events.jsonl` records each signal, order, and fill in sequence. The buy signal records RSI at 73.33, and the sell signal records a close of 13 USDT.

### 4. Change one line and rerun

Replace `buy using 100% of equity` with `buy using 25% of equity` in `strategy.trade`. Save it and run the backtest into a separate directory.

```sh
uv run --no-sync tradelang backtest strategy.trade --data examples/quick/recovery.csv --metadata docs/fixtures/metadata.json --out runs/rsi-25
```

| Equity used | Ending equity | Return |
| --- | ---: | ---: |
| 100% | 1,076.92 USDT | +7.69% |
| 25% | 1,019.23 USDT | +1.92% |

Both runs start at 1,000 USDT, use the same six synthetic candles with zero fees and slippage, and close one trade at the same fill prices. The smaller position leaves 750 USDT in cash at entry, so the same price move has one quarter of the impact on the account.

## Capabilities

- **Express and check rules.** Use built-in indicators such as RSI, EMA, and ATR, plus crossovers, named conditions, and prior-candle lookbacks. The compiler checks units for prices, ratios, and other values. [Writing strategies](docs/writing-strategies.md)
- **Set position size, costs, and protection.** Size entries as a percentage of equity or a fixed cash budget. Model per-side fees and slippage, and set stop-loss and take-profit triggers. [Execution semantics](docs/execution-semantics.md)
- **Run on your own candles.** Backtest one long spot position at a time on 24/7 UTC candles supplied as CSV or Parquet. [Candle data](docs/candle-data.md)
- **Inspect and replay results.** Read the equity curve in `equity.csv` or `equity.parquet`, the buy-and-hold benchmark in `summary.json`, and the order trace in `events.jsonl`. The run bundle preserves the strategy, input data, metadata, and runtime details for replay. [Results and artifacts](docs/results.md)

## Compare tools

- **TradeLang** fits when you want to write, check, and trace a supported spot strategy locally. In the walkthrough, changing one line of the strategy was enough to isolate position sizing. The same CLI ran both versions and saved each run’s inputs and results.
- **Backtesting.py** fits when you want to write custom Python strategy logic. Its `Strategy` class uses `init()` to prepare indicators and `next()` to make decisions bar by bar. [Backtesting.py user guide](https://kernc.github.io/backtesting.py/doc/examples/Quick%20Start%20User%20Guide.html)
- **VectorBT** fits when you want to work with signal arrays in Python and sweep many parameter combinations across assets. [VectorBT usage guide](https://vectorbt.dev/getting-started/usage/)

## Next steps

- [Try the EMA crossover, breakout, and other strategy examples](docs/example-strategies.md)
- [Prepare your own candles](docs/candle-data.md)
- [Replay or compare a run](docs/results.md)

## Contributing

[Contributing guide](CONTRIBUTING.md) · [Changelog](CHANGELOG.md) · [Build and publish the docs](docs/publishing.md)

## License

TradeLang is licensed under the [Apache License, Version 2.0](LICENSE).
