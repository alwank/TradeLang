# TradeLang strategy language v3

Use `tradelang 3` at the start of a strategy to read one named higher-timeframe feed. The strategy still fills orders and marks equity on the primary candles. The [DSL 2 reference](language-v2.md) applies to the other constructs. [Grammar overlay](grammar-v3.lark) · [Typed strategy schema](schemas/strategy-v3.schema.json)

## Read a four-hour trend from an hourly strategy

Declare the feed after `market` and `timeframe` and before parameters and bindings. In this example, `on` evaluates the exponential moving average on four-hour candles. `align` makes that result available to rules on the hourly clock.

```text
feed trend timeframe 4h max_age 8h
let average = on(trend, EMA(2))
let regime = align(average)
```

From a TradeLang checkout, run the [complete example](fixtures/feeds/trend.trade).

```sh
tradelang backtest docs/fixtures/feeds/trend.trade \
  --data docs/fixtures/feeds/primary.csv \
  --metadata docs/fixtures/feeds/primary.json \
  --feed trend=docs/fixtures/feeds/trend.csv \
  --feed-metadata trend=docs/fixtures/feeds/trend.json \
  --out runs/four-hour-trend
```

At 08:00 UTC on January 1, 2024, the second four-hour candle closes and the average becomes 105. The hourly candle that closes at that time queues the entry. The next hourly open fills at 100 USDT. Inspect the signal at primary bar index 7 and its fill at index 8.

## Choose the evaluation clock

The secondary duration must be a larger, exact multiple of the primary duration. Imported candles must match the primary symbol, quote currency, calendar, timestamp convention, price basis, and volume unit. The declaration sets the expected duration and a positive maximum age. Both use ordinary timeframe syntax and are capped at seven days.

Inside `on(trend, expression)`, built-in candle fields and indicator inputs use the named clock. An immutable `let` can hold a series or record on that clock. A series from a different clock must be aligned before combining with primary expressions. Select a record field before alignment. Volume Profile uses its own lower-timeframe pairing on the primary clock.

An offset before alignment counts observed secondary rows. For example, `align(average[1])` reads the previous four-hour result. `align(average)[1]` reads the value available at the previous observed hourly row. Gaps affect which observations exist, and a secondary indicator uses its own candle history.

## Align completed candles

At a primary close, `align` selects the latest secondary candle whose close is at or before that time. An equal close timestamp qualifies. A partial or future candle contributes zero samples. Alignment uses any supplied pre-window history. Primary structural warmup follows primary expressions. Secondary readiness determines whether an aligned value is available on each row.

| Condition | Inspection reason |
| --- | --- |
| The first secondary close is still in the future. | `feed_no_completed_candle` |
| The selected candle is at least `max_age` old. | `feed_stale` |
| The next expected secondary close is missing and the age is below `max_age`. | `feed_gap` |
| The selected candle precedes the expression's native readiness. | `feed_insufficient_history` |

These conditions yield an unavailable aligned value. A condition that requires the value remains unavailable. Use `available`, `coalesce`, or `choose` to express a policy for that case. A feed that no execution rule reaches requires no dataset.

DSL 3 selects execution semantics 3.0.0. A run with a named feed records policy `completed_close_v1`, the source and normalized candle hashes, the feed files, and the replay settings in artifact schema 4. [Replay configured runs](results.md#replay-configured-runs)
