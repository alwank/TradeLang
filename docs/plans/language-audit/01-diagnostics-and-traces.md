# Diagnostics and decision traces

Make compiler feedback actionable and let authors verify decisions down to the expression and candle that supplied each value. Land CLI diagnostic improvements first. Build sample-aware traces before exposing selected-bar inspection.

## Sample-aware traces

The engine's trace walks the syntax tree using one bar index. A cross exposes its current operands, and a lookback's child is read at the current index. Trace construction also treats a binding reference as a leaf. [Existing trace](../../../src/tradelang/engine.py)

1. Share expression addressing with the typed strategy or verify one canonical mapping for both. Record a stable expression node ID, value, type or unit, availability, sample bar index, and timestamp. Keep the decision phase and observed time separate from sample times.
2. Evaluate an offset's child at the shifted index and propagate that index through nested offsets. Record current and prior samples for both operands of a crossing, including the equality that can qualify on the prior bar. Point binding references to their definition's node ID and expose the definition at the same effective sample index.
3. Expose the signal-close market samples separately from fill-time cash, sizing, and protection calculations. Keep the event's order, trade, and fill links on rejections and protective exits where applicable. Use Boolean values in the new trace shape and retain the existing representation for older readers.
4. Bound expanded trace depth and sample count. Show deterministic truncation when a trace exceeds the bound. Version the trace and artifact reader before changing existing event and trade payloads.

**Acceptance.** The crossing fixture shows a prior close of 100 and a current close of 112 against 105. In the lookback fixture, both `close[1]` and the child `close` sample the bar with value 100. Nested lookbacks, an aliased operand, and a crossing across an allowed gap point to the correct observed rows. The original next-open fill sequence and accounting still match the golden fixture. [Evaluator](../../../src/tradelang/evaluator.py) · [Golden trace](../../results.md#trace-the-quickstart-trade)

## Selected-bar inspection

A compatible dataset can still produce unavailable values. In the audit, complete lower-timeframe candles with zero volume produced no signals and no useful explanation in the summary. The existing event log is concentrated on actionable or ignored signals, and its aggregate evaluator counts need context. [Volume Profile kernel](../../../src/tradelang/functions/profile.py) · [Decision loop](../../../src/tradelang/engine.py)

1. Capture decision outcomes by eligible bar and rule when scanning the ledger. Keep predicate outcomes such as true, false, and unavailable distinct from phase outcomes such as warmup, holding, exit priority, post-exit suppression, rejected proposal, and final-bar expiry. Record whether the phase actually evaluated the rule. Preserve the documented treatment of an unavailable exit while flat.
2. Add bounded reason tracking for structural warmup, missing input, zero denominator, invalid arithmetic, and Volume Profile coverage, empty distributions, or invalid bin ranges. Attribute root causes to their source nodes and distinguish propagated unavailability from a new fault. Keep reason summaries scoped to the requested analysis and report their counting unit.
3. Expose one run-scoped selected-bar response for the editor and result view. Use the saved strategy, exact inputs, and recorded semantic version. Pick a bounded stored or replay-backed approach in the implementation design. A replay-backed inspector must restore prior state and refuse a version mismatch with an explanation.
4. Keep summary counts compact. Cap individual inspections and avoid writing a full expression tree for every bar. Allow old artifacts to show their saved evidence and an explicit inspection availability state.

**Acceptance.** The zero-volume profile fixture reports the unavailable input and no entry. Separate cases show a false rule, an unavailable rule, a true rule blocked by an exit, and a rejected fill-time budget. Selecting the same bar through different views returns the same source span, samples, phase, and order references. [Profile candle contract](../../candle-data.md#pair-candles-for-volume-profile) · [Workload estimates](02-readiness-and-results.md#workload-estimates)

## Scale-aware diagnostics

The compiler recognizes a narrow direct RSI and percentage pattern. The audit's aliased RSI and MFI comparisons with `30%` both used 0.3 points without a warning. The catalogue already carries scale information for several functions. [RSI diagnostic](../../../src/tradelang/compiler.py) · [Indicator registry](../../../src/tradelang/functions/builtins.py)

1. Add audited point or fractional scale metadata to function outputs and individual fields, including mixed-scale records. Propagate it through grouping, aliases, field access, and lookbacks. Preserve percentage-literal provenance where the diagnostic needs it.
2. Define which arithmetic preserves scale and which arithmetic clears it. Provide an explicit normalization expression in the reference and recognize it in the diagnostic. Preserve binary64 values and units for v1.
3. Add a warning at the percentage operand when comparing or crossing points against a percentage. Display the interpreted value and suggest the corresponding point spelling. Preserve the legacy `W_RSI_SCALE` behavior on the v1 compatibility path and define a stable code for the broader warning on the new path.

**Acceptance.** Direct, grouped, aliased, and lagged RSI comparisons with `30%` warn consistently on the new path. MFI and applicable record fields receive the same help. A point threshold of 30 and a fractional comparison after explicit normalization pass without a misleading warning. [Indicator scales](../../indicators.md) · [Compatibility gates](07-delivery-and-verification.md#version-and-replay-gates)

## Author-facing diagnostics

1. Translate expected tokens into source constructs and spellings. Add nearby-name suggestions for unknown calls and fields, including lowercase `ema(...)` → `EMA(...)`. For wrong arity, show accepted signatures and identify the offending argument when available.
2. Print warnings on successful human-readable CLI validation and explanation, including the span and suggestion when available. Preserve JSON output as one envelope and keep its exit-status contract. Provide an actionable dataset error for edge coverage and insufficient history using requested bounds, observed bounds, and the required next executable open.
3. Add bounded, editor-oriented recovery for independent errors only after single-error messages are useful. Keep an exact-source final compile authoritative for execution. Apply fixes only to the source revision and byte span that produced the diagnostic.

**Acceptance.** Human-readable validation shows `W_UNUSED_LET`. A lowercase call gets a casing suggestion without parser token names. Wrong arity shows the supported forms. Check UTF-8, a byte-order mark, and CRLF across CLI JSON and editor span focus. Verify independent recoverable errors alongside a failed final compile. [Compiler diagnostics](../../../src/tradelang/compiler.py) · [CLI diagnostics](../../../src/tradelang/cli.py) · [CLI contract](../../cli.md#json-and-exit-status)
