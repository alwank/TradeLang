# TradeLang strategy language v5

Declare `tradelang 5` to use named exit rules, a trailing stop, or signal order expiry. DSL 5 also supports the sizing, parameters, and data feeds from earlier language versions. It selects execution semantics 5.0.0. [Grammar overlay](grammar-v5.lark) · [Typed strategy schema](schemas/strategy-v5.schema.json)

## Choose the first exit that matches

```text
exit:
  rule profit when close >= 120 price sell all
  rule timeout after 2 bars sell all
```

Use a unique name for each of up to 16 rules. TradeLang checks rules in source order. An unavailable condition gives the next rule a chance. The first true condition queues a sale for the next observed open and skips the rules below it. The order and fill record that rule's name. While flat, a true market exit condition can block an entry, following the single-rule behavior. A time rule is false while flat.

`after 2 bars` counts completed primary candles held, starting at one at the close of the entry candle. Missing candles contribute zero to the count. You can use a whole number or a static count expression, such as a count parameter. The effective count must be from 1 through 1,000,000. [Parameters and static arguments](language-v2.md#parameters-and-static-arguments)

When you use ordered rules, each market predicate has its own readiness. A slower exit predicate can be unavailable while entry and other exit rules already run. For one close-based exit, you can still use `when CONDITION sell all` and its existing readiness semantics.

## Raise a trailing stop

```text
risk:
  stop loss 10%
  trailing stop 5 price
  take profit 50%
```

Supply an initial `stop loss` before the trailing stop. The initial level anchors to the entry fill. If a position survives a candle, TradeLang subtracts the trailing distance from that candle's completed close. You can use a price distance, such as `2 * ATR(14)`, or a ratio of the close. TradeLang schedules an update when the result is strictly between the active stop and the completed close. An unavailable distance or a lower candidate keeps the active stop.

The updated stop takes effect at the next observed open before open protection checks. During the candle that produced the update, the old stop controls intrabar protection. A close at the end of the window has no following open, so it schedules zero updates.

## Expire a queued signal order

```text
execute at next bar open expire after 1d
```

The duration uses minute, hour, or day syntax and can be at most seven days. A queued buy or signal sell expires if the candidate open is at least that duration after its signal close. A contiguous next open has age zero. Protection at the open can close a position and cancel a queued sell before the age check. Omit `expire after` to keep the next-observed-open policy. [Order priority](execution-semantics.md#exit-and-protection-priority-in-semantics-500)

## Run and inspect the example

Backtest the [strategy](fixtures/ordered-exits/ordered.trade) on the [four sample candles](fixtures/ordered-exits/ordered.csv).

```sh
tradelang backtest docs/fixtures/ordered-exits/ordered.trade \
  --data docs/fixtures/ordered-exits/ordered.csv \
  --metadata docs/fixtures/metadata.json \
  --out runs/ordered-exits
```

The entry fills at 100 USDT. Its candle closes at 115, raising the stop from 90 to 110 at the next open. The following close reaches 125 on the second completed holding candle. Both the profit condition and the timer qualify. The profit rule comes first and its sale fills at 122 on the last candle. Final equity is 1,110 USDT.

To see the timer win sooner, repeat the command with `--param hold_bars=1` and a fresh output path. The timer queues at the entry candle's close and fills at 114 on the next open. In the browser, inspect the signal candle's **Ordered exit rules** and the next candle's **Trailing stop changes**.
