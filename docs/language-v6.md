# TradeLang strategy language v6

Declare `tradelang 6` to trim or add to a single long position. DSL 6 also supports [ordered exits and trailing stops](language-v5.md). It selects execution semantics 6.0.0. [Grammar overlay](grammar-v6.lark) · [Typed strategy schema](schemas/strategy-v6.schema.json)

## Sell part of a position

```text
exit:
  rule first_trim when close == 115 price sell 25% of position
  rule second_trim when close == 121 price sell 3 units
  rule finish when close == 130 price sell all
```

Use `sell <ratio> of position` to sell a fraction in `(0, 1]` or `sell <amount> units` to request a base quantity. You can use either action on a single `when` exit, a named market exit, or a time exit. TradeLang samples the amount at the signal close and applies it to the quantity held at the next executable open. A request above the held quantity or too small to change the quantity is rejected. The first matching rule still owns the signal when its size is rejected.

`sell all` and protective exits close the entire remainder. After a partial exit at the open, the stop and target apply to the remaining quantity during that candle. An open protective exit takes priority over any queued action.

## Add to a held position

```text
scale:
  when close == 105 price
  add using 252.5 USDT
```

Place `scale` after `exit` and before `risk` or `backtest`. An add can use a fixed budget in the quote currency or a fraction such as `add using 20% of cash`. The budget includes the entry fee and must fit in uncommitted cash at the fill. Market inputs come from the signal close. If the sizing expression uses `equity`, it reads cash plus the held quantity marked at the candidate opening price.

TradeLang considers an add while holding, after the exit rules. A matching exit takes priority. A fill adds to the same position cycle and shares its active protection and original holding clock.

To apply an increment, put `quantity step 0.5 units` in the risk section after the protection rules. Strategy purchases and partial exit quantities round down to the increment. A rounded zero is rejected. A full close consumes the remainder. The benchmark uses its usual fee-inclusive buy-and-hold sizing.

## Run and inspect the example

```sh
tradelang backtest docs/fixtures/position-ledger/position.trade \
  --data docs/fixtures/position-ledger/position.csv \
  --metadata docs/fixtures/metadata.json \
  --out runs/position-ledger
```

The [strategy](fixtures/position-ledger/position.trade) and [candles](fixtures/position-ledger/position.csv) produce one closed position with five fills. The two trims realize 44.50 and 23.70 USDT after fees. The add increases remaining gross basis from 450 to 700 USDT. The final sale realizes 33.025 USDT, leaving 2,101.225 USDT in cash before display rounding.

Repeat with `--to-date 2024-01-04` and a fresh output directory to stop after the two trims. The position has 4.5 units with 450 USDT gross basis and 4.50 USDT in allocated entry fees. The final mark is 2,086.20 USDT, with 68.20 USDT realized net P&L.

Open **Position fill ledger** in the browser's open-position or trade inspector to check the fills, remaining basis, and realized amounts. The same evidence is under `ledger` in `events.jsonl`. [Position accounting](execution-semantics.md#position-accounting-in-semantics-600)
