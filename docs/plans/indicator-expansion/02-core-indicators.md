# Core indicators, ranks 1–8

Use these call contracts for the first eight families. The formula notes specify seeds and edge cases that affect backtest parity. Readiness assumes continuous valid input unless stated otherwise. [Shared conventions](01-language-and-runtime.md#apply-shared-indicator-conventions)

| Rank | Proposed calls | Output | First ready index |
| --- | --- | --- | --- |
| 1 | `DMI(di_period, adx_period)` | Numeric points `.plus_di`, `.minus_di`, `.adx` | DI fields at `di_period`, ADX at `di_period + adx_period - 1` |
| 2 | `STOCH(n, k_smooth, d_smooth)` | Numeric points `.k` and `.d` | K at `n + k_smooth - 2`, D at `n + k_smooth + d_smooth - 3` |
| 3 | `VWAP()` | Price | Structural row 0, available once the UTC day accumulates positive volume |
| 4 | `SUPERTREND(atr_period, factor)` | Price `.line` and numeric `.direction` | Both at `atr_period - 1` |
| 5 | `DONCHIAN(n)` | Price `.upper`, `.middle`, `.lower` | All at `n - 1` |
| 6 | `KELTNER(ema_period, atr_period, factor)` and `KELTNER(x, ema_period, atr_period, factor)` | Price `.upper`, `.middle`, `.lower` | Middle at `source_ready + ema_period - 1`. Outer bands at the greater of middle and ATR readiness. |
| 7 | `STOCHRSI(rsi_period, stoch_period, k_smooth, d_smooth)` | Numeric points `.k` and `.d` | K at `rsi_period + stoch_period + k_smooth - 2`, D at K readiness plus `d_smooth - 1` |
| 8 | `OBV()` | Volume | 0 |

## 1. ADX and directional movement

Compute `up = high[t] - high[t-1]` and `down = low[t-1] - low[t]`. Retain positive `up` only when `up > down`, and positive `down` only when `down > up`. Equal moves contribute zero to both. Use only rows with a valid previous candle. Smooth the two movement streams and true range with the same Wilder period. Compute `100 × smoothed_move / smoothed_range` for each DI. If smoothed true range is zero, emit zero for both. Compute `DX = 100 × abs(plus_di - minus_di) / (plus_di + minus_di)`, using zero when the sum is zero. Apply Wilder smoothing over `adx_period` to DX. Reset all stages after unavailable candle inputs.

Use equal up/down movement and a flat series to verify the zero rules. Verify that selecting DI alone gives the earlier warmup, and check unequal DI and ADX periods against an independent derivation. TA-Lib exposes the components separately and TradingView has a two-period DMI setup. [TA-Lib ADX](https://ta-lib.org/functions/adx.html), [TradingView Technical Ratings](https://www.tradingview.com/support/solutions/43000614331-technical-ratings/)

## 2. Stochastic oscillator

Compute raw K as `100 × (close - MINn(low)) / (MAXn(high) - MINn(low))`. Use zero for a fully valid flat range. Apply SMA with `k_smooth` to raw K, then SMA with `d_smooth` to K. Period 1 for either smoothing stage is the identity. Verify `(14, 3, 3)`, fast K with `k_smooth=1`, flat windows, and an unavailable input that propagates through both smoothing stages. [TA-Lib Stochastic](https://ta-lib.org/functions/stoch.html)

## 3. UTC-day VWAP

Within each UTC opening date, accumulate `HLC3 × volume` and `volume`. Reset both sums before processing the first row with a different UTC opening date. A zero-volume row before any positive volume in that day yields unavailable. Once a day has positive volume, later zero-volume rows carry the weighted average forward. Dataset history begins at the first supplied row. A leading partial UTC day uses that day's supplied completed candles. An allowed missing timestamp contributes no sample. An internally invalid OHLCV value clears the accumulators, and the next valid row starts a partial segment.

Require a timeframe below one UTC day that divides 86,400 seconds evenly so no eligible bar straddles midnight. Use the actual timestamp to reset after a gap. Test equivalent UTC/offset imports, multiple skipped days, an exact midnight boundary, partial initial day, and a day with all zero volume. If bars at 23:59 and 00:00 have prices 100 and 110 with equal volumes and each is the first observed bar of its day, expect 100 and 110. A single TA-Lib range over those two bars produces 100 and 105. [TA-Lib VWAP](https://ta-lib.org/functions/vwap.html), [TradingView VWAP](https://www.tradingview.com/support/solutions/43000502018-volume-weighted-average-price-vwap/), [LEAN intraday VWAP](https://github.com/QuantConnect/Lean/blob/master/Indicators/IntradayVwap.cs)

## 4. Supertrend

Use TradeLang ATR. Define basic upper and lower as `HL2 ± factor × ATR`. At the first ready bar, initialize both bands from the basic bands and emit the upper band with direction `-1`. Thereafter, replace the upper band with the basic upper if it is lower than the prior upper or the prior close exceeds the prior upper. Replace the lower band with the basic lower if it is higher than the prior lower or the prior close falls below the prior lower. Otherwise carry the respective prior band. If prior direction was down, flip up only when the current close exceeds the updated upper band. If prior direction was up, flip down only when the current close falls below the updated lower band. Emit the lower band for `+1` and the upper for `-1`. Use the saved direction to resolve equal-band cases and reseed after a break in valid state.

Test both flips, equality without a flip, flat ATR, and mixed price and ratio output units. Record TradeLang's seed and sign convention when comparing another platform. [TradingView Supertrend](https://www.tradingview.com/support/solutions/43000634738-supertrend/), [TA-Lib Supertrend](https://ta-lib.org/functions/supertrend.html)

## 5. Donchian Channels

Compute upper from `MAXn(high)`, lower from `MINn(low)`, and middle as their midpoint. Upper and lower depend on their own source. The middle requires both. Include the signal candle in the channel. To test a close breakout against the preceding channel, use `close crosses above DONCHIAN(20).upper[1]`. Verify monotonic and tied extrema, missing input in a single field, and equivalence to the baseline `HIGHEST` and `LOWEST` calls. [TA-Lib Donchian](https://ta-lib.org/functions/donchian.html)

## 6. Keltner Channels

Use the EMA of `x` as the middle and `middle ± factor × ATR(atr_period)` as the outer bands. Omitted `x` means close. Require an explicit source to be a price series, since the outer bands add or subtract a price distance. Use the candle OHLC for ATR even with a custom source. Test a source that starts late, different EMA and ATR periods, and the middle field during outer-band warmup. Compare references using the ATR-based band variant. [TradingView Keltner Channels](https://www.tradingview.com/support/solutions/43000502266-keltner-channels-kc/)

## 7. Stochastic RSI

Calculate the existing close-based RSI over `rsi_period`. Calculate raw Stochastic K on the RSI series, using its own rolling minimum and maximum over `stoch_period`. Apply K and D SMA stages as for Stochastic. Use zero for a fully valid flat RSI range. Emit both outputs on a 0–100 point scale. Test `(14, 14, 3, 3)` and compare TA-Lib raw K only when `k_smooth=1` and upstream seeds and flat behavior agree. Keep the D smoothing period distinct from the K period. [TA-Lib Stochastic RSI](https://ta-lib.org/functions/stochrsi.html), [TradingView Stochastic RSI](https://www.tradingview.com/support/solutions/43000502333-stochastic-rsi-stoch-rsi/), [LEAN Stochastic RSI](https://github.com/QuantConnect/Lean/blob/master/Indicators/StochasticRelativeStrengthIndex.cs)

## 8. On-Balance Volume

Seed the first valid row of a segment at zero and store its close. Thereafter add current volume when close rises, subtract it when close falls, and carry forward when close is equal or volume is zero. Clear the accumulator and previous close after an invalid input or nonfinite update. Volume outputs use the same unit as candle volume. Test rising, falling, equal-close, zero-volume, and reset cases. Reference comparisons should account for a possible constant offset from a different initial value. [TA-Lib OBV](https://ta-lib.org/functions/obv.html)
