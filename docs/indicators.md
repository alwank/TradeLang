# Indicator reference

TradeLang strategy language v1 has ten built-in indicators. Names are uppercase. A period is an unsigned decimal integer literal between 1 and 10,000. For example, `EMA(20)` is valid, while `EMA(10 + 10)` and `EMA(20.0)` are rejected. An explicit source `x` must be a numeric series with price, volume, or ratio units. It can be a candle field or a typed expression such as `close / SMA(20)`.

The table gives the first structurally ready **zero-based** row for an input available from row 0. Add any input warmup to this index. Every indicator uses completed candles, including the current candle at signal time. Periods count observed rows, including when [gaps are allowed](candle-data.md#choose-a-gap-policy).

| Function | Accepted call forms | Output | First ready index |
| --- | --- | --- | --- |
| SMA | `SMA(n)`, `SMA(x, n)` | Source unit | `n - 1` |
| EMA | `EMA(n)`, `EMA(x, n)` | Source unit | `n - 1` |
| RSI | `RSI(n)` | Ratio on a 0–100 scale | `n` |
| MACD | `MACD(fast, slow, signal)` | Price fields `.line`, `.signal`, `.histogram` | Line at `slow - 1`. Signal and histogram at `slow + signal - 2`. |
| ATR | `ATR(n)` | Price distance | `n - 1` |
| BBANDS | `BBANDS(x, n, k)` | Source-unit fields `.upper`, `.middle`, `.lower` | `n - 1` |
| HIGHEST | `HIGHEST(x, n)` | Source unit | `n - 1` |
| LOWEST | `LOWEST(x, n)` | Source unit | `n - 1` |
| ROC | `ROC(x, n)` | Fractional ratio | `n` |
| STDDEV | `STDDEV(x, n)` | Source unit | `n - 1` |

SMA and EMA default to `close` when called with one argument. RSI and MACD always use `close`. ATR uses high, low, and the previous close. The compiler expands the implicit close arguments in the typed representation.

## Formulas

- **SMA** is the arithmetic mean of the last `n` consecutive inputs, including the current input.
- **EMA** seeds with that first `n`-sample mean. After seeding, `EMA = α × x + (1 − α) × previous EMA`, where `α = 2 / (n + 1)`.
- **RSI** splits each close change into a nonnegative gain and loss magnitude. It seeds the two averages with the first `n` changes and then uses Wilder smoothing, `(previous × (n − 1) + current) / n`. RSI is `100 − 100 / (1 + average gain / average loss)`. If both averages are zero, RSI is 50. If only the loss is zero, RSI is 100. If only the gain is zero, RSI is 0.
- **MACD** requires `fast < slow`. The line is the fast EMA minus the slow EMA. The signal is an EMA of that line, seeded from the first `signal` valid line values. The histogram is line minus signal. Selecting `.line` only requires the line's history.
- **ATR** uses true range. On the first row, true range is `high − low`. Later it is the maximum of that range, the absolute difference between high and previous close, and the absolute difference between low and previous close. ATR seeds with the mean of the first `n` ranges and uses Wilder smoothing thereafter.
- **BBANDS** uses SMA for the middle band and middle ± `k` times population standard deviation for the outer bands. The multiplier `k` must be an unsuffixed numeric literal greater than zero and at most 10.
- **HIGHEST** and **LOWEST** return the maximum and minimum over the current `n`-sample window.
- **ROC** is `x[i] / x[i - n] - 1`. It requires all `n + 1` inputs in the interval. A zero denominator in a complete valid window makes the result unavailable.
- **STDDEV** computes population standard deviation using the sum of squared deviations from the mean divided by `n`, then taking the square root. A valid one-sample window has standard deviation zero.

**V1-MISS02.** Unavailable source values break a rolling window. Recursive smoothing resets after an unavailable input and reseeds once it has sufficient consecutive inputs again. Each record field has its own availability mask. The strategy's [structural warmup](language-spec.md#unavailable-and-bounded-computation) is based on dependencies and stays fixed if later arithmetic makes a value unavailable.

## Common usage

| Goal | Expression |
| --- | --- |
| Compare RSI with 30 points | `RSI(14) > 30` |
| Compare a 12-bar return with 2% | `ROC(close, 12) > 2%` |
| Cross above the previous 20-bar high | `close crosses above HIGHEST(high, 20)[1]` |
| Compare with a Bollinger band | `close < BBANDS(close, 20, 2).lower` |
| Compare the prior MACD line with zero | `MACD(12, 26, 9).line[1] > 0` |
| Set a stop two ATRs from the fill | `stop loss 2 * ATR(14)` |
