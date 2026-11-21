# TradeLang

Write trading rules in a `.trade` file and test them on historical candles. TradeLang runs backtests locally and records which rules triggered, when orders filled, and how cash and holdings changed.

[**Run your first backtest**](quickstart.md) to trace a complete trade on three sample candles. The tutorial includes the strategy, data, and expected fills.

## Learn TradeLang

- [Write a strategy](writing-strategies.md) and see how changing the position size affects the same trade.
- [Use your own candle data](use-your-own-candles.md) to check a CSV or Parquet dataset and run a strategy on it.
- [Learn backtesting basics](backtesting-basics.md) if candles, fills, or equity are new to you.

TradeLang models one long spot position at a time on a 24/7 UTC candle grid. Entry and exit rules use completed candles. The resulting orders can fill at the next observed open. See [execution semantics](execution-semantics.md) for protective orders and the simulator's other fill rules.

## Reference

Look up [strategy syntax and types](language-spec.md), [indicators](indicators.md), [candle data](candle-data.md), [CLI commands](cli.md), [backtest artifacts](results.md), or the [optional local HTTP API](local-api.md).

The package, strategy language, and simulator are versioned independently. The language reference covers version 1, and run manifests record the [execution semantics version](execution-semantics.md). Use `tradelang --version` to check your installed package.

[TradeLang on GitHub](https://github.com/alwank/TradeLang)
