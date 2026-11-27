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
from dataclasses import asdict
from datetime import UTC, datetime
from importlib import metadata
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from .data import (
    COLUMNS,
    canonical,
    digest,
    hash_json,
    instant,
    prepare_window,
)
from .decision import DECISION_FILE, DecisionLog
from .engine import ARTIFACT_SCHEMA_VERSION, execute_prepared, semantics_version
from .feeds import ALIGNMENT_POLICY
from .model import UNITS, Problem
from .run_config import configuration_view

PROFILE_ARTIFACT_SCHEMA_VERSION = 3
FEED_ARTIFACT_SCHEMA_VERSION = 4


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


def resolved(s, d, *, profile=None, prepared=None, feeds=None):
    if prepared is None:
        prepared = prepare_window(s, d, profile, feeds=feeds)
    a, j, k = prepared.first, prepared.first_signal, prepared.last
    return dict(
        first_open=instant(d.times[a]),
        last_close_at=instant(d.close_at(k)),
        readiness_index=s.warmup,
        first_signal_at=instant(d.close_at(j)),
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
        case "let" | "account" | "builtin" | "parameter":
            return e.value
        case "field":
            return f"{args[0]}.{e.value}"
        case "on_feed":
            return f"on({e.value}, {args[0]})"
        case "align":
            return f"align({args[0]})"
        case "offset":
            return f"{args[0]}[{e.value}]"
        case "call" | "choice":
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


def explain(s, d=None, *, profile=None, prepared=None, feeds=None):
    def exit_action(sale):
        if sale is None:
            return "all"
        return render(sale.expression) + (
            " of position" if sale.kind == "fraction" else " units"
        )

    symbol = d.meta.symbol if d is not None else s.symbol
    duration = d.timeframe_seconds if d is not None else s.seconds
    market = symbol or "Market from selected dataset"
    clock = (
        f"{duration} nominal seconds per session candle"
        if duration is not None and s.config.calendar == "session"
        else f"{duration} seconds per UTC bar"
        if duration is not None
        else "timeframe from selected dataset"
    )
    lines = [
        s.name,
        f"{market}, {clock}, {s.config.from_date} through {s.config.to_date} inclusive.",
        f"Start with {canonical(s.config.capital)} {s.config.currency}.",
    ]
    if s.version >= 2:
        lines.extend(
            f"Parameter {parameter.name} = {canonical(parameter.value)} ({parameter.kind})."
            for parameter in s.parameters
        )
        for name, expression, _ in s.bindings:
            if expression.field_ready:
                fields = ", ".join(
                    f"{field} at {row}" for field, row in expression.field_ready
                )
                lines.append(f"{name} field readiness · {fields}.")
    lines.extend(f"let {n} = {render(e)}" for n, e, _ in s.bindings)
    sizing = (
        f"At next open, allocate {render(s.sizing)} "
        + (s.config.currency if s.fixed else "of equity")
        + " including entry fee."
    )
    if s.stop_risk:
        cap = render(s.allocation_cap) if s.allocation_cap is not None else "100%"
        sizing = (
            f"At next open, risk {render(s.sizing)} of equity at the modeled stop touch. "
            f"Cap the fee-inclusive entry debit at {cap} of equity and available cash. "
            "The model includes fees and adverse slippage on both sides. "
            "An opening gap can exceed the modeled loss."
        )
    if s.short_margin is not None:
        margin = s.short_margin
        sizing = (
            f"At next open, reserve {render(s.sizing)} "
            + (s.config.currency if s.fixed else "of equity")
            + " for the short's initial margin and entry fee."
        )
        lines.append(
            f"Borrowed-asset short with {canonical(margin.initial_rate * 100)}% initial margin, "
            f"{canonical(margin.maintenance_rate * 100)}% maintenance margin, "
            f"and {canonical(margin.borrow_rate_per_day * 10000)} bps of borrow per day."
        )
    exit_verb = "cover" if s.short_margin is not None else "sell"
    lines.extend(
        [
            f"At close, enter when {render(s.entry)}.",
            sizing,
        ]
    )
    if s.exit is not None:
        lines.append(
            f"Exit {exit_action(s.sale)} at the next open after {render(s.exit)}."
        )
    else:
        if any(rule.sale is not None for rule in s.exit_rules):
            lines.append(
                "Execute the first true exit rule at the next open. Skip unavailable predicates."
            )
        else:
            lines.append(
                "Exit all at the next open after the first true rule in source order. Skip unavailable predicates."
            )
        for rule in s.exit_rules:
            criterion = (
                f"when {render(rule.condition)}"
                if rule.condition is not None
                else f"after {rule.after_bars} completed holding candles"
            )
            action = (
                f" {exit_verb} {exit_action(rule.sale)}"
                if rule.sale is not None
                else ""
            )
            lines.append(f"Exit rule {rule.name} {criterion}{action}.")
    if s.scale is not None:
        unit = s.config.currency if s.scale.fixed else "of available cash"
        lines.append(
            f"While holding, add {render(s.scale.sizing)} {unit} at the next open "
            f"when {render(s.scale.condition)}. A matching exit takes priority."
        )
    if s.quantity_step is not None:
        lines.append(
            f"Round purchases and partial exits down to {canonical(s.quantity_step)}-unit steps."
        )
    for key, e in (("Stop", s.stop), ("Target", s.target)):
        if e:
            update = (
                "frozen at entry"
                if key != "Stop" or s.trail is None
                else "anchored to the entry fill"
            )
            lines.append(
                f"{key} distance {render(e)} ({'price' if e.type.unit == (1, -1) else 'fraction of fill'}), sampled at signal and {update}."
            )
    if s.trail is not None:
        direction = "lower" if s.short_margin is not None else "higher"
        lines.append(
            f"Trailing distance {render(s.trail)} uses the completed close. A {direction} valid trigger activates at the next observed open."
        )
    if s.order_max_age_seconds:
        lines.append(
            f"Queued orders expire at an open at least {s.order_max_age_seconds} seconds after their signal close. Open protection acts first."
        )
    lines.append(
        f"Warmup index {s.warmup}. Protection at open precedes signal exits. Stop wins simultaneous intrabar touches. Final holdings marked at close."
    )
    if s.version >= 2 and s.warmup:
        lines.append(f"Warmup requires {s.warmup} earlier observed candles.")
        for label, expression in s.named_roots(warmup=True):
            if expression is not None and expression.ready == s.warmup:
                origin = expression.span
                lines.append(
                    f"Warmup driver · {label}, line {origin.start_line}, "
                    f"column {origin.start_column}: {render(expression)}."
                )
    lines.append(
        f"Fee {canonical(s.config.fee_rate * 10000)} bps and adverse slippage {canonical(s.config.slippage_rate * 10000)} bps per side. Buy-and-hold enters at the first executable open."
    )
    win = (
        resolved(s, d, profile=profile, prepared=prepared, feeds=feeds)
        if d is not None
        else None
    )
    if win is not None:
        lines.append(
            f"Dataset {d.dataset_hash}. Gap policy {d.meta.gap_policy}. First eligible close {win['first_signal_at']}, first executable open {win['first_execution_at']}."
        )
        if s.version >= 2:
            window = (
                prepared
                if prepared is not None
                else prepare_window(s, d, profile, feeds=feeds)
            )
            lines.append(
                f"Dataset supplied {window.first} observed pre-window candles."
            )
    else:
        lines.append(
            "Select a dataset to resolve bar coverage and execution timestamps."
        )
        if next(s.calls("VPROFILE"), None):
            lines.append("Volume Profile requires an aligned lower-timeframe dataset.")
    if profile is not None:
        lines.append(f"Volume Profile dataset {profile.dataset_hash}.")
    if s.feed is not None:
        feed = s.feed
        lines.append(
            f"Feed {feed.name} uses {feed.seconds}-second candles. Align selects completed closes at or before the primary close. Maximum age is {feed.max_age_seconds} seconds."
        )
        if prepared is not None and feed.name in prepared.feeds:
            aligned = prepared.feeds[feed.name]
            lines.append(f"Feed {feed.name} dataset {aligned.dataset.dataset_hash}.")
    if d is not None and d.grid is not None:
        schedule = d.grid.schedule
        lines.append(
            f"Session schedule {schedule.market} {schedule.version} in {schedule.timezone}. Price basis {d.meta.price_basis}."
        )
    return dict(
        **identity(s),
        text="\n".join(lines),
        assumptions=dict(
            calendar=s.config.calendar,
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
SHORT_TRADE_FIELDS = ["initial_collateral", "borrow_cost"]


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


def run_identity(s, d, prepared, profile, environment):
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
    if s.order_max_age_seconds is not None:
        policy["order_max_age_seconds"] = s.order_max_age_seconds
    if s.manages_quantity:
        policy["position_basis"] = "weighted_average"
        policy["quantity_step"] = s.quantity_step
    if s.short_margin is not None:
        policy["short_margin"] = {
            "model": "borrowed_asset_v1",
            **asdict(s.short_margin),
        }
    if d.grid is not None:
        policy["session_calendar"] = {
            "market": d.grid.schedule.market,
            "version": d.grid.schedule.version,
            "timezone": d.grid.schedule.timezone,
        }
        policy["price_basis"] = d.meta.price_basis
    win = resolved(s, d, prepared=prepared)
    ids = identity(s)
    configuration = dict(
        policy=policy,
        window=win,
        backtest=asdict(s.config),
        dataset_hash=d.dataset_hash,
    )
    if profile is not None:
        configuration["profile_dataset"] = dict(
            role="volume_profile",
            dataset_hash=profile.dataset_hash,
            gap_policy=profile.meta.gap_policy,
        )
    secondary = [
        dict(
            name=name,
            role="higher_timeframe",
            policy=ALIGNMENT_POLICY,
            timeframe_seconds=alignment.dataset.timeframe_seconds,
            max_age_seconds=s.feed.max_age_seconds,
            dataset_hash=alignment.dataset.dataset_hash,
            gap_policy=alignment.dataset.meta.gap_policy,
        )
        for name, alignment in sorted(prepared.feeds.items())
    ]
    if secondary:
        configuration["feeds"] = secondary
    signature = dict(
        dsl_version=s.version,
        semantics_version=semantics_version(s.version),
        spec_hash=ids["spec_hash"],
        dataset_hash=d.dataset_hash,
        environment_hash=hash_json(environment),
        config_hash=hash_json(configuration),
    )
    if profile is not None:
        signature["profile_dataset"] = dict(
            role="volume_profile",
            dataset_hash=profile.dataset_hash,
        )
    if secondary:
        signature["feeds"] = secondary
    return policy, win, ids, signature


def publish(
    s,
    d,
    out,
    *,
    profile=None,
    progress=None,
    expected_fingerprint=None,
    run_id=None,
    feeds=None,
):
    out = Path(out)
    if out.exists() and (not out.is_dir() or any(out.iterdir())):
        raise FileExistsError("Output directory must be new or empty")
    paired = (
        profile is not None
        or next(s.calls("VPROFILE"), None) is not None
        or s.requires_feed
        or feeds
    )
    prepared = prepare_window(s, d, profile, feeds=feeds) if paired else None
    out.parent.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix="." + out.name + "-", dir=out.parent))
    started = now()
    try:
        if prepared is None:
            prepared = prepare_window(s, d)
        env = environment_snapshot(stage)
        policy, win, ids, signature = run_identity(s, d, prepared, profile, env)
        fingerprint = hash_json(signature)
        if expected_fingerprint is not None and fingerprint != expected_fingerprint:
            raise Problem(
                "E_ENV_CHANGED", "Run environment or snapshot changed after submission"
            )
        decisions = DecisionLog(
            prepared.first,
            prepared.last,
            ordered_exits=bool(s.exit_rules),
            closes=d.session_rows.close if d.session_rows is not None else None,
            split_factors=d.split_factors,
        )
        result = execute_prepared(
            s, d, prepared, progress=progress, decisions=decisions
        )
        summary = result["summary"]
        eq = result["equity"]
        write_json(stage / "summary.json", summary)
        write_json(stage / "strategy-spec.json", s.public())
        write_json(stage / "diagnostics.json", result["diagnostics"])
        (stage / "source.trade").write_bytes(s.source)
        trade_fields = (
            TRADE_FIELDS + SHORT_TRADE_FIELDS if s.short_margin else TRADE_FIELDS
        )
        write_csv(stage / "trades.csv", trade_fields, result["trades"])
        write_csv(stage / "equity.csv", list(eq[0]), eq)
        with pq.ParquetWriter(
            stage / "equity.parquet", pa.Table.from_pylist(eq[:2]).schema
        ) as writer:
            for start in range(0, len(eq), 8192):
                writer.write_table(
                    pa.Table.from_pylist(eq[start : start + 8192], schema=writer.schema)
                )
        offsets = [0]
        with (stage / "events.jsonl").open("wb") as f:
            for event in result["events"]:
                offsets.append(
                    offsets[-1] + f.write((canonical(event) + "\n").encode("utf-8"))
                )
        decisions.write(stage / DECISION_FILE, d.times, offsets)
        copied = stage / ("input" + d.path.suffix.lower())
        shutil.copyfile(d.path, copied)
        if digest(copied.read_bytes()) != d.source_hash:
            raise Problem("E401_DATA", "Dataset changed after loading")
        write_json(stage / "metadata.json", d.meta.model_dump())
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
            profile_manifest["profile_input"] = dict(
                role="volume_profile",
                dataset_hash=profile.dataset_hash,
                source_hash=profile.source_hash,
                gap_policy=profile.meta.gap_policy,
                data_file=data_file,
                metadata_file=metadata_file,
            )
        feed_files = {}
        recorded_feeds = []
        for feed in signature.get("feeds", ()):
            name = feed["name"]
            dataset = prepared.feeds[name].dataset
            data_file = f"feed-{name}-input{dataset.path.suffix.lower()}"
            metadata_file = f"feed-{name}-metadata.json"
            shutil.copyfile(dataset.path, stage / data_file)
            with (stage / data_file).open("rb") as stream:
                if (
                    hashlib.file_digest(stream, "sha256").hexdigest()
                    != dataset.source_hash
                ):
                    raise Problem("E401_DATA", f"Feed {name} changed after loading")
            write_json(stage / metadata_file, dataset.meta.model_dump())
            feed_files[name] = {"data": data_file, "metadata": metadata_file}
            recorded_feeds.append(
                {**feed, **feed_files[name], "source_hash": dataset.source_hash}
            )
        if (
            s.run_settings is not None
            or s.parameter_overrides
            or feed_files
            or d.grid is not None
            or s.short_margin is not None
        ):
            replay = dict(
                schema_version=1,
                settings=s.run_settings
                if s.run_settings is not None
                else {"parameters": dict(s.parameter_overrides)},
                data=copied.name,
                metadata="metadata.json",
            )
            if profile_manifest:
                replay.update(
                    profile_data=profile_manifest["profile_input"]["data_file"],
                    profile_metadata=profile_manifest["profile_input"]["metadata_file"],
                )
            if feed_files:
                replay["feeds"] = feed_files
            write_json(stage / "run-config.json", replay)
        write_json(
            stage / "dataset-summary.json",
            dict(
                row_count=len(d.times),
                first_open=instant(d.times[0]),
                last_open=instant(d.times[-1]),
                last_close_at=instant(d.close_at(-1)),
                missing_bar_count=d.missing,
                pre_window_missing_bar_count=d.missing_between(0, prepared.first),
                execution_window_missing_bar_count=d.missing_between(
                    prepared.first, prepared.last
                ),
                largest_gap_seconds=d.largest_gap_seconds(),
                zero_volume_count=int((d.values[:, 4] == 0).sum()),
                minimum=dict(zip(COLUMNS[1:], d.values.min(axis=0).tolist())),
                maximum=dict(zip(COLUMNS[1:], d.values.max(axis=0).tolist())),
                source_hash=d.source_hash,
                dataset_hash=d.dataset_hash,
                filename=d.path.name,
            ),
        )
        write_json(stage / "environment.json", env)
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
                FEED_ARTIFACT_SCHEMA_VERSION
                if recorded_feeds
                else ARTIFACT_SCHEMA_VERSION
                if profile is None
                else PROFILE_ARTIFACT_SCHEMA_VERSION
            ),
            engine_name="bar-event-v1",
            decision_inspection={
                "schema_version": decisions.version,
                "artifact": DECISION_FILE,
            },
            decision_counts=decisions.counts(),
            **(
                {
                    "position_ledger": {
                        "schema_version": 2 if s.short_margin else 1,
                        "artifact": "events.jsonl",
                    }
                }
                if s.manages_quantity
                else {}
            ),
            workload=prepared.workload,
            **(
                dict(parameter_overrides=dict(s.parameter_overrides))
                if s.version >= 2
                else {}
            ),
            **(
                dict(
                    run_settings=s.run_settings,
                    effective_configuration=configuration_view(s, d, profile),
                )
                if s.run_settings is not None
                else {}
            ),
            run_id=run_id if run_id is not None else str(uuid.uuid4()),
            **signature,
            source_hash=ids["source_hash"],
            run_fingerprint=fingerprint,
            result_digest=logical.hexdigest(),
            **env,
            **profile_manifest,
            **(dict(feed_inputs=recorded_feeds) if recorded_feeds else {}),
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
