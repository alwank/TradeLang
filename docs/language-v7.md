# TradeLang strategy language v7

Declare `tradelang 7` and use `calendar session` to run on a recorded exchange schedule. The schedule and price basis come from candle metadata. DSL 7 also supports `calendar 24x7`. [Grammar overlay](grammar-v7.lark) · [Typed strategy schema](schemas/strategy-v7.schema.json)

## Attach a recorded exchange schedule

Use metadata schema 2 with `calendar: "session"`. In `session_schedule`, supply the exchange identifier, IANA time zone, source, version, inclusive coverage dates, and ordered sessions. Every session supplies a local trading `date` and UTC `open` and `close` instants. The declared coverage represents the complete schedule for that range. Covered dates without sessions are market closures.

Timestamp daily candles at the session open. Intraday grids start at each session open and their final candle ends at the actual scheduled close. The strategy's window uses exchange-local trading dates. Signals observe the recorded close and fill at the next eligible observed open. Order age uses the elapsed time from that close. Gap policy counts missing scheduled candles.

Use the same session schedule and price-basis policy on a named feed or Volume Profile input. Alignment uses actual closes and counts a gap after a scheduled secondary close is missing. A feed's maximum age uses elapsed time. Intraday VWAP resets at each session open.

## Choose the price basis

| Basis | Input and execution units |
| --- | --- |
| `raw_equity` | Use submitted OHLCV directly for a window that needs no split adjustment. |
| `split_reference` | Supply raw OHLCV and a `splits` array. Each item supplies its effective session `date`, `new_shares`, and `old_shares`. An empty list indicates zero splits. |

The factor starts at one. At each split's effective session, `split_reference` multiplies subsequent prices by the cumulative share ratio and divides volume by it. Prices, quantities, protection, and marked equity use reference units. Divide a fill price by the factor to recover its raw share price. Multiply its quantity by the factor to recover raw shares. Cash dividends and other corporate actions are outside this policy.

## Replay the holiday and split example

The [strategy](fixtures/exchange/session.trade), [candles](fixtures/exchange/session.csv), and [metadata](fixtures/exchange/session.json) use NYSE core session dates and synthetic prices and split data. [NYSE 2024 trading calendar](https://www.nyse.com/publicdocs/ICE_NYSE_2024_Yearly_Trading_Calendar.pdf)

```sh
tradelang backtest docs/fixtures/exchange/session.trade \
  --data docs/fixtures/exchange/session.csv \
  --metadata docs/fixtures/exchange/session.json \
  --out runs/exchange-session
```

The November 27 signal fills at 14:30 UTC on November 29. That shortened session closes at 18:00 UTC. A synthetic two-for-one split makes the next raw open of 50 equivalent to 100 per reference unit. The last sale fills at 120 per reference unit and leaves 1,200 USD in cash.

The bundle preserves raw candles and the exact schedule and split list. Its `run-config.json` points to those inputs. In the browser, select the same metadata file under **Metadata JSON** when importing candles. Candle inspection shows the recorded close and shares per reference unit. DSL 7 selects execution semantics 7.0.0. [Replay configured runs](results.md#replay-configured-runs)
