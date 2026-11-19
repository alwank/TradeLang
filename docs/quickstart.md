# Run your first backtest

Use the included three-candle fixture to check your installation and see exactly when each trade fills. Run the commands from the root of a local TradeLang checkout.

## Install

Install [uv](https://docs.astral.sh/uv/getting-started/installation/). The project uses Python 3.12 and the checked-in dependency lock. `uv` can install the interpreter when needed.

```sh
uv sync --locked --no-dev --no-editable
uv run --no-sync tradelang --version
```

`uv run --no-sync` uses the environment created by the first command. The same commands work in PowerShell.

If you edit the TradeLang source in this checkout, refresh the installed copy with `uv sync --locked --no-dev --no-editable --reinstall-package tradelang`.

## Validate and explain

The fixture strategy starts with 1,000 USDT. It buys with all available equity when flat and the exit condition is false. It signals an exit when the completed close is at least `112 price`. The fee and slippage are both zero.

```sh
uv run --no-sync tradelang validate docs/fixtures/core.trade
uv run --no-sync tradelang explain docs/fixtures/core.trade --data docs/fixtures/core.csv --metadata docs/fixtures/metadata.json
```

Validation reports `Warmup index 0`. Explanation with data resolves the first eligible close and the first executable open. Each candle is timestamped at its open. For daily candles, the January 1 candle closes at the same UTC instant that the January 2 candle opens. The simulator processes the January 1 close first.

## Simulate and check the fills

```sh
uv run --no-sync tradelang backtest docs/fixtures/core.trade --data docs/fixtures/core.csv --metadata docs/fixtures/metadata.json --out runs/first
```

| UTC candle (by opening date) | Open | Close | Strategy action |
| --- | ---: | ---: | --- |
| 2024-01-01 | 100 | 100 | The close queues a buy. |
| 2024-01-02 | 110 | 112 | The open buys `1000 / 110` units. The close queues a sell. |
| 2024-01-03 | 120 | 120 | The open sells the whole position. |

Expected final equity is approximately **1,090.91 USDT**, a return of **9.09%**. Check `final_equity` in `runs/first/summary.json` and the entry and exit prices in `runs/first/trades.csv`. `events.jsonl` shows the signal-to-fill sequence. Use a new or empty `--out` directory for each run.

Fixture files are available as [strategy source](fixtures/core.trade), [candles](fixtures/core.csv), and [metadata](fixtures/metadata.json).

Next, [write a strategy](writing-strategies.md), [try the examples](example-strategies.md), or [prepare your own candles](candle-data.md).
