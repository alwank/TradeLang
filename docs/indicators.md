# Indicator reference

Indicator names are uppercase. A period is an unsigned decimal integer literal between 1 and 10,000. For example, `EMA(20)` is valid, while `EMA(10 + 10)` and `EMA(20.0)` are rejected. An explicit source `x` must be a numeric series with price, volume, or ratio units. It can be a candle field or a typed expression such as `close / SMA(20)`.

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
| WMA | `WMA(n)`, `WMA(x, n)` | Source unit | `n - 1` |
| RMA | `RMA(n)`, `RMA(x, n)` | Source unit | `n - 1` |
| VWMA | `VWMA(n)`, `VWMA(x, n)` | Source unit | `n - 1` |
| CMF | `CMF(n)` | Fractional ratio from −1 to 1 | `n - 1` |
| OBV | `OBV()` | Volume | 0 |
| VWAP | `VWAP()` | Price | 0 structurally, available after positive volume in the UTC day |
| DONCHIAN | `DONCHIAN(n)` | Price fields `.upper`, `.middle`, `.lower` | `n - 1` |
| KELTNER | `KELTNER(ema, atr, factor)`, `KELTNER(x, ema, atr, factor)` | Price fields `.upper`, `.middle`, `.lower` | Middle at `x_ready + ema - 1`. Outer bands at the later of the middle and ATR. |
| SUPERTREND | `SUPERTREND(n, factor)` | Price field `.line` and direction field `.direction` | `n - 1` |
| DMI | `DMI(di, adx)` | Point-scale fields `.plus_di`, `.minus_di`, `.adx` | DI at `di`. ADX at `di + adx - 1`. |
| STOCH | `STOCH(n, k, d)` | 0–100 point fields `.k` and `.d` | K at `n + k - 2`. D at `n + k + d - 3`. |
| STOCHRSI | `STOCHRSI(rsi, n, k, d)` | 0–100 point fields `.k` and `.d` | K at `rsi + n + k - 2`. D at K readiness plus `d - 1`. |
| MFI | `MFI(n)` | 0–100 points | `n` |
| CCI | `CCI(n)` | Numeric points | `n - 1` |
| WILLR | `WILLR(n)` | −100 to 0 points | `n - 1` |
| SAR | `SAR(step, maximum)` | Price | 1 |
| HMA | `HMA(n)`, `HMA(x, n)` | Source unit | `n + floor(sqrt(n)) - 2` |
| ICHIMOKU | `ICHIMOKU(conversion, base, span_b)` | Price fields `.conversion`, `.base`, `.span_a`, `.span_b` | Conversion, base, and Span B at their length minus one. Span A at base readiness. |
| AROON | `AROON(n)` | Point fields `.up`, `.down`, `.oscillator` | `n` |
| MOM | `MOM(n)`, `MOM(x, n)` | Source unit | `n` |
| TRANGE | `TRANGE()` | Price distance | 0 |
| NATR | `NATR(n)` | Fractional ratio | `n - 1` |
| BBPCTB | `BBPCTB(x, n, k)` | Fractional ratio | `n - 1` |
| BBWIDTH | `BBWIDTH(x, n, k)` | Fractional ratio | `n - 1` |
| ADL | `ADL()` | Volume | 0 |
| RVOL | `RVOL(n)` | Fractional ratio | `n` |
| DEMA | `DEMA(n)`, `DEMA(x, n)` | Source unit | `2 × (n - 1)` |
| TEMA | `TEMA(n)`, `TEMA(x, n)` | Source unit | `3 × (n - 1)` |
| ALMA | `ALMA(n, offset, sigma)`, `ALMA(x, n, offset, sigma)` | Source unit | `n - 1` |
| KAMA | `KAMA(n, fast, slow)`, `KAMA(x, n, fast, slow)` | Source unit | `n` |
| AO | `AO(fast, slow)` | Price | `slow - 1` |
| CHOP | `CHOP(n)` | Numeric points | `n - 1` |
| ULTOSC | `ULTOSC(short, medium, long)` | 0–100 points | `long` |
| TSI | `TSI(slow, fast)`, `TSI(x, slow, fast)` | −100 to 100 points | `slow + fast - 1` |
| LSMA | `LSMA(n)`, `LSMA(x, n)` | Source unit | `n - 1` |
| CHANDELIER | `CHANDELIER(n, atr, factor)` | Price fields `.long_exit` and `.short_exit` | `max(n, atr) - 1` |
| ZIGZAG | `ZIGZAG(left, right, reversal)` | Price fields `.pivot`, `.last_high`, and `.last_low` and numeric field `.direction` | `left + right` structurally, with availability determined by confirmed pivots |
| VPROFILE | `VPROFILE(n, bin_width, value_area)` | Price fields `.poc`, `.vah`, and `.val` | `n - 1` structurally, subject to lower-timeframe coverage and volume |

Calls that accept an optional source default to `close`. RSI, MACD, and Stochastic RSI always use `close`. The compiler expands the implicit close arguments in the typed representation.

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
- **WMA** assigns weights from 1 to `n` from oldest to newest within the window. It divides the weighted sum by `n × (n + 1) / 2`.
- **RMA** seeds with the first full-window mean. Each subsequent value is the weighted mean of the previous result and the current input, with weight `1/n` for the current input.
- **VWMA** divides the sum of source times candle volume by total volume over the same window. A complete window with zero total volume yields an unavailable value.
- **CMF** weights candle volume by `((close − low) − (high − close)) / (high − low)` and divides the sum of weighted volume by total window volume. A candle with equal high and low contributes zero weighted volume. A complete window with zero total volume yields an unavailable value.
- **OBV** starts at zero. Add a candle's volume when its close rises and subtract it when its close falls. Equal closes carry the total forward.
- **VWAP** weights `(high + low + close)/3` by candle volume from the first supplied bar of each UTC opening date. It requires intraday bars whose duration divides 86,400 seconds. A zero-volume bar carries an existing average forward. The average stays unavailable until the first positive-volume bar of the day.
- **DONCHIAN** returns the current window's highest high, lowest low, and their midpoint.
- **KELTNER** uses the EMA of the chosen price series as its middle and offsets the outer bands by `factor × ATR(atr)`. Omitting the source uses close. The factor must be a positive unsuffixed numeric literal at most 10.
- **SUPERTREND** starts at the midpoint plus `factor × ATR(n)` with direction −1. Upper and lower bands track the tighter band until the previous close breaks it. A close strictly above the upper band switches from −1 to +1. A close strictly below the lower band switches from +1 to −1. The line uses the lower band in direction +1 and the upper band in direction −1. The factor must be a positive unsuffixed numeric literal at most 10.
- **DMI** uses the larger positive comparison of each high's increase and each low's decrease. Equal moves contribute zero to both. DI fields divide Wilder-smoothed moves by Wilder-smoothed true range and multiply by 100. ADX smooths the absolute DI difference divided by their sum, also scaled by 100. Either zero denominator gives zero points. The first range sample requires a previous candle.
- **STOCH** divides the difference between close and the lowest low by the width of the high–low window, then multiplies by 100. A flat range gives zero. Smooth the raw series with a `k`-bar SMA, then smooth that result with a `d`-bar SMA.
- **STOCHRSI** applies the same calculation and smoothing to the rolling range of close-based RSI.
- **MFI** assigns typical price times volume to positive or negative flow using the direction of the change in typical price. Equal typical prices contribute zero. Divide the positive flow by total absolute flow over the window and multiply by 100. A window with no flow gives 50.
- **CCI** divides the difference between typical price and its rolling mean by 0.015 times the window's mean absolute deviation from that mean. A flat window gives zero.
- **WILLR** subtracts the highest high from close, divides by the high–low window width, and multiplies by 100. A flat range gives zero.
- **SAR** requires unsuffixed literals with `0 < step ≤ maximum ≤ 1`. Seed direction and the first extreme from two candles. The level accelerates toward the trend's extreme, constrained by the previous two candles. Touching the level reverses direction and resets the acceleration to `step`.
- **HMA** applies a weighted mean over `floor(sqrt(n))` bars to twice the short WMA minus the full WMA. The short length is `max(1, floor(n/2))`.
- **ICHIMOKU** uses the midpoint of the highest high and lowest low over each given period. Span A averages conversion and base. Require `conversion ≤ base ≤ span_b`. Fields refer to their calculation bar. Use a lookback such as `ICHIMOKU(9, 26, 52).span_a[26]` for the cloud line dated at the signal bar.
- **AROON** finds the most recent equal or better extreme among the current row and the preceding `n` rows. Each line is `100 × (n − age)/n`. The oscillator is up minus down.
- **MOM** subtracts the source `n` bars ago from the current source and requires a complete interval.
- **TRANGE** returns the maximum of high minus low and the absolute distances from high and low to the prior close. The first bar uses high minus low.
- **NATR** divides ATR by close. An output of 0.02 means 2%.
- **BBPCTB** divides the source's distance above the lower Bollinger band by the band width. A collapsed band gives unavailable.
- **BBWIDTH** divides Bollinger band width by the absolute value of the middle band. A zero middle gives unavailable.
- **ADL** accumulates location-weighted volume using the CMF weighting rule. The first bar contributes its weighted volume.
- **RVOL** divides current base-quantity volume by the average of the preceding `n` observed bars. A zero baseline gives unavailable.
- **DEMA** combines two successive EMA passes as `2 × EMA1 − EMA2`.
- **TEMA** combines three successive EMA passes as `3 × EMA1 − 3 × EMA2 + EMA3`.
- **ALMA** uses normalized Gaussian weights centered at `offset × (n − 1)` with standard deviation `n/sigma`. Both are unsuffixed literals. The offset ranges from 0 to 1 inclusive and sigma is positive and at most 100.
- **KAMA** adjusts its EMA weight based on absolute net change divided by total absolute movement over `n` bars. A flat path uses efficiency zero. Interpolate between the slow and fast EMA weights, then square the result. Seed the first update with the preceding source value. Require `fast < slow`.
- **AO** subtracts the slow SMA of candle midpoints from the fast SMA. Require `fast < slow`.
- **CHOP** divides the sum of true ranges by the high–low window range, takes the base-10 logarithm, and scales by `100/log10(n)`. Require `n ≥ 2`. A flat price range yields unavailable. Gaps can produce values above 100.
- **ULTOSC** divides rolling buying pressure by rolling true range for each period. Buying pressure is close minus the lesser of low and the prior close. Combine the three ratios with weights 4, 2, and 1 and scale to 100 points. Require `short < medium < long`. A zero range sum yields unavailable.
- **TSI** double-smooths the signed and absolute one-bar changes, using the slow EMA followed by the fast EMA. Divide the two and multiply by 100. A flat path gives zero. Require `fast < slow`.
- **LSMA** evaluates the rolling ordinary least-squares line at the latest observation in the window. Require `n ≥ 2`.
- **CHANDELIER** subtracts `factor × ATR(atr)` from the highest high for the long exit, and adds the same distance to the lowest low for the short exit. The factor is a positive unsuffixed literal at most 10. Compare the close directly with a level to create an exit signal.
- **ZIGZAG** checks each swing only after `right` bars close. A swing must be strict against the preceding `left` bars and may tie following extremes. Confirmed swings alternate after moving at least the reversal fraction from the last pivot. Each leg is in 1–1,000. The reversal is an unsuffixed literal greater than 0 and at most 1. The event field `.pivot` is available only on a confirmation bar. The latest high, low, and direction carry forward once confirmed. Direction is +1 after a high and −1 after a low.
- **VPROFILE** uses up to 256 primary bars and a separate lower-timeframe dataset. Each child candle contributes its volume to its close-price bin. Supply a positive bin-width literal with the `price` suffix and an unsuffixed value-area fraction greater than 0 and at most 1. The point of control is the midpoint of the highest-volume bin. Ties choose the lower bin. Starting there, expand toward the next adjacent bin with more volume, taking the lower bin on a tie, until the selected fraction is reached. `.val` and `.vah` are the outer edges. Missing child bars, zero total volume, and spans over 256 bins make the window unavailable. [Pair candle datasets](candle-data.md#pair-candles-for-volume-profile)

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
| Cross above the preceding Donchian channel | `close crosses above DONCHIAN(20).upper[1]` |
| Filter an uptrend using Supertrend | `SUPERTREND(10, 3).direction > 0` |
| Require 25 points of trend strength | `DMI(14, 14).adx > 25` |
| Detect a newly confirmed Zig Zag high after a low | `ZIGZAG(3, 3, 0.05).direction crosses above 0` |
| Compare close with the point of control | `close > VPROFILE(20, 1 price, 0.7).poc` |
