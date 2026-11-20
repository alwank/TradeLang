# Write a strategy

Write the rules from the [first backtest](quickstart.md), diagnose a type error, and rerun the trade with a smaller position. Complete the first backtest before you start so you have TradeLang, the three sample candles, and a run to compare. Work from the same checkout.

## Build the strategy

Create `runs/strategy.trade` in your editor and save the following rules.

```text
tradelang 1
strategy "Golden next-open ledger"
market TESTUSDT
timeframe 1d

entry:
  when true
  buy using 100% of equity

exit:
  when close >= 112 price
  sell all

backtest:
  from 2024-01-01 to 2024-01-03
  capital 1000 USDT
  fee 0 bps per side
  slippage 0 bps per side
  execute at next bar open
  calendar 24x7
```

- `market TESTUSDT` and `timeframe 1d` match the sample data.
- The `entry:` rule allows a buy when you hold no position and the exit rule is false. The buy uses 100% of available equity.
- The `exit:` rule queues a sell when a completed candle closes at or above 112 USDT.
- The `backtest:` block sets the dates, starting capital, costs, fill timing, and calendar. Zero fees and slippage let you compare the effect of sizing on its own.

Run the validator. The output should name your strategy and report `Warmup index 0`.

```sh
tradelang validate runs/strategy.trade
```

## Diagnose a unit error

Change the exit condition to `when close >= 112`, save the file, and rerun the validator.

```sh
tradelang validate runs/strategy.trade
```

Look for `E201_UNIT` on the exit condition. `close` has price units, while a bare `112` is a ratio. Restore `112 price` and explain the strategy with the sample candles.

```sh
tradelang explain runs/strategy.trade --data docs/fixtures/core.csv --metadata docs/fixtures/metadata.json
```

The explanation includes the restored threshold and shows the first executable open at `2024-01-02T00:00:00Z`.

## Change the size and rerun

Change `buy using 100% of equity` to `buy using 25% of equity`. Save the file and run it against the same candles.

```sh
tradelang backtest runs/strategy.trade --data docs/fixtures/core.csv --metadata docs/fixtures/metadata.json --out runs/quarter-size
```

Compare the new `summary.json` and `trades.csv` with those in `runs/first`.

| Starting equity committed | Entry price | Exit price | Final equity |
| ---: | ---: | ---: | ---: |
| 100% | 110 USDT | 120 USDT | 1,090.91 USDT |
| 25% | 110 USDT | 120 USDT | 1,022.73 USDT |

The smaller buy acquires one quarter as many units and leaves 750 USDT in cash at entry. The fill prices match because the entry and exit rules stayed the same.

Next, [trace an RSI signal on six candles](example-strategies.md#inspect-six-candles-by-hand).

## Strategy reference and patterns

- <a id="file-structure"></a>[Strategy file structure](language-spec.md#strategy-file-structure) lists the required and optional sections.
- <a id="choose-the-right-units"></a>[Choose the right units](strategy-patterns.md#choose-the-right-units) for price, volume, and ratio comparisons.
- <a id="refer-to-prior-candles"></a>[Refer to prior candles](strategy-patterns.md#refer-to-prior-candles) for lookbacks and crossings.
- <a id="size-the-entry-and-set-protection"></a>[Size the entry and set protection](strategy-patterns.md#size-the-entry-and-set-protection) with fixed budgets, equity fractions, stops, and targets.
- <a id="check-readiness-before-running"></a>[Check readiness before running](strategy-patterns.md#check-readiness-before-running) to find how much history your rules need.
- <a id="ema-confirmation-example"></a>[Run the EMA confirmation example](strategy-patterns.md#ema-confirmation-example) to try a moving average crossover.
