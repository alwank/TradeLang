# TradeLang

TradeLang is a typed strategy language and local backtester. Write entry, exit, sizing, and risk rules in a `.trade` file, then simulate them on a historical candle dataset you supply.

- [Run your first backtest](quickstart.md) on a three-candle fixture with known fills and ending equity.
- [Write a strategy](writing-strategies.md) using named conditions, typed expressions, and frozen protection.
- [Try the examples](example-strategies.md) for RSI recovery, an EMA crossover, a previous-high breakout, and arithmetic sizing.
- [Look up the language](language-spec.md), [indicators](indicators.md), and [execution order](execution-semantics.md) when you need an exact rule.

The simulator models one long spot position at a time on a continuous UTC calendar. It evaluates signals at candle close and ordinarily fills them at the next observed open. It models per-side fees, adverse slippage, stop-loss and take-profit triggers, and a warmup-aligned buy-and-hold benchmark. Backtests run locally through the [CLI](cli.md). The optional [loopback API](local-api.md) exposes source inspection, strategy drafts, and dataset imports.

| Version | Scope |
| --- | --- |
| Package `0.1.0` | Installed Python distribution and CLI |
| TradeLang strategy language v1 | Source syntax and types |
| Execution semantics `1.1.0` | Simulation rules recorded in run manifests |
