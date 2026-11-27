# TradeLang strategy language v2

Use DSL 2 to tune inputs without changing the source, name an indicator record, and refer to prior Boolean conditions. Start the source with `tradelang 2`. Strategies without a directive use DSL 1. The [v1 language reference](language-spec.md) applies except for the changes on this page. [Grammar overlay](grammar-v2.lark) · [Typed strategy JSON Schema](schemas/strategy-v2.schema.json)

## Run a parameterized MACD strategy

The [complete example](fixtures/macd-v2.trade) binds the moving average convergence divergence (MACD) record once. It buys on a transition from false to true and exits on a transition from true to false.

```text
param fast: count = 2 range [1 count, 5 count]
param slow: count = 3
param signal_period: count = 2
let macd = MACD(fast, slow, signal_period)
let uptrend = macd.line > macd.signal
entry:
  when uptrend and not uptrend[1]
  buy using 10% of equity
```

From a checkout, run the example with a different fast period. The fixture covers nine daily candles. The strategy buys at the January 9 open at **21 USDT**.

```sh
tradelang backtest docs/fixtures/macd-v2.trade \
  --data docs/fixtures/macd-v2.csv --metadata docs/fixtures/metadata.json \
  --param fast=1 --out runs/macd-fast-1
```

If the fast period equals or exceeds the slow period, validation rejects the call. For this example, choose `fast=1` or `fast=2` when `slow=3`.

## Parameters and static arguments

Declare parameters after any market and timeframe declarations and before the first `let`. Use an independent constant for the default and each optional bound. The bounds are inclusive. Choose a unique name that follows the binding-name rules. The compiler resolves the effective value before it checks indicator periods, readiness, and the run window.

| Type | Example declaration | Example override |
| --- | --- | --- |
| Count | `param period: count = 20` | `--param period=14` |
| Ratio | `param allocation: ratio = 10%` | `--param allocation=0.08` |
| Price | `param distance: price = 5 price` | `--param distance=4.5` |
| Boolean | `param enabled: bool = true` | `--param enabled=false` |

Counts are integers from 0 through 2⁵³ − 1. An indicator period requires a positive integer and applies the indicator's bounds and argument relationships. A period argument accepts a compile-time count or ratio expression, including a parameter reference or a constant `let`. Write a literal for band multipliers, numeric-literal roles, and price-literal roles. Boolean parameters have no range. Ratio overrides use decimal fractions, and price overrides use the declared quote-per-base units.

Repeat `--param NAME=VALUE` on the CLI for distinct parameters. Unknown names, duplicate CLI overrides, values outside the bounds, and mismatched types produce `E208_PARAMETER`. An invalid resolved period produces `E202_PERIOD`. [HTTP overrides](local-api.md#validate-or-explain-source) · [Browser overrides](browser.md#override-strategy-parameters) · [Replay](results.md#compare-and-replay-runs)

## Record fields, history, and scale

A `let` can hold an immutable indicator record or alias another record. Select a field before applying arithmetic or a lookback. Fields can have different units, scales, and readiness. For instance, the MACD line becomes structurally ready before its smoothed signal. The typed strategy gives each record's `field_readiness` as zero-based observed-row indices.

Use `[k]` on numeric and Boolean market series. `[1]` samples the previous observed candle, including across an allowed gap. A missing prior Boolean value stays unavailable. Scalar values and expressions that depend on account state have no market lookback.

When a comparison or crossing pairs a point-scale value with an explicit percentage, validation reports `W_POINT_SCALE` at the percentage operand. For example, `RSI(14) < 30%` compares against 0.3 points. Write `RSI(14) < 30` for 30 points or `RSI(14) / 100 < 30%` for the equivalent fractional comparison. Scale follows grouping, aliases, selectors, and offsets. Addition and subtraction retain matching scale or the scale of a scaled operand combined with an unscaled scalar. Division by 100 converts points to a fraction. Other multiplication, division, and powers clear scale metadata.

## Unavailable expressions

| Form | Result |
| --- | --- |
| `available(value)` | True if the sample has an available numeric or Boolean value. False otherwise. |
| `coalesce(value, fallback)` | The first available value in argument order. If both are unavailable, the result is unavailable. |
| `choose(condition, when_true, when_false)` | The branch selected by a Boolean sample. If the condition is unavailable, the result is unavailable. |

Branches must have matching kinds and units. Select a field before using these expressions on a record. Scalars broadcast over series. For example, `coalesce(close[1], close)` supplies the current close when the previous close is unavailable. The evaluator can compute both branches and report arithmetic diagnostics for that work. A fault in an unselected branch leaves the selected value intact.

## Warmup and input requirements

DSL 2 uses execution semantics 2.0.0. Entry, exit, sizing, and protection determine structural readiness through the expressions and bindings they use. An unused declaration passes normal compilation and can emit `W_UNUSED_LET`. It contributes no run warmup, workload, or auxiliary input requirement. The typed strategy's `requires_profile` flag identifies a reachable Volume Profile call.

`available` has structural readiness at the first row. `coalesce` uses the earlier readiness of its arguments. `choose` waits for its predicate and at least one branch's structural readiness. Actual values still depend on observed data. Explain reports the overall warmup, its driving rule, and the first eligible close and next executable open when you supply candles.
