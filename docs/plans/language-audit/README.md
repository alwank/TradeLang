# TradeLang language improvement plan

If you maintain TradeLang, use these plans to turn the audit findings into reviewable changes. Start with trustworthy explanations and results, then make strategies easier to write and rerun. Add secondary feeds and richer execution after those foundations are in place.

**Status** · The implementation checklist is complete. The original baseline was DSL 1, typed strategy schema 1, execution semantics 1.1.0, and artifact schemas 2 and 3. The delivered portfolio path uses DSL 9 and execution semantics 9.0.0. [Completion audit](07-delivery-and-verification.md#completion-audit) · [Version and replay contract](../../results.md#compare-and-replay-runs)

## Delivery order

| Release milestone | Work in order | Release outcome |
| --- | --- | --- |
| Trustworthy results | Isolate integration tests first. Repair traces, warnings, metrics, and diagnostics. Add selected-bar inspection and bounded run preparation. | An author can account for a fill, diagnose a no-trade run, and distinguish incomplete data from an unavailable metric. [Diagnostics](01-diagnostics-and-traces.md) · [Results](02-readiness-and-results.md) |
| Reusable strategy logic | Add compile-time arguments, typed parameters, record bindings, and Boolean history. Implement reachable warmup under the new semantic version. Add explicit conditional and fallback expressions. | One named MACD record and two configurable periods are enough to express a trend change and replay the exact run. [Language composition](03-language-composition.md) |
| Faster experiments | Add shared run configuration, editor assistance, an exact-revision save-and-run action, and a common-start benchmark. Editor work that uses existing contracts can start earlier. | An author can change one input, run the same strategy, and compare the results on a disclosed benchmark window. [Author workflow](04-author-workflow.md) · [Benchmark](02-readiness-and-results.md#comparable-benchmark) |
| Broader strategies | Add a same-market secondary timeframe, then single-position risk and exit improvements. Introduce quantity changes and broader market support in later slices. | Multi-timeframe signals stay causal. New execution features retain explicit order and accounting rules. [Data feeds](05-data-feeds.md) · [Execution](06-execution-capabilities.md) |

Use the [implementation checklist](08-implementation-checklist.md) to select work by dependency and see what still needs evidence. Use the [delivery and verification plan](07-delivery-and-verification.md) for version decisions, release checks, and recorded results. Coordinate browser changes with the existing [research terminal plan](../research-terminal/README.md).

## Audit coverage

| Finding | Planned resolution |
| --- | --- |
| Crossings omit the prior samples, and lookback children display the current bar. | [Sample-aware traces](01-diagnostics-and-traces.md#sample-aware-traces) |
| Zero-trade runs lack decision evidence, including when a compatible Volume Profile input has zero volume. | [Selected-bar inspection](01-diagnostics-and-traces.md#selected-bar-inspection) |
| RSI warnings disappear through a binding, and other point-scale indicators accept percentage thresholds silently. | [Scale-aware diagnostics](01-diagnostics-and-traces.md#scale-aware-diagnostics) |
| Syntax errors expose parser tokens, default CLI output hides successful validation warnings, and validation stops at the first error. | [Author-facing diagnostics](01-diagnostics-and-traces.md#author-facing-diagnostics) |
| Unused bindings delay trading, and the benchmark anchor varies with strategy warmup. | [Reachable readiness](02-readiness-and-results.md#reachable-readiness) · [Comparable benchmark](02-readiness-and-results.md#comparable-benchmark) |
| Out-of-window gaps produce run-level warnings, and a nonfinite Sharpe can fail publication as an I/O error. | [Gap scope and finite metrics](02-readiness-and-results.md#gap-scope-and-finite-metrics) |
| Large expression graphs and event streams need predictable resource admission. | [Workload estimates](02-readiness-and-results.md#workload-estimates) |
| Indicator periods require literals, records cannot be named, and Boolean conditions cannot use history. | [Static arguments, parameters, and types](03-language-composition.md) |
| Authors cannot express explicit fallback or size an entry by modeled stop loss directly. | [Unavailable expressions](03-language-composition.md#explicit-unavailable-values) · [Stop-based sizing](06-execution-capabilities.md#stop-based-sizing) |
| Varying a run means editing strategy source, and the browser run flow has separate save and validation steps. | [Run configuration and editor workflow](04-author-workflow.md) |
| Pattern-based suggestions lack the type and source context needed for dependable completions and fixes. | [Context-aware editor assistance](04-author-workflow.md#context-aware-editor-assistance) |
| Secondary candles are available only through dedicated Volume Profile inputs. | [Named data feeds](05-data-feeds.md) |
| One full-position exit, frozen protection, and a continuous spot market limit strategy coverage. | [Single-position and broader execution stages](06-execution-capabilities.md) |
| An integration test wrote fixture records to an existing preview. The workspace's duplicate type directories also interfered with TypeScript verification. | [Isolated verification](07-delivery-and-verification.md#isolate-integration-tests) · [Release checks](07-delivery-and-verification.md#release-checks) |

## End-to-end acceptance

A user changes configurable MACD periods, binds the record once, and references the previous daily trend value. The workspace runs the exact selected revision and inputs, explains a selected no-trade bar, and can replay the run from its bundle. The same release opens historical single-input and Volume Profile artifacts and passes the published v1 golden cases. [Reference scenario and release checks](07-delivery-and-verification.md#reference-scenario)
