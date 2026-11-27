# TradeLang portfolio language v9

Declare a portfolio with two through eight asset aliases, one starting balance, and a maximum number of open positions. The order of the `asset` declarations sets priority when commitments compete for cash. [Grammar](grammar-v9.lark) · [Typed portfolio schema](schemas/strategy-v9.schema.json)

## Bind the assets

Bind each alias in the JSON file passed to `--run-config`. Each asset has a single-market strategy file, primary candle file, and metadata file. Paths are relative to the JSON file. Give every asset a distinct market and match its quote currency to the portfolio currency. The portfolio supplies starting capital. The strategy files supply their own dates, fees, slippage, rules, and calendar. Optional per-asset `settings` override dates, fees, slippage, or parameters. Each asset can supply its own `profile` and named `feeds` entries using `data` and `metadata` paths. [Example asset bindings](fixtures/portfolio/inputs.json)

## Follow the shared clock and cash

Each asset observes its own candle opens and closes. At a shared timestamp, completed candles are processed first. Protective exits and queued reductions at observed opens settle before new commitments. New entries and adds then use declaration order. An intrabar exit uses the touched price and posts at the containing candle's close. Its event records the interval's opening time and the time its proceeds became available.

A fixed budget must fit the unreserved cash balance. An equity fraction uses the portfolio's marked equity. A long sized by stop risk is also capped by available cash and its configured allocation. For a short, restricted proceeds and initial margin are reserved for that position. Borrow charges consume the reserve and shared cash. Maintenance checks use that position's remaining collateral. An uncovered liquidation deficit reduces the shared balance.

Portfolio equity is shared cash plus signed market values. Each asset uses its most recent observed price. The portfolio records one mark after all activity at each timestamp. Its equal-capital buy-and-hold reference allocates a share to each asset at its own first eligible fill open. Exposure is measured by elapsed time. Sharpe is unavailable on the combined clock.

## Run the shared-cash example

Both assets request 750 USD at the same open. Alpha fills first for 7.5 units at 100 USD, leaving 250 USD for Beta's rejected request. Alpha marks at 120 USD and final equity is **1,150 USD**. Reverse the two declarations to give Beta priority. [Portfolio strategy](fixtures/portfolio/priority.trade) · [Inputs](fixtures/portfolio/inputs.json)

```sh
tradelang backtest docs/fixtures/portfolio/priority.trade \
  --run-config docs/fixtures/portfolio/inputs.json \
  --out runs/portfolio
```

Read shared cash, equity, and gross and net market values in `equity.csv`. Use `asset-marks.csv` for signed quantity, mark time, and realized P&L by asset. The `events.jsonl` sequence records the asset, available cash, and outcome for each competing entry. Each asset also has its own decision file and event journal so you can trace a decision to the exact bar and portfolio equity it used. The bundle preserves every strategy and candle input. [Replay configured runs](results.md#replay-configured-runs)

Compare compatible portfolio runs using their full-run metrics and equity curves. The overlay uses shared recorded mark timestamps and indexes each curve to its own starting capital. The common-start single-market benchmark reports portfolio pairs as unavailable.
