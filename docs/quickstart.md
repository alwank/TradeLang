# Run your first backtest

Install TradeLang, run an included strategy on three synthetic candles, and trace one completed trade. If candles, signals, or fills are new to you, start with [backtesting basics](backtesting-basics.md).

## Install

Install [Git](https://git-scm.com/install/) and [uv](https://docs.astral.sh/uv/getting-started/installation/), then open a terminal. TradeLang uses Python 3.12, which `uv` can install when needed.

Clone the repository and enter its root directory. If you already have a checkout, run the install command from there.

```sh
git clone https://github.com/alwank/TradeLang.git
cd TradeLang
uv tool install --python 3.12 .
tradelang --version
```

`uv tool install` makes `tradelang` available in new terminals and from any directory. If your shell cannot find `tradelang`, run `uv tool update-shell` and reopen the terminal. The commands also work in PowerShell.

After pulling updates, repeat your install command with `--reinstall` to refresh the CLI. Run the examples below from the repository root so their relative paths resolve.

## Validate and explain

The [strategy file](fixtures/core.trade) sets the rules and starts with 1,000 USDT. The [candles](fixtures/core.csv) provide prices and volume. The [metadata](fixtures/metadata.json) describes the market, currency, and candle interval.

The strategy buys with all available equity when flat and the exit condition is false. It signals an exit when the completed close is at least `112 price`. The fee and slippage are both zero.

```sh
tradelang validate docs/fixtures/core.trade
tradelang explain docs/fixtures/core.trade --data docs/fixtures/core.csv --metadata docs/fixtures/metadata.json
```

`validate` checks the strategy and reports `Warmup index 0`, which means it needs no earlier candles before evaluating its rules. `explain` shows how TradeLang reads the rules and uses the data to report the first eligible signal close and execution open. For this fixture, both occur at `2024-01-02T00:00:00Z`. The simulator processes the January 1 close before the January 2 open.

## Simulate and check the fills

```sh
tradelang backtest docs/fixtures/core.trade --data docs/fixtures/core.csv --metadata docs/fixtures/metadata.json --out runs/first
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
