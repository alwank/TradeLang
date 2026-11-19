<a id="language-specification-dsl-1"></a>

# TradeLang strategy language v1

This reference describes the syntax and types accepted by the TradeLang compiler. See the [Lark grammar](grammar-v1.lark), [typed strategy JSON Schema](schemas/strategy.schema.json), and [execution semantics](execution-semantics.md). The [typed strategy example](schemas/strategy.example.json) illustrates the structure for the [quickstart fixture](fixtures/core.trade). Semantic validation applies additional constraints beyond JSON Schema.

## Source and lexical contract

Source is UTF-8 and can begin with a byte-order mark. Both LF and CRLF are accepted. TradeLang hashes the original bytes. Section keywords, builtins, and identifiers are lowercase. Indicator names are uppercase. Strategy names are JSON double-quoted strings that decode to 1–120 printable characters.

Let names start with a lowercase letter or underscore and may continue with lowercase letters, digits, or underscores. Choose names that do not collide with language keywords, candle fields, indicator output fields, the `equity` builtin, or unit suffixes. Market symbols are opaque uppercase identifiers. Quote currency comes from `capital` and must match the dataset and any fixed-money sizing.

Whitespace, including indentation and newlines, separates tokens. A `#` outside a quoted string starts a comment through the end of the line. Expressions may span lines.

Use the optional `tradelang 1` directive before the `strategy` header to declare version 1. This is also the default when the directive is omitted. The legacy spelling `dsl 1` is accepted as an alias. Typed strategy JSON and run manifests record the language version as `dsl_version: 1`.

Sections and directives follow the order in [Write a strategy](writing-strategies.md#file-structure). Entry and exit each require one Boolean condition and one order. An omitted risk block leaves the position without protective levels. The maximum is always one position.

## Expression grammar and precedence

A numeric literal starts with a decimal digit and may have a fractional part and a base-10 exponent. Use `0.5`, `1e3`, or a signed expression such as `-0.5`. The decimal point requires digits on both sides. Leading zeros are disallowed except in the single digit `0`, the fractional part, or the exponent.

| Binding, strongest first | Rule |
| --- | --- |
| Calls, grouping, `.field`, `[k]` | Postfix selectors and offsets bind in written order. |
| `**` | Right associative, with a unary expression allowed on the right. |
| Unary `+`, `-` | `-2 ** 2` gives `-4`. `2 ** -2` gives `0.25`. |
| `*`, `/` | Left associative. |
| `+`, `-` | Left associative. |
| `<`, `<=`, `>`, `>=`, `==`, `!=`, `is above`, `is below`, `crosses above`, `crosses below` | One predicate per comparison. Chained comparisons are invalid. |
| `not` | Boolean negation. |
| `and` | Left associative. |
| `or` | Left associative. |

`2 ** 3 ** 2` gives `512` and `(2 ** 3) ** 2` gives `64`. `is above` normalizes to `>`, and `is below` to `<`. Use parentheses to group arithmetic or Boolean expressions.

## Types, units and AST

Each expression has a scalar or series shape and a numeric, Boolean, or record kind. A scalar broadcasts over a series. Constants are scalar. Candle fields and indicator outputs are series. Record fields are numeric series.

| Unit | Literal examples | Dimension `(quote, base)` |
| --- | --- | --- |
| Ratio | `0.02`, `2%` | `(0, 0)` |
| Price | `100 price` | `(1, -1)` |
| Volume | `50 volume` | `(0, 1)` |
| Money | `500 money` | `(1, 0)` |
| Count | `2 count` | Nominal dimension |

`open`, `high`, `low`, and `close` have price units. `volume` has volume units. Percentage literals represent ratios divided by 100. RSI uses points on a 0–100 scale. For example, `RSI(14) > 30` tests 30 points and `RSI(14) > 30%` tests 0.3 points. A direct percent threshold against an RSI call emits `W_RSI_SCALE`. Basis points apply to cost directives and are divided by 10,000.

- Addition and subtraction require equal numeric dimensions and preserve that dimension. Use `close * (1 + 2%)` to apply a relative change.
- Multiplication adds dimension exponents. Division subtracts them. Price times volume yields money. Price divided by price yields a ratio. Each resulting exponent must stay within `[-8, 8]`. Count can be multiplied by or divided by a ratio, and count divided by count yields a ratio.
- A power needs a constant ratio exponent. Ratio bases allow real exponents in `[-16, 16]`. Other dimensions require integral exponents in `[-8, 8]`, subject to the resulting dimension limits. Count bases are invalid. Complex results, zero to a negative power, and `0 ** 0` are invalid.
- Numeric comparisons and crossings require compatible dimensions. Use `close > 30 price`. A ratio-zero literal can compare or cross against another numeric unit, as in `(close - EMA(20)) crosses above 0`. Comparisons use exact binary64 values.
- `not`, `and`, and `or` require Boolean operands. The literals are `true` and `false`. Both operands of a binary Boolean operation must be available.
- Apply `[k]` to a numeric market series, with `k` a literal integer from 0 to 100,000. `[0]` is the current value and `[1]` is the previous observed value. Chained offsets add their lookback. Select a numeric field before applying a record lookback, as in `MACD(12, 26, 9).line[1]`.

A `let` binds an immutable numeric or Boolean scalar or series. A name can reference earlier declarations. Its type and readiness come from the definition. Use `let trend_confirmed = close > SMA(20)` to reuse a condition and `let enabled = true` for a Boolean scalar.

`validate --json` exposes the compiler's versioned typed strategy. Its expression nodes include literals, references, unary and binary arithmetic, indicators, fields, lookbacks, comparisons, crossings, and Boolean operators. Each node carries an inferred type, path-based `node_id`, and source span. Line and column numbers are one-based, the span's end is exclusive, and UTF-8 byte offsets are zero-based. A tab counts as one column.

The typed representation normalizes indicator defaults and operator aliases. It retains named references and declaration order. The spec hash excludes display name, spans, node IDs, and inferred type caches. See [run identity](results.md#compare-and-replay-runs).

## Indicator registry

See the [indicator reference](indicators.md) for all ten signatures, formulas, units, and first-ready rows. Select a numeric field from `MACD` or `BBANDS` before comparing, offsetting, or binding its output.

## Unavailable and bounded computation

Constant division by zero, invalid powers, and nonfinite constants fail compilation. At runtime these faults can make a value unavailable. Arithmetic, comparisons, and Boolean operators propagate unavailable inputs, including under `not`. For example, `false and unavailable` is unavailable. Only an available true signal can queue an order.

`a crosses above b` requires `a <= b` on the previous observed row and `a > b` on the current row. `crosses below` uses previous `a >= b` and current `a < b`. All four samples must be available. Missing timestamps allowed by the gap policy leave adjacent observed rows consecutive for this purpose.

Structural warmup includes every declaration, even unused ones, and the history required by conditions, sizing, protection, lookbacks, and crossings. An unavailable runtime value does not move the structural warmup index. If no next in-window open follows the first eligible close, execution fails with `E_NO_EXECUTION_WINDOW`.

| Limit | Maximum |
| --- | ---: |
| Source | 64 KiB |
| Expression nodes and nesting depth | 2,048 nodes and depth 64 |
| Let declarations | 128 |
| Distinct indicator calls | 128 |
| Structural lookback | 100,000 observed bars |
| Indicator period | 10,000 |
| Timeframe duration | 7 days |

## Sizing and risk context types

`buy using expr of equity` requires a ratio. `buy using expr CURRENCY` accepts a money expression or a numeric ratio interpreted as a cash amount in that currency. Either context accepts scalar or series expressions. The fixed currency must match `capital`.

The `equity` builtin is a scalar money value available in sizing arithmetic only. It resolves at fill time. Indicator sources, lookbacks, conditions, `let` declarations, and protection cannot use it. Sizing expressions read pure market inputs from the completed signal bar and apply the available cash check at the next open.

A valid equity fraction is greater than zero and at most one. Fixed budgets must be positive and fit within the available cash at fill. Invalid constants such as `0% of equity` fail compilation. A positive fixed budget can compile and still exceed available cash at runtime.

`stop loss` and `take profit` require a price or ratio expression. The signal bar supplies the sampled value and the entry fill anchors the level. A ratio stop must be greater than zero and less than one, and every computed stop must stay above zero and below the fill. A valid target is finite and above the fill. Negative constant distances are compile errors. A series distance such as `-2 * ATR(14)` can compile and cause the entry to reject when evaluated. See [frozen protection](execution-semantics.md#frozen-protection).

## Diagnostics and explanation

CLI and HTTP JSON responses include diagnostics with `code`, `severity`, `message`, `span`, `node_id`, `suggestion`, `data_row`, and `details`. Source errors may carry a span. Row errors may carry a one-based data row, counting from the first candle. A fatal source error leaves the strategy without a runnable spec.

| Diagnostic | Typical cause or next step |
| --- | --- |
| `E101_SYNTAX` | Check directive order, keyword spelling, or the expected tokens near the span. Unsupported constructs such as another calendar or execution mode can fail at parsing. |
| `E102_UNKNOWN_NAME` | Check the spelling or whether the identifier is declared. |
| `E103_DUPLICATE_BINDING`, `E104_FORWARD_REFERENCE` | Use a unique unreserved name and declare it before referencing it. |
| `E201_UNIT` | Use `close * (1 + 2%)` to raise a price by 2%. Use `close > 30 price` to compare with a price threshold. |
| `E202_PERIOD` | Use an integer literal from 1 to 10,000. For MACD, keep the fast period below the slow period. |
| `E203_TYPE`, `E204_SELECTOR`, `E205_OFFSET` | Check the expected type, record field, or offset operand and range. |
| `E206_CONSTANT_INVALID`, `E207_LIMIT` | Check for invalid constant arithmetic or an exceeded source, expression, or lookback limit. |
| `E302_SIZING`, `E303_RISK` | Check the sizing currency, capital, costs, and constant budget or risk distance. |
| `E401_DATA`, `E402_WINDOW`, `E_NO_EXECUTION_WINDOW` | Check the [data contract](candle-data.md) for format, metadata, date coverage, and readiness. |
| `W_UNUSED_LET`, `W_RSI_SCALE` | Review unused declarations and percentage literals used directly in RSI comparisons. |
| `W_WARMUP_DELAY` | The first eligible decision moved later in the window. Supply additional pre-window candles to warm the strategy earlier. |

Use [`explain`](cli.md#explain) to see normalized expressions, expanded indicator defaults, and structural warmup. Explanation writes percentage literals as their normalized ratios and periods as integers. Include a dataset to resolve the execution window.

## Complete strategies

See the [runnable examples](example-strategies.md) for RSI recovery, EMA crossover, a lagged breakout, and arithmetic sizing.
