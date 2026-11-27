# Strategy authoring and run configuration

Shorten the edit-to-run loop while retaining exact revision, validation, and replay identity. Implement editor assistance that works with existing contracts first. Add shared configuration before browser controls that submit parameter or run overrides. [Research terminal plan](../research-terminal/README.md)

## Resolved run configuration

The strategy source supplies dates, starting capital, and costs. The browser selects datasets and submits a saved strategy revision and gap policy. [CLI run inputs](../../cli.md) · [Submission request](../../../src/tradelang/api/backtests.py)

1. Define one resolver shared by CLI validation, explanation, and backtest, HTTP inspection and submission, and the worker. Use source defaults, then a named run configuration if selected, then explicit per-run overrides. Validate each field in the resolver and return the effective values and their origins.
2. Support dataset selection, UTC window, starting capital, fee, slippage, and resolved language parameters. Preserve currency and market compatibility and validate the selected import's gap policy. Use stable identifiers for browser presets and their edits.
3. Include the effective policy and inputs in the immutable snapshot and run fingerprint. Keep reusable preset names as display information. Changing a preset affects future submissions. A queued worker loads the recorded inputs and checks the fingerprint before publication.
4. Present a compact resolved configuration before execution and in the result view. Let an author duplicate a configuration and vary one input. Include a small experiment fixture that changes a period and keeps the strategy revision and datasets constant.

**Acceptance.** Equivalent CLI and browser settings resolve the same inputs and effective configuration in the same runtime environment. Changing a preset after submission does not change either the queued run or its replay. Incompatible dates, costs, currency, or parameters fail before queueing with an actionable reason. [Run identity](../../results.md#compare-and-replay-runs) · [Parameters](03-language-composition.md#static-arguments-and-parameters)

## Context-aware editor assistance

CodeMirror uses a generated catalogue and source-pattern completion. Extend that metadata and use compiler information where syntax patterns lose the type or scope. [Editor completion](../../../apps/web/src/components/code-editor.tsx) · [Catalogue generation](../../../scripts/web_contracts.py)

1. Debounce source-only validation. Abort superseded requests and associate every response with exact source and a request generation. Keep dataset-aware validation tied to the chosen datasets and overrides. Use compiler-reported input requirements to drive dataset selectors once feed roles and reachability are available.
2. Add argument hints with names, units, valid ranges, defaults, and overloads. Limit field suggestions to the record expression at the cursor, including a record alias or nested call. Use field and scale metadata for hover text and point-versus-fraction help.
3. Offer span-bound quick fixes for known casing, spelling, and scale errors where the compiler can propose a precise edit. Preserve keyboard navigation, focus return, and access to the full diagnostics list.

**Acceptance.** A stale validation response never changes diagnostics for a later edit or marks a different dataset ready. Complete a MACD field after a record alias, show the correct signature inside a nested call, and apply a verified casing fix. Exercise UTF-8 spans, keyboard-only validation, and a failed data check. [Diagnostic plan](01-diagnostics-and-traces.md#author-facing-diagnostics)

## Save and run an exact revision

The existing browser flow requires a saved revision and compatible validation before enabling a run. The submission endpoint independently checks the saved revision and prepares its inputs. Build the combined action on those contracts. [Browser run gate](../../../apps/web/src/components/strategy-editor.tsx) · [Server submission](../../../src/tradelang/api/backtests.py)

1. Capture source bytes, base revision, input IDs, and overrides when the author invokes the combined action. Validate the captured values. If valid, save with the revision precondition, then submit the acknowledged revision and captured configuration. A source or configuration edit during the action stays in the current editor state for the next submission.
2. Reuse submission idempotency for an identical payload on retries. Make a successful save followed by failed submission recoverable without another revision. Surface conflicts with a path to compare or reload the revised source.
3. Keep standalone Save available, including for invalid drafts. Report which revision and settings queued, and let the user open the immutable executed-source view from the result.

**Acceptance.** Test edits during save, changed dataset selection during validation, superseded source responses, a stale precondition, a lost acknowledgement, and an unavailable worker. Assert the exact snapshot for any accepted run and that repeated submission does not create duplicate runs. Verify keyboard access and focus return. [Existing browser tests](../../../apps/web/tests/research.spec.ts)
