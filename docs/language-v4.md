# TradeLang strategy language v4

Declare `tradelang 4` to size a long by its modeled loss at a protective stop. DSL 4 includes [DSL 2 parameters and expressions](language-v2.md) and [DSL 3 named data feeds](language-v3.md). [Grammar overlay](grammar-v4.lark) · [Typed strategy schema](schemas/strategy-v4.schema.json)

## Size a long by stop loss

```text
entry:
  when close >= 100 price
  buy risking 2% of equity max allocation 50% of equity
exit:
  when false
  sell all
risk:
  stop loss 10%
```

Use `buy risking <ratio> of equity` and declare a `stop loss` in the risk section. Each ratio must be greater than zero and at most 100%. The optional `max allocation <ratio> of equity` caps the fee-inclusive entry debit. If you omit it, the available cash is the allocation limit. The stop accepts a ratio of the entry fill or a price distance such as `2 * ATR(14)`.

At the signal close, TradeLang samples market expressions used for the stop and sizing. At the next open, the flat account's cash supplies equity. TradeLang computes the proposed entry price with adverse buy slippage and anchors the stop to that proposed price. The model values an exit at a touch of that stop with sell slippage and fees.

```text
unit loss = fee-inclusive entry debit per unit - net stop proceeds per unit
quantity = min(risk budget / unit loss, cash / entry debit per unit,
               allocation limit / entry debit per unit)
```

The risk budget and allocation limit are their respective ratios times equity. TradeLang rounds fractional quantity toward zero as needed to keep the debit and modeled loss within their limits. An invalid stop or sizing proposal produces an entry rejection before the ledger changes. When a candle opens through the stop, including at the entry open, the realized loss can exceed the modeled loss. [Execution phases](execution-semantics.md#event-order-within-a-candle)

## Run and inspect the example

From a checkout, backtest the [strategy](fixtures/risk-sizing/stop-risk.trade) on the [three sample candles](fixtures/risk-sizing/stop-risk.csv).

```sh
tradelang backtest docs/fixtures/risk-sizing/stop-risk.trade \
  --data docs/fixtures/risk-sizing/stop-risk.csv \
  --metadata docs/fixtures/metadata.json \
  --out runs/stop-risk
```

The entry fills at 101 USDT with a stop trigger of 90.90 USDT. Fees and slippage make the modeled loss 12.91891 USDT per unit. The risk budget is 20 USDT and the strategy buys about 1.548 units. The third candle touches the stop and closes the trade for a loss of 20 USDT to displayed precision.

To compare an allocation-limited run, repeat the command with `--param allocation_limit=0.15` and a fresh output directory. The entry debit is capped at 150 USDT, which reduces the quantity to about 1.470 units.

In the browser, inspect the fill candle and open **Stop-based sizing** to see the price inputs, limits, loss per unit, quantity, and binding constraint. The entry fill in `events.jsonl` records the same evidence in `trace.risk_sizing`. DSL 4 selects execution semantics 4.0.0. [Replay configured runs](results.md#replay-configured-runs)
