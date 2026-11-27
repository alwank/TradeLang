"""Compact execution evidence and bounded, sample-aware expression inspection."""

from pathlib import Path

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq

from .data import instant
from .functions.profile import profile_key
from .model import UNITS, Expr

DECISION_FILE = "decisions.parquet"
DECISION_VERSION = 1
ORDERED_DECISION_VERSION = 2
SESSION_DECISION_VERSION = 3
PORTFOLIO_DECISION_VERSION = 4
MAX_TRACE_SAMPLES = 128
MAX_TRACE_DEPTH = 32
DECISION_STAGES = ("warmup", "post_exit", "close")


class DecisionLog:
    def __init__(
        self,
        first: int,
        last: int,
        *,
        ordered_exits=False,
        closes=None,
        split_factors=None,
        portfolio_account=False,
    ):
        self.first = first
        size = last - first + 1
        self.states = np.zeros((size, 4), dtype=np.int8)
        self.ranges = np.zeros((size, 2), dtype=np.int64)
        self.holding_closes = np.zeros(size, dtype=np.int32) if ordered_exits else None
        self.closes, self.split_factors = closes, split_factors
        self.entry_equity: dict[int, float] | None = {} if portfolio_account else None
        self.version = (
            PORTFOLIO_DECISION_VERSION
            if portfolio_account
            else SESSION_DECISION_VERSION
            if closes is not None
            else (ORDERED_DECISION_VERSION if ordered_exits else DECISION_VERSION)
        )
        self.entry_fills: dict[int, tuple[int, float, float | None, float | None]] = {}

    def record(
        self,
        row,
        stage,
        holding,
        entry,
        exit,
        event_start,
        event_end,
        *,
        holding_closes=0,
    ):
        index = row - self.first
        self.states[index] = (
            stage,
            holding,
            int(entry == 1) - int(not np.isfinite(entry)),
            int(exit == 1) - int(not np.isfinite(exit)),
        )
        self.ranges[index] = event_start, event_end
        if self.holding_closes is not None:
            self.holding_closes[index] = holding_closes

    def entry(self, row, signal_bar, cash, sizing, budget, *, equity=None):
        self.entry_fills[row] = (
            signal_bar,
            cash,
            sizing,
            budget if budget is not None and np.isfinite(budget) else None,
        )
        if self.entry_equity is not None and equity is not None:
            self.entry_equity[row] = equity

    def counts(self):
        stage = self.states[:, 0]
        eligible = stage == 2
        counts: dict[str, str | int | dict[str, int]] = {
            "counting_unit": "observed_bar",
            "warmup": int(np.count_nonzero(stage == 0)),
            "post_exit": int(np.count_nonzero(stage == 1)),
        }
        for column, side in enumerate(("entry", "exit"), 2):
            values = self.states[eligible, column]
            counts[side] = {
                name: int(np.count_nonzero(values == code))
                for code, name in ((-1, "unavailable"), (0, "false"), (1, "true"))
            }
        return counts

    def write(self, path: Path, times, event_offsets):
        offsets = np.asarray(event_offsets, dtype=np.int64)
        schema = pa.schema(
            [
                ("bar_index", pa.int64()),
                ("open_us", pa.int64()),
                ("stage", pa.int8()),
                ("holding", pa.bool_()),
                ("entry", pa.int8()),
                ("exit", pa.int8()),
                ("event_offset", pa.int64()),
                ("event_end", pa.int64()),
                ("signal_bar", pa.int64()),
                ("fill_cash", pa.float64()),
                ("sizing", pa.float64()),
                ("budget", pa.float64()),
            ],
            metadata={b"tradelang.decision_version": str(self.version).encode()},
        )
        if self.holding_closes is not None:
            schema = schema.append(pa.field("holding_closes", pa.int32()))
        if self.closes is not None:
            schema = schema.append(pa.field("close_us", pa.int64())).append(
                pa.field("split_factor", pa.float64())
            )
        if self.entry_equity is not None:
            schema = schema.append(pa.field("entry_equity", pa.float64()))
        size = len(self.states)
        with pq.ParquetWriter(path, schema) as writer:
            for start in range(0, size, 8192):
                end = min(start + 8192, size)
                rows = range(self.first + start, self.first + end)
                states = self.states[start:end]
                ranges = self.ranges[start:end]
                fills = [
                    self.entry_fills.get(row, (None, None, None, None)) for row in rows
                ]
                session_columns = []
                if self.closes is not None:
                    session_columns.append(
                        pa.array(self.closes[rows.start : rows.stop])
                    )
                    session_columns.append(
                        pa.array(self.split_factors[rows.start : rows.stop])
                        if self.split_factors is not None
                        else pa.nulls(len(rows), type=pa.float64())
                    )
                if self.entry_equity is not None:
                    session_columns.append(
                        pa.array(
                            [self.entry_equity.get(row) for row in rows],
                            type=pa.float64(),
                        )
                    )
                writer.write_table(
                    pa.Table.from_arrays(
                        [
                            pa.array(rows, type=pa.int64()),
                            pa.array(times[rows.start : rows.stop], type=pa.int64()),
                            pa.array(states[:, 0]),
                            pa.array(states[:, 1] != 0),
                            pa.array(states[:, 2]),
                            pa.array(states[:, 3]),
                            pa.array(offsets[ranges[:, 0]]),
                            pa.array(offsets[ranges[:, 1]]),
                            *(
                                pa.array(values, type=field.type)
                                for values, field in zip(
                                    zip(*fills), list(schema)[8:12], strict=True
                                )
                            ),
                            *(
                                [pa.array(self.holding_closes[start:end])]
                                if self.holding_closes is not None
                                else []
                            ),
                            *session_columns,
                        ],
                        schema=schema,
                    )
                )


class Samples:
    def __init__(self, strategy, evaluator):
        self.ev = evaluator
        self.bindings = {
            name: (expr, f"bindings.{index}.expression")
            for index, (name, expr, _) in enumerate(strategy.bindings)
        }
        self.interval = self.ev.timeframe_seconds * 1_000_000

    def trace(self, expr: Expr, path: str, bar: int, *, cash=None, fill_bar=None):
        samples: list[dict] = []
        truncated = False
        seen: dict[tuple, dict] = {}

        def visit(node, node_id, index, depth, field=None):
            nonlocal truncated
            if depth > MAX_TRACE_DEPTH or len(samples) >= MAX_TRACE_SAMPLES:
                truncated = True
                return None
            key = node_id, index, field
            if key in seen:
                return seen[key]
            record = node.type.kind == "record"
            evaluator = self.ev.domain(node)
            result_type = node.type.field_type(field) if record and field else node.type
            value = None
            if index >= 0 and not record:
                value = evaluator.value(node, index, cash)
                if value is not None and result_type.kind == "boolean":
                    value = bool(value)
            elif index >= 0 and field:
                out = evaluator.evaluate(node)[field][index]
                value = float(out) if np.isfinite(out) else None
            actual_index = fill_bar if node.account else index
            definition = self.bindings.get(node.value) if node.op == "let" else None
            sample = dict(
                node_id=node_id,
                span=node.span.model_dump(),
                kind=result_type.kind,
                unit=next(
                    (name for name, unit in UNITS.items() if unit == result_type.unit),
                    str(result_type.unit),
                )
                if result_type.kind == "numeric"
                else None,
                value=value,
                available=value is not None,
                bar_index=actual_index
                if actual_index is not None and actual_index >= 0
                else None,
                observed_at=(
                    instant(
                        evaluator.times[actual_index]
                        if node.account
                        else evaluator.close_at(actual_index)
                    )
                    if actual_index is not None and actual_index >= 0
                    else None
                ),
                definition_node_id=definition[1] if definition else None,
                unavailable_reason=None,
                field=field,
            )
            if node.type.clock is not None or node.op == "align":
                sample["feed"] = node.type.clock if node.op != "align" else node.value
                sample["clock"] = node.type.clock or "primary"
            samples.append(sample)
            seen[key] = sample
            children = []
            if definition:
                children.append(visit(*definition, index, depth + 1, field))
            for label, child in node.children():
                child_id = f"{node_id}.{label}"
                child_index = index - node.value if node.op == "offset" else index
                if node.op == "align":
                    child_index = self.ev.aligned_row(node.value, index)
                children.append(
                    visit(
                        child,
                        child_id,
                        child_index,
                        depth + 1,
                        node.value if node.op == "field" else None,
                    )
                )
                if node.op == "cross":
                    children.append(visit(child, child_id, index - 1, depth + 1))
            if value is None:
                if index < 0:
                    sample["unavailable_reason"] = "missing_history"
                elif node.op == "account":
                    sample["unavailable_reason"] = "account_at_fill"
                elif node.op == "align":
                    alignment = self.ev.feeds[node.value]
                    selected = self.ev.aligned_row(node.value, index)
                    sample["unavailable_reason"] = alignment.reason(index) or (
                        "feed_insufficient_history"
                        if selected < node.args[0].ready
                        else "upstream_unavailable"
                    )
                elif index < node.ready and (not record or not field):
                    sample["unavailable_reason"] = "structural_warmup"
                elif node.op == "call" and node.value == "VPROFILE":
                    arguments = [arg.value for arg in node.args]
                    window = evaluator.profiles[profile_key(arguments)]
                    sample["unavailable_reason"] = window.unavailable_reason(
                        index, int(arguments[0])
                    )
                elif (
                    node.op == "binary"
                    and node.value == "/"
                    and evaluator.value(node.args[1], index, cash) == 0
                ):
                    sample["unavailable_reason"] = "zero_denominator"
                elif any(item and item["unavailable_reason"] for item in children):
                    sample["unavailable_reason"] = "upstream_unavailable"
                else:
                    sample["unavailable_reason"] = (
                        "invalid_arithmetic"
                        if node.op == "binary"
                        else "indicator_unavailable"
                    )
            return sample

        root = visit(expr, path, bar, 0)
        return dict(
            root_node_id=path,
            value=root["value"] if root else None,
            truncated=truncated,
            samples=samples,
        )
