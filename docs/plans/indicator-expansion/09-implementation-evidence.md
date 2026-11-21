# Indicator expansion implementation evidence

The candidate implements all 38 ranked indicator families and exposes 48 total calls in DSL v1. The source baseline for the expansion is `6da1e38f822800d53f5c37d0a96d0b578735af4b`. Package builds use the unreleased `0.1.0` version. The published strategy AST retains schema 1. The engine keeps semantics 1.1.0 and records artifact schema 3 only for runs with a profile input.

## Contract evidence

| Work package | Evidence |
| --- | --- |
| Registry and artifacts | The registry test compares 48 names and all field names against the packaged and documentation schema mirrors. The full expansion catalog compiles as a single strategy, and its typed AST validates against the HTTP schema. Tests cover mixed units, normalized calls, and formerly valid binding names. [Registry checks](../../../tests/test_function_registry.py), [Catalog compilation](../../../tests/test_indicator_expansion.py) |
| Ranks 1–16 | Hand-calculated examples check trend direction, independent warmup, UTC-day boundaries, oscillator smoothing, neutral outputs, and volume scales. A Donchian breakout filtered by RVOL signals before the next-open fill at 120. [Numeric checks](../../../tests/test_indicator_expansion.py), [Runnable strategy](../../examples/05-donchian-volume.trade) |
| Ranks 17–28 | Checks cover each family, including raw Ichimoku outputs and explicit displacement, most recent ties in Aroon, full-interval momentum, fractional Bollinger outputs, prior-only volume, and EMA cascades. [Numeric checks](../../../tests/test_indicator_expansion.py) |
| Ranks 29–37 | Checks cover fractional ALMA centering, adaptive seed and recovery, midpoint momentum, true-range regime filters, large baselines for rolling regression, and confirmed Zig Zag. The causality matrix compares exact outputs and masks after truncating and mutating the suffix for ranks 1–37. [Numeric and causality checks](../../../tests/test_indicator_expansion.py) |
| Rank 38 | Paired CLI and HTTP inspection, next-open execution, CSV and Parquet identity, child file tampering, and profile workload limits have dedicated tests. An independent histogram compares profile values and prefix stability on generated windows. [Volume Profile checks](../../../tests/test_volume_profile.py) |
| Baseline and replay | The pinned legacy corpus compares the ten originals against the earlier evaluator and compiler. Profile tests recompute the schema 3 signature, verify input file hashes, and replay a bundle with the recorded inputs. [Baseline parity](../../../tests/test_registry_parity.py), [Identity checks](../../../tests/test_identity_protocol.py), [Replay documentation](../../results.md#replay-a-volume-profile-run) |

Volume Profile compares bin volumes and the value-area threshold exactly using integer units of binary64 volume. The output levels use binary64 prices. The profile reuses canonical calls across selectors and stores the secondary input with its role, source bytes, and both identity hashes.

## Vendor comparisons

The offline fixture stores the synthetic OHLCV input, its SHA-256, arguments, and output samples including warmup rows. TA-Lib Python 0.8.3 with C core 0.8.3 produced 14 comparison families. Eleven match directly. OBV matches after correcting the starting offset. Stochastic K matches from TA-Lib's shared K/D output start, two rows later than TradeLang's K. ALMA differs starting at index 4, where TA-Lib floors the Gaussian center and TradeLang uses 1.28. An independent calculation checks both ALMA variants. The same fixture compares LEAN's documented Bollinger formulas at revision `32a302a9a0fde64c0435798c0c4cb2c2309873ed` and TradingView's documented prior-bar RVOL formula. Those two comparisons use formula-derived expectations on synthetic inputs. [Reference fixture](../../../tests/fixtures/indicator-expansion/vendor-reference.json), [Offline replay](../../../tests/test_indicator_references.py), [TA-Lib ALMA](https://ta-lib.org/functions/alma.html), [LEAN Bollinger source](https://github.com/QuantConnect/Lean/blob/32a302a9a0fde64c0435798c0c4cb2c2309873ed/Indicators/BollingerBands.cs), [TradingView RVOL](https://www.tradingview.com/support/solutions/43000635874-how-do-we-calculate-relative-volume-and-relative-volume-at-time/)

## Legacy benchmark

The established ten-indicator harness measured five runs per size in separate processes on a Mac14,2 arm64 host with 16 GiB RAM, macOS 26.2, Python 3.12.16, and NumPy 2.5.5. Its p95 includes the initial cold run. [Legacy harness](../../../scripts/benchmark.py)

| Minute rows | Median baseline → candidate | p95 baseline → candidate | Peak RSS baseline → candidate |
| ---: | ---: | ---: | ---: |
| 1,440 | 12.42 → 12.66 ms | 151.82 → 125.62 ms | 82.8 → 81.9 MiB |
| 14,400 | 105.94 → 104.83 ms | 216.86 → 211.04 ms | 93.4 → 93.4 MiB |
| 100,800 | 717.16 → 721.17 ms | 828.95 → 816.67 ms | 164.3 → 161.4 MiB |
| 999,360 | Candidate 7.16 s | Candidate 7.39 s | Candidate 644.1 MiB |

## Expanded benchmark

The expansion harness measures compile, primary and child input import, preparation, evaluator, and full backtest separately. It reports median, p95, maximum process RSS, and estimated profile work units. Reproduce a sample from the repository root. [Expansion harness](../../../scripts/benchmark_indicators.py)

```sh
uv run --locked --extra api python scripts/benchmark_indicators.py \
  --workload profile-dense --rows 100800 --repeats 5
```

| Window size | CCI evaluator median | ALMA evaluator median |
| ---: | ---: | ---: |
| 20 | 5.85 ms | 3.67 ms |
| 500 | 65.80 ms | 48.33 ms |
| 10,000 | 1.652 s | 696.22 ms |

Each of these samples used 100,800 primary rows. Wide CCI maintains an ordered multiset and exact rolling subtotals. ALMA evaluates each weighted window in bounded batches. The release gate uses offline correctness tests. Wall-clock measurements provide local performance evidence.

At period 10,000, increasing the input from 50,400 to 100,800 rows raised the CCI evaluator median from 0.749 to 1.652 seconds and the ALMA evaluator median from 0.304 to 0.696 seconds.

| Catalog workload | Primary rows | Distinct evaluated calls | Evaluator median / p95 | Backtest median | Peak RSS |
| --- | ---: | ---: | ---: | ---: | ---: |
| First release | 100,800 | 16 | 1.461 / 1.468 s | 1.748 s | 170.0 MiB |
| Mixed nested indicators | 100,800 | 11 | 1.083 / 1.090 s | 1.357 s | 165.8 MiB |
| Mixed nested indicators | 999,360 | 11 | 10.804 / 10.853 s | 13.484 s | 727.9 MiB |

| Volume Profile layout | Primary / child rows | Work units | Preparation median | Evaluator median / p95 | Backtest median | Peak RSS |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Sparse | 100,800 / 201,600 | 1,409,930 | 155.73 ms | 369.28 / 370.41 ms | 647.66 ms | 253.2 MiB |
| Dense | 100,800 / 201,600 | 26,061,394 | 154.46 ms | 2.622 / 2.636 s | 2.893 s | 253.5 MiB |

The dense workload with 129,600 primary rows returned `E_DATA_LIMIT` at the configured 30-million-unit ceiling.

## Local release verification

| Check | Result |
| --- | --- |
| Locked source environment | 800 passing tests |
| Source distribution and installed wheel | Built `0.1.0` and ran 800 passing tests from the installed wheel |
| Deep conformance profile | 519 passing tests. The independent profile histogram and prefix test passed 2,000 generated cases. |
| Static checks and documentation | Ruff, mypy, grammar and schema mirror checks, and strict MkDocs passed |
| Production wheel | The locked no-dev installation validated the original golden strategy. The dependency inventory completed and pip-audit 2.10.0 reported zero known vulnerabilities. |

All three test runs emitted the existing Starlette TestClient deprecation warning.
