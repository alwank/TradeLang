# Apply common strategy patterns

Use these patterns to write price and volume conditions, refer to earlier candles, and add position sizing and protection. Before you begin, complete [Write a strategy](writing-strategies.md). Run the examples from the repository root.

## Choose the right units

`open`, `high`, `low`, and `close` are price series. `volume` is a base-quantity series. A literal such as `2%` is a ratio with value `0.02`. Use the matching unit for a nonzero price or volume threshold. The examples show the unit or scale each comparison uses.

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

Run [`explain`](cli.md#explain) to find the structural warmup index, the first zero-based row with enough history for all strategy expressions. Every `let` declaration contributes to that index, including unused declarations. With a dataset, the explanation also shows the first eligible signal close and the first executable open. Add pre-window history if you want the rules to be ready on the first candle in your date range.

Runtime arithmetic can still make a structurally ready value unavailable. If you expected a trade, inspect [diagnostics and events](inspect-backtest-results.md#trace-the-quickstart-trade) for rejected or skipped decisions.

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

Save the example as `runs/ema-confirmation.trade`. Explain it before supplying data.

```sh
tradelang explain runs/ema-confirmation.trade
```

Expect `EMA(close, 4)` and `EMA(close, 12)` in the explanation and `Warmup index 12`. The slow average is first ready at row 11. The crossover also needs the previous row.

[Generate the example dataset](example-strategies.md#run-the-full-examples), then explain and run the strategy with the generated data.

```sh
tradelang explain runs/ema-confirmation.trade --data runs/example-data/example.csv --metadata runs/example-data/metadata.json
tradelang backtest runs/ema-confirmation.trade --data runs/example-data/example.csv --metadata runs/example-data/metadata.json --out runs/ema-confirmation
```

The first eligible close and executable open are both `2022-01-01T13:00:00Z`. Open `runs/ema-confirmation/trades.csv` to check whether each completed trade exited on a signal, stop, or target.

### Check MACD warmup

Save a copy of the [quickstart strategy](fixtures/core.trade) as `runs/macd-warmup.trade`. Insert this declaration immediately before `entry:`.

```text
let prior = MACD(12, 26, 9).line[1]
```

Run [source-only explanation](cli.md#explain) to check structural readiness.

```sh
tradelang explain runs/macd-warmup.trade --json
```

`result.warmup_index` is `26`. The line is first ready at zero-based row 25 and the one-row lookback adds one. Replace `.line[1]` with `.signal[1]` or `.histogram[1]` and rerun the command. Both fields are first ready at row 33, so the index becomes `34`. Every declaration contributes to strategy warmup, including this unused one.
