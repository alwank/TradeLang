# Implementation checklist

Use this checklist to choose the next reviewable change. Each item links to its design and fixtures. Checked items have recorded verification evidence. Open items may already have work in progress. Follow the dependencies to select work that can proceed in parallel. [Implementation progress](07-delivery-and-verification.md#implementation-progress)

## Trustworthy results

| Item | Work | Prerequisite | Verify before closing |
| --- | --- | --- | --- |
| A1 | ✅ Isolate integration services and libraries. [Test isolation](07-delivery-and-verification.md#isolate-integration-tests) | Existing baseline | An occupied default port receives no fixture writes. Concurrent services and restart route to the correct test instance. |
| A2 | ✅ Improve single-error messages and surface successful CLI warnings. [Author-facing diagnostics](01-diagnostics-and-traces.md#author-facing-diagnostics) | A1 for integration checks | Human-readable output includes warnings, casing and arity suggestions, and actionable data coverage errors. JSON diagnostics and exit statuses remain compatible. |
| A3 | ✅ Record samples at their effective bar and expose selected-bar decisions. [Sample-aware traces](01-diagnostics-and-traces.md#sample-aware-traces) · [Selected-bar inspection](01-diagnostics-and-traces.md#selected-bar-inspection) | A1 | Crossings, offsets, aliases, zero-volume profile inputs, and blocked rules expose the correct samples and reasons. Legacy readers retain saved evidence. |
| A4 | ✅ Scope gap warnings and make optional metrics safe to serialize. [Gap scope and finite metrics](02-readiness-and-results.md#gap-scope-and-finite-metrics) | A1 | A gap outside execution changes dataset quality only. A valid ledger with an unrepresentable Sharpe publishes with a reason. |
| A5 | ✅ Estimate workload and enforce the supported admission limit. [Workload estimates](02-readiness-and-results.md#workload-estimates) | A1 | Estimate cache reuse, reject an oversized request before queueing, and record measured workload and publication evidence. |
| A6 | ✅ Recover independent compiler errors for editing. [Author-facing diagnostics](01-diagnostics-and-traces.md#author-facing-diagnostics) | A2 | A draft shows multiple independent errors with exact spans. The final compile still rejects the invalid source. |

## Reusable expressions and experiments

| Item | Work | Prerequisite | Verify before closing |
| --- | --- | --- | --- |
| B1 | ✅ Version the language and typed schema. Add typed parameters and named static periods. [Static arguments and parameters](03-language-composition.md#static-arguments-and-parameters) | A1, A5 | Existing DSL 1 golden outputs pass. Named and literal periods produce the same decisions. Invalid values fail before queueing. Effective overrides survive replay. |
| B2 | ✅ Add record bindings, Boolean history, and scale diagnostics. [Record bindings and Boolean history](03-language-composition.md#record-bindings-and-boolean-history) · [Scale-aware diagnostics](01-diagnostics-and-traces.md#scale-aware-diagnostics) | B1 | A named MACD record matches the inline crossing. Prior unavailable Boolean samples stay unavailable. Grouped, aliased, lagged, and record-field comparisons warn on the affected threshold. |
| B3 | ✅ Add explicit conditional and fallback expressions. [Explicit unavailable values](03-language-composition.md#explicit-unavailable-values) | B1 | Fallback values fill unavailable samples. Incompatible branches fail compilation. Evaluating a prefix gives the same values as the corresponding rows of a full run. |
| B4 | ✅ Compute readiness and input requirements from reachable expressions. [Reachable readiness](02-readiness-and-results.md#reachable-readiness) | B2, B3 | An unused binding leaves the first tradable bar and required feeds unchanged. Explain identifies which selected field determines the warmup. DSL 1 retains its warmup rule. |
| B5 | ✅ Resolve and snapshot reusable run settings. [Resolved run configuration](04-author-workflow.md#resolved-run-configuration) | B1 | CLI, HTTP, and browser use the same effective window, fees, data, and parameters. Editing a preset leaves a queued run and its replay unchanged. |
| B6 | ✅ Add editor validation, typed completion, and quick fixes. [Context-aware editor assistance](04-author-workflow.md#context-aware-editor-assistance) | A2 for validation. A6 for recovered diagnostics. B2 and B4 for typed hints and feed selection. | Stale responses have no effect. A keyboard-only author can complete a record field and apply a casing fix at the verified span. |
| B7 | ✅ Save and run the exact revision captured by the author. [Save and run an exact revision](04-author-workflow.md#save-and-run-an-exact-revision) | B5 | Edits during submission preserve the captured revision and configuration. Conflicts and retry after a partial failure preserve revision and run identity. |
| B8 | ✅ Compare compatible runs on a common-start benchmark. [Comparable benchmark](02-readiness-and-results.md#comparable-benchmark) | B4, B5 | A compatible pair shares a normalized reference over the overlapping interval. An incompatible run reports a reason and leaves the compatible pair available. |

## Data and execution capabilities

| Item | Work | Prerequisite | Verify before closing |
| --- | --- | --- | --- |
| C1 | ✅ Bind and align one same-market higher-timeframe feed. [Named data feeds](05-data-feeds.md) | A3, B4, B5 | The signal uses only completed secondary candles. Check staleness, native and aligned lookbacks, causal prefixes, and historical Volume Profile replay. |
| C2 | ✅ Size a single long by modeled stop loss. [Stop-based sizing](06-execution-capabilities.md#stop-based-sizing) | A3, B1, B5 | Hand-calculated fee, slippage, cap, and rounding cases reconcile with the ledger and order trace. |
| C3 | ✅ Add ordered exits, a time exit, and trailing protection. [Ordered exits and trailing protection](06-execution-capabilities.md#ordered-exits-and-trailing-protection) | A3, B1, B5 | Simultaneous rules resolve in the documented order. A trail derived from a completed bar applies from the next bar. Test pending orders across gaps. |
| C4 | ✅ Add partial exits for one long, then position scaling. [Partial exits and position scaling](06-execution-capabilities.md#partial-exits-and-position-scaling) | C2, C3 | Quantity, cost basis, realized profit and loss, fees, and remaining protection reconcile across fill legs. |
| C5 | ✅ Add exchange sessions and a price basis policy. [Additional markets](06-execution-capabilities.md#additional-markets) | C1, C3 | A signal before a closure fills at the next session open. Holiday, shortened-session, daylight-saving, and split fixtures use the declared calendar and price rules. |
| C6 | ✅ Add a single-market shorting model. [Shorting acceptance data](06-execution-capabilities.md#single-market-shorting-acceptance-data) | C4 and the relevant calendar policy from C5 | A hand-calculated short round trip reconciles signed exposure, costs, collateral, and applicable financing. |
| C7 | ✅ Add multi-asset portfolio execution. [Portfolio acceptance data](06-execution-capabilities.md#multi-asset-portfolio-acceptance-data) | C1, C4, C5 | Simultaneous orders competing for the same cash follow a stable priority across reruns. Portfolio and per-asset values reconcile. |

## Release acceptance

Verify the MACD workflow after B8, including exact revision, parameter overrides, selected-bar evidence, shared comparison, and replay. For each subsequent release, apply the applicable version, replay, and workload gates. Verify historical single-input and Volume Profile artifacts alongside the new fixtures. [Reference scenario](07-delivery-and-verification.md#reference-scenario) · [Release checks](07-delivery-and-verification.md#release-checks)
