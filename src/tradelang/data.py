"""Validate a single immutable, ordered OHLCV snapshot."""

import csv
import hashlib
import json
import re
import struct
from array import array
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Literal

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from .compiler import seconds
from .model import Problem

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
    schema_version: Literal[1] = 1
    symbol: str = Field(pattern=r"^[A-Z0-9][A-Z0-9_.-]{0,31}$")
    quote_currency: str = Field(pattern=r"^[A-Z][A-Z0-9]{1,11}$")
    timeframe: str = Field(pattern=r"^[1-9][0-9]{0,5}[mhd]$")
    calendar: Literal["24x7"]
    timestamp_convention: Literal["bar_open"]
    volume_unit: Literal["base_quantity"]
    price_basis: Literal["raw_spot"]
    gap_policy: Literal["allow", "reject"] = "reject"


@dataclass(frozen=True)
class Dataset:
    meta: Metadata
    times: np.ndarray
    values: np.ndarray
    dataset_hash: str
    source_hash: str
    missing: int
    path: Path

    def column(self, name):
        return self.values[:, COLUMNS.index(name) - 1]


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
        o, h, low, c, v = values.T
        bad = (
            (~np.isfinite(values).all(axis=1))
            | (low <= 0)
            | (low > np.minimum(o, c))
            | (h < np.maximum(o, c))
            | (v < 0)
            | (times % delta != 0)
        )
        if bad.any():
            raise Problem(
                "E401_DATA",
                "Invalid OHLCV or timestamp alignment",
                row=int(np.argmax(bad)) + 1,
            )
        diff = np.diff(times)
        bad = (diff <= 0) if meta.gap_policy == "allow" else (diff != delta)
        if bad.any():
            raise Problem(
                "E401_DATA",
                "Unsorted, duplicate or missing candle",
                row=int(np.argmax(bad)) + 2,
            )
        if int(times[-1]) + delta > micros(as_of_utc or datetime.now(UTC)):
            raise ValueError("Incomplete candle")
    except (ValueError, ValidationError, UnicodeError, csv.Error, OverflowError) as exc:
        if isinstance(exc, Problem):
            raise
        raise Problem("E401_DATA", str(exc)) from exc
    values[values == 0] = 0
    sem = meta.model_dump(exclude={"gap_policy", "schema_version"})
    sem["timeframe"] = delta // 1000000
    header = canonical(sem).encode()
    hasher = hashlib.sha256(
        b"tradelang.dataset.v1\n" + struct.pack("<I", len(header)) + header
    )
    packed = np.empty((len(times), 6), dtype="<f8")
    packed[:, 0].view("<i8")[:] = times
    packed[:, 1:] = values
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
        int(np.sum(diff // delta - 1)),
        path,
    )


def window(s, d):
    if (s.symbol, s.seconds, s.config.currency) != (
        d.meta.symbol,
        seconds(d.meta.timeframe),
        d.meta.quote_currency,
    ):
        raise Problem("E402_WINDOW", "Strategy and dataset metadata differ")
    delta = s.seconds * 1000000
    a = micros(datetime.fromisoformat(s.config.from_date).replace(tzinfo=UTC))
    b = micros(
        datetime.fromisoformat(s.config.to_date).replace(tzinfo=UTC) + timedelta(days=1)
    )
    start = -(-a // delta) * delta
    last = b // delta * delta - delta
    i, k = map(int, d.times.searchsorted([start, last]))
    if k >= len(d.times) or i > k or d.times[i] != start or d.times[k] != last:
        raise Problem("E402_WINDOW", "Missing complete edge coverage")
    j = max(i, s.warmup)
    if j >= k:
        raise Problem(
            "E_NO_EXECUTION_WINDOW", "Insufficient completed bars after warmup"
        )
    return i, j, k
