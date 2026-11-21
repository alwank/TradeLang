# Verification

Use this matrix to verify every indicator from the DSL through strategy and artifact behavior. Treat existing parity tests as a compatibility check and the new scalar oracles as independent checks of the proposed formulas.

## Conformance matrix

For each of the 38 ranks, record its reference, exact arguments, hand-checked rows, expected first ready index per field, accepted tolerance, known reference differences, and the CI tests that exercise it.

| Area | Required cases and evidence |
| --- | --- |
| Catalog and packaging | Check each enabled name in the registry, both grammar files, both strategy schema files, the resulting OpenAPI schema, and the reference. Compile the full catalog from the installed wheel. Verify that existing names still resolve. Run Lark strict grammar checks and keep case and identifier prefix tests. |
| Calls and diagnostics | Test every overload, omitted and explicit close normalization, finite fractions and factors, valid and invalid boundaries, ordered periods, wrong arity, wrong source unit, invalid field, record-as-number rejection, and a valid field lookback. Preserve error precedence and byte spans. Assert correct unit metadata for both fields in a mixed record. |
| Kernels | For every indicator, compare a deterministic hand-computed case and an independent scalar implementation with the production output. Test short and empty evaluation prefixes, a long complete input, minimum and maximum valid parameters, flat series, ties, step changes, lack of volume, and missing recovery where applicable. Retain formula-specific cases from the catalog pages. |
| Dimensions and scale | Check price, volume, and ratio inputs where allowed. Verify price subtraction and a price-unit comparison, an OBV comparison in volume units, point-based oscillator comparisons, and percentage literals with fractional measures. Verify the readiness of a selected field, its offset, and a crossing that uses it. |
| Availability and numerical limits | Compare masks exactly. Exercise nonfinite intermediates, valid neutral cases, a true zero denominator, and a source expression that creates a hole. Check deterministic recovery and counter totals for repeated calls and multiple field selectors. Verify that a runtime hole changes available signals without shifting structural warmup. |
| Causality and order timing | Run every family on prefixes and append or perturb a suffix. Compare all earlier finite values and masks exactly within one build. Use future extremes for Zig Zag and Ichimoku and late child candles for Volume Profile. In engine runs, compare events within a fixed shared execution window and assert next-open fills, unchanged protection phases, and frozen risk sampling. |
| Transports and identities | Run CLI validate, explain, and backtest. Compare the local HTTP validate/explain projection, diagnostics, availability of data compatibility, and OpenAPI output. Check CSV and Parquet fixtures. Compare same-build replay fingerprints and logical digests. Compare legacy strategy results across builds on identical input and dependencies. |
| Volume Profile input and artifacts | Exercise missing and unknown inputs, invalid metadata pairings, gaps, boundary alignment, limits, replay with both files, tampering, and a failed run with no partially published bundle. See the [Volume Profile acceptance cases](06-zigzag-and-volume-profile.md#bound-and-verify-the-workload). |

Use a scalar oracle that takes ordinary Python collections and recomputes the formula directly. Avoid calling the production registry, rolling kernels, or cached intermediate stages in that oracle. Prefer exact equality for masks, statuses, categorical values, dimensions, fixture values with an exact binary64 representation, and legacy parity. For new finite floating-point fixtures, start with `rtol=1e-10` and an absolute tolerance of `1e-12` times a documented natural scale of the output. Set the scale from the fixture design. Review tighter or looser per-indicator limits with cancellation and long-window evidence, checking crossing outcomes separately from numeric closeness.

## Cross-platform comparisons

1. Record tool versions, source revision, data hash, price input, parameters, and variant for every comparison. Use official TA-Lib C or a wrapper version that exposes the tested function, and use an identified LEAN revision. Store any TradingView exports as fixed fixture inputs with the script settings and recorded symbol, timeframe, dates, and feed. Keep tools for generating external fixtures outside production dependencies and keep CI replay offline.
2. Capture the first output row and unavailable mask before comparing values. Preserve differences attributable to period definitions, seeding, price series, and output alignment in the evidence. Apply explicit conversions, such as going from TA-Lib NATR percent points to a fraction. Compare VWAP within known anchor windows and OBV increments where seed offsets differ.
3. Classify each comparison as an agreed variant, expected semantic difference, or unexpected mismatch. For an expected difference, specify the first divergent row, the source rule, and a minimal fixture that demonstrates the TradeLang choice. For any indicator without a matching reference variant, use the independent oracle and hand calculation as acceptance evidence.
4. Keep fixtures for old contracts and expected new results independent. When a legacy strategy differs, trace the first changed node, sample, or event before changing an expected value. Use the project's release process for deliberate semantics changes.

[TA-Lib releases](https://github.com/TA-Lib/ta-lib/releases), [LEAN source](https://github.com/QuantConnect/Lean/tree/master/Indicators), [Pine reference](https://www.tradingview.com/pine-script-reference/v6/), [Current parity test](../../../tests/test_registry_parity.py), [Identity tests](../../../tests/test_identity_protocol.py)

## Performance and resource checks

1. Run the existing baseline benchmark at 1,440, 14,400, and 100,800 rows. Keep its original ten-indicator workload intact. Extend the harness with separately named workloads for the first release, mixed nested calls, large-period kernels, repeated fields from one call, the largest supported single dataset, and Volume Profile with sparse and dense bins. A 999,360-row minute test fits complete days under the one-million-row limit.
2. Measure separate compile, import, evaluator, and end-to-end run costs. For profile runs also record child-to-parent mapping time, preflight work units, and histogram scan time. Record five measured runs after warmup, the median, p95, peak process RSS, the dataset sizes and periods, hardware, interpreter, dependency versions, and commit. Use isolated processes when comparing peak RSS.
3. Investigate a baseline regression over 10% in median time or peak RSS on identical environments and inputs. Treat this as a proposed review trigger and rerun to estimate variance. For new kernels, test scaling as row count doubles and compare periods 20, 500, and 10,000 where supported. Benchmark CCI's mean absolute deviation, long-window ALMA, and multi-field call caching explicitly. Verify bounded behavior at the admission limits and clean rejection one step beyond.
4. Keep small deterministic cases in the standard CI suite. Use the existing deep profile for expanded generative cases and replay comparisons. Keep wall-clock performance on a controlled benchmark runner or manual review packet.

Run the standard contributor checks from the repository root. These check source, linting, types, packaging, and public documentation.

```sh
uv sync --locked --extra api
uv run --locked --extra api pytest
uv run --locked --extra api ruff check src tests scripts
uv run --locked --extra api mypy src
uv build
uv run --no-project --python 3.12 --with-requirements docs/requirements.txt mkdocs build --strict
```

Use the installed-wheel steps and the `language-deep` job in the existing workflow for release verification. [Contributor checks](../../../CONTRIBUTING.md), [CI workflow](../../../.github/workflows/test.yml), [Benchmark harness](../../../scripts/benchmark.py)
