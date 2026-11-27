# Write a strategy

In this lesson, you’ll write the strategy from the [first backtest](quickstart.md), fix a compiler error, and change the position size. Use the same checkout and three candles so you can compare the two runs.

## Build the strategy

1. **Name the strategy.** Start with the optional `tradelang 1` directive and give the strategy a name. The example uses `market TESTUSDT` and `timeframe 1d` to require a match with its dataset.
2. **Set entry and exit rules.** In `entry:`, `when true` permits a buy whenever the strategy is flat and its exit rule is false. `buy using 100% of equity` commits the available equity. In `exit:`, `when close >= 112 price` queues a sale of the whole position when the completed close reaches 112 USDT.
3. **Set the backtest assumptions.** Choose the dates covered by the three candles and start with 1,000 USDT. Set fees and slippage to zero so you can check the result by hand. The last two lines select the next-open execution rule and the 24/7 calendar.

Save the complete file as `strategy.trade` in the checkout root.

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

## Diagnose a unit error

Change `when close >= 112 price` to `when close >= 112`, save the file, and validate it.

```sh
tradelang validate strategy.trade
```

Look for `E201_UNIT` on the exit condition. A bare `112` is a ratio, while `close` is a price. Restore `112 price` and run the validation command again. Then explain the strategy with the example candles to check the normalized rules and first executable open.

```sh
tradelang explain strategy.trade --data docs/fixtures/core.csv --metadata docs/fixtures/metadata.json
```

## Change the size and rerun

Predict which values will change if the strategy commits one quarter of its equity. Change `buy using 100% of equity` to `buy using 25% of equity`, then run the same candles into a fresh folder.

```sh
tradelang backtest strategy.trade --data docs/fixtures/core.csv --metadata docs/fixtures/metadata.json --out runs/quarter-size
```

| Equity used | Entry price | Exit price | Final equity |
| ---: | ---: | ---: | ---: |
| 100% | 110 USDT | 120 USDT | 1,090.91 USDT |
| 25% | 110 USDT | 120 USDT | 1,022.73 USDT |

Check the new `trades.csv` and `summary.json` in `runs/quarter-size`. Both runs have the same entry and exit rules, so the fill prices match. The second run buys one quarter as many units and keeps 750 USDT in cash at entry.

Next, [try RSI on six candles](example-strategies.md#inspect-six-candles-by-hand) or use the sections below as a reference while writing your own strategy.

## File structure

| In order | Purpose |
| --- | --- |
| `tradelang 1` | Optional version directive. Version 1 is the default. Existing strategies can still use `dsl 1`. |
| `strategy "…"` | Required display name in double quotes. |
| `market` | Optional symbol constraint. Omit it to use the selected dataset's symbol. |
| `timeframe` | Optional candle duration constraint, such as `15m`, `1h`, or `1d`. Omit it to use the selected dataset's duration. |
| `let` | Optional immutable declarations. A declaration can reference earlier declarations. |
| `entry:` | Required Boolean `when` condition followed by `buy using`. |
| `exit:` | Required Boolean `when` condition followed by `sell all`. |
| `risk:` | Optional. Include at least one of `stop loss`, `take profit`, or `max open positions 1`, in that order. |
| `backtest:` | Required inclusive UTC date range, capital, fee, slippage, execution mode, and calendar, in the order shown above. |

Indent for readability. The parser uses keywords and punctuation to identify sections and treats newlines as whitespace. Use `#` for a comment through the end of a line. Keywords and field names are lowercase, and indicator names are uppercase.

## Choose the right units

`open`, `high`, `low`, and `close` are price series. `volume` is a base-quantity series. A literal such as `2%` is a ratio with value `0.02`. Add an explicit unit when comparing a series with a nonzero threshold in that unit.

| Expression | Meaning |
| --- | --- |
| `close >= 100 price` | The close is at least 100 quote-currency units per base unit. |
| `volume > 50 volume` | More than 50 base units traded on this candle. |
| `close > SMA(20) * (1 + 2%)` | The close is over 2% above its moving average. |
| `ROC(close, 12) > 2%` | The close rose by over 2% over 12 bars. |
| `RSI(14) crosses above 30` | RSI crossed above 30 points on its 0–100 scale. |
| `(close - EMA(20)) crosses above 0` | The price spread crossed above zero. Comparisons and crossings allow a ratio-zero literal to match a numeric unit. |

See the [units and arithmetic rules](language-spec.md#types-units-and-ast) for derived units, count literals, and exponentiation.

## Refer to prior candles

`close[1]` is the previous observed close. `HIGHEST(high, 20)` includes the current completed high, so write `HIGHEST(high, 20)[1]` for the highest high over the 20 observed candles ending one bar earlier. Select a record field before applying a lookback, as in `MACD(12, 26, 9).line[1]`.

`a crosses above b` requires `a <= b` on the previous bar and `a > b` on the current bar. A crossover stays false on later bars where both values are already above the threshold. Use `a > b` for a level condition that stays true as long as the relationship holds.

## Size the entry and set protection

- `buy using 25% of equity` uses one quarter of available equity at the fill. A fraction must be in `(0, 1]`.
- `buy using 250 USDT` allocates a fixed cash budget. Use the capital currency. Both sizing forms include the entry fee in the budget.
- `stop loss 3%` sets a stop 3% below the actual entry fill. `stop loss 2 * ATR(8)` uses a price distance sampled from the signal candle. `take profit 8%` sets a trigger 8% above the actual fill. Each level stays fixed for the life of the position.

The `equity` expression can also appear inside sizing arithmetic. For example, `buy using (0.25 * equity) USDT` computes a fixed-money budget at fill time. Pure market inputs come from the completed signal bar. The [execution rules](execution-semantics.md#frozen-protection) explain protection and rejected entries.

With DSL 4, use `buy risking 1% of equity` and a `stop loss` to size the entry by its modeled loss at a stop touch. Add `max allocation 25% of equity` to cap the fee-inclusive debit. [Stop-based sizing](language-v4.md#size-a-long-by-stop-loss)

With DSL 5, list named market and time exits in the order they should be tested. Add a trailing distance to raise the initial stop from completed closes. [Ordered exits and trailing stops](language-v5.md)

With DSL 6, use `sell 25% of position` or `sell 3 units` in an exit and an optional `scale` rule to add to the same long. [Position sizing and worked ledger](language-v6.md)

## Check readiness before running

### EMA confirmation example

This example enters when a fast moving average crosses above a slow one and the close is above the slow average. It exits after the reverse crossover or when the position touches a protective level.

```text
tradelang 1
strategy "EMA confirmation"
market BTCUSDT
timeframe 1h

let fast = EMA(4)
let slow = EMA(12)
let trend_up = fast crosses above slow
let trend_down = fast crosses below slow

entry:
  when trend_up and close > slow
  buy using 25% of equity

exit:
  when trend_down
  sell all

risk:
  stop loss 2 * ATR(8)
  take profit 8%
  max open positions 1

backtest:
  from 2022-01-01 to 2022-01-07
  capital 1000 USDT
  fee 10 bps per side
  slippage 5 bps per side
  execute at next bar open
  calendar 24x7
```

Save it as `ema-confirmation.trade` and run `tradelang explain ema-confirmation.trade` after completing the [installation](quickstart.md#install). Explanation expands defaults such as `EMA(4)` to `EMA(close, 4)` and shows the structural warmup index. The [example generator](example-strategies.md#run-the-full-examples) produces hourly synthetic `BTCUSDT` data covering the requested dates. After generating it, run the backtest.

```sh
tradelang backtest ema-confirmation.trade --data runs/example-data/example.csv --metadata runs/example-data/metadata.json --out runs/ema-confirmation
```

In the EMA example, `EMA(12)` first becomes structurally ready at zero-based row 11. The crossings need one prior sample, so the full strategy has warmup index 12. Every `let` counts toward readiness, including unused declarations. Supply pre-window history if you want indicators to be ready on the first in-window candle.

Runtime arithmetic can still make a structurally ready value unavailable. Unavailable inputs propagate through comparisons and Boolean operators, including `not`. Only a valid true condition can queue an order. Use [`explain` with the dataset](cli.md#explain) to check resolved timestamps, then inspect run [diagnostics and events](results.md#artifact-files) to investigate rejected or missing orders.
