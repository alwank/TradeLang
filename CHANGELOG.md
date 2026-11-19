# Changelog

## 0.1.0 (unreleased)

- DSL 1 supports typed arithmetic, named numeric and Boolean conditions, ten indicators, and fee-inclusive position sizing.
- The CLI validates and explains strategies and runs historical CSV or Parquet backtests. Execution semantics 1.1.0 define next-open fills, frozen stop-loss and take-profit levels, and a warmup-aligned buy-and-hold benchmark.
- Run bundles use artifact schema 2 and include the exact inputs, equity curves, trades, ordered events, and runtime identity.
- The optional loopback API supports source inspection, strategy drafts and revisions, and historical candle imports.
- MkDocs provides a quickstart, runnable strategies, and language and execution references. CI checks the documentation build.
