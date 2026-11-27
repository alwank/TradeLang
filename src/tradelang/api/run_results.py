"""Read immutable run artifacts, deterministic envelopes and run comparisons."""

import base64
import csv
import hashlib
import itertools
import json
from functools import lru_cache
from threading import BoundedSemaphore
from typing import Annotated, Any, Literal
from uuid import UUID

import numpy as np
import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq
from fastapi import Header, Path, Query, Response
from fastapi.responses import FileResponse
from pydantic import Field

from ..data import MAX_ROWS, canonical, hash_json, instant, load_dataset, prepare_window
from ..decision import (
    DECISION_FILE,
    DECISION_STAGES,
    DECISION_VERSION,
    ORDERED_DECISION_VERSION,
    PORTFOLIO_DECISION_VERSION,
    SESSION_DECISION_VERSION,
    Samples,
)
from ..engine import semantics_version
from ..evaluator import Evaluator
from ..model import Problem, Span
from ..order_sizing import RiskSizingTrace
from ..persistence import LibraryError, not_found, protected
from ..position_ledger import FillLedger
from ..run_config import RunSettings, configured_strategy
from .common_benchmark import common_benchmark
from .contracts import Closed, Diagnostic, Hash, Scalar, UuidText
from .library import Cursor, Limit, Page

EXPORTS = {
    "summary.json",
    "trades.csv",
    "equity.csv",
    "equity.parquet",
    "events.jsonl",
    "manifest.json",
    "source.trade",
    "run-config.json",
    DECISION_FILE,
    "asset-marks.csv",
    "asset-marks.parquet",
}
IfNoneMatch = Annotated[str | None, Header(alias="If-None-Match")]
INSPECTION_REPLAY = BoundedSemaphore(1)
MAX_INSPECTION_VALUES = 8_000_000


class Metrics(Closed):
    total_return: float
    cagr: float | None
    sharpe: float | None
    max_drawdown: float
    closed_trades: int
    wins: int
    losses: int
    breakeven: int
    win_rate: float | None
    profit_factor: float | None
    profit_factor_status: str
    exposure_fraction: float
    total_fees: float
    total_slippage_cost: float


class PositionAccounting(Closed):
    realized_net_pnl: float
    fill_count: int


class ShortAccounting(Closed):
    liquidations: int
    insolvent: bool
    restricted_proceeds: float
    initial_margin: float
    reserved_cash: float
    available_cash: float


class ResultSummary(Closed):
    schema_version: Literal[1]
    quote_currency: str
    symbol: str
    timeframe: str
    starting_capital: float
    final_equity: float
    final_cash: float
    open_position: dict[str, Any] | None
    benchmark: dict[str, Any]
    costs: dict[str, float]
    metrics: Metrics
    counts: dict[str, Any]
    window: dict[str, str]
    benchmark_entry_at: str
    warnings: list[Diagnostic]
    position_accounting: PositionAccounting | None = None
    short_accounting: ShortAccounting | None = None


class PortfolioSummary(Closed):
    schema_version: Literal[1]
    kind: Literal["portfolio"]
    quote_currency: str
    starting_capital: float
    final_equity: float
    final_cash: float
    reserved_cash: float
    available_cash: float
    net_market_value: float
    gross_market_value: float
    assets: list[dict[str, Any]]
    benchmark: dict[str, Any]
    benchmark_entry_at: str
    metrics: Metrics
    metric_unavailability: dict[str, str]
    costs: dict[str, float]
    warnings: list[dict[str, Any]]
    window: dict[str, str]


class EquityPoint(Closed):
    index: int
    timestamp: str
    phase: Literal["initial", "close"]
    bar_index: int | None
    mark_price: float | None
    cash: float
    quantity: float
    equity: float
    peak_equity: float
    drawdown: float
    cumulative_return: float
    exposed: bool
    benchmark_cash: float
    benchmark_quantity: float
    benchmark_equity: float
    benchmark_peak_equity: float
    benchmark_drawdown: float


class PortfolioEquityPoint(Closed):
    index: int
    timestamp: str
    phase: Literal["initial", "mark"]
    cash: float
    reserved_cash: float
    available_cash: float
    net_market_value: float
    gross_market_value: float
    equity: float
    peak_equity: float
    drawdown: float
    cumulative_return: float
    open_positions: int
    benchmark_cash: float
    benchmark_equity: float
    benchmark_peak_equity: float
    benchmark_drawdown: float


class EquityResponse(Page[EquityPoint | PortfolioEquityPoint]):
    mode: Literal["full", "envelope"]
    total_points: int
    returned_points: int
    full_resolution: bool
    buckets: int | None


class Trade(Closed):
    trade_id: str
    direction: Literal["long", "short"]
    entry_signal_bar: int
    entry_signal_at: str
    entry_bar: int
    entry_at: str
    entry_reference: float
    entry_price: float
    exit_signal_bar: int | None
    exit_signal_at: str | None
    exit_bar: int
    exit_at: str
    exit_time_precision: Literal["open", "bar", "close"]
    exit_reference: float
    exit_price: float
    quantity: float
    entry_fee: float
    exit_fee: float
    entry_slippage_cost: float
    exit_slippage_cost: float
    gross_pnl: float
    net_pnl: float
    return_fraction: float
    bars_held: int
    exit_reason: str
    entry_rationale: dict[str, Any]
    exit_rationale: dict[str, Any] | None
    protection: dict[str, Any]
    initial_collateral: float | None = None
    borrow_cost: float | None = None
    asset: str | None = None


class RunEvent(Closed):
    sequence: int
    event_id: str
    kind: str
    reason: str
    observed_at: str
    bar_open_at: str
    time_precision: Literal["open", "close", "bar"]
    order_id: str | None
    fill_id: str | None
    linked_event_id: str | None
    trade_id: str | None
    data: dict[str, Any]
    ledger: FillLedger | None = None


class TraceSample(Closed):
    node_id: str
    span: Span
    kind: str
    unit: str | None
    value: bool | float | None
    available: bool
    bar_index: int | None
    observed_at: str | None
    definition_node_id: str | None
    unavailable_reason: str | None
    field: str | None
    feed: str | None = None
    clock: str | None = None


class ExpressionTrace(Closed):
    root_node_id: str
    value: bool | float | None
    truncated: bool
    samples: list[TraceSample]


class RuleInspection(Closed):
    evaluated: bool
    predicate: bool | None
    outcome: str
    expression: ExpressionTrace | None


class OrderedExitInspection(Closed):
    name: str
    after_bars: int | None
    outcome: Literal["selected", "exit_priority", "false", "unavailable", "skipped"]
    expression: ExpressionTrace | None
    sale_expression: ExpressionTrace | None = None


class TrailUpdate(Closed):
    node_id: str
    sampled_bar: int
    sampled_at: str
    expression_value: float
    unit: Literal["price", "ratio"]
    close_anchor: float
    distance: float
    trigger_price: float
    previous_trigger_price: float
    effective_open_at: str | None = None


class EntryFillInspection(Closed):
    signal_bar: int
    cash: float
    sizing_value: float | None
    budget: float | None
    expression: ExpressionTrace
    protection: dict[str, Any] | None
    allocation_expression: ExpressionTrace | None = None


class BarInspection(Closed):
    schema_version: Literal[1]
    available: bool
    reason: str | None = None
    bar_index: int
    bar_open_at: str | None = None
    close_at: str | None = None
    split_factor: float | None = None
    phase: str | None = None
    entry: RuleInspection | None = None
    exit: RuleInspection | None = None
    entry_inputs: dict[str, ExpressionTrace] = {}
    entry_fill: EntryFillInspection | None = None
    risk_sizing: RiskSizingTrace | None = None
    holding_closes: int | None = None
    exit_rules: list[OrderedExitInspection] = []
    trail_updates: list[TrailUpdate] = []
    trail_expression: ExpressionTrace | None = None
    sale_expression: ExpressionTrace | None = None
    scale_expression: ExpressionTrace | None = None
    add_sizing: ExpressionTrace | None = None
    events: list[RunEvent] = []


class NormalizedPoint(Closed):
    timestamp: str
    phase: Literal["initial", "close", "mark"]
    run_id: UuidText
    index: int
    value: float
    drawdown: float


class ComparisonRun(Closed):
    run_id: UuidText
    strategy_id: UuidText
    strategy_name: str
    strategy_revision: int
    source_hash: Hash
    dataset_hash: Hash
    configuration: dict[str, Any]
    metrics: Metrics
    final_equity: float
    benchmark_entry_at: str
    curve: list[NormalizedPoint]


class Difference(Closed):
    field: str
    values: list[Scalar]
    severity: Literal["info", "warning", "incompatible"]


class CommonWindowStrategy(Closed):
    run_id: UuidText
    open_equity: float | None
    open_quantity: float
    total_return: float | None
    excess_return: float | None
    reason: Literal["invalid_open_mark", "invalid_index_value"] | None


class CommonWindowPoint(Closed):
    timestamp: str
    phase: Literal["initial", "close"]
    benchmark: float
    strategies: dict[str, float]


class BenchmarkCohort(Closed):
    run_ids: list[UuidText]
    start_at: str
    end_at: str
    reference_price: float
    entry_price: float
    entry_fee: float
    fee_rate: float
    slippage_rate: float
    total_return: float
    strategies: list[CommonWindowStrategy]
    points: list[CommonWindowPoint]


class BenchmarkPair(Closed):
    run_ids: Annotated[list[UuidText], Field(min_length=2, max_length=2)]
    reason: (
        Literal[
            "market_or_semantics_mismatch",
            "primary_data_mismatch",
            "cost_mismatch",
            "no_overlap",
            "numeric_range",
            "recorded_input_unavailable",
            "portfolio_reference_unavailable",
        ]
        | None
    )


class CommonBenchmark(Closed):
    policy: Literal["common_start_hold_v1"]
    cohorts: list[BenchmarkCohort]
    pairs: list[BenchmarkPair]


class Comparison(Closed):
    schema_version: Literal[1]
    runs: list[ComparisonRun]
    differences: list[Difference]
    alignment: Literal["exact", "intersection", "unavailable"]
    display_window: dict[str, str] | None
    warnings: list[str]
    common_benchmark: CommonBenchmark


@lru_cache(maxsize=128)
def checksum(path, size, modified, changed):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


class Result:
    def __init__(self, runs, ident):
        self.row = runs.row(ident)
        if self.row["status"] != "succeeded":
            raise LibraryError(
                409, "E_RESULT_NOT_READY", "This run has no published result"
            )
        self.digest = self.row["result_digest"]
        self.path = runs.directory(ident)
        try:
            self.manifest = manifest = json.loads(
                protected(self.path / "manifest.json").read_text()
            )
            if manifest["result_digest"] != self.digest or manifest["run_id"] != ident:
                raise ValueError("Mismatched result digest")
            self.files = {
                record["name"]: record for record in manifest["artifact_files"]
            }
        except (OSError, ValueError, KeyError, TypeError) as exc:
            raise LibraryError(
                500, "E_RUN_ARTIFACT", "The result manifest failed integrity checks"
            ) from exc

    def file(self, name):
        path = protected(self.path / name)
        if name == "manifest.json":
            return path
        try:
            expected = self.files[name]
            stat = path.stat()
            if (
                stat.st_size != expected["bytes"]
                or checksum(path, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns)
                != expected["sha256"]
            ):
                raise ValueError("Mismatched result artifact digest")
        except (OSError, ValueError, KeyError, TypeError) as exc:
            raise LibraryError(
                500, "E_RUN_ARTIFACT", "A result artifact failed integrity checks"
            ) from exc
        return path

    def headers(self, response):
        response.headers["ETag"] = f'"{self.digest}"'
        response.headers["Cache-Control"] = "private, no-cache"

    def conditional(self, response, tag, data):
        self.headers(response)
        expected = f'"{self.digest}"'
        if tag is not None and any(
            value.strip().removeprefix("W/") in {expected, "*"}
            for value in tag.split(",")
        ):
            return Response(status_code=304, headers=dict(response.headers))
        return data


def page_cursor(digest, scope, cursor):
    if cursor is None:
        return 0
    try:
        signature, key, offset = json.loads(base64.urlsafe_b64decode(cursor))
        if (
            signature != digest
            or key != hash_json(scope)
            or type(offset) is not int
            or offset < 1
        ):
            raise ValueError("Invalid cursor")
    except (ValueError, TypeError) as exc:
        raise LibraryError(
            400, "E_CURSOR", "Invalid or incompatible result cursor"
        ) from exc
    return offset


def continuation(digest, scope, offset):
    return base64.urlsafe_b64encode(
        canonical([digest, hash_json(scope), offset]).encode()
    ).decode()


def parquet_range(file, first, last):
    position = 0
    groups = []
    start = None
    for group in range(file.num_row_groups):
        count = file.metadata.row_group(group).num_rows
        if position <= last and position + count > first:
            if start is None:
                start = first - position
            groups.append(group)
        position += count
    return file.read_row_groups(groups).slice(start or 0, max(0, last - first + 1))


def envelope_indices(length, maximum, columns):
    if length <= maximum:
        return np.arange(length), None
    buckets = max(1, maximum // (len(columns) + 2))
    indices = {0, length - 1}
    for first, end in zip(
        np.linspace(0, length, buckets + 1, dtype=int)[:-1],
        np.linspace(0, length, buckets + 1, dtype=int)[1:],
    ):
        indices.update((int(first), int(end - 1)))
        for values, select in columns:
            indices.add(int(first + select(values[first:end])))
    return np.array(sorted(indices)), buckets


def equity_page(result, mode, limit, max_points, from_index, to_index, cursor):
    file = pq.ParquetFile(result.file("equity.parquet"))
    last = file.metadata.num_rows - 1
    first = from_index if from_index is not None else 0
    last = min(last, to_index) if to_index is not None else last
    if first > last:
        raise LibraryError(422, "E_RANGE", "Select a non-empty equity range")
    total = last - first + 1
    scope = ["equity", first, last]
    buckets = None
    next_cursor = None
    if mode == "envelope":
        if cursor is not None:
            raise LibraryError(400, "E_CURSOR", "Envelope responses use a point limit")
        table = parquet_range(file, first, last)
        columns = []
        for name in ("equity", "benchmark_equity"):
            columns.extend(
                [
                    (table[name].to_numpy(), np.argmin),
                    (table[name].to_numpy(), np.argmax),
                ]
            )
        for name in ("drawdown", "benchmark_drawdown"):
            columns.append((table[name].to_numpy(), np.argmin))
        indices, buckets = envelope_indices(total, max_points, columns)
        rows = table.take(pa.array(indices)).to_pylist()
    else:
        start = first + page_cursor(result.digest, scope, cursor)
        end = min(start + limit - 1, last)
        rows = parquet_range(file, start, end).to_pylist()
        if end < last:
            next_cursor = continuation(result.digest, scope, end + 1 - first)
    return dict(
        mode=mode,
        items=rows,
        next_cursor=next_cursor,
        snapshot=result.digest,
        total_points=total,
        returned_points=len(rows),
        full_resolution=buckets is None,
        buckets=buckets,
    )


def parse_trade(row):
    parsed = {}
    for field, value in row.items():
        if field in {
            "trade_id",
            "direction",
            "exit_time_precision",
            "exit_reason",
            "asset",
        } or field.endswith("_at"):
            parsed[field] = value or None
        else:
            parsed[field] = json.loads(value) if value else None
    return parsed


def parse_event(event):
    keys = RunEvent.model_fields.keys() - {"data"}
    return {
        **{key: event.get(key) if key == "ledger" else event[key] for key in keys},
        "data": {key: value for key, value in event.items() if key not in keys},
    }


def rule_inspection(stage, code, side, holding, events, trace):
    evaluated = stage == "close"
    predicate = bool(code) if evaluated and code >= 0 else None
    if not evaluated:
        outcome = stage
    elif predicate is None:
        outcome = "unavailable"
    elif not predicate:
        outcome = "false"
    else:
        signal_orders = {
            event["order_id"]
            for event in events
            if event["kind"] == "signal"
            and event["side"] == side
            and event["order_id"] is not None
        }
        disposition = next(
            (
                event["kind"]
                for event in reversed(events)
                if event["phase"] >= 7
                and event["order_id"] in signal_orders
                and event["kind"]
                in {"order_queued", "order_expired_end", "exit_rejected"}
            ),
            None,
        )
        if disposition is not None:
            outcome = disposition
        elif side in ("sell", "cover"):
            outcome = "flat"
        elif holding:
            outcome = "holding"
        elif any(
            event["kind"] == "entry_rejected" and event["phase"] == 7
            for event in events
        ):
            outcome = "entry_rejected"
        else:
            outcome = "exit_priority"
    return dict(
        evaluated=evaluated, predicate=predicate, outcome=outcome, expression=trace
    )


def recorded_events(result, row, filename="events.jsonl"):
    start, end = row["event_offset"], row["event_end"]
    if not 0 <= end - start <= 16 * 1024 * 1024:
        raise LibraryError(500, "E_RUN_ARTIFACT", "Invalid inspection event range")
    if start == end:
        return []
    with result.file(filename).open("rb") as stream:
        stream.seek(start)
        return [json.loads(line) for line in stream.read(end - start).splitlines()]


def inspect_exit_rules(strategy, samples, index, holding_closes):
    inspected = []
    found = False
    for number, rule in enumerate(strategy.exit_rules):
        expression = None
        sale = None
        if found:
            outcome = "skipped"
        else:
            verdict = rule.predicate(
                lambda expr: samples.ev.value(expr, index), holding_closes
            )
            if rule.condition is not None:
                expression = samples.trace(
                    rule.condition, f"exit.rules.{number}.condition", index
                )
            if verdict is True:
                outcome = "selected" if holding_closes else "exit_priority"
                if holding_closes and rule.sale is not None:
                    sale = samples.trace(
                        rule.sale.expression,
                        f"exit.rules.{number}.action.expression",
                        index,
                    )
                found = True
            else:
                outcome = "unavailable" if verdict is None else "false"
        inspected.append(
            dict(
                name=rule.name,
                after_bars=rule.after_bars,
                outcome=outcome,
                expression=expression,
                sale_expression=sale,
            )
        )
    return inspected


def inspect_bar(result, index, environment, asset=None):
    manifest = result.manifest
    base = dict(schema_version=1, bar_index=index)
    leg = next(
        (item for item in manifest.get("assets", []) if item["asset"] == asset), None
    )
    if manifest.get("schema_version") == 5 and leg is None:
        raise LibraryError(422, "E_ASSET", "Select a recorded portfolio asset")
    decision = (
        leg["decision_inspection"] if leg else manifest.get("decision_inspection", {})
    )
    decision_version = decision.get("schema_version")
    if (
        leg is None and decision.get("artifact") != DECISION_FILE
    ) or decision_version not in (
        DECISION_VERSION,
        ORDERED_DECISION_VERSION,
        SESSION_DECISION_VERSION,
        PORTFOLIO_DECISION_VERSION,
    ):
        return dict(**base, available=False, reason="inspection_not_recorded")
    rows = pq.read_table(
        result.file(decision["artifact"]), filters=[("bar_index", "=", index)]
    )
    if not rows.num_rows:
        raise LibraryError(
            422, "E_RANGE", "Select an observed candle inside the execution window"
        )
    if (
        rows.num_rows != 1
        or rows.schema.metadata.get(b"tradelang.decision_version")
        != str(decision_version).encode()
    ):
        raise LibraryError(500, "E_RUN_ARTIFACT", "Invalid decision record")
    row = rows.to_pylist()[0]
    stage = DECISION_STAGES[row["stage"]]
    events = recorded_events(
        result, row, decision.get("events_artifact", "events.jsonl")
    )
    short = bool(
        (leg["policy"] if leg else manifest.get("resolved_policy", {})).get(
            "short_margin"
        )
    )
    entry_side, exit_side = ("short", "cover") if short else ("buy", "sell")
    if "holding_closes" in row:
        base["holding_closes"] = row["holding_closes"] if stage == "close" else None
    if decision_version in (SESSION_DECISION_VERSION, PORTFOLIO_DECISION_VERSION):
        base["split_factor"] = row["split_factor"]
    base["trail_updates"] = [
        event["trail"]
        for event in events
        if event["kind"] in ("trail_queued", "trail_activated")
    ]
    buy_fill = next(
        (
            event
            for event in events
            if event["phase"] == 3
            and event["kind"] == "fill"
            and event["side"] == entry_side
        ),
        None,
    )
    if (
        buy_fill
        and (sizing := (buy_fill["trace"] or {}).get("risk_sizing")) is not None
    ):
        base["risk_sizing"] = sizing
    duration = result.row["snapshot"]["configuration"]["timeframe_seconds"]
    base.update(
        bar_open_at=instant(row["open_us"]),
        close_at=instant(
            row["close_us"]
            if decision_version
            in (SESSION_DECISION_VERSION, PORTFOLIO_DECISION_VERSION)
            else row["open_us"] + duration * 1_000_000
        ),
        phase=stage,
        events=[parse_event(event) for event in events],
    )
    expected = dict(
        entry=rule_inspection(
            stage, row["entry"], entry_side, row["holding"], events, None
        ),
        exit=rule_inspection(
            stage, row["exit"], exit_side, row["holding"], events, None
        ),
    )
    if stage != "close" and row["signal_bar"] is None:
        return dict(**base, **expected, available=True)
    execution = leg["configuration"] if leg else manifest
    version = execution.get("dsl_version", 1)
    if (
        version not in (1, 2, 3, 4, 5, 6, 7, 8)
        or execution.get("semantics_version") != semantics_version(version)
        or manifest.get("environment_hash") != hash_json(environment())
    ):
        return dict(
            **base, **expected, available=False, reason="inspection_runtime_mismatch"
        )
    if not INSPECTION_REPLAY.acquire(blocking=False):
        return dict(**base, **expected, available=False, reason="inspection_busy")
    try:
        source = result.file(
            leg["inputs"]["strategy"] if leg else "source.trade"
        ).read_bytes()
        typed = json.loads(
            result.file(
                f"asset-{asset}-strategy-spec.json" if leg else "strategy-spec.json"
            ).read_text()
        )
        # Count normalized expression nodes, including implicit indicator arguments.
        pending = [typed]
        spec_nodes = 0
        while pending:
            node = pending.pop()
            if isinstance(node, dict):
                spec_nodes += "inferred_type" in node
                pending.extend(node.values())
            elif isinstance(node, list):
                pending.extend(node)
        if (index + 1) * spec_nodes > MAX_INSPECTION_VALUES:
            return dict(
                **base, **expected, available=False, reason="inspection_work_limit"
            )
        input_files = (
            [name for name in ("input.csv", "input.parquet") if name in result.files]
            if leg is None
            else [leg["inputs"]["data"]]
        )
        if len(input_files) != 1:
            raise LibraryError(500, "E_RUN_ARTIFACT", "Invalid primary input inventory")
        dataset = load_dataset(
            result.file(input_files[0]),
            json.loads(result.file(leg["inputs"]["metadata"]).read_text())
            if leg
            else manifest["dataset_metadata"],
        )
        profile = None
        if leg and leg["inputs"].get("profile"):
            profile_input = leg["inputs"]["profile"]
            profile = load_dataset(
                result.file(profile_input["data"]),
                json.loads(result.file(profile_input["metadata"]).read_text()),
            )
        elif profile_input := manifest.get("profile_input"):
            profile = load_dataset(
                result.file(profile_input["data_file"]),
                json.loads(result.file(profile_input["metadata_file"]).read_text()),
            )
        strategy = configured_strategy(
            source,
            RunSettings.model_validate(leg["inputs"]["settings"])
            if leg and "settings" in leg["inputs"]
            else RunSettings.model_validate(manifest["run_settings"])
            if "run_settings" in manifest
            else None,
            parameters=manifest.get("parameter_overrides")
            if "run_settings" not in manifest
            else None,
            dataset=dataset,
        )
        feeds = {
            item["name"]: load_dataset(
                result.file(item["data"]),
                json.loads(result.file(item["metadata"]).read_text()),
            )
            for item in manifest.get("feed_inputs", [])
        }
        if leg:
            feeds = {
                name: load_dataset(
                    result.file(item["data"]),
                    json.loads(result.file(item["metadata"]).read_text()),
                )
                for name, item in leg["inputs"].get("feeds", {}).items()
            }
        prepared = prepare_window(
            strategy, dataset, profile, profile_end=index, feeds=feeds
        )
        samples = Samples(
            strategy,
            Evaluator(
                strategy,
                dataset,
                index,
                profiles=prepared.profiles,
                feeds=prepared.feeds,
            ),
        )
        if stage == "close":
            expected["entry"]["expression"] = samples.trace(
                strategy.entry, "entry.condition", index
            )
            if strategy.exit is not None:
                expected["exit"]["expression"] = samples.trace(
                    strategy.exit, "exit.condition", index
                )
                if row["holding"] and row["exit"] == 1 and strategy.sale is not None:
                    base["sale_expression"] = samples.trace(
                        strategy.sale.expression, "exit.action.expression", index
                    )
            else:
                base["exit_rules"] = inspect_exit_rules(
                    strategy, samples, index, row["holding_closes"]
                )
            if row["holding"] and strategy.trail is not None:
                base["trail_expression"] = samples.trace(
                    strategy.trail, "risk.trail.expression", index
                )
            if row["holding"] and strategy.scale is not None:
                base["scale_expression"] = samples.trace(
                    strategy.scale.condition, "scale.condition", index
                )
                if any(
                    event["kind"] == "signal" and event["side"] == "add"
                    for event in events
                ):
                    base["add_sizing"] = samples.trace(
                        strategy.scale.sizing, "scale.sizing.expression", index
                    )
            if expected["entry"]["outcome"] in {
                "order_queued",
                "order_expired_end",
                "entry_rejected",
            }:
                rejected = next(
                    (
                        event["reason"]
                        for event in events
                        if event["phase"] == 7 and event["kind"] == "entry_rejected"
                    ),
                    None,
                )
                signal_inputs = {}
                for name, expr, path in (
                    ("stop", strategy.stop, "risk.stop.expression"),
                    ("target", strategy.target, "risk.target.expression"),
                    ("sizing", strategy.sizing, "entry.sizing.expression"),
                    (
                        "allocation_cap",
                        strategy.allocation_cap,
                        "entry.sizing.allocation_cap",
                    ),
                ):
                    if expr is not None and not expr.account:
                        signal_inputs[name] = samples.trace(expr, path, index)
                    if rejected == f"invalid_{name}":
                        break
                base["entry_inputs"] = signal_inputs
        fill = None
        if row["signal_bar"] is not None:
            fill = dict(
                signal_bar=row["signal_bar"],
                cash=row["fill_cash"],
                sizing_value=row["sizing"],
                budget=row["budget"],
                protection=buy_fill["protection"] if buy_fill else None,
                expression=samples.trace(
                    strategy.sizing,
                    "entry.sizing.expression",
                    row["signal_bar"],
                    cash=row.get("entry_equity") if leg else row["fill_cash"],
                    fill_bar=index,
                ),
            )
            if strategy.allocation_cap is not None:
                fill["allocation_expression"] = samples.trace(
                    strategy.allocation_cap,
                    "entry.sizing.allocation_cap",
                    row["signal_bar"],
                    cash=row.get("entry_equity") if leg else row["fill_cash"],
                    fill_bar=index,
                )
        return dict(**base, **expected, available=True, entry_fill=fill)
    except Problem as exc:
        if exc.diagnostic["code"] == "E_DATA_LIMIT":
            return dict(
                **base, **expected, available=False, reason="inspection_work_limit"
            )
        raise LibraryError(
            500, "E_RUN_ARTIFACT", "The saved inputs cannot be inspected"
        ) from exc
    finally:
        INSPECTION_REPLAY.release()


def rows_page(result, kind, records, limit, cursor, filters):
    scope = [kind, filters]
    offset = page_cursor(result.digest, scope, cursor)
    rows = list(itertools.islice(records, offset, offset + limit + 1))
    next_ = (
        continuation(result.digest, scope, offset + limit)
        if len(rows) > limit
        else None
    )
    return dict(items=rows[:limit], next_cursor=next_, snapshot=result.digest)


def comparison(results):
    rows = [result.row for result in results]
    configs = [row["snapshot"]["configuration"] for row in rows]
    summaries = [row["summary"] for row in rows]
    fields = (
        "market",
        "currency",
        "timeframe_seconds",
        "calendar",
        "semantics_version",
        "dataset_hash",
        "profile_dataset_hash",
        "first_open",
        "last_close_at",
        "capital",
        "fee_rate",
        "slippage_rate",
        "gap_policy",
        "engine_version",
    )
    differences = []
    for index, key in enumerate(fields):
        values = [config[key] for config in configs]
        if any(value != values[0] for value in values[1:]):
            differences.append(
                dict(
                    field=key,
                    values=values,
                    severity="incompatible"
                    if index < 5
                    else "info"
                    if key == "capital"
                    else "warning",
                )
            )
    benchmark = [summary["benchmark_entry_at"] for summary in summaries]
    if len(set(benchmark)) > 1:
        differences.append(
            dict(field="benchmark_entry_at", values=benchmark, severity="warning")
        )
    alignment = "unavailable"
    window = None
    warnings = []
    curves: list[list] = [[] for _ in rows]
    if any(item["severity"] == "incompatible" for item in differences):
        warnings.append(
            "The runs use incompatible markets, currencies, intervals, calendars, or semantics."
        )
    else:
        tables = [
            pq.read_table(
                result.file("equity.parquet"),
                columns=["index", "timestamp", "phase", "equity", "drawdown"],
            )
            for result in results
        ]
        keys = [
            pc.cast(table["timestamp"], pa.timestamp("us", "UTC"))
            .to_numpy()
            .astype("int64")
            * 2
            + pc.not_equal(table["phase"], "initial").to_numpy()
            for table in tables
        ]
        if all(np.array_equal(keys[0], key) for key in keys[1:]):
            alignment = "exact"
            common = keys[0]
        else:
            alignment = "intersection"
            common = keys[0]
            for key in keys[1:]:
                common = np.intersect1d(common, key, assume_unique=True)
        if not len(common):
            alignment = "unavailable"
            warnings.append("The runs have no matching timestamps.")
        else:
            matching = [
                table.take(pa.array(np.searchsorted(key, common)))
                for table, key in zip(tables, keys)
            ]
            columns = []
            for table in matching:
                equity = table["equity"].to_numpy()
                columns.extend(
                    [
                        (equity, np.argmin),
                        (equity, np.argmax),
                        (table["drawdown"].to_numpy(), np.argmin),
                    ]
                )
            sampled, _ = envelope_indices(len(common), 2000, columns)
            window = {
                "from": matching[0]["timestamp"][0].as_py(),
                "to": matching[0]["timestamp"][-1].as_py(),
            }
            for index, (table, row, config) in enumerate(zip(matching, rows, configs)):
                for point in table.take(pa.array(sampled)).to_pylist():
                    curves[index].append(
                        dict(
                            timestamp=point["timestamp"],
                            phase=point["phase"],
                            run_id=row["id"],
                            index=point["index"],
                            value=100 * (point["equity"] / config["capital"]),
                            drawdown=point["drawdown"],
                        )
                    )
    return dict(
        schema_version=1,
        differences=differences,
        alignment=alignment,
        display_window=window,
        warnings=warnings,
        common_benchmark=common_benchmark(results, envelope_indices),
        runs=[
            dict(
                run_id=row["id"],
                strategy_id=row["strategy_id"],
                strategy_name=snapshot["strategy_name"],
                strategy_revision=snapshot["strategy_revision"],
                source_hash=snapshot["source_hash"],
                dataset_hash=snapshot["dataset_hash"],
                configuration=config,
                metrics=summary["metrics"],
                final_equity=summary["final_equity"],
                benchmark_entry_at=summary["benchmark_entry_at"],
                curve=curve,
            )
            for row, snapshot, config, summary, curve in zip(
                rows, [r["snapshot"] for r in rows], configs, summaries, curves
            )
        ],
    )


def result_routes(router, runs, errors, environment):
    cached = {**errors, 304: {"description": "Result has not changed"}}

    @router.get("/compare", response_model=Comparison, responses=errors)
    def compare(ids: Annotated[str, Query(max_length=147)]):
        try:
            identifiers = [str(UUID(raw)) for raw in ids.split(",")]
            if not 2 <= len(identifiers) <= 4 or len(set(identifiers)) != len(
                identifiers
            ):
                raise ValueError("Invalid run count")
        except ValueError as exc:
            raise LibraryError(
                422, "E_COMPARE_SELECTION", "Select two to four distinct succeeded runs"
            ) from exc
        results = [Result(runs, ident) for ident in identifiers]
        return comparison(results)

    @router.get("/{ident}/equity", response_model=EquityResponse, responses=cached)
    def equity(
        ident: UUID,
        response: Response,
        mode: Literal["full", "envelope"] = "full",
        limit: Annotated[int, Query(ge=1, le=5000)] = 2000,
        max_points: Annotated[int, Query(ge=100, le=5000)] = 2000,
        from_index: Annotated[int | None, Query(ge=0)] = None,
        to_index: Annotated[int | None, Query(ge=0)] = None,
        cursor: Cursor = None,
        tag: IfNoneMatch = None,
    ):
        result = Result(runs, str(ident))
        return result.conditional(
            response,
            tag,
            equity_page(result, mode, limit, max_points, from_index, to_index, cursor),
        )

    @router.get("/{ident}/trades", response_model=Page[Trade], responses=cached)
    def trades(
        ident: UUID,
        response: Response,
        limit: Limit = 50,
        cursor: Cursor = None,
        reason: Annotated[str | None, Query(max_length=40)] = None,
        tag: IfNoneMatch = None,
    ):
        result = Result(runs, str(ident))
        with result.file("trades.csv").open(newline="") as stream:
            rows = (
                parse_trade(row)
                for row in csv.DictReader(stream)
                if reason is None or row["exit_reason"] == reason
            )
            return result.conditional(
                response,
                tag,
                rows_page(result, "trades", rows, limit, cursor, [reason]),
            )

    @router.get("/{ident}/events", response_model=Page[RunEvent], responses=cached)
    def events(
        ident: UUID,
        response: Response,
        limit: Limit = 50,
        cursor: Cursor = None,
        trade_id: Annotated[str | None, Query(max_length=40)] = None,
        kind: Annotated[str | None, Query(max_length=40)] = None,
        tag: IfNoneMatch = None,
    ):
        result = Result(runs, str(ident))
        with result.file("events.jsonl").open() as stream:
            orders, event_ids = set(), set()
            if trade_id is not None:
                for line in stream:
                    event = json.loads(line)
                    if event["trade_id"] == trade_id:
                        event_ids.add(event["event_id"])
                        if event["order_id"] is not None:
                            orders.add(event["order_id"])
                stream.seek(0)
            records = (json.loads(line) for line in stream)
            rows = (
                parse_event(event)
                for event in records
                if (
                    trade_id is None
                    or event["trade_id"] == trade_id
                    or event["order_id"] in orders
                    or event["linked_event_id"] in event_ids
                )
                and (kind is None or event["kind"] == kind)
            )
            return result.conditional(
                response,
                tag,
                rows_page(result, "events", rows, limit, cursor, [trade_id, kind]),
            )

    @router.get("/{ident}/bars/{index}", response_model=BarInspection, responses=errors)
    def bar(
        ident: UUID,
        index: Annotated[int, Path(ge=0, le=MAX_ROWS - 1)],
        asset: Annotated[str | None, Query(max_length=32)] = None,
    ):
        return inspect_bar(Result(runs, str(ident)), index, environment, asset)

    @router.get(
        "/{ident}/artifacts/{name}", response_class=FileResponse, responses=cached
    )
    def artifact(ident: UUID, name: str, tag: IfNoneMatch = None):
        if name not in EXPORTS:
            raise not_found()
        result = Result(runs, str(ident))
        if name in {DECISION_FILE, "run-config.json"} and name not in result.files:
            raise not_found()
        response = FileResponse(result.file(name), filename=name)
        return result.conditional(response, tag, response)
