"""Deterministic preflight for the evaluator's retained arrays and ledger output."""

from typing import Any, Literal, TypedDict

from .model import Problem

MEMORY_LIMIT_BYTES = 1024**3
FLOAT_BYTES = 8
MAX_EVENTS_PER_BAR = 8
# A planning allowance for Python dictionaries and samples. Heap use and the
# number of orders depend on the run, so this estimate does not gate admission.
EVENT_BYTES = 1024
TRACE_SAMPLE_BYTES = 512


class Workload(TypedDict):
    schema_version: Literal[1]
    evaluated_rows: int
    execution_rows: int
    kernel_calls: int
    retained_series: int
    retained_series_bytes: int
    input_bytes: int
    curve_bytes: int
    decision_bytes: int
    profile_bytes: int
    profile_work_units: int
    minimum_resident_bytes: int
    memory_limit_bytes: int
    event_count_ceiling: int
    event_memory_allowance_bytes: int
    dominant_component: str
    dominant_expression: str | None
    dominant_expression_series: int


def estimate_workload(
    strategy, primary, child, first, last, profiles, feeds=None
) -> Workload:
    from .curve import FIELDS

    evaluated = last + 1
    execution = last - first + 1
    definitions = {name: expr for name, expr, _ in strategy.bindings}
    roots = strategy.named_roots()
    cache: dict[Any, tuple] = {}
    kernels: set[tuple] = set()
    retained = retained_rows = certain_rows = 0
    feeds = feeds or {}
    dominant: str | None = None
    largest = 0

    def visit(node, required):
        nonlocal retained, retained_rows, certain_rows
        if node in cache:
            return cache[node]
        args = tuple(visit(arg, required) for arg in node.args)
        backing: tuple = ("node", node)
        clock = node.type.clock
        rows = evaluated if clock is None else feeds[clock].rows
        if node.op == "let":
            backing = visit(definitions[node.value], required)
        elif node.op in {"literal", "parameter"}:
            backing = ("scalar", node.constant)
        elif node.op == "builtin":
            backing = ("input", clock, node.value)
        elif node.op == "on_feed":
            backing = args[0]
        elif node.op == "field":
            backing = ("field", args[0], node.value)
        elif (node.op == "offset" and node.value == 0) or (
            node.op == "unary" and node.value == "+"
        ):
            backing = args[0]
        elif node.op == "call":
            key = (clock, node.value, args)
            fields = len(node.type.fields)
            if key not in kernels:
                kernels.add(key)
                retained += fields or 1
                retained_rows += (fields or 1) * rows
            if fields:
                # The evaluator normalizes record fields per call expression.
                retained += fields
                retained_rows += fields * rows
                certain_rows += fields * rows if required else 0
            else:
                # Equal arguments share the numeric kernel output. Any
                # normalization copy on exceptional values is data-dependent.
                backing = ("kernel", key)
        elif node.type.series and not node.account:
            retained += 1
            retained_rows += rows
            certain_rows += rows if required else 0
        cache[node] = backing
        return backing

    for required in (True, False):
        for label, expr in roots:
            if expr is None or required == expr.account:
                continue
            before = retained
            visit(expr, required)
            if retained - before > largest:
                largest, dominant = retained - before, label

    input_bytes = sum(
        dataset.times.nbytes + dataset.values.nbytes
        for dataset in (
            primary,
            child,
            *(alignment.dataset for alignment in feeds.values()),
        )
        if dataset is not None
    )
    for dataset in (
        primary,
        child,
        *(alignment.dataset for alignment in feeds.values()),
    ):
        if dataset is None or dataset.session_rows is None:
            continue
        input_bytes += sum(
            array.nbytes
            for array in (
                dataset.session_rows.close,
                dataset.session_rows.ordinal,
                dataset.session_rows.session_index,
                dataset.session_rows.next_close,
            )
        )
        if dataset.raw_values is not None:
            input_bytes += dataset.raw_values.nbytes + dataset.split_factors.nbytes
    input_bytes += sum(
        alignment.indices.nbytes + alignment.status.nbytes
        for alignment in feeds.values()
    )
    curve_bytes = (execution + 1) * (len(FIELDS) * FLOAT_BYTES + 1)
    holding_age_bytes = 4 * execution if strategy.exit_rules else 0
    decision_bytes = execution * (4 + 2 * FLOAT_BYTES) + holding_age_bytes
    profile_arrays = {
        id(array): array.nbytes
        for profile in profiles.values()
        for array in (
            profile.offsets,
            profile.volumes,
            profile.bins,
            profile.lowest,
            profile.highest,
            profile.eligible,
            profile.coverage,
        )
    }
    profile_bytes = sum(profile_arrays.values())
    profile_work = sum(profile.work_units for profile in profiles.values())
    series_bytes = retained_rows * FLOAT_BYTES
    minimum = (
        input_bytes
        + curve_bytes
        + profile_bytes
        + certain_rows * FLOAT_BYTES
        + holding_age_bytes
    )

    def trace_size(node):
        return (node.type.kind != "record" and not node.account) + sum(
            trace_size(arg) for arg in node.args
        )

    eligible = execution - (strategy.warmup - first if strategy.warmup > first else 0)
    max_events = MAX_EVENTS_PER_BAR + (2 if strategy.trail is not None else 0)
    if strategy.short_margin is not None:
        max_events += 2
    event_ceiling = 0 if strategy.entry.constant is False else eligible * max_events
    trace_roots = [
        strategy.entry,
        strategy.exit,
        *(rule.condition for rule in strategy.exit_rules),
    ]
    if strategy.scale is not None:
        trace_roots.append(strategy.scale.condition)
    event_allowance = event_ceiling * EVENT_BYTES + (
        eligible
        * max(trace_size(node) for node in trace_roots if node is not None)
        * TRACE_SAMPLE_BYTES
        if event_ceiling
        else 0
    )
    components = {
        "retained series": series_bytes,
        "events and traces": event_allowance,
        "inputs": input_bytes,
        "equity curve": curve_bytes,
        "decision evidence": decision_bytes,
        "profile preparation": profile_bytes,
    }
    return Workload(
        schema_version=1,
        evaluated_rows=evaluated,
        execution_rows=execution,
        kernel_calls=len(kernels),
        retained_series=retained,
        retained_series_bytes=series_bytes,
        input_bytes=input_bytes,
        curve_bytes=curve_bytes,
        decision_bytes=decision_bytes,
        profile_bytes=profile_bytes,
        profile_work_units=profile_work,
        minimum_resident_bytes=minimum,
        memory_limit_bytes=MEMORY_LIMIT_BYTES,
        event_count_ceiling=event_ceiling,
        event_memory_allowance_bytes=event_allowance,
        dominant_component=max(components, key=components.__getitem__),
        dominant_expression=dominant,
        dominant_expression_series=largest,
    )


def admit_workload(workload: Workload):
    if workload["minimum_resident_bytes"] > workload["memory_limit_bytes"]:
        raise Problem(
            "E_DATA_LIMIT",
            f"Retained backtest arrays need at least {workload['minimum_resident_bytes']:,} bytes. "
            f"The worker memory budget is {workload['memory_limit_bytes']:,} bytes.",
            suggestion="Shorten the input history or reduce the number of calculated series",
            details={
                "minimum_resident_bytes": workload["minimum_resident_bytes"],
                "memory_limit_bytes": workload["memory_limit_bytes"],
                "dominant_expression": workload["dominant_expression"],
            },
        )
