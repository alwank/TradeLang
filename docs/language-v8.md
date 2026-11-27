# TradeLang strategy language v8

Declare `tradelang 8` to backtest a borrowed-asset short in one market. Choose the position direction in the entry action. DSL 8 also runs long strategies with the existing order forms. [Grammar overlay](grammar-v8.lark) · [Typed strategy schema](schemas/strategy-v8.schema.json)

## Set the collateral budget and borrow rate

`short using 255 USD` reserves a fixed budget for initial margin and the entry fee. `short using 25% of equity` uses a fraction of the flat account's equity. In the `backtest` block, add `initial margin`, `maintenance margin`, and `borrow` after the calendar. Maintenance must be positive and below the initial margin. Initial margin is at most 100%. The borrow rate ranges from zero up to, and excluding, 10,000 basis points per day.

The short fill price is the opening reference reduced by adverse sell slippage. TradeLang sizes the position within the fee-inclusive margin budget and rounds down when a quantity step applies. The cash balance receives sale proceeds less the entry fee. Reserved cash consists of the sale proceeds and the committed initial margin. At a close, equity equals cash minus absolute quantity times the close price.

## Cover the position

Use `cover all`, `cover 50% of position`, or `cover 2 units`. Ordered rules can combine market conditions and holding durations. A partial cover releases proceeds, initial margin, entry fees, and accrued borrow costs in proportion to the quantity covered. A full cover consumes any remainder even when a quantity step applies.

Short stops sit above the entry price and targets sit below it. A trailing stop derived from a completed close can move down at the next observed open. A cover increases the reference price by adverse buy slippage. Net profit equals released sale proceeds less cover notional, both fees, and allocated borrow costs. Trade return divides net profit by the initial margin plus the entry fee.

## Reconcile borrowing and liquidation

Borrowing charges apply to the remaining entry notional for elapsed UTC time, including time between recorded sessions. The engine accrues at an observed open for elapsed time since the previous charge and again at the close if the position survives. An intrabar close uses the candle open as its execution time for borrowing.

The liquidation trigger uses the cash balance, absolute quantity, maintenance ratio, and fee-inclusive cover costs. If `f` is the fee rate, `s` the slippage rate, and `m` the maintenance ratio, the trigger is `cash / (abs(quantity) × ((1 + s) × (1 + f) + m))`.

An open at or above the maintenance trigger covers the full position at the observed open before any queued order or stop. During a candle, the lower of the stop and maintenance triggers acts first, with liquidation winning a tie. Either adverse trigger has priority over a target when both directions touch in one candle. A close borrow debit can cause liquidation at that close. If the cover costs more than the remaining cash, the final balance reflects the deficit, and the run records insolvency.

The financing and collateral terms are fixed simulation inputs. Choose `calendar 24x7` or supply a recorded exchange clock and price basis with `calendar session`. [Exchange sessions and split-reference units](language-v7.md)

## Run the short example

The fixture shorts five units at 100 USD from 1,000 USD of starting capital. It reserves 750 USD and pays 5 USD of entry fees. One day of borrow costs 5 USD. The cover at 90 USD and its 4.50 USD fee leave **1,035.50 USD**. [Strategy](fixtures/short/round-trip.trade) · [Candles](fixtures/short/round-trip.csv) · [Metadata](fixtures/short/round-trip.json)

```sh
tradelang backtest docs/fixtures/short/round-trip.trade \
  --data docs/fixtures/short/round-trip.csv \
  --metadata docs/fixtures/short/round-trip.json \
  --out runs/short-round-trip
```

The bundle records signed quantities on equity marks and fill ledgers. The trade table gives the positive filled quantity and direction, initial collateral, and borrow cost. Use `events.jsonl` to reconcile cash debits and match a liquidation fill to its maintenance trigger. Use the recorded configuration to replay the run. [Replay configured runs](results.md#replay-configured-runs)
