# Additional indicators, ranks 29–36

Use this wave to add adaptive smoothers, further momentum and regime measures, a regression line, and an ATR-based exit level. [Shared conventions](01-language-and-runtime.md#apply-shared-indicator-conventions)

| Rank | Proposed calls | Output | First ready index |
| --- | --- | --- | --- |
| 29 | `ALMA(n, offset, sigma)` and `ALMA(x, n, offset, sigma)` | Source unit | `n - 1` |
| 30 | `KAMA(n, fast, slow)` and `KAMA(x, n, fast, slow)` | Source unit | `n` |
| 31 | `AO(fast, slow)` | Price | `slow - 1` |
| 32 | `CHOP(n)` | Numeric points | `n - 1` |
| 33 | `ULTOSC(short, medium, long)` | 0–100 points | `long` |
| 34 | `TSI(slow, fast)` and `TSI(x, slow, fast)` | −100–100 points | `slow + fast - 1` |
| 35 | `LSMA(n)` and `LSMA(x, n)` | Source unit | `n - 1` |
| 36 | `CHANDELIER(n, atr_period, factor)` | Price `.long_exit` and `.short_exit` | Both at `max(n, atr_period) - 1` |

## 29. Arnaud Legoux Moving Average

For window indices `0…n-1` from oldest to newest, set `m = offset × (n-1)`. Use normalized weights proportional to `exp(-0.5 × ((i-m) × sigma/n)²)`. Use a fractional center and no center rounding. Accept unsuffixed `0 ≤ offset ≤ 1` and `0 < sigma ≤ 100`. Precompute the weights per call. Compare period 1, an asymmetric offset, and a non-integer center. Use bounded batches of weighted windows with a consistent reduction order per window. Measure the largest periods and keep an independent scalar oracle. [TA-Lib ALMA](https://ta-lib.org/functions/alma.html), [Pine reference](https://www.tradingview.com/pine-script-reference/v6/)

## 30. Kaufman Adaptive Moving Average

Require `fast < slow`. Over `n` changes compute efficiency `abs(x[t] - x[t-n]) / sum(abs(change))`. If that sum is zero, use efficiency 0. Set `fast_alpha = 2/(fast+1)` and `slow_alpha = 2/(slow+1)`. Square the interpolation `slow_alpha + efficiency × (fast_alpha - slow_alpha)` to obtain the adaptive factor. On the first eligible row or after a new full seed history, initialize the previous KAMA to `x[t-1]`, then emit the regular update `previous + factor × (x[t] - previous)`. Compare trending, flat, and alternating partial paths, including the first update after a gap in valid values. [TA-Lib KAMA](https://ta-lib.org/functions/kama.html), [TradingView KAMA](https://www.tradingview.com/support/solutions/43000773012-kaufman-s-adaptive-moving-average-kama/)

## 31. Awesome Oscillator

Require `fast < slow`. Return `SMA(HL2, fast) - SMA(HL2, slow)`. Verify the common `(5, 34)` form and a dataset where candle midpoint and close diverge. [TradingView Technical Ratings](https://www.tradingview.com/support/solutions/43000614331-technical-ratings/), [TA-Lib function catalog](https://ta-lib.org/functions/)

## 32. Choppiness Index

Require `n ≥ 2`. Compute `100 × log10(sum(TRANGE(), n)/(MAXn(high) - MINn(low))) / log10(n)`. A zero price range yields unavailable. An invalid logarithm input yields unavailable and counts a domain failure when the input window is otherwise complete. Use true range with the preceding close at the start of a filled window when available. Keep the computed value if a prior gap from price makes it exceed 100. Test a steady trend, a flat range, and a gap into a window. [TA-Lib Choppiness Index](https://ta-lib.org/functions/chop.html)

## 33. Ultimate Oscillator

Require `short < medium < long`. For each row with valid current and prior candles, set `floor = min(low, prior_close)`, `ceiling = max(high, prior_close)`, buying pressure to `close - floor`, and range to `ceiling - floor`. Each horizon's contribution is its rolling buying-pressure sum divided by its rolling range sum. Combine with weights 4, 2, and 1 for short, medium, and long and multiply their weighted mean by 100. A zero range sum in any otherwise complete required horizon yields unavailable. Test `(7, 14, 28)`, full-range upward and downward movement, and insufficient prior history. [TA-Lib Ultimate Oscillator](https://ta-lib.org/functions/ultosc.html)

## 34. True Strength Index

Apply EMA over `slow` to the signed one-bar change, then EMA over `fast`. Repeat both EMA stages for absolute changes. Return `100 × smoothed_signed_change / smoothed_absolute_change`, using zero when both terms are zero. Require `fast < slow`. Use the listed order for the two seeds. Supply a TSI signal line through the existing `EMA` call if a strategy needs one. Verify flat prices, monotonic paths, sign reversal, and restart after a nested-source hole. [TA-Lib TSI](https://ta-lib.org/functions/tsi.html)

## 35. Least Squares Moving Average

Require `n ≥ 2`. Fit a least-squares line to `x` against equally spaced indices `0…n-1`, then return the fitted value at index `n-1`. Use centered weights to reduce cancellation and verify a rolling implementation against direct regression. Test exact linear data, constant values, and a large constant baseline with small variation. [TA-Lib LINEARREG](https://ta-lib.org/functions/linearreg.html), [LEAN indicator catalog](https://www.quantconnect.com/docs/v2/writing-algorithms/indicators/supported-indicators)

## 36. Chandelier Exit

Compute `.long_exit = MAXn(high) - factor × ATR(atr_period)` and `.short_exit = MINn(low) + factor × ATR(atr_period)`. Both use the current completed candle. An invalid input invalidates the fields that depend on it. Output the levels as calculated, including a finite negative long level when warranted. Verify both sides, different window lengths, and a long-only exit rule using a price comparison. TradeLang fills an exit signal at the next eligible open. The `risk` block uses frozen entry-relative distances. [TradingView Chandelier Exit](https://www.tradingview.com/support/solutions/43000773013-chandelier-exit/), [TradeLang execution semantics](../../execution-semantics.md)
