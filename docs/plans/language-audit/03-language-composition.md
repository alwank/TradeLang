# Reusable strategy expressions

Give authors names for inputs, indicator results, and past conditions. Keep dimensional checking, causal evaluation, and bounded computation as the language grows. The examples in this plan show proposed syntax.

## Static arguments and parameters

Function arguments use lexical checks for roles such as period, multiplier, and literal price. The compiler already folds constant numeric expressions. Use that foundation to support named static values. [Function argument binding](../../../src/tradelang/functions/contracts.py) · [Compiler](../../../src/tradelang/compiler.py)

1. Allow compile-time positive integral arguments in period slots under the chosen language version. Apply the existing function-specific bounds and relationships after resolution. Preserve the declared dimension rules and distinguish an invalid period from an expression that depends on market or account data. Review multiplier and literal-price roles separately because their accepted units and ranges differ.
2. Add typed strategy parameters with defaults and optional bounds. A parameter resolves once before computing readiness and workload admission. Require overrides to use the declared type and reject unknown names, duplicates, and out-of-range values. Apply the same validation to defaults and overrides.
3. Keep the source and parameter declarations inspectable. Record effective values and their provenance in the run configuration so changing a resolved period changes the run fingerprint. Canonicalize parameter order and define the equivalence of a default and an explicit override of the same value.
4. Initially support periods, ratios, price distances, and Boolean switches where their types are already understood. Treat an experiment sweep as a later client of the single-run parameter contract.

**Acceptance.** A named period and an equivalent literal produce the same signal series, readiness, and fills. Changing the period through the CLI or browser yields the same resolved strategy for the same values and environment. A fractional, zero, over-limit, or series-derived period produces a diagnostic at its use. A parameterized MACD still enforces the fast and slow relationship. [Indicator contract](../../indicators.md) · [Run configuration](04-author-workflow.md#resolved-run-configuration)

## Record bindings and Boolean history

`let` accepts numeric and Boolean expressions. Record fields can be selected from calls, and `[k]` applies to numeric market series. [Types and units](../../language-spec.md#types-units-and-ast) · [Compiler selectors](../../../src/tradelang/compiler.py)

1. Allow immutable record bindings. Carry the field name, dimension, scale, and readiness through the type and expression graph. Resolve fields from record metadata through aliases. Retain field selection as the way to use a record in a scalar or series expression.
2. Allow lookbacks on Boolean series with the same observed-row clock and bounds as numeric lookbacks. Preserve unavailable samples, reject a scalar or account-dependent offset, and keep offsets on fields distinct from offsets on records.
3. Reuse the evaluator's call cache for repeated selectors. Add the versioned typed strategy shape and generated editor metadata alongside the compiler change. Update Explain to expose field readiness and the source definition behind each reference.

The following excerpt illustrates the target authoring experience.

```text
param fast: count = 12
param slow: count = 26
let macd = MACD(fast, slow, 9)
let uptrend = macd.line > macd.signal
entry:
  when uptrend and not uptrend[1]
  buy using 10% of equity
```

**Acceptance.** The excerpt's full fixture compiles and makes the same decisions as the equivalent v1 inline crossing. Prove that MACD line and signal readiness remain distinct, multiple field references reuse the call result, and a missing prior Boolean stays unavailable. Cover `[0]`, nested offsets, invalid field names, and allowed gaps. [Current MACD readiness](../../indicators.md) · [Readiness changes](02-readiness-and-results.md#reachable-readiness)

## Explicit unavailable values

DSL 1 requires both sides of a binary Boolean expression to be available. Give authors explicit tools for a conditional result or fallback while preserving that truth table in v1. [Unavailable-value rules](../../language-spec.md#unavailable-and-bounded-computation)

1. Add an availability predicate, a fallback expression, and a typed conditional. Require compatible units and kinds for branches. Specify scalar-to-series broadcasting, evaluation clock, and behavior when the conditional predicate is unavailable.
2. Define the result row by row. An available predicate selects one branch, and an unavailable predicate yields an unavailable result. A fallback selects the first available value. Unselected values or faults do not invalidate a selected result. Specify how vectorized preparation accounts for computation that a result did not use.
3. Define structural readiness so an intentional fallback can work before a slower input is ready. Keep readiness, actual availability, and runtime reason reporting distinct. Preserve causal histories for indicators used inside branches.

**Acceptance.** A fixture deliberately falls back while a market series is unavailable, then uses it when ready. A fault in an unselected branch does not invalidate the result. A unit mismatch fails compilation. Tests cover each combination of Boolean truth and unavailable state, as well as batch and prefix evaluation. [Existing missing-value property tests](../../../tests/property/test_missing_semantics.py)
