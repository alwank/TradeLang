# Execution semantics 1.1.0

The 1.1.0 baseline models one long spot position and a quote-currency cash balance with fractional quantity on a fixed UTC grid. The versioned sections below describe changes to execution, accounting, and the clock. Volume is observational. A fill on a zero-volume candle can emit `W_ZERO_VOLUME_FILL`.

## Clock, window and readiness

**V1-TIME02.** A candle with opening time `t` and duration `Δ` covers `[t, t + Δ)`. The close decision observes its completed OHLCV at `t + Δ`. For contiguous candles, the decision and next open share a timestamp. The simulator processes them in that order and models zero decision latency.

`from A to B` includes both UTC dates. Only complete candles inside the interval from `A 00:00Z` to the midnight after `B` can execute. The [dataset](candle-data.md#cover-the-dates-and-supply-warmup) must cover the first and last complete grid candles.

The structural warmup index is the latest first-ready row across all declarations, conditions, sizing, and risk expressions. It includes history required by indicator windows, lookbacks, and crosses. Earlier rows can warm expressions before the execution window. Let `j` be the first in-window observed row at or beyond structural warmup. The first eligible decision is at its close and the earliest signal fill is at the next in-window observed open. Without that next row, preparation fails with `E_NO_EXECUTION_WINDOW`. Runtime unavailability suppresses affected decisions and keeps the structural anchor fixed.

With `gap_policy=allow`, a pending order fills at the next observed in-window open, and lookbacks count observed rows. Protection can observe that open and the subsequent recorded high and low. The simulator creates zero synthetic candles. Evaluating a fixed window uses rows only through its last candle. Earlier rows can supply history.

## Event order within a candle

**V1-TIME01.** Each candle runs through these phases in order.

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

## Stop-based sizing in semantics 4.0.0

With DSL 4, `buy risking` samples market-only risk and allocation ratios at phase 7. An unavailable ratio or a ratio outside `(0, 1]` rejects the order. When a ratio uses account equity, TradeLang resolves it at phase 3 using the flat account's cash and the signal bar's market values. It derives the proposed protection levels before changing the ledger.

In phase 3, the position size takes the smallest quantity allowed by the stop-touch risk budget, cash, and allocation limit. Ties prioritize the risk budget, then cash, then allocation. The quantity may move down by up to four representable steps to keep the rounded debit and modeled loss within their limits. Invalid arithmetic or an unavailable positive quantity rejects the order. Accepted orders record `trace.risk_sizing` on the buy fill. Existing open and intrabar protection phases still determine the actual sale. [Sizing equations and example](language-v4.md#size-a-long-by-stop-loss)

## Exit and protection priority in semantics 5.0.0

The phase order still applies to DSL 5. The following steps specify where active trails and expiring signal orders fit in that order.

| Phase | DSL 5 behavior |
| --- | --- |
| 1 | Activate the previous close's queued trail. Test open protection against the active stop and target. A protective fill cancels a queued sell. |
| 2 | Check a queued sell's age limit, when present. Expire it at the limit or fill it at the executable open. |
| 3 | Check a queued buy's age limit, when present. Validate and fill an eligible order with its initial protection. |
| 4–5 | Check entry-open and intrabar touches of active protection. The stop wins a dual touch. |
| 6–7 | Mark equity. For a surviving position, evaluate its trailing distance using the completed close and schedule a higher valid trigger for the next open. Check exits in source order and queue the first true rule. |
| 8 | Expire a final-candle signal with no in-window fill open. |

The event log records a trail proposal as `trail_queued` and its effective open as `trail_activated`. An age-based expiry records `order_expired_stale` with age and limit in seconds. Later gap protection still applies after a signal sell expires. [Ordered exit examples](language-v5.md)

## Position accounting in semantics 6.0.0

A position cycle starts at the first buy and ends when quantity reaches zero. Each fill has a run-wide fill ID and a leg number within its cycle. A partial sale adds realized P&L to the open cycle. Only a cycle that reaches zero counts as a closed trade.

The ledger tracks remaining gross cost basis and entry fees separately. An add increases each balance by its fill notional and fee. A sale releases the same proportion of each balance as the proportion of quantity sold. The final sale releases the remaining balances. Realized net P&L on a sale equals gross proceeds minus the released gross basis, released entry fees, and sale fee.

At the open, active protection can close the position before a queued sell or add. If a signal sale leaves quantity, active protection continues through the intrabar phase. A surviving position can queue a new action at the close. Exit rules take priority over an add within that close decision. A full exit suppresses new signals on its candle under the existing phase rules.

The closed-trade row rolls up the cycle using quantity-weighted fill prices and totals across its fill legs. Its quantity is cumulative bought quantity. Its times run from the first entry to the last exit. The position mark uses the closing price, remaining gross basis, and retained entry fees. [Quantity-changing orders](language-v6.md)

## Exchange sessions in semantics 7.0.0

With `calendar session`, a completed candle can queue an order before a closure. The normal phases resume at the next observed candle's open. Order age includes the elapsed time during the closure. The engine checks an explicit age limit before filling the queued signal. Lookbacks and holding periods count observed candles.

Scheduled ordinals determine gaps. CAGR uses elapsed calendar time and exposure counts observed candles. Session runs report Sharpe unavailable with reason `session_intervals`. [Session metadata and split-reference units](language-v7.md)

## Short accounts in semantics 8.0.0

A borrowed-asset short carries negative quantity and reserves its sale proceeds and initial margin. Borrow is debited on elapsed time at the open before assessing margin and at the close before marking a surviving position. An observed open can liquidate before gap protection or a queued cover. A close liquidation uses the observed close and is recorded before the equity mark.

A gap can leave a deficit after liquidation. Drawdown can exceed 100%. A terminal deficit makes CAGR unavailable. A continuous curve with nonpositive equity also makes Sharpe unavailable. [Collateral, financing, and liquidation rules](language-v8.md)

## Numerical policy

The compiler and simulator use binary64 values. Signal comparisons and OHLC trigger tests use exact comparisons of those values. Entry quantity can move toward zero by up to four representable steps so the rounded fee-inclusive debit stays within budget. An invalid entry proposal can be rejected while the run continues. A sale with invalid prices, proceeds, or accounting fails with `E_NUMERIC_EXECUTION`. An exit fee that underflows to zero when the fee rate is positive also fails.

Use the recorded runtime and input identity when [replaying a run](results.md#compare-and-replay-runs). Platform and dependency changes can affect results.

## Buy-and-hold and terminal state

The benchmark starts in cash at the same first in-window open and buys once at the first executable open, immediately after close `j`. It spends its full capital budget including fees and uses the same slippage. It holds through the last close. Both equity curves include the initial cash point and one row per observed in-window close. Open holdings contribute to final equity. Only completed strategy round trips contribute to closed-trade statistics.

## Audit record

Use `sequence` from `events.jsonl` for chronological order. Sorting by timestamp alone can conflate a previous close with the next open. Intrabar fills carry the containing candle's opening timestamp with `time_precision=bar`, which identifies a candle interval. Open fills carry `time_precision=open`. A close decision carries the bar's ending timestamp with `time_precision=close`. See [artifact files](results.md#artifact-files).
