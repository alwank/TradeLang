# Run your first backtest

Run a bundled strategy on three sample candles. You’ll see why the strategy buys at 110 USDT, sells at 120 USDT, and finishes with about 1,090.91 USDT. If you’re new to candles or simulated orders, see [Backtesting basics](backtesting-basics.md).

Before you start, install [Git](https://git-scm.com/install/) and [uv](https://docs.astral.sh/uv/getting-started/installation/). The commands work in a POSIX shell or PowerShell.

## Install

Clone the repository and enter its root directory. If you already have a checkout, start there and skip the first two commands.

```sh
git clone https://github.com/alwank/TradeLang.git
cd TradeLang
uv tool install --python 3.12 .
tradelang --version
```

`uv` can fetch Python 3.12 during installation. The last command prints the installed TradeLang version. If your shell cannot find `tradelang`, run `uv tool update-shell` and open a new terminal in the checkout. After updating the checkout, add `--reinstall` to the install command to refresh the CLI.

Run the remaining commands from the repository root so the example paths resolve.

## Validate and explain

Validate the [example strategy](fixtures/core.trade). It starts with 1,000 USDT, buys when it holds no position and the exit rule is false, and signals an exit at a completed close of at least `112 price`. Fees and slippage are zero so you can check the result by hand.

```sh
tradelang validate docs/fixtures/core.trade
```

Look for `Valid strategy: Golden next-open ledger. Warmup index 0.` A warmup index of zero means the rules have enough history on the first candle.

Ask TradeLang to explain the strategy using the [sample candles](fixtures/core.csv) and their [metadata](fixtures/metadata.json). The metadata describes the market, quote currency, and candle interval.

```sh
tradelang explain docs/fixtures/core.trade --data docs/fixtures/core.csv --metadata docs/fixtures/metadata.json
```

Look for `First eligible close 2024-01-02T00:00:00Z, first executable open 2024-01-02T00:00:00Z`. The January 1 candle closes at the same instant the January 2 candle opens. TradeLang processes the close decision first.

## Simulate and check the fills

Run the backtest and write its files to `runs/first`.

```sh
tradelang backtest docs/fixtures/core.trade --data docs/fixtures/core.csv --metadata docs/fixtures/metadata.json --out runs/first
```

The CLI prints `Final equity 1090.9091 USDT` and the output path. If that directory already contains a run, see [Choose a fresh output directory](troubleshoot-backtests.md#choose-a-fresh-output-directory).

The trade follows the three candles in order. Each row is labeled by its UTC opening date.

| Candle opens | Open | Close | What TradeLang does |
| --- | ---: | ---: | --- |
| January 1 | 100 | 100 | Queues a buy at the close. |
| January 2 | 110 | 112 | Buys `1000 / 110` units at the open and queues a sell at the close. |
| January 3 | 120 | 120 | Sells the whole position at the open. |

Open `runs/first` and check the output files.

- In `summary.json`, `final_equity` is about **1,090.91 USDT**.
- In `trades.csv`, the one completed trade has an `entry_price` of **110 USDT** and an `exit_price` of **120 USDT**.
- In `events.jsonl`, each signal comes before its queued order and fill. [Trace the quickstart trade](inspect-backtest-results.md#trace-the-quickstart-trade) to see how the records link together.

Next, [write a strategy](writing-strategies.md) and see what happens when you commit a quarter of the starting equity. If your strategy is ready, [use your own candle data](use-your-own-candles.md).
