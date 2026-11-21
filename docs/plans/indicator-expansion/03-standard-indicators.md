# Standard indicators, ranks 9–16

Use these contracts for the remaining families in the first release. Implement WMA and RMA early because later families depend on their kernels. [Shared conventions](01-language-and-runtime.md#apply-shared-indicator-conventions)

| Rank | Proposed calls | Output | First ready index |
| --- | --- | --- | --- |
| 9 | `MFI(n)` | 0–100 points | `n` |
| 10 | `CCI(n)` | Unbounded numeric points | `n - 1` |
| 11 | `WILLR(n)` | −100–0 points | `n - 1` |
| 12 | `SAR(step, maximum)` | Price | 1 |
| 13 | `WMA(n)` and `WMA(x, n)` | Source unit | `n - 1` |
| 14 | `RMA(n)` and `RMA(x, n)` | Source unit | `n - 1` |
| 15 | `VWMA(n)` and `VWMA(x, n)` | Source unit | `n - 1` |
| 16 | `CMF(n)` | Fractional ratio | `n - 1` |

## 9. Money Flow Index

Classify `HLC3 × volume` by the sign of the current change in HLC3. A tie contributes zero on both sides. Sum positive and negative magnitudes separately over `n` classified bars and emit `100 × positive / (positive + negative)`. Both sums zero yields 50 points. Positive-only yields 100, and negative-only yields zero. An invalid candle breaks the comparison sequence and the rolling sums. Cover all-positive and all-negative sequences, ties, and zero-volume windows. [TA-Lib MFI](https://ta-lib.org/functions/mfi.html)

## 10. Commodity Channel Index

Over the current `n` HLC3 samples, compute the mean and the mean absolute deviation from that same mean. Return `(HLC3 - mean) / (0.015 × mean_absolute_deviation)`. Emit zero for a truly flat window, including `n=1`. Check a hand-computable window plus a large-period case. For scalable evaluation, use an online ordered multiset with subtree counts and sums. Split at the window mean to compute absolute deviation from the counts and sums on each side. Ensure that adding future values cannot change the aggregation order for a finished window. Keep a direct scalar mean-absolute-deviation oracle. [TA-Lib CCI](https://ta-lib.org/functions/cci.html)

## 11. Williams %R

Return `-100 × (MAXn(high) - close) / (MAXn(high) - MINn(low))`. A fully valid zero range returns zero. Cover both endpoints and verify `WILLR = raw Stochastic K - 100` only on nonflat ranges. [TA-Lib Williams %R](https://ta-lib.org/functions/willr.html)

## 12. Parabolic SAR

Accept unsuffixed literals satisfying `0 < step ≤ maximum ≤ 1`. Use high and low with state for trend side, SAR, extreme point, and acceleration. Adopt the following explicit initialization and reversal rules.

1. After two consecutive valid candles, use down as the initial trend if prior low minus current low exceeds the greater of zero and current high minus prior high. Otherwise use up. For an up seed, set SAR to the minimum of both lows and extreme point to the maximum of both highs. For a down seed, use the maximum of both highs and minimum of both lows. Start acceleration at `step`.
2. At each later row, project SAR from the prior SAR toward the prior extreme point by the prior acceleration factor. Clamp an up projection to at most the prior two lows, or a down projection to at least the prior two highs.
3. In an uptrend, reverse if current low is at or below the clamped projection. Emit the maximum of the prior extreme point, prior high, and current high. Set the new extreme point to current low and reset acceleration. Mirror this for a downtrend using current high at or above the projection, the prior extreme point and lows for the new SAR, and current high for the new extreme point.
4. If the trend continues, emit the clamped projection. Update the extreme and increase acceleration by `step` up to `maximum` only if the current high or low strictly extends the trend. Clear state after an invalid row and wait for two valid candles to reseed.

Use independent traces for both directions, equality at reversal, caps, consecutive reversals, and resets. Compare the chosen seed and clamp order explicitly when reading a TA-Lib or Pine reference. [TA-Lib SAR](https://ta-lib.org/functions/sar.html), [Pine reference](https://www.tradingview.com/pine-script-reference/v6/)

## 13. Weighted Moving Average

Weight observations oldest to newest from 1 through `n`. Divide their weighted sum by `n(n+1)/2`. Use a rolling ordinary sum alongside the weighted sum, with periodic rebasing if large-window drift exceeds the documented tolerance. Compare with direct weighting for `n=1` and `n=10,000`. Test source dimensions and holes. [TA-Lib WMA](https://ta-lib.org/functions/wma.html)

## 14. Wilder's Moving Average

Seed with the first full-window arithmetic mean, then update with factor `1/n`. Period 1 returns each valid source value. Reuse the same arithmetic in new code where compatible. Compare the existing ATR and RSI evaluation bits before changing their kernel bindings. Use a hole followed by a fresh seed to distinguish reseeding from a skipped sample. [TA-Lib RMA](https://ta-lib.org/functions/rma.html)

## 15. Volume-Weighted Moving Average

Return `sum(x × volume) / sum(volume)` over the same trailing `n` bars. Use close when the source is omitted and preserve any accepted source unit. If the full window has zero volume, emit unavailable. The first valid window with positive volume should recover immediately. Equal positive volume should agree with SMA for the same source and period. [TA-Lib VWMA](https://ta-lib.org/functions/vwma.html)

## 16. Chaikin Money Flow

Set the per-bar location multiplier to `(2 × close - high - low)/(high - low)`, using zero when the high equals the low. Sum the multiplier times volume over `n` bars and divide by total volume over the same window. A flat candle with positive volume contributes zero numerator and positive denominator. A complete all-zero-volume window yields unavailable. Cover close at both extremes, flat candles, zero-volume recovery, and expected bounds of −1 through 1 with legal candles. [TA-Lib CMF](https://ta-lib.org/functions/cmf.html)
