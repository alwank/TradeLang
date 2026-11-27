"""Validate a single immutable, ordered OHLCV snapshot."""

import csv
import hashlib
import json
import re
import struct
from array import array
from dataclasses import dataclass
from dataclasses import field as dataclass_field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Literal

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    model_serializer,
    model_validator,
)

from .compiler import seconds
from .feeds import FeedAlignment, prepare_feeds
from .functions.profile import ProfileKey, ProfileWindow, prepare_profiles, profile_key
from .model import Problem
from .session_clock import SessionGrid, SessionRows, SessionSchedule, StockSplit
from .workload import Workload, admit_workload, estimate_workload

COLUMNS = ("timestamp", "open", "high", "low", "close", "volume")
EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
MAX_ROWS = 1_000_000


def instant(us):
    return (EPOCH + timedelta(microseconds=int(us))).isoformat().replace("+00:00", "Z")


def micros(dt):
    delta = dt - EPOCH
    return (delta.days * 86400 + delta.seconds) * 1000000 + delta.microseconds


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def unique_json_members(pairs: list[tuple[str, object]]) -> dict[str, object]:
    obj: dict[str, object] = {}
    for name, value in pairs:
        if name in obj:
            raise ValueError(f"Duplicate JSON member {name!r}")
        obj[name] = value
    return obj


def canonical(obj):
    """Encode finite JSON with sorted keys and normalized decimal exponents."""
    if isinstance(obj, dict):
        return (
            "{"
            + ",".join(
                canonical(str(k)) + ":" + canonical(v) for k, v in sorted(obj.items())
            )
            + "}"
        )
    if isinstance(obj, (list, tuple)):
        return "[" + ",".join(map(canonical, obj)) + "]"
    if isinstance(obj, float):
        if not np.isfinite(obj):
            raise ValueError("Nonfinite JSON number")
        if obj == 0:
            return "0"
        mant, sep, exp = repr(obj).partition("e")
        return mant.removesuffix(".0") + ("e" + str(int(exp)) if sep else "")
    return json.dumps(obj, ensure_ascii=False, allow_nan=False, separators=(",", ":"))


def timeframe_label(duration: int) -> str:
    """Format a validated whole-minute bar duration."""
    for scale, unit in ((86400, "d"), (3600, "h"), (60, "m")):
        if duration % scale == 0:
            return f"{duration // scale}{unit}"
    raise ValueError("Expected a whole-minute timeframe")


def hash_json(obj):
    return digest(canonical(obj).encode())


class Metadata(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)
    schema_version: Literal[1, 2] = 1
    symbol: str = Field(pattern=r"^[A-Z0-9][A-Z0-9_.-]{0,31}$")
    quote_currency: str = Field(pattern=r"^[A-Z][A-Z0-9]{1,11}$")
    timeframe: str = Field(pattern=r"^[1-9][0-9]{0,5}[mhd]$")
    calendar: Literal["24x7", "session"]
    timestamp_convention: Literal["bar_open"]
    volume_unit: Literal["base_quantity"]
    price_basis: Literal["raw_spot", "raw_equity", "split_reference"]
    gap_policy: Literal["allow", "reject"] = "reject"
    session_schedule: SessionSchedule | None = None
    splits: list[StockSplit] | None = Field(default=None, max_length=10_000)

    @model_validator(mode="after")
    def calendar_contract(self):
        if self.calendar == "24x7":
            if (
                self.schema_version != 1
                or self.price_basis != "raw_spot"
                or self.session_schedule is not None
                or self.splits is not None
            ):
                raise ValueError("Continuous candles use schema 1 and raw spot prices")
        elif (
            self.schema_version != 2
            or self.session_schedule is None
            or self.price_basis == "raw_spot"
        ):
            raise ValueError(
                "Session candles require schema 2, a session schedule, and an equity price basis"
            )
        if (self.price_basis == "split_reference") != (self.splits is not None):
            raise ValueError(
                "Supply an explicit split list only for the split_reference price basis"
            )
        return self

    @model_serializer(mode="wrap")
    def serialize(self, handler):
        return {key: value for key, value in handler(self).items() if value is not None}


@dataclass(frozen=True)
class Dataset:
    meta: Metadata
    times: np.ndarray
    values: np.ndarray
    dataset_hash: str
    source_hash: str
    missing: int
    path: Path
    grid: SessionGrid | None = None
    session_rows: SessionRows | None = None
    split_factors: np.ndarray | None = None
    raw_values: np.ndarray | None = None

    @property
    def timeframe_seconds(self) -> int:
        return seconds(self.meta.timeframe)

    def column(self, name):
        return self.values[:, COLUMNS.index(name) - 1]

    def close_at(self, row):
        if self.session_rows is not None:
            return self.session_rows.close[row]
        return self.times[row] + self.timeframe_seconds * 1_000_000

    def missing_between(self, first: int, last: int) -> int:
        """Count missing grid opens between two observed row indices."""
        if self.session_rows is not None:
            return int(
                self.session_rows.ordinal[last] - self.session_rows.ordinal[first]
            ) - (last - first)
        elapsed = int(self.times[last]) - int(self.times[first])
        return elapsed // (self.timeframe_seconds * 1000000) - (last - first)

    def largest_gap_seconds(self) -> int:
        if not self.missing:
            return 0
        elapsed = np.diff(self.times)
        if self.session_rows is not None:
            elapsed = elapsed[np.diff(self.session_rows.ordinal) > 1]
        return int(elapsed.max() // 1_000_000)


@dataclass(frozen=True)
class PreparedWindow:
    first: int
    first_signal: int
    last: int
    profiles: dict[ProfileKey, ProfileWindow]
    timeframe_seconds: int
    workload: Workload
    feeds: dict[str, FeedAlignment] = dataclass_field(default_factory=dict)


def timestamp(text):
    if not re.fullmatch(
        r"\d{4}-\d\d-\d\d[T ]\d\d:\d\d:\d\d(?:\.\d{1,6})?(?:Z|[+-]\d\d:\d\d)", text
    ):
        raise ValueError("Expected offset-aware timestamp")
    return micros(datetime.fromisoformat(text).astimezone(UTC))


DECIMAL = re.compile(r"[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?")


def csv_number(text):
    if not text or not DECIMAL.fullmatch(text):
        raise ValueError("Invalid decimal OHLCV cell")
    value = float(text)
    if abs(value) > 2**53 and text.lstrip("+-").isdigit() and int(text) != value:
        raise ValueError("Integer cannot be represented exactly")
    return value


def read_csv(path):
    times = array("q")
    values = array("d")
    with path.open(encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f, strict=True)
        if sorted(reader.fieldnames or []) != sorted(COLUMNS):
            raise ValueError(
                "Expected exactly timestamp, open, high, low, close, volume"
            )
        for i, r in enumerate(reader, 1):
            if i > MAX_ROWS:
                raise Problem("E_DATA_LIMIT", "Dataset exceeds one million rows")
            try:
                if None in r:
                    raise ValueError("Extra CSV cells")
                times.append(timestamp(r["timestamp"]))
                values.extend(csv_number(r[k]) for k in COLUMNS[1:])
            except (TypeError, ValueError, OverflowError) as exc:
                raise Problem("E401_DATA", str(exc), row=i) from exc
    return np.array(times, dtype="<i8"), np.asarray(values, dtype="<f8").reshape(-1, 5)


def read_parquet(path):
    pf = pq.ParquetFile(path)
    if sorted(pf.schema_arrow.names) != sorted(COLUMNS):
        raise ValueError("Unexpected Parquet schema")
    if (
        pf.metadata.num_rows > MAX_ROWS
        or sum(
            pf.metadata.row_group(i).total_byte_size for i in range(pf.num_row_groups)
        )
        > 512 * 1024**2
    ):
        raise Problem("E_DATA_LIMIT", "Parquet exceeds decoded size or row limit")
    stamp = pf.schema_arrow.field("timestamp").type
    if not pa.types.is_timestamp(stamp) or not stamp.tz:
        raise ValueError("Expected timezone-aware timestamp column")
    for k in COLUMNS[1:]:
        typ = pf.schema_arrow.field(k).type
        if not (pa.types.is_integer(typ) or pa.types.is_floating(typ)):
            raise ValueError(f"Expected numeric {k}")
    table = pf.read()
    if any(col.null_count for col in table.columns):
        raise ValueError("Null Parquet cells")
    times = (
        table["timestamp"].cast(pa.timestamp("us", "UTC")).cast(pa.int64()).to_numpy()
    )
    vals = np.column_stack(
        [table[k].cast(pa.float64(), safe=True).to_numpy() for k in COLUMNS[1:]]
    )
    return times, vals


def load_dataset(path, metadata, *, as_of_utc: datetime | None = None):
    path = Path(path)
    try:
        meta = Metadata.model_validate(metadata)
        delta = seconds(meta.timeframe) * 1000000
        if delta > 604800000000:
            raise ValueError("Timeframe exceeds limit")
        if path.stat().st_size > 100 * 1024**2:
            raise Problem("E_DATA_LIMIT", "Dataset exceeds the input size limit")
        reader = {".csv": read_csv, ".parquet": read_parquet}.get(path.suffix.lower())
        if reader is None:
            raise ValueError("Expected CSV or Parquet")
        before = path.stat()
        times, values = reader(path)
        if not len(times):
            raise ValueError("Empty dataset")
        grid = (
            SessionGrid(meta.session_schedule, delta, timestamp)
            if meta.session_schedule
            else None
        )
        session_rows, bad_clock = (
            grid.map_rows(times) if grid else (None, times % delta != 0)
        )
        o, h, low, c, v = values.T
        bad = (
            (~np.isfinite(values).all(axis=1))
            | (low <= 0)
            | (low > np.minimum(o, c))
            | (h < np.maximum(o, c))
            | (v < 0)
            | bad_clock
        )
        if bad.any():
            raise Problem(
                "E401_DATA",
                "Invalid OHLCV or timestamp alignment",
                row=int(np.argmax(bad)) + 1,
            )
        diff = (
            np.diff(session_rows.ordinal)
            if session_rows is not None
            else np.diff(times) // delta
        )
        bad = (diff <= 0) if meta.gap_policy == "allow" else (diff != 1)
        if bad.any():
            raise Problem(
                "E401_DATA",
                "Unsorted, duplicate or missing candle",
                row=int(np.argmax(bad)) + 2,
            )
        last_close = (
            session_rows.close[-1]
            if session_rows is not None
            else int(times[-1]) + delta
        )
        if last_close > micros(as_of_utc or datetime.now(UTC)):
            raise ValueError("Incomplete candle")
        values[values == 0] = 0
        raw_values = None
        split_factors = None
        if meta.splits is not None:
            assert grid is not None and session_rows is not None
            split_factors = grid.factors(meta.splits, session_rows)
            raw_values = values
            with np.errstate(all="ignore"):
                values = values.copy()
                values[:, :4] *= split_factors[:, None]
                values[:, 4] /= split_factors
            if not (
                np.isfinite(values).all()
                and np.all(values[:, :4] > 0)
                and np.all((values[:, 4] > 0) | (raw_values[:, 4] == 0))
            ):
                raise ValueError("Split normalization exceeds the numeric range")
            raw_values.flags.writeable = False
    except (ValueError, ValidationError, UnicodeError, csv.Error, OverflowError) as exc:
        if isinstance(exc, Problem):
            raise
        raise Problem("E401_DATA", str(exc)) from exc
    sem = meta.model_dump(exclude={"gap_policy", "schema_version"})
    sem["timeframe"] = delta // 1000000
    header = canonical(sem).encode()
    hasher = hashlib.sha256(
        f"tradelang.dataset.v{meta.schema_version}\n".encode()
        + struct.pack("<I", len(header))
        + header
    )
    packed = np.empty((len(times), 6), dtype="<f8")
    packed[:, 0].view("<i8")[:] = times
    packed[:, 1:] = values if raw_values is None else raw_values
    hasher.update(memoryview(packed))
    times.flags.writeable = False
    values.flags.writeable = False
    with path.open("rb") as f:
        raw = hashlib.file_digest(f, "sha256").hexdigest()
    after = path.stat()
    if (before.st_ino, before.st_size, before.st_mtime_ns) != (
        after.st_ino,
        after.st_size,
        after.st_mtime_ns,
    ):
        raise Problem("E401_DATA", "Dataset changed during import")
    return Dataset(
        meta,
        times,
        values,
        hasher.hexdigest(),
        raw,
        int(np.sum(diff - 1)),
        path,
        grid=grid,
        session_rows=session_rows,
        split_factors=split_factors,
        raw_values=raw_values,
    )


def validate_indicator_data(s, timeframe_seconds=None):
    duration = s.seconds if timeframe_seconds is None else timeframe_seconds
    session_based = s.config.calendar == "session"
    if (
        duration is not None
        and (duration >= 86400 or (not session_based and 86400 % duration))
        and any(call.type.clock is None for call in s.calls("VWAP"))
    ):
        raise Problem(
            "E402_WINDOW",
            "VWAP requires intraday session candles"
            if session_based
            else "VWAP requires an intraday timeframe that divides a UTC day",
        )


def window(s, d):
    duration = d.timeframe_seconds
    for field, expected, actual in (
        ("market", s.symbol, d.meta.symbol),
        ("timeframe", s.seconds, duration),
        ("quote currency", s.config.currency, d.meta.quote_currency),
        ("calendar", s.config.calendar, d.meta.calendar),
    ):
        if expected is not None and expected != actual:
            if field == "timeframe":
                expected, actual = timeframe_label(expected), d.meta.timeframe
            raise Problem(
                "E402_WINDOW",
                f"Strategy requires {field} {expected}, dataset has {actual}",
            )
    validate_indicator_data(s, duration)
    delta = duration * 1000000
    if d.grid is not None:
        try:
            bounds = d.grid.window(s.config.from_date, s.config.to_date)
        except ValueError as exc:
            raise Problem("E402_WINDOW", str(exc)) from exc
    else:
        a = micros(datetime.fromisoformat(s.config.from_date).replace(tzinfo=UTC))
        b = micros(
            datetime.fromisoformat(s.config.to_date).replace(tzinfo=UTC)
            + timedelta(days=1)
        )
        start = -(-a // delta) * delta
        last = b // delta * delta - delta
        bounds = (start, last) if start <= last else None
    if bounds is None:
        raise Problem(
            "E402_WINDOW",
            "The requested dates contain no complete candles at this timeframe",
            suggestion="Use a wider date range or select a shorter timeframe",
            details={
                "from_date": s.config.from_date,
                "to_date": s.config.to_date,
                "timeframe_seconds": duration,
            },
        )
    start, last = bounds
    i, k = map(int, d.times.searchsorted([start, last]))
    if k >= len(d.times) or i > k or d.times[i] != start or d.times[k] != last:
        first_required, last_required = instant(start), instant(last)
        first_observed, last_observed = instant(d.times[0]), instant(d.times[-1])
        raise Problem(
            "E402_WINDOW",
            f"The window requires complete candles opening at {first_required} and "
            f"{last_required}. Dataset opens span {first_observed} through {last_observed}.",
            suggestion="Include both endpoint candles or choose dates covered by the dataset",
            details={
                "required_first_open": first_required,
                "required_last_open": last_required,
                "observed_first_open": first_observed,
                "observed_last_open": last_observed,
            },
        )
    j = max(i, s.warmup)
    if j >= k:
        eligible_close = instant(d.close_at(j)) if j == k else None
        history_needed = max(0, s.warmup - k + 1)
        suggestion = (
            "Extend the date window to include an eligible close and a later open"
        )
        if i < k and history_needed:
            unit = "candle" if history_needed == 1 else "candles"
            suggestion += (
                f", or supply {history_needed} more observed {unit} before the window"
            )
        raise Problem(
            "E_NO_EXECUTION_WINDOW",
            "The first eligible close has no later in-window open"
            if eligible_close
            else "Insufficient completed candles for structural warmup in this window",
            suggestion=suggestion,
            details={
                "warmup_index": s.warmup,
                "observed_pre_window_rows": i,
                "observed_window_rows": k - i + 1,
                "first_eligible_close": eligible_close,
                "next_grid_open": eligible_close if d.grid is None else None,
                "last_observed_window_open": instant(d.times[k]),
            },
        )
    return i, j, k


def prepare_window(strategy, primary, profile=None, *, profile_end=None, feeds=None):
    keys = dict.fromkeys(
        profile_key([argument.value for argument in call.args])
        for call in strategy.calls("VPROFILE")
    )
    if keys and profile is None:
        raise Problem(
            "E402_WINDOW", "Volume Profile requires a lower-timeframe dataset"
        )
    if profile is not None and not keys:
        raise Problem("E402_WINDOW", "A profile dataset requires a VPROFILE call")
    first, signal, last = window(strategy, primary)
    duration = primary.timeframe_seconds
    profiles = {}
    if profile is not None:
        compatibility_fields = (
            "symbol",
            "quote_currency",
            "price_basis",
            "calendar",
            "volume_unit",
            "timestamp_convention",
            "session_schedule",
            "splits",
        )
        profile_seconds = profile.timeframe_seconds
        if (
            profile_seconds >= duration
            or (
                duration % profile_seconds
                and not (primary.grid is not None and duration == 86400)
            )
            or any(
                getattr(primary.meta, field) != getattr(profile.meta, field)
                for field in compatibility_fields
            )
        ):
            raise Problem(
                "E402_WINDOW",
                "Profile candles must match the primary market and divide its timeframe",
            )
        end = last if profile_end is None else min(last, profile_end)
        profiles = prepare_profiles(
            primary.times[: end + 1],
            duration * 1_000_000,
            profile.times,
            profile_seconds * 1_000_000,
            profile.column("close"),
            profile.column("volume"),
            keys,
            primary_closes=primary.session_rows.close[: end + 1]
            if primary.session_rows is not None
            else None,
            child_closes=profile.session_rows.close
            if profile.session_rows is not None
            else None,
        )
    alignments = prepare_feeds(
        strategy,
        primary,
        feeds,
        last if profile_end is None else min(last, profile_end),
    )
    workload = estimate_workload(
        strategy, primary, profile, first, last, profiles, alignments
    )
    admit_workload(workload)
    return PreparedWindow(first, signal, last, profiles, duration, workload, alignments)
