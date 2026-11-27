# Readiness, metrics, and comparison

Make the trading window and result quality explainable across the CLI, API, and browser. Treat readiness changes, benchmark policy, and result reporting as independently reviewable changes.

## Reachable readiness

DSL 1 computes structural warmup across every binding, including unused declarations. The audit's unused `SMA(2)` moved the fixture's first executable open and warmup-aligned benchmark entry from January 2 to January 3. [Readiness contract](../../language-spec.md#unavailable-and-bounded-computation) · [Strategy roots](../../../src/tradelang/model.py)

1. Start with order predicates, sizing, and protection. Follow binding references transitively and carry field-specific readiness from record selections. Keep structural readiness distinct from the first observed available value.
2. Report the critical expression paths, required history, supplied pre-window rows, first eligible close, and first executable open. Point a warmup diagnostic to the binding or expression that drives it. This explanation can ship for legacy runs using their existing root policy.
3. Add reachable-root warmup behind an explicit semantic version. For that version, an unused binding is still compiled and can receive warnings. Computing its series, requiring its auxiliary data, or charging its work depends on reachability or an explicit inspection request.
4. Use the same resolved window in validation, explanation, submission, the worker, and the manifest. Keep the old warmup policy available for replay.

**Acceptance.** The v1 fixture matches its recorded delay. Under reachable warmup, adding or removing an unused indicator leaves first execution, trades, and the benchmark anchor equal. Direct use and transitive use both delay readiness correctly. Test a record whose selected field is ready earlier than another field, a long lookback, pre-window history, and a window without a subsequent open. [Window preparation](../../../src/tradelang/data.py) · [Explanation](../../../src/tradelang/report.py)

## Comparable benchmark

Keep the warmup-aligned buy-and-hold series for understanding an individual run. Add a common-start benchmark for a compatible group of comparison runs. The comparison API already reports differing `benchmark_entry_at` values. [Benchmark contract](../../results.md#read-the-equity-and-benchmark) · [Comparison implementation](../../../src/tradelang/api/run_results.py)

1. Start with a strict cohort that shares the primary candle series, currency, cost model, calendar, and an overlapping executable interval. Take the latest first executable open as the common start and the earliest terminal close as the common end. Verify those observed boundaries on the participating runs and require an end after the start.
2. Read the shared opening price and close series from the recorded primary input. Build a fee-inclusive reference using the existing buy-and-hold accounting, then normalize it to a shared starting value so it works across differing capital amounts. Display the start, last close, cost assumptions, and eligibility reason.
3. Keep full-run strategy metrics labeled with their own windows. Label chart reindexing and any intersection display. Only show excess-return comparisons for explicitly comparable periods under a documented treatment of positions at the start.
4. Treat the derived benchmark as comparison data with a versioned policy. If a later implementation persists it in a run bundle, specify its identity and digest treatment before release.

**Acceptance.** Two same-data variants with different warmups retain their separate individual benchmarks and share one normalized reference over the valid overlap. A differing fee, dataset, or disjoint executable range yields an explicit unavailable reason. A third incompatible run does not suppress an eligible pair. [Existing comparison gates](../research-terminal/04-verification-and-release.md)

## Gap scope and finite metrics

1. Compute and label distinct gap counts for the submitted dataset, the pre-window history used, and the execution interval. Include a leading or trailing boundary failure with a coverage diagnostic. Base execution warnings and interval-sensitive metrics on the actual execution grid. Keep child feed coverage separate from primary timestamp gaps.
2. Use guarded, numerically stable computations for returns and variance. Reject invalid ledger accounting through the numerical execution boundary. For a valid ledger, convert an unrepresentable statistic to JSON null with a specific reason. Preserve ordinary golden outputs and document any approved precision change. Audit aggregation and serialization together across summary, diagnostics, the API, and the browser.
3. Keep data import behavior visible. `gap_policy=allow` uses the next observed open and keeps observed-row history. Provide evidence when an order crosses a gap. Define any stale-order expiry with the future execution policy.

**Acceptance.** A two-candle gap after the execution window appears in dataset quality only. An in-window gap retains its run warning and the existing unavailable Sharpe behavior. The extreme finite-price fixture with valid final equity publishes a valid bundle with an unavailable metric reason. Nonfinite or invalid ledger accounting still produces a numerical failure. [Gap policy](../../candle-data.md#choose-a-gap-policy) · [Metrics and publication](../../../src/tradelang/engine.py) · [Bundle writer](../../../src/tradelang/report.py)

## Workload estimates

The evaluator retains series and the engine accumulates events. The supervised worker has memory and time limits, and Volume Profile already estimates bounded work. [Evaluator](../../../src/tradelang/evaluator.py) · [Worker limits](../../../src/tradelang/run_worker.py) · [Profile workload](../../../src/tradelang/functions/profile.py)

1. Estimate retained numeric arrays by effective rows, unique evaluated nodes, and retained record fields. Include profile work, data inputs, curve rows, and a conservative range for events and trace payloads. Deduplicate based on demonstrated cache reuse. Identify the expression or output that dominates the estimate.
2. Run the estimate during preparation and expose it consistently to CLI and HTTP. Use policy-backed hard admission only for validated limits. Keep runtime enforcement for actual memory, time, cancellation, and publication. Event-heavy runs need a stress case before raising existing limits.
3. Use the existing benchmark harness to compare ordinary, wide, and profile workloads on the same machine. Add an event-heavy workload with the same input across pre-change and post-change runs. Record rows, expression counts, events, peak memory, throughput, and whether publication is included.

**Acceptance.** A near-limit formula gets an estimate before queueing. Repeated references do not inflate its retained-array estimate. An over-budget case reports the specific limit. An accepted near-limit case finishes inside the worker budget or returns the documented runtime resource diagnostic. [Benchmark harness](../../../scripts/benchmark_indicators.py) · [Release checks](07-delivery-and-verification.md#release-checks)
