# Write a strategy

A strategy describes decisions for one market, one candle duration, and one quote currency. This example enters when a fast moving average crosses above a slow one and the close is above the slow average. It exits after the reverse crossover or when the position touches a protective level.

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

Save it as `strategy.trade` and run `uv run --no-sync tradelang explain strategy.trade` after completing the [installation](quickstart.md#install). Explanation expands defaults such as `EMA(4)` to `EMA(close, 4)` and shows the structural warmup index. The [example generator](example-strategies.md#run-the-full-examples) produces hourly synthetic `BTCUSDT` data covering the requested dates. After generating it, run the backtest.

```sh
uv run --no-sync tradelang backtest strategy.trade --data runs/example-data/example.csv --metadata runs/example-data/metadata.json --out runs/ema-confirmation
```

## File structure

| In order | Purpose |
| --- | --- |
| `tradelang 1` | Optional version directive. Version 1 is the default. Existing strategies can still use `dsl 1`. |
| `strategy "…"` | Required display name in double quotes. |
| `market` and `timeframe` | Required symbol and fixed duration such as `15m`, `1h`, or `1d`. |
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

## Check readiness before running

In the example, `EMA(12)` first becomes structurally ready at zero-based row 11. The crossings need one prior sample, so the full strategy has warmup index 12. Every `let` counts toward readiness, including unused declarations. Supply pre-window history if you want indicators to be ready on the first in-window candle.

Runtime arithmetic can still make a structurally ready value unavailable. Unavailable inputs propagate through comparisons and Boolean operators, including `not`. Only a valid true condition can queue an order. Use [`explain` with the dataset](cli.md#explain) to check resolved timestamps, then inspect run [diagnostics and events](results.md#artifact-files) to investigate rejected or missing orders.
