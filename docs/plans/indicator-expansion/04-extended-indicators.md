# Extended indicators, ranks 17–28

Use the source-taking variants with close as the default only where both signatures are listed. The readiness indices assume inputs available from row 0. [Shared conventions](01-language-and-runtime.md#apply-shared-indicator-conventions)

| Rank | Proposed calls | Output | First ready index |
| --- | --- | --- | --- |
| 17 | `HMA(n)` and `HMA(x, n)` | Source unit | `n + floor(sqrt(n)) - 2` |
| 18 | `ICHIMOKU(conversion, base, span_b)` | Price fields `.conversion`, `.base`, `.span_a`, `.span_b` | Respective lengths minus 1. Span A uses the greater of conversion and base readiness. |
| 19 | `AROON(n)` | Numeric points `.up`, `.down`, `.oscillator` | `n` |
| 20 | `MOM(n)` and `MOM(x, n)` | Source unit | `n` |
| 21 | `TRANGE()` | Price | 0 |
| 22 | `NATR(n)` | Fractional ratio | `n - 1` |
| 23 | `BBPCTB(x, n, k)` | Fractional ratio | `n - 1` |
| 24 | `BBWIDTH(x, n, k)` | Fractional ratio | `n - 1` |
| 25 | `ADL()` | Volume | 0 |
| 26 | `RVOL(n)` | Fractional ratio | `n` |
| 27 | `DEMA(n)` and `DEMA(x, n)` | Source unit | `2(n - 1)` |
| 28 | `TEMA(n)` and `TEMA(x, n)` | Source unit | `3(n - 1)` |

## 17. Hull Moving Average

Let `h = max(1, floor(n/2))` and `s = max(1, floor(sqrt(n)))`. Return `WMA(2 × WMA(x,h) - WMA(x,n), s)`. Use floor for both derived periods. Cover `n=1`, odd periods, and periods on either side of a square. Record any external rounding difference when comparing output arrays. [TA-Lib HMA](https://ta-lib.org/functions/hma.html)

## 18. Ichimoku Cloud

Require `conversion ≤ base ≤ span_b`. The conversion, base, and Span B values are midpoints of the highest high and lowest low over their respective windows. Span A is the midpoint of conversion and base. Expose the four values at their calculation rows. To compare close with the cloud plotted at the signal bar using a displacement of 26, use `ICHIMOKU(9, 26, 52).span_a[26]` and the analogous Span B lookback. The Chikou plot uses the current close drawn into historical chart space. A strategy can compare the available close with historical prices through lookbacks. The kernel publishes only the four calculated lines.

Verify each field independently, calculate a displaced cloud comparison by hand, and prove that extending the data cannot revise earlier lines. [TA-Lib Ichimoku](https://ta-lib.org/functions/ichimoku.html), [TradingView Ichimoku](https://www.tradingview.com/support/solutions/43000589152-ichimoku-cloud/)

## 19. Aroon

Search the current row and preceding `n` observed rows. For equal extrema, select the most recent. Return `100 × (n - bars_since_extreme)/n` for the high and low streams and their difference as `.oscillator`. Respect each extrema stream's own availability. Test newest and oldest extrema, ties, and independence from the previous out-of-window row. [TA-Lib Aroon](https://ta-lib.org/functions/aroon.html), [LEAN indicator reference](https://www.quantconnect.com/docs/v1/algorithm-reference/indicators)

## 20. Momentum

Return `x[t] - x[t-n]`. Require all `n+1` observations in the span, using the same missing-interval convention as ROC. Preserve the input dimension. Verify a missing interior value between two finite endpoints. [TA-Lib Momentum](https://ta-lib.org/functions/mom.html), [TradeLang ROC](../../indicators.md)

## 21. True Range

Compute the maximum of current high minus low, absolute high minus prior close, and absolute low minus prior close. Use high minus low on the first valid row of a segment. Reject an internally unavailable current candle and restart the prior-close state. With valid candles, prove `RMA(TRANGE(), n)` agrees with the baseline ATR within the numeric tolerance. Keep the ATR behavior for the first row even if a library requires a previous close. [Baseline ATR](../../indicators.md), [TA-Lib True Range](https://ta-lib.org/functions/trange.html)

## 22. Normalized ATR

Return `ATR(n) / close`. An output of `0.02` represents 2%. Compare TA-Lib and TradingView ATR% values after dividing by 100 and aligning the ATR seed. Valid imported spot prices are positive. Cover denominator failure at kernel level and preserve ATR's first ready row. [TA-Lib NATR](https://ta-lib.org/functions/natr.html), [TradingView ATR%](https://my.tradingview.com/support/solutions/43000734653/)

## 23. Bollinger %B

Use the same SMA, population deviation, and positive multiplier as existing BBANDS. Return `(x - lower)/(upper - lower)`. A collapsed band yields unavailable. Allow values outside 0–1 when the source sits outside the bands. Verify boundary and out-of-band values. [TradeLang BBANDS](../../indicators.md), [LEAN Bollinger Bands](https://www.quantconnect.com/docs/v2/writing-algorithms/indicators/supported-indicators/bollinger-bands)

## 24. Bollinger BandWidth

Return `(upper - lower)/abs(middle)` from the same band calculation. Absolute normalization gives positive width on negative-valued custom sources. A zero middle yields unavailable. A collapsed band with a nonzero middle yields zero. Compare external percent-scaled and signed variants only after accounting for scale and sign. Verify positive, negative, and zero middle values. Keep both Bollinger-derived metrics as separate calls to preserve the published `BBANDS` record fields. [TA-Lib function catalog](https://ta-lib.org/functions/), [LEAN Bollinger Bands](https://www.quantconnect.com/docs/v2/writing-algorithms/indicators/supported-indicators/bollinger-bands)

## 25. Accumulation/Distribution Line

Use the per-bar location-weighted volume from Chaikin Money Flow. Sum from the first valid row of each segment, including that row's contribution. Use zero contribution for high equal to low. A zero-volume row carries the total forward. An invalid input or nonfinite update clears the total. Test flat candles, both close extremes, and independent OBV behavior on unchanged closes. [TA-Lib A/D Line](https://ta-lib.org/functions/ad.html)

## 26. Relative Volume

Divide current base-quantity volume by the simple mean of volumes in the preceding `n` observed rows. Exclude current volume from that baseline. Require all `n+1` values. A zero baseline yields unavailable. Test a tenfold spike after a constant positive baseline, then verify that the spike changes the next row's baseline. LEAN's time-of-day variant uses cumulative volume. [TA-Lib RVOL](https://ta-lib.org/functions/rvol.html), [TradingView Relative Volume](https://www.tradingview.com/support/solutions/43000635874-how-do-we-calculate-relative-volume-and-relative-volume-at-time/), [LEAN Relative Daily Volume](https://www.quantconnect.com/docs/v2/writing-algorithms/indicators/supported-indicators/relative-daily-volume)

## 27. Double EMA

Let `E1 = EMA(x,n)` and `E2 = EMA(E1,n)`. Return `2 × E1 - E2` when both are ready. Verify identity at period 1 and the propagation of a source hole through the two seeds. [TA-Lib DEMA](https://ta-lib.org/functions/dema.html)

## 28. Triple EMA

Build `E3 = EMA(E2,n)` from the DEMA stages. Return `3 × E1 - 3 × E2 + E3` when all stages are ready. Verify the extra warmup and reset delay after an invalid value and preserve the source dimension. [TA-Lib TEMA](https://ta-lib.org/functions/tema.html)
