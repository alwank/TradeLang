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
- The CLI validates and explains strategies and runs historical CSV or Parquet backtests. Execution semantics 1.1.0 define next-open fills, frozen stop-loss and take-profit levels, and a warmup-aligned buy-and-hold benchmark.
- Install TradeLang as a shell command with `uv tool install --python 3.12 .` and invoke it directly as `tradelang`.
- Run bundles use artifact schema 2 and include the exact inputs, equity curves, trades, ordered events, and runtime identity.
- The optional loopback API supports source inspection, strategy drafts and revisions, and historical candle imports.
- MkDocs provides a quickstart, runnable strategies, and language and execution references. CI checks the documentation build.
- The v1 contract now identifies its conformance clauses and failure phases. The internal indicator registry preserves existing signatures, readiness, and backtest results.
