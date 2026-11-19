# TradeLang

TradeLang is a typed strategy language and local backtester. Write entry, exit, sizing, and risk rules in a `.trade` file, then simulate them on a historical candle dataset you supply.

**[Run your first backtest](quickstart.md)** using three included candles. You’ll see when each order fills and check the final equity yourself.

## Learn TradeLang

1. [Learn backtesting basics](backtesting-basics.md) if candles, signals, and fills are new to you.
2. [Run your first backtest](quickstart.md) to install the CLI and trace a completed trade.
3. [Write and change a strategy](writing-strategies.md) to see how a sizing change affects the same trade.
4. [Try an indicator](example-strategies.md#inspect-six-candles-by-hand) with the six-candle RSI exercise, or [use your own candles](candle-data.md#use-your-own-candles).

## Reference

Look up [language syntax](language-spec.md), [indicators](indicators.md), [execution rules](execution-semantics.md), or [result files](results.md). The [command-line reference](cli.md) covers the local CLI, and the optional [local HTTP API](local-api.md) covers source inspection, strategy drafts, and dataset imports.

| Version | Scope |
| --- | --- |
| Package `0.1.0` | Installed Python distribution and CLI |
| TradeLang strategy language v1 | Source syntax and types |
| Execution semantics `1.1.0` | Simulation rules recorded in run manifests |

[TradeLang on GitHub](https://github.com/alwank/TradeLang)
