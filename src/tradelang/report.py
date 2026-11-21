"""Reproducible run bundles with staged publication."""

import csv
import hashlib
import json
import os
import platform
import re
import shutil
import tempfile
import tomllib
import uuid
import zipfile
from datetime import UTC, datetime
from importlib import metadata
from pathlib import Path

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq

from .data import (
    COLUMNS,
    canonical,
    digest,
    hash_json,
    instant,
    prepare_window,
    validate_indicator_data,
)
from .engine import ARTIFACT_SCHEMA_VERSION, SEMANTICS_VERSION, execute_prepared
from .model import UNITS, Problem

PROFILE_ARTIFACT_SCHEMA_VERSION = 3


def projection(value):
    if isinstance(value, list):
        return [projection(v) for v in value]
    if isinstance(value, dict):
        return {
            k: projection(v)
            for k, v in value.items()
            if k not in {"span", "inferred_type", "node_id"}
        }
    return value


def identity(s):
    spec = s.public()
    return dict(
        source_hash=digest(s.source),
        spec_hash=hash_json(projection({k: v for k, v in spec.items() if k != "name"})),
    )


def resolved(s, d, *, profile=None, prepared=None):
    if prepared is None:
        prepared = prepare_window(s, d, profile)
    a, j, k = prepared.first, prepared.first_signal, prepared.last
    dt = s.seconds * 1000000
    return dict(
        first_open=instant(d.times[a]),
        last_close_at=instant(d.times[k] + dt),
        readiness_index=s.warmup,
        first_signal_at=instant(d.times[j] + dt),
        first_execution_at=instant(d.times[j + 1]),
    )


def render(e):
    args = [render(c) for c in e.args]
    match e.op:
        case "literal":
            if e.type.kind == "boolean":
                return str(e.value).lower()
            unit = next(k for k, v in UNITS.items() if v == e.type.unit)
            return canonical(e.value) + (f" {unit}" if unit != "ratio" else "")
        case "let" | "account" | "builtin":
            return e.value
        case "field":
            return f"{args[0]}.{e.value}"
        case "offset":
            return f"{args[0]}[{e.value}]"
        case "call":
            arguments = [
                canonical(c.value)
                if c.op == "literal" and c.type.unit == "count"
                else arg
                for c, arg in zip(e.args, args)
            ]
            return f"{e.value}(" + ", ".join(arguments) + ")"
        case _:
            if len(args) == 1:
                return f"({e.value} {args[0]})"
            op = f"crosses {e.value}" if e.op == "cross" else e.value
            return f"({args[0]} {op} {args[1]})"


def explain(s, d=None, *, profile=None):
    lines = [
        s.name,
        f"{s.symbol}, {s.seconds} seconds per UTC bar, {s.config.from_date} through {s.config.to_date} inclusive.",
        f"Start with {canonical(s.config.capital)} {s.config.currency}.",
    ]
    lines.extend(f"let {n} = {render(e)}" for n, e, _ in s.bindings)
    lines.extend(
        [
            f"At close, enter when {render(s.entry)}.",
            f"At next open, allocate {render(s.sizing)} "
            + (s.config.currency if s.fixed else "of equity")
            + " including entry fee.",
            f"Exit all at the next open after {render(s.exit)}.",
        ]
    )
    for key, e in (("Stop", s.stop), ("Target", s.target)):
        if e:
            lines.append(
                f"{key} distance {render(e)} ({'price' if e.type.unit == (1, -1) else 'fraction of fill'}), sampled at signal and frozen at entry."
            )
    lines.append(
        f"Warmup index {s.warmup}. Protection at open precedes signal exits. Stop wins simultaneous intrabar touches. Final holdings marked at close."
    )
    lines.append(
        f"Fee {canonical(s.config.fee_rate * 10000)} bps and adverse slippage {canonical(s.config.slippage_rate * 10000)} bps per side. Buy-and-hold enters at the first executable open."
    )
    win = resolved(s, d, profile=profile) if d is not None else None
    if win is not None:
        lines.append(
            f"Dataset {d.dataset_hash}. Gap policy {d.meta.gap_policy}. First eligible close {win['first_signal_at']}, first executable open {win['first_execution_at']}."
        )
    else:
        lines.append(
            "Select a dataset to resolve bar coverage and execution timestamps."
        )
        if next(s.calls("VPROFILE"), None):
            lines.append("Volume Profile requires an aligned lower-timeframe dataset.")
    if profile is not None:
        lines.append(f"Volume Profile dataset {profile.dataset_hash}.")
    return dict(
        **identity(s),
        text="\n".join(lines),
        assumptions=dict(
            calendar="24x7",
            gap_policy=d.meta.gap_policy if d else None,
            terminal="mark_to_market",
            benchmark="warmup_aligned_hold",
        ),
        warmup_index=s.warmup,
        resolved_window=win,
    )


TRADE_FIELDS = [
    "trade_id",
    "direction",
    "entry_signal_bar",
    "entry_signal_at",
    "entry_bar",
    "entry_at",
    "entry_reference",
    "entry_price",
    "exit_signal_bar",
    "exit_signal_at",
    "exit_bar",
    "exit_at",
    "exit_time_precision",
    "exit_reference",
    "exit_price",
    "quantity",
    "entry_fee",
    "exit_fee",
    "entry_slippage_cost",
    "exit_slippage_cost",
    "gross_pnl",
    "net_pnl",
    "return_fraction",
    "bars_held",
    "exit_reason",
    "entry_rationale",
    "exit_rationale",
    "protection",
]


def write_json(path, obj):
    path.write_text(
        json.dumps(obj, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False)
        + "\n"
    )


def write_csv(path, fields, rows):
    with path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for row in rows:
            w.writerow(
                {
                    k: canonical(v) if isinstance(v, (bool, list, dict)) else v
                    for k, v in row.items()
                }
            )


def now():
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def package_revision(package, archive_path):
    files: dict[str, str] = {}
    with zipfile.ZipFile(
        archive_path, "w", compression=zipfile.ZIP_DEFLATED
    ) as archive:
        for path in sorted(package.rglob("*")):
            relative = path.relative_to(package)
            if (
                not path.is_file()
                or "__pycache__" in relative.parts
                or relative.parts[0] == "_build"
                or path.suffix in {".pyc", ".pyo"}
            ):
                continue
            name = relative.as_posix()
            raw = path.read_bytes()
            files[name] = digest(raw)
            archive.writestr(f"tradelang/{name}", raw)
    return hash_json(files)


def environment_snapshot(stage):
    package = Path(__file__).parent
    revision = package_revision(package, stage / "source-package.zip")
    installed = sorted(
        (re.sub(r"[-_.]+", "-", p.metadata["Name"]).lower(), p.version)
        for p in metadata.distributions()
        if p.metadata["Name"]
    )
    inventory = "".join(f"{name}=={version}\n" for name, version in installed).encode()
    (stage / "dependency-lock.txt").write_bytes(inventory)
    build = package / "_build"
    lock_path = build / "uv.lock"
    project_path = build / "pyproject.toml"
    release_lock_hash = None
    if lock_path.is_file() and project_path.is_file():
        lock = lock_path.read_bytes()
        locked = {
            (p["name"], p["version"]) for p in tomllib.loads(lock.decode())["package"]
        }
        if set(installed) <= locked:
            release_lock_hash = digest(lock)
            (stage / "uv.lock").write_bytes(lock)
            shutil.copyfile(project_path, stage / "pyproject.toml")
    return dict(
        code_revision=revision,
        dirty_patch_hash=None,
        python_version=platform.python_version(),
        dependency_lock_hash=digest(inventory),
        release_lock_hash=release_lock_hash,
        platform=platform.platform(),
        engine_version="0.1.0",
    )


def publish(s, d, out, *, profile=None):
    out = Path(out)
    if out.exists() and (not out.is_dir() or any(out.iterdir())):
        raise FileExistsError("Output directory must be new or empty")
    paired = profile is not None or next(s.calls("VPROFILE"), None) is not None
    prepared = prepare_window(s, d, profile) if paired else None
    if not paired:
        validate_indicator_data(s)
    out.parent.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix="." + out.name + "-", dir=out.parent))
    started = now()
    try:
        if prepared is None:
            prepared = prepare_window(s, d)
        result = execute_prepared(s, d, prepared)
        summary = result["summary"]
        eq = result["equity"]
        write_json(stage / "summary.json", summary)
        write_json(stage / "strategy-spec.json", s.public())
        write_json(stage / "diagnostics.json", result["diagnostics"])
        (stage / "source.trade").write_bytes(s.source)
        write_csv(stage / "trades.csv", TRADE_FIELDS, result["trades"])
        write_csv(stage / "equity.csv", list(eq[0]), eq)
        with pq.ParquetWriter(
            stage / "equity.parquet", pa.Table.from_pylist(eq[:2]).schema
        ) as writer:
            for start in range(0, len(eq), 8192):
                writer.write_table(
                    pa.Table.from_pylist(eq[start : start + 8192], schema=writer.schema)
                )
        with (stage / "events.jsonl").open("w") as f:
            for event in result["events"]:
                f.write(canonical(event) + "\n")
        copied = stage / ("input" + d.path.suffix.lower())
        shutil.copyfile(d.path, copied)
        if digest(copied.read_bytes()) != d.source_hash:
            raise Problem("E401_DATA", "Dataset changed after loading")
        write_json(stage / "metadata.json", d.meta.model_dump())
        profile_identity = None
        profile_manifest = {}
        if profile is not None:
            data_file = "profile-input" + profile.path.suffix.lower()
            metadata_file = "profile-metadata.json"
            profile_copy = stage / data_file
            shutil.copyfile(profile.path, profile_copy)
            with profile_copy.open("rb") as stream:
                if (
                    hashlib.file_digest(stream, "sha256").hexdigest()
                    != profile.source_hash
                ):
                    raise Problem("E401_DATA", "Profile dataset changed after loading")
            write_json(stage / metadata_file, profile.meta.model_dump())
            profile_identity = dict(
                role="volume_profile", dataset_hash=profile.dataset_hash
            )
            profile_manifest["profile_input"] = dict(
                **profile_identity,
                source_hash=profile.source_hash,
                gap_policy=profile.meta.gap_policy,
                data_file=data_file,
                metadata_file=metadata_file,
            )
        gap_sizes = np.diff(d.times) // 1000000
        write_json(
            stage / "dataset-summary.json",
            dict(
                row_count=len(d.times),
                first_open=instant(d.times[0]),
                last_open=instant(d.times[-1]),
                last_close_at=instant(d.times[-1] + s.seconds * 1000000),
                missing_bar_count=d.missing,
                largest_gap_seconds=int(gap_sizes.max())
                if len(gap_sizes) and d.missing
                else 0,
                zero_volume_count=int((d.values[:, 4] == 0).sum()),
                minimum=dict(zip(COLUMNS[1:], d.values.min(axis=0).tolist())),
                maximum=dict(zip(COLUMNS[1:], d.values.max(axis=0).tolist())),
                source_hash=d.source_hash,
                dataset_hash=d.dataset_hash,
                filename=d.path.name,
            ),
        )
        env = environment_snapshot(stage)
        write_json(stage / "environment.json", env)
        policy = dict(
            schema_version=1,
            gap_policy=d.meta.gap_policy,
            benchmark="warmup_aligned_hold",
            terminal="mark_to_market",
            intrabar="stop_first",
            exit_priority="gap_then_signal_then_intrabar",
            numeric="binary64_v1",
            max_rows=1000000,
        )
        win = resolved(s, d, prepared=prepared)
        ids = identity(s)
        configuration = dict(
            policy=policy,
            window=win,
            backtest=projection(s.public()["backtest"]),
            dataset_hash=d.dataset_hash,
        )
        if profile is not None:
            configuration["profile_dataset"] = dict(
                role="volume_profile",
                dataset_hash=profile.dataset_hash,
                gap_policy=profile.meta.gap_policy,
            )
        signature = dict(
            dsl_version=1,
            semantics_version=SEMANTICS_VERSION,
            spec_hash=ids["spec_hash"],
            dataset_hash=d.dataset_hash,
            environment_hash=hash_json(env),
            config_hash=hash_json(configuration),
        )
        if profile_identity is not None:
            signature["profile_dataset"] = profile_identity
        logical = hashlib.sha256()
        for key in ("summary", "trades", "equity", "events", "diagnostics"):
            items = [result[key]] if key == "summary" else result[key]
            logical.update(key.encode() + b"\n")
            for item in items:
                if key == "diagnostics":
                    item = {k: v for k, v in item.items() if k != "span"}
                if key == "summary":
                    item = {
                        **item,
                        "warnings": [
                            {k: v for k, v in w.items() if k != "span"}
                            for w in item["warnings"]
                        ],
                    }
                logical.update(canonical(item).encode() + b"\n")
        manifest = dict(
            schema_version=(
                ARTIFACT_SCHEMA_VERSION
                if profile is None
                else PROFILE_ARTIFACT_SCHEMA_VERSION
            ),
            engine_name="bar-event-v1",
            run_id=str(uuid.uuid4()),
            **signature,
            source_hash=ids["source_hash"],
            run_fingerprint=hash_json(signature),
            result_digest=logical.hexdigest(),
            **env,
            **profile_manifest,
            resolved_policy=policy,
            dataset_metadata=d.meta.model_dump(),
            requested_window={"from": s.config.from_date, "to": s.config.to_date},
            resolved_window=win,
            warnings=result["diagnostics"],
            created_at=started,
            finished_at=now(),
            source_filename=None,
            import_source_hash=d.source_hash,
            artifact_files=[
                dict(name=p.name, sha256=digest(p.read_bytes()), bytes=p.stat().st_size)
                for p in sorted(stage.iterdir())
            ],
        )
        write_json(stage / "manifest.json", manifest)
        os.replace(stage, out)
        return dict(
            run_id=manifest["run_id"],
            run_fingerprint=manifest["run_fingerprint"],
            result_digest=manifest["result_digest"],
            artifact_directory=str(out.resolve()),
            summary=summary,
        )
    except BaseException as exc:
        if profile is not None:
            shutil.rmtree(stage, ignore_errors=True)
            raise
        try:
            for name in ("manifest.json", "summary.json"):
                (stage / name).unlink(missing_ok=True)
            failure = dict(message=str(exc)[:512], failed_at=now())
            if isinstance(exc, Problem):
                failure["diagnostic"] = exc.diagnostic
            write_json(stage / "failure.json", failure)
        except OSError:
            pass
        raise
