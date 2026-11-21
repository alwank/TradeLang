# Delivery roadmap

Ship additive changes in small pull requests. Each release boundary has a usable set of indicators with its own compiler, runtime, docs, and replay evidence.

| Work package | Depends on | Scope | Merge evidence |
| --- | --- | --- | --- |
| Foundation | Baseline | Extend function metadata, mixed field units, zero-argument signatures, and dataset context. Add compatibility and oracle fixture templates. | Existing ten-call vocabulary, AST, and execution parity. Internal tests exercise mixed units, zero arguments, and read-only timestamp context. |
| Shared first-release primitives | Foundation | Ranks 13–16, WMA, RMA, VWMA, and CMF. | Unit preservation, full-window masks, no-volume recovery, and independent comparisons. |
| Direction and momentum | Shared primitives | Ranks 1, 2, 7, and 9–11, DMI, Stochastic, Stochastic RSI, MFI, CCI, and Williams %R. | Per-field warmup, neutral and flat behavior, two-stage smoothing, point-scale examples, and large-window CCI results. |
| Bands and stops | Foundation and shared primitives | Ranks 4–6 and 12, Supertrend, Donchian, Keltner, and SAR. | Mixed-field typing, band equality and flip cases, Keltner source restrictions, SAR reset cases, and breakout timing. |
| Cumulative volume | Foundation | Ranks 3 and 8, VWAP and OBV. | UTC reset and input eligibility for VWAP, consistent CLI/HTTP preparation diagnostics, and correct volume output for OBV. |
| **First release** | All preceding packages | Ranks **1–16**, with 26 total built-ins. | Installed-wheel catalog, a hand-checked strategy for breakout and volume use, baseline parity, updated spec and changelog. |
| Trend, range, and bands | First release | Ranks 17–24, HMA, Ichimoku, Aroon, Momentum, True Range, Normalized ATR, Bollinger %B, and BandWidth. | A causal Ichimoku example, independent line readiness, seed-aligned range checks, and fractional scale examples. |
| Volume and EMA derivatives | First release | Ranks 25–28, ADL, RVOL, DEMA, and TEMA. | Prior-only RVOL window, cumulative recovery, and EMA cascade readiness. |
| **Second release** | Both extended packages | Ranks **1–28**, with 38 total built-ins. | Full catalog and wheel tests, causal and missing-value property checks, and end-to-end performance evidence. |
| Adaptive smoothing and regression | Second release | Ranks 29, 30, and 35, ALMA, KAMA, and LSMA. | Long-period cost measurements, seed fixtures, and centered regression checks. |
| Regime, momentum, and exits | Second release | Ranks 31–34 and 36, AO, CHOP, Ultimate Oscillator, TSI, and Chandelier Exit. | Range and denominator cases, sign and smoothing fixtures, and a next-open exit scenario. |
| Confirmed swing events | Second release | Rank 37, Zig Zag. | Suffix-invariant pivot confirmations and an executable direction-change strategy. |
| Lower-timeframe data and replay | Foundation and second release | Prepare role-based secondary input, alignment, workload admission, and versioned publication for rank 38. | Legacy single-input replay, dataset pairing tests, and identity and atomic publication evidence using internal fixture calls. |
| Rolling Volume Profile | Lower-timeframe data and replay | Rank 38, Volume Profile. | Public calls, both input paths, histogram parity, workload bounds, and end-to-end replay and documentation. |
| **Final release** | All packages | Ranks **1–38**, with 48 total built-ins. | Every rank maps to a public call, tests, doc entry, and release note. All source, wheel, deep, docs, and artifact gates pass. |

The rank numbers are stable references for review. The roadmap moves reusable primitives earlier so the first release can reuse code without delaying later families.

## Complete each public indicator change

1. Add the independent fixture and the compiler and evaluator tests first. Include a failure case for literal arguments, missing input, or a meaningful indicator-specific boundary.
2. Add the descriptor, kernel, and any narrowly scoped runtime support. Keep registry, grammar, schema, and docs changes in the same public PR. Preserve the existing limits except where the catalog supplies a narrower bound.
3. Update the [indicator reference](../../indicators.md) with syntax, inputs, scales, first ready rows, and edge behavior. Update the [language spec](../../language-spec.md) for cross-cutting semantics, [examples](../../example-strategies.md) for release walkthroughs, and the [changelog](../../../CHANGELOG.md) for public additions. For Volume Profile also update the [candle data](../../candle-data.md), [CLI](../../cli.md), [HTTP API](../../local-api.md), and [results](../../results.md) references.
4. Record changed call names, formulas and references, verification commands, fixture identities, benchmark results, and baseline differences in the PR. Compare CLI and HTTP cases where input preparation changes. Identify accepted charting and library variants.
5. Before release, run the [verification matrix](07-verification.md#conformance-matrix), build the wheel, and run source and installed-wheel tests. Pin the released runtime for replay fixtures and record the version decisions.

## Versioning and rollback

| Change | Proposed treatment |
| --- | --- |
| New calls and compatible field types on those calls | Additive language v1 features. Keep strategy node shapes and record serialization compatible. Ship with a package release and document the minimum version for each shipped wave. Older packages reject unfamiliar names. |
| Legacy formula, warning, or fill behavior | Investigate with the pinned baseline corpus. If a legacy behavior change is required, document and version it as a separate semantic change with its own fixtures. |
| Secondary dataset signature and bundle | Use a new versioned manifest shape for profile-enabled runs and pin its signature rules. Keep existing single-input bundle readers and identity behavior compatible. Include both input hashes in the profile signature and compare old and new bundles in release checks. |
| Failed marker or regression | Revert the affected catalog package together with its grammar, schema, and reference entries. If the runtime foundation causes a failure, revert dependent public packages first. Preserve already published bundle bytes and replay them with their recorded runtime. Forward-fix incompatible replay before re-releasing. |

[Baseline publishing rules](../../publishing.md), [Artifact format and replay](../../results.md), [Existing compatibility tests](../../../tests/test_registry_parity.py)
