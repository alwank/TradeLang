# Changelog

## 0.1.0 (unreleased)

- TradeLang strategy language v1 supports typed arithmetic, named numeric and Boolean conditions, built-in indicators, and fee-inclusive position sizing.
- WMA, RMA, and VWMA support explicit numeric series or default to close. CMF measures volume-weighted money flow.
- Add OBV, UTC-day VWAP, Donchian and Keltner Channels, Supertrend, and DMI.
- Add Stochastic, Stochastic RSI, MFI, CCI, Williams %R, and Parabolic SAR.
- Add HMA, Ichimoku, Aroon, Momentum, True Range, Normalized ATR, Bollinger %B and BandWidth, ADL, RVOL, DEMA, and TEMA.
- Add ALMA, KAMA, Awesome Oscillator, Choppiness, Ultimate Oscillator, TSI, LSMA, Chandelier Exit, and confirmed Zig Zag.
- Add rolling Volume Profile with paired lower-timeframe candles and schema 3 run bundles for profile runs.
- Use `tradelang 1` to declare the language version explicitly. The directive is optional, and existing `dsl 1` declarations still work.
- Omit `market` and `timeframe` to use the selected dataset's symbol and candle duration. Keep either declaration to require a match.
- The CLI validates and explains strategies and runs historical CSV or Parquet backtests. Execution semantics 1.1.0 define next-open fills, frozen stop-loss and take-profit levels, and a warmup-aligned buy-and-hold benchmark.
- Install TradeLang as a shell command with `uv tool install --python 3.12 .` and invoke it directly as `tradelang`.
- Single-market runs with only primary candles use artifact schema 2. Their bundles include the exact inputs, equity curves, trades, ordered events, and runtime identity.
- The optional loopback API supports source inspection, strategy drafts and revisions, and historical candle imports.
- MkDocs provides a quickstart, runnable strategies, and language and execution references. CI checks the documentation build.
- The v1 contract now identifies its conformance clauses and failure phases. The internal indicator registry preserves existing signatures, readiness, and backtest results.
- Validation and explanation display warnings in text output. Syntax, indicator calls, and incompatible execution windows provide more specific diagnostics.
- The local supervisor supports custom loopback API and browser ports. Integration tests start and verify isolated services and libraries.
- Run warnings count missing bars inside the execution window. Dataset summaries also report pre-window gaps. Optional metrics outside the numeric range report an unavailable reason.
- Completed runs support candle inspection with rule outcomes, sample times, fill-time sizing, and linked events.
- Dataset-aware checks estimate backtest workload before execution. The worker budget rejects runs whose required resident arrays already exceed it.
- Opt into DSL 2 with `tradelang 2` to use typed run parameters, named indicator periods and records, Boolean history, and explicit unavailable-value handling. DSL 2 derives warmup and auxiliary inputs from expressions reachable from execution rules and warns when a point-scale threshold uses a percentage.
- The browser checks drafts while you edit, reports independent errors, and offers source-bound fixes. Indicator signatures and record completion show the applicable argument and field information.
- Reuse named run presets or apply one-run overrides for dates, capital, costs, and strategy parameters. Configured bundles include a replay configuration with the recorded candle inputs.
- Save and run a draft in one action. If submission fails after a save, retry the captured revision and inputs from the editor.
- Compare compatible runs against one fee-inclusive buy-and-hold reference over a shared executable window, with explicit reasons for unavailable pairs.
- Use `tradelang 3` to read a named higher-timeframe feed and align completed secondary values to primary candle closes. Artifact schema 4 records the feed input and alignment policy for replay.
- Use `tradelang 4` to size a long against its modeled stop loss, cap the allocation, and inspect the calculated quantity and binding constraint.
- Use `tradelang 5` for ordered market and time exits, trailing stops that activate at the next open, and optional signal-order expiry across gaps.
- Use `tradelang 6` to trim a long by fraction or units and add to it with available cash. Fill records show weighted-average basis and realized P&L.
- Use `tradelang 7` to execute on recorded exchange sessions and normalize supplied splits into reference units.
- Use `tradelang 8` to backtest a short with a collateral budget, elapsed-time borrow charges, partial covers, and maintenance liquidation.
- Use `tradelang 9` to backtest a portfolio from the CLI or browser with independent asset clocks, shared cash, and deterministic order priority. Artifact schema 5 records each asset's strategy and inputs for replay.
- In the browser, validate and run a portfolio with pinned strategy revisions and inspect candle decisions by asset.
- Portfolio ledger overflow reports `E_NUMERIC_EXECUTION` and leaves no published bundle.
