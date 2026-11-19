# Execution semantics 1.1.0

TradeLang models a single long spot position and one cash balance in the quote currency. It uses fractional quantity and a fixed UTC candle grid. The model omits borrowing, shorting, scaling into positions, partial fills, lot sizes, market impact, and corporate actions. Volume is observational. A fill on a zero-volume candle can emit `W_ZERO_VOLUME_FILL`.

## Clock, window and readiness

A candle with opening time `t` and duration `Δ` covers `[t, t + Δ)`. The close decision observes its completed OHLCV at `t + Δ`. For contiguous candles, the decision and next open share a timestamp. The simulator processes them in that order and models zero decision latency.

`from A to B` includes both UTC dates. Only complete candles inside the interval from `A 00:00Z` to the midnight after `B` can execute. The [dataset](candle-data.md#cover-the-dates-and-supply-warmup) must cover the first and last complete grid candles.

The structural warmup index is the latest first-ready row across all declarations, conditions, sizing, and risk expressions. It includes history required by indicator windows, lookbacks, and crosses. Earlier rows can warm expressions before the execution window. Let `j` be the first in-window observed row at or beyond structural warmup. The first eligible decision is at its close and the earliest signal fill is at the next in-window observed open. Without that next row, preparation fails with `E_NO_EXECUTION_WINDOW`. Runtime unavailability suppresses affected decisions and keeps the structural anchor fixed.

With `gap_policy=allow`, a pending order fills at the next observed in-window open, and lookbacks count observed rows. Protection can observe that open and the subsequent recorded high and low. The simulator creates zero synthetic candles.

## Event order within a candle

| Phase | Rule |
| ---: | --- |
| 1 | **Check existing protection at the open.** An open at or below the stop triggers `stop_gap`. An open at or above the target triggers `target_gap`. Use the open as the sell reference and cancel any pending signal exit. |
| 2 | **Fill a queued signal exit.** If the position is still open, sell all at the open reference with reason `signal_exit`. |
| 3 | **Fill a queued entry.** While flat, resolve the budget using available equity and the signal bar's market values. Check the budget against available cash and compute protection levels relative to the proposed fill. Reject an invalid proposal and consume the order before any debit. A valid entry activates protection immediately. |
| 4 | **Check a new position's stop at the open.** Adverse entry slippage can put the new stop at or above the raw open. Sell using the raw open as the reference with reason `stop_entry_open`. |
| 5 | **Check intrabar protection.** If still holding, test `low <= stop` and `high >= target`. Use the touched level as the sell reference. If both touch, prioritize the stop with reason `stop_dual_touch`. |
| 6 | **Mark equity.** Record each account's value using the close and record whether the strategy held any quantity during this bar. |
| 7 | **Evaluate close signals.** Decisions start at row `j`. While holding, queue a sell on a valid true exit and ignore a competing entry. While flat, consider a buy when entry is valid true and exit is anything other than valid true. Check each configured protection value and any market-only sizing expression. An unavailable or nonpositive value records `entry_rejected` before queuing. Skip scheduling entirely on any bar that already exited. |
| 8 | **Expire final-bar orders.** A would-be order with no next in-window bar records `order_expired_end`. The position, if any, remains marked at the final close. |

After an exit on bar `i`, the earliest fresh entry decision is the close of bar `i + 1`, with a fill on the open of bar `i + 2` if it exists. A position opened on bar `i` can queue a signal exit at the same bar's close if it survived protection.

For example, consider a stop at 95 and a target at 110 on a position carried into the candle. These are reference prices before sell slippage.

| Queued signal exit | Open | Low | High | Exit outcome |
| --- | ---: | ---: | ---: | --- |
| Yes | 90 | 88 | 115 | `stop_gap` at 90 |
| Yes | 100 | 90 | 115 | `signal_exit` at 100 |
| No | 100 | 90 | 115 | `stop_dual_touch` at 95 |
| No | 112 | 90 | 115 | `target_gap` at 112 |

Stop and take-profit levels are market-on-touch triggers. The simulator applies sell slippage to the chosen reference. It can report a fill outside the candle range and record `W_FILL_OUTSIDE_RANGE`.

## Fill, cash and P&L equations

The fee rate `f` and slippage rate `s` are the configured basis points divided by 10,000. Both rates must be in `[0, 1)`. For reference price `r`, the buy fill is `r × (1 + s)` and the sell fill is `r × (1 - s)`. The fee on each side is `quantity × actual fill price × f`.

| Quantity | Calculation |
| --- | --- |
| Cash budget `B` | Equity fraction times available cash, or the evaluated fixed money amount. |
| Purchased quantity `q` | `B / (buy fill × (1 + f))`, with a downward float adjustment when needed to respect the budget. |
| Cash debit | `q × buy fill + entry fee` |
| Cash credit on exit | `q × sell fill - exit fee` |
| Closed trade net P&L | `q × (sell fill - buy fill) - entry fee - exit fee` |
| Closed trade return | Net P&L divided by the entry debit. |
| Close equity | `cash + q × close` |

A budget must be positive and fit within available cash. The entry fee is part of that budget. A price gap changes the acquired quantity for the same cash budget. At fill, `equity` is the available cash of the flat account. Sizing expressions that combine account and market inputs use the signal bar for the market inputs.

Slippage is embedded in the fill price. The run also reports `q × abs(actual fill - reference)` as a cost attribution. The mark of an open position uses the raw close with zero hypothetical exit cost.

## Frozen protection

At the signal close (phase 7), TradeLang samples each configured protection expression and rejects an unavailable or nonpositive result with `invalid_stop` or `invalid_target`. The same early check applies to sizing that does not depend on account equity, with reason `invalid_sizing`. The rejection is linked to the signal in the event log.

At the next open (phase 3), a sampled ratio becomes a distance relative to the proposed entry fill. A sampled price value is already an absolute distance. For a buy at `p`, the stop is `p - distance` and the target is `p + distance`. The entry is rejected if the resulting level is nonfinite, if a stop is outside `(0, p)`, or if a target is at or below `p`.

For example, with a fill at 100 and a sampled ATR of 2, `stop loss 2 * ATR(14)` gives a stop at 96. With the same fill, `take profit 8%` gives a target at 108. Those levels remain fixed until exit.

## Numerical policy

The compiler and simulator use binary64 values. Signal comparisons and OHLC trigger tests use exact comparisons of those values. Entry quantity can move toward zero by up to four representable steps so the rounded fee-inclusive debit stays within budget. An invalid entry proposal can be rejected while the run continues. A sale with invalid prices, proceeds, or accounting fails with `E_NUMERIC_EXECUTION`. An exit fee that underflows to zero when the fee rate is positive also fails.

Use the recorded runtime and input identity when [replaying a run](results.md#compare-and-replay-runs). Platform and dependency changes can affect results.

## Buy-and-hold and terminal state

The benchmark starts in cash at the same first in-window open and buys once at the first executable open, immediately after close `j`. It spends its full capital budget including fees and uses the same slippage. It holds through the last close. Both equity curves include the initial cash point and one row per observed in-window close. Open holdings contribute to final equity. Only completed strategy round trips contribute to closed-trade statistics.

## Audit record

Use `sequence` from `events.jsonl` for chronological order. Sorting by timestamp alone can conflate a previous close with the next open. Intrabar fills carry the containing candle's opening timestamp with `time_precision=bar`, which identifies a candle interval. Open fills carry `time_precision=open`. A close decision carries the bar's ending timestamp with `time_precision=close`. See [artifact files](results.md#artifact-files).
