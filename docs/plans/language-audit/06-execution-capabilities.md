# Execution capabilities

Use the existing single-long, next-open ledger as the baseline. Add stop-based sizing and richer exits for one position first. Specify the accounting model for quantity changes and additional markets before enabling them. [Execution phases](../../execution-semantics.md#event-order-within-a-candle)

## Stop-based sizing

DSL 4 implements `buy risking 1% of equity` with an optional `max allocation` ratio. It uses the existing stop-distance forms and phase boundaries. Quantities use fractional base units and round down in binary64 where necessary to respect the limits. [Stop-based sizing](../../language-v4.md) · [Fill arithmetic](../../execution-semantics.md#fill-cash-and-pl-equations)

1. Require a valid protective stop. Sample the market-dependent stop distance at the signal close. Compute the stop level from the actual proposed entry fill and the sampled distance at the next open.
2. Compute modeled loss per unit from the fee-inclusive entry debit and expected proceeds from a stop touch with sell slippage and fees. Derive quantity from the risk budget and clamp it to the available cash and configured allocation cap. Apply downward quantity rounding where needed. Reject an unavailable or invalid proposal before modifying the ledger.
3. Record the modeled risk budget, price basis, per-unit loss, cash cap, final quantity, and binding constraint in the order trace. Explain that an opening gap can lead to a realized loss beyond the modeled touch loss.

**Acceptance.** Hand-calculate several fills with percent and ATR stops, fees, and slippage. Check a cap-limited quantity, missing stop, invalid stop, rounding at the budget boundary, an entry-open stop, and a subsequent gap exit. Legacy cash and equity-fraction sizing retain their golden values.

## Ordered exits and trailing protection

1. Add named or ordered close-based exit rules and a time-based exit. Specify first-match priority, how unavailable conditions participate, and the clock for time-based exits. Keep queued signal exits at the next executable open and records tied to the triggering rule.
2. Add a trailing stop that updates from completed bars for the next bar. Define initial protection, monotonic tightening for a long, handling of unavailable updates, and the effective phase. Keep initial price protection and intrabar dual-touch rules explicit.
3. Document a priority table covering old protection at the open, queued exits, new entry protection, intrabar touches, and close-generated updates. Add an optional stale-order duration only after specifying how a pending order that spans a gap expires.

Use source order to choose the first available true exit. Count completed primary candles held for the time exit, including the close of the entry candle. A gap contributes zero candles to this count. Keep the triggering rule with the queued order and its fill. Preserve the behavior of the single-rule syntax.

For a long, initialize protection from the configured stop loss. A completed primary close can raise the stop to the close minus the evaluated trailing distance. An unavailable update keeps the previous stop. Activate a raised stop at the next executable open before checking open protection. Store the source candle, previous trigger, new trigger, and effective open in the evidence.

Measure any queued-order age limit as elapsed time from signal close to the candidate fill open. At the limit, expire the pending signal order before executing it. Existing gap protection still acts first and can cancel a queued sell. Without an age limit, keep the next-observed-open policy.

**Acceptance.** Simultaneous exit rules resolve deterministically. A time exit fills at the next open. A trail calculated from the current close cannot be triggered by the current bar's earlier low. Gaps, dual touches, and final-bar expiry retain causal ordering. [Legacy phase rules](../../execution-semantics.md#event-order-within-a-candle)

## Partial exits and position scaling

Specify the ledger and artifact model before adding grammar for quantity changes.

- Define order sizing in position fractions or units, quantity and lot rounding, cash reservation, fee attribution, and remaining basis. Choose and document how to account for multiple entry lots.
- Define how protection applies to remaining quantity and how an exit cancels or reduces competing orders. Separate a strategy-requested partial exit from a venue partial fill. Define how fill legs roll up into trades and exposure metrics.
- Add partial exits for one long before scaling in. Require the event and ledger views to show quantities, order sequence, and fee and realized P&L attribution on every leg.

Use a position cycle from the first buy through the sell that brings quantity to zero. Give every fill a stable identifier and link it to the position cycle. Show partial realized P&L even if the cycle remains open. Count a closed trade when the position reaches zero, and expose the individual fills alongside the cycle totals.

Track remaining gross cost basis and remaining entry fees separately. A partial sale removes each in the same fraction as the sold quantity. Realized net P&L subtracts both allocations and the sale fee from gross sale proceeds. A final sale consumes the remaining basis and fees. When scaling in, add the new gross debit and entry fee to those balances to maintain weighted-average basis.

Size a partial sale from the quantity held at its candidate fill open. Round the requested quantity down when a quantity step applies. Reject a rounded zero. A full close consumes the complete remaining quantity. Keep one pending strategy order for the position. Gap protection preempts pending actions. After a partial sale, active stops and targets cover the remaining quantity. A later add uses available cash and shares the position's active protection and original holding clock.

Use a 2,000 USDT account with a 1% fee per side and zero slippage for the ledger fixture. Stop the partial-exit fixture after the second sale and mark the remaining quantity at 105 USDT for final equity of 2,086.20 USDT. Continue through the add and final sale to test the weighted-average basis.

| Fill | Cash after fill | Remaining quantity | Remaining gross basis | Remaining entry fees | Realized net P&L on fill |
| --- | ---: | ---: | ---: | ---: | ---: |
| Buy 10 at 100 | 990.00 | 10 | 1,000.00 | 10.00 | — |
| Sell 25% at 120 | 1,287.00 | 7.5 | 750.00 | 7.50 | 44.50 |
| Sell 40% at 110 | 1,613.70 | 4.5 | 450.00 | 4.50 | 23.70 |
| Add 2 at 125 | 1,361.20 | 6.5 | 700.00 | 7.00 | — |
| Sell all at 115 | 2,101.225 | 0 | 0 | 0 | 33.025 |

**Acceptance.** Hand-check cash, quantity, fees, realized P&L, and remaining basis through two partial exits and terminal mark. Exercise same-bar conflicts, tiny residual quantities, and the invariant that total recorded fees equal the sum across fills. Preserve compatibility for historical `sell all` results. [Existing trade artifacts](../../results.md#read-the-artifact-fields)

## Additional markets

Treat each stage as a separate execution contract with a narrow reference scenario.

| Stage | Specify before implementation | First acceptance case |
| --- | --- | --- |
| Exchange sessions | Trading calendar source and version, time zone, holidays, daylight-saving transitions, early closes, expected gaps, and raw or adjusted price basis and corporate-action treatment. | A signal before a closure executes at the next eligible open. An overnight closure does not register as a data gap. A split and a shortened session follow the chosen data and ledger policies. |
| Single-market shorting | Instrument and contract type, borrow or funding, margin and collateral, adverse price signs, realized P&L, and liquidation policy where applicable. | A hand-calculated round trip and a gap past protection reconcile cash, signed exposure, fees, and applicable financing. |
| Multi-asset portfolios | Independent market clocks, currency and conversion policy, simultaneous-order arbitration, position and capital limits, and per-asset and portfolio marking. | Two assets request the same limited cash at the same decision time. An explicit stable priority determines the result and survives replay. |

### Exchange session acceptance data

Use an explicit, versioned schedule of exchange-local dates and UTC open and close instants with declared coverage. Preserve its source, version, time zone, and contents with the dataset and bundle. Match daily candles to one scheduled session. For intraday data, anchor the grid to the session open and bound its final candle by the session close. Count absent scheduled observations as gaps. Drive signal closes, order age, and next-open execution from the recorded instants.

For the first exchange fixture, use the NYSE core session in `America/New_York`. Test a signal on November 27, 2024, that fills after Thanksgiving at 14:30 UTC on November 29. The shortened November 29 session closes at 18:00 UTC. Add a separate fixture for the March 8 to March 11, 2024, daylight-saving transition, where the core open moves from 14:30 to 13:30 UTC. [NYSE core hours](https://www.nyse.com/trade/hours-calendars) · [NYSE 2024 holiday and early closing notice](https://ir.theice.com/press/news-details/2023/NYSE-Group-Announces-2024-2025-and-2026-Holiday-and-Early-Closings-Calendar/default.aspx) · [IANA time-zone database](https://www.iana.org/time-zones/tz-link)

Define a split policy with supplied effective session dates and positive share ratios. For a causal normalized series, fix the quantity unit to the reference session. On each split's effective open, scale subsequent raw prices by the cumulative shares-per-reference-unit factor and divide raw volume by it. Run decisions, fills, and marks in those reference units and expose the factor for reconciling raw prices and quantities. In the synthetic two-for-one split fixture, a raw price move from 100 to 50 leaves the normalized price and marked position value equal. Include the action list and normalization policy in input identity. Keep raw candle values in the library's replay input so each run applies that policy exactly once.

### Single-market shorting acceptance data

Model a synthetic borrowed-asset short in one quote currency. One strategy chooses its side in the entry action. The collateral budget includes the initial margin and entry fee. Short proceeds stay in the cash balance as restricted proceeds, and the margin reserve also includes the committed initial margin. Mark equity as cash minus the cover liability at the candle close. A cover releases the proportion of proceeds, initial margin, entry fee, and accrued borrow cost allocated to that quantity.

Use a fixed borrow rate on the remaining entry notional and accrue by elapsed UTC seconds. Debit at each observed open for any interval since the preceding charge, and at the close if the position survives. Use the candle open as the known time for an intrabar exit. Adverse slippage reduces the short sale price and increases the cover price.

Define the maintenance trigger as cash divided by the product of absolute quantity and the sum of the fee-inclusive cover multiplier and maintenance ratio. At an observed open, maintenance liquidation has priority over a queued cover and gap protection. Within a candle, the lower adverse trigger wins between the stop and liquidation, with liquidation winning a tie. Adverse protection wins a dual touch with a target. Financing at the close can cause liquidation at that close. Record actual gap costs and retain any resulting deficit.

Start the hand-calculated fixture at 1,000 USD. A 255 USD budget at 50% initial margin and a 1% fee opens five units short at 100. Cash becomes 1,495 USD and the reserve is 750 USD. One day of borrowing at 100 basis points per day costs 5 USD. Covering at 90 costs 450 USD plus a 4.50 USD fee, leaving 1,035.50 USD. A separate gap to 125 beyond a stop at 120 covers at 125 and leaves 858.75 USD. Check a maintenance gap with a deficit and a split-reference exchange run as additional ledger and clock cases.

### Multi-asset portfolio acceptance data

Give each asset its own primary candles, execution clock, and causal source of signal values. Build one execution timeline from the observed UTC opens and closes. Process completed candles before opens at the same timestamp. Post intrabar exits at the containing candle's close so that an order on another asset cannot spend proceeds inferred from a candle that is still open. At a shared open, complete protective exits and eligible queued reductions before considering new commitments. Process competing entries and additions in asset declaration order.

Use one quote currency for shared cash and reject inputs outside that currency. Reserve any restricted proceeds and committed collateral before assessing an order's available funds. Enforce the portfolio's open-position limit and any per-asset sizing limit before recording a fill. Portfolio equity is shared cash plus each signed position marked at its most recent observable price. Show per-asset quantity, mark time, market value, and realized P&L alongside the portfolio totals.

For the reference case, give two assets a shared 1,000 USD balance. Have each request 750 USD at the same executable open, with zero fees and a price of 100 USD. The first declared asset buys 7.5 units, and the second receives an insufficient-cash decision. Mark the first asset at 120 USD and reconcile its 900 USD value plus 250 USD of shared cash to 1,150 USD of portfolio equity. Reverse declaration order to exercise the priority rule. Include a separate clock test where an asset's bar spans an intervening order on another asset, and a scheduled closure where only one asset can trade.

Preserve the declaration order, each leg's source and input data identity, the resolved shared policy, and independent clocks in the replay bundle. A new run with the same inputs must produce the same event sequence and result digest. A changed asset order or candle input must change the fingerprint.

Keep data-feed alignment independent of order routing until the portfolio model has its own acceptance fixtures and identity policy. [Named feed plan](05-data-feeds.md) · [Version gates](07-delivery-and-verification.md#version-and-replay-gates)
