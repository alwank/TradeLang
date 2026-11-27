# TradeLang

TradeLang is a typed strategy language and deterministic local backtester for historical candles. Keep your entry, exit, position sizing, risk rules, and execution settings in one `.trade` file. The CLI checks and explains those rules before you run them, then saves the strategy, candles, and evidence behind each fill.

[Run your first backtest](https://tradelang.readthedocs.io/en/latest/quickstart/) · [Learn backtesting basics](https://tradelang.readthedocs.io/en/latest/backtesting-basics/) · [Capabilities](#capabilities) · [Compare tools](#compare-tools)

## Walkthrough

Install [Git](https://git-scm.com/install/) and [uv](https://docs.astral.sh/uv/getting-started/installation/), then run the included strategy on three synthetic candles.

```sh
git clone https://github.com/alwank/TradeLang.git
cd TradeLang
uv tool install --python 3.12 .
tradelang backtest docs/fixtures/core.trade --data docs/fixtures/core.csv --metadata docs/fixtures/metadata.json --out runs/first
```

The backtest buys at **110 USDT**, sells at **120 USDT**, and ends with **1,090.91 USDT** from a starting balance of 1,000 USDT. Check `runs/first/trades.csv` for both fills and `runs/first/summary.json` for final equity. Use a new or empty output directory for each run.

Follow the [first backtest guide](https://tradelang.readthedocs.io/en/latest/quickstart/) to validate the rules, see how the orders fill, and find the next exercise.

## Browser workspace

Import candles, edit and validate strategy revisions, and inspect or compare backtests in the local web app. [Start the browser workspace](docs/browser.md)

## Capabilities

- **Express and check rules.** Use built-in indicators such as RSI, EMA, and ATR, plus crossovers, named conditions, and prior-candle lookbacks. The compiler checks units for prices, ratios, and other values. [Writing strategies](docs/writing-strategies.md)
- **Set position size, costs, and protection.** Size entries as a percentage of equity or a fixed cash budget. Model per-side fees and slippage, and set stop-loss and take-profit triggers. [Execution semantics](docs/execution-semantics.md)
- **Run on your own candles.** Supply CSV or Parquet candles on a continuous UTC grid or a recorded exchange schedule. Backtest one position at a time, including borrowed-asset shorts with explicit margin and borrow terms. [Candle data](docs/candle-data.md) · [Short strategies](docs/language-v8.md)
- **Share cash across markets.** Bind independently timed strategies to one portfolio and run them from the CLI. [Portfolio strategies](docs/language-v9.md)
- **Inspect and replay results.** Read the equity curve in `equity.csv` or `equity.parquet`, the buy-and-hold benchmark in `summary.json`, and the order trace in `events.jsonl`. The run bundle preserves the strategy, input data, metadata, and runtime details for replay. [Results and artifacts](docs/results.md)

## Compare tools

- **TradeLang** fits when you want to write, check, and trace a candle-based strategy locally. The strategy-writing lesson changes one line to isolate the effect of position sizing. The CLI saves the inputs and results for both runs.
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
