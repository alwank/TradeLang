# Run your first backtest

Install TradeLang, run an included strategy on three synthetic candles, and trace one completed trade. If candles, signals, or fills are new to you, start with [backtesting basics](backtesting-basics.md).

## Install

Install [Git](https://git-scm.com/install/) and [uv](https://docs.astral.sh/uv/getting-started/installation/), then open a terminal. TradeLang uses Python 3.12 and the repository’s dependency lock. `uv` can install Python when needed.

Clone the repository and enter its root directory. If you already have a checkout, open a terminal there and start with `uv sync`.

```sh
git clone https://github.com/alwank/TradeLang.git
cd TradeLang
uv sync --locked --no-dev --no-editable
uv run --no-sync tradelang --version
```

`tradelang --version` prints the installed version. `uv run --no-sync` uses the environment created by `uv sync`. The commands also work in PowerShell.

If the terminal cannot find `uv` after installation, reopen it and run `uv --version`. If a command cannot find `pyproject.toml` or a path under `docs/fixtures/`, return to the repository root before retrying.

## Validate and explain

The [strategy file](fixtures/core.trade) sets the rules and starts with 1,000 USDT. The [candles](fixtures/core.csv) provide prices and volume. The [metadata](fixtures/metadata.json) describes the market, currency, and candle interval.

The strategy buys with all available equity when flat and the exit condition is false. It signals an exit when the completed close is at least `112 price`. The fee and slippage are both zero.

```sh
uv run --no-sync tradelang validate docs/fixtures/core.trade
uv run --no-sync tradelang explain docs/fixtures/core.trade --data docs/fixtures/core.csv --metadata docs/fixtures/metadata.json
```

`validate` checks the strategy and reports `Warmup index 0`, which means it needs no earlier candles before evaluating its rules. `explain` shows how TradeLang reads the rules and uses the data to report the first eligible signal close and execution open. For this fixture, both occur at `2024-01-02T00:00:00Z`. The simulator processes the January 1 close before the January 2 open.

## Simulate and check the fills

```sh
uv run --no-sync tradelang backtest docs/fixtures/core.trade --data docs/fixtures/core.csv --metadata docs/fixtures/metadata.json --out runs/first
```

| UTC candle (by opening date) | Open | Close | Strategy action |
| --- | ---: | ---: | --- |
| 2024-01-01 | 100 | 100 | The close queues a buy. |
| 2024-01-02 | 110 | 112 | The open buys `1000 / 110` units. The close queues a sell. |
| 2024-01-03 | 120 | 120 | The open sells the whole position. |

Open `runs/first` in a file browser or editor and check these outputs.

- `summary.json` contains `final_equity`. Expect approximately **1,090.91 USDT**, a return of **9.09%**.
- `trades.csv` records one completed trade with an `entry_price` of **110 USDT** and an `exit_price` of **120 USDT**.
- `events.jsonl` lists the signals, queued orders, and fills in order.

If TradeLang reports that the output directory must be new or empty, choose another `--out` path, such as `runs/first-again`.

Next, [write and change the strategy](writing-strategies.md) to see how sizing changes the result.
