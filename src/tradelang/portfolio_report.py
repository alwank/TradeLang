"""Portable inputs, inspection, and atomic publication for portfolio runs."""

import hashlib
import json
import os
import shutil
import tempfile
import uuid
from contextlib import ExitStack
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Literal

import pyarrow as pa
import pyarrow.parquet as pq
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from .data import (
    canonical,
    digest,
    hash_json,
    instant,
    load_dataset,
    unique_json_members,
)
from .decision import DecisionLog
from .model import Problem
from .portfolio import (
    MAX_ASSETS,
    PORTFOLIO_POLICY,
    PORTFOLIO_SEMANTICS,
    PORTFOLIO_VERSION,
    AssetInputs,
    PortfolioPreparation,
    PortfolioSpec,
    compile_portfolio,
    execute_portfolio_prepared,
    prepare_portfolio,
)
from .report import (
    SHORT_TRADE_FIELDS,
    TRADE_FIELDS,
    environment_snapshot,
    identity,
    now,
    run_identity,
    write_csv,
    write_json,
)
from .run_config import FeedFiles, RunSettings, configured_strategy

PORTFOLIO_ARTIFACT_SCHEMA_VERSION = 5


class PortfolioAssetFiles(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    strategy: str
    data: str
    metadata: str
    settings: RunSettings | None = None
    profile: FeedFiles | None = None
    feeds: Annotated[dict[str, FeedFiles], Field(max_length=1)] = Field(
        default_factory=dict
    )


class PortablePortfolioConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    schema_version: Literal[1] = 1
    assets: Annotated[
        dict[str, PortfolioAssetFiles], Field(min_length=2, max_length=MAX_ASSETS)
    ]


def load_portfolio_inputs(spec: PortfolioSpec, path: Path) -> dict[str, AssetInputs]:
    try:
        config = PortablePortfolioConfig.model_validate(
            json.loads(
                path.read_text(encoding="utf-8"), object_pairs_hook=unique_json_members
            )
        )
    except ValidationError as error:
        first = error.errors()[0]
        field = ".".join(map(str, first["loc"])) or "portfolio binding"
        raise Problem("E209_RUN_CONFIG", f"{field}: {first['msg']}") from error
    except (ValueError, RecursionError) as error:
        raise Problem(
            "E209_RUN_CONFIG", f"Invalid portfolio configuration: {error}"
        ) from error
    if config.assets.keys() != set(spec.assets):
        raise Problem(
            "E305_PORTFOLIO",
            "Run configuration must bind every declared asset alias exactly once",
        )
    checked_at = datetime.now(UTC)

    def load(data, metadata):
        raw = json.loads(
            (path.parent / metadata).read_text(encoding="utf-8"),
            object_pairs_hook=unique_json_members,
        )
        return load_dataset(path.parent / data, raw, as_of_utc=checked_at)

    inputs = {}
    for name in spec.assets:
        item = config.assets[name]
        try:
            primary = load(item.data, item.metadata)
            with (path.parent / item.strategy).open("rb") as stream:
                source = stream.read(65_537)
            if item.settings is not None and item.settings.capital is not None:
                raise Problem(
                    "E305_PORTFOLIO", "Set shared capital in the portfolio declaration"
                )
            strategy = configured_strategy(source, item.settings, dataset=primary)
            profile = (
                load(item.profile.data, item.profile.metadata) if item.profile else None
            )
            feeds = {
                name: load(feed.data, feed.metadata)
                for name, feed in item.feeds.items()
            }
            inputs[name] = AssetInputs(strategy, primary, profile, feeds)
        except Problem as error:
            diagnostic = error.diagnostic
            raise Problem(
                diagnostic["code"],
                f"{name}: {diagnostic['message']}",
                suggestion=diagnostic["suggestion"],
                row=diagnostic["data_row"],
                details={**diagnostic["details"], "asset": name},
            ) from error
    return inputs


def portfolio_inspection(
    spec: PortfolioSpec, prepared: PortfolioPreparation | None = None
) -> dict:
    resolved = None
    lines = [
        spec.name,
        f"Start with {spec.capital:g} {spec.currency}. Hold at most {spec.max_positions} assets.",
        "At a shared open, reductions settle before entries and adds.",
        "Commitment order · " + ", ".join(spec.assets) + ".",
        "Each market uses its own observed candle opens and closes.",
    ]
    if prepared is not None:
        assets = prepared.assets
        resolved = {
            "first_open": instant(
                min(int(item.primary.times[window.first]) for _, item, window in assets)
            ),
            "last_close_at": instant(
                max(
                    int(item.primary.close_at(window.last))
                    for _, item, window in assets
                )
            ),
            "readiness_index": max(item.strategy.warmup for _, item, _ in assets),
            "first_signal_at": instant(
                min(
                    int(item.primary.close_at(window.first_signal))
                    for _, item, window in assets
                )
            ),
            "first_execution_at": instant(
                min(
                    int(item.primary.times[window.first_signal + 1])
                    for _, item, window in assets
                )
            ),
        }
        lines.extend(
            f"{name} uses {item.primary.meta.symbol} on {item.primary.meta.timeframe} candles."
            for name, item, _ in assets
        )
    return dict(
        **identity(spec),
        spec=spec.public(),
        data_compatible=True if prepared else None,
        warmup_index=resolved["readiness_index"] if resolved else None,
        resolved_window=resolved,
        workload=prepared.workload if prepared else None,
        text="\n".join(lines),
        assumptions=PORTFOLIO_POLICY,
    )


def portfolio_identity(prepared: PortfolioPreparation, environment: dict):
    spec = prepared.spec
    legs = []
    for name, item, window in prepared.assets:
        leg_policy, leg_window, leg_ids, leg_signature = run_identity(
            item.strategy, item.primary, window, item.profile, environment
        )
        legs.append(
            dict(
                asset=name,
                market=item.primary.meta.symbol,
                configuration=leg_signature,
                policy=leg_policy,
                window=leg_window,
                source_hash=leg_ids["source_hash"],
                import_source_hash=item.primary.source_hash,
            )
        )
    signature = dict(
        dsl_version=PORTFOLIO_VERSION,
        semantics_version=PORTFOLIO_SEMANTICS,
        environment_hash=hash_json(environment),
        spec_hash=identity(spec)["spec_hash"],
        dataset_hash=hash_json(
            [
                (
                    leg["asset"],
                    leg["configuration"]["dataset_hash"],
                    leg["configuration"].get("profile_dataset"),
                    leg["configuration"].get("feeds"),
                )
                for leg in legs
            ]
        ),
        config_hash=hash_json(
            {
                "policy": PORTFOLIO_POLICY,
                "assets": [(leg["asset"], leg["configuration"]) for leg in legs],
            }
        ),
    )
    return signature, legs


def copy_input(stage, basename, dataset):
    path = stage / (basename + dataset.path.suffix.lower())
    shutil.copyfile(dataset.path, path)
    with path.open("rb") as stream:
        if hashlib.file_digest(stream, "sha256").hexdigest() != dataset.source_hash:
            raise Problem("E401_DATA", "Dataset changed after loading")
    metadata_path = stage / (basename + "-metadata.json")
    write_json(metadata_path, dataset.meta.model_dump())
    return dict(data=path.name, metadata=metadata_path.name)


def write_table(stage, stem, rows):
    write_csv(stage / f"{stem}.csv", list(rows[0]), rows)
    schema = pa.Table.from_pylist(rows[:2]).schema
    with pq.ParquetWriter(stage / f"{stem}.parquet", schema) as writer:
        for start in range(0, len(rows), 8192):
            writer.write_table(
                pa.Table.from_pylist(rows[start : start + 8192], schema=schema)
            )


def publish_portfolio(
    prepared: PortfolioPreparation,
    out: Path,
    *,
    progress=None,
    expected_fingerprint=None,
    run_id=None,
) -> dict:
    out = Path(out)
    if out.exists() and (not out.is_dir() or any(out.iterdir())):
        raise FileExistsError("Output directory must be new or empty")
    out.parent.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix="." + out.name + "-", dir=out.parent))
    spec = prepared.spec
    started = now()
    try:
        environment = environment_snapshot(stage)
        signature, legs = portfolio_identity(prepared, environment)
        fingerprint = hash_json(signature)
        if expected_fingerprint is not None and fingerprint != expected_fingerprint:
            raise Problem(
                "E_ENV_CHANGED", "Run environment or snapshot changed after submission"
            )
        decisions = {
            name: DecisionLog(
                window.first,
                window.last,
                ordered_exits=bool(item.strategy.exit_rules),
                closes=item.primary.close_at(slice(None)),
                split_factors=item.primary.split_factors,
                portfolio_account=True,
            )
            for name, item, window in prepared.assets
        }
        result = execute_portfolio_prepared(
            prepared, progress=progress, decisions=decisions
        )
        (stage / "source.trade").write_bytes(spec.source)
        write_json(stage / "strategy-spec.json", spec.public())
        replay_assets = {}
        for leg, (name, item, _) in zip(legs, prepared.assets, strict=True):
            source_path = stage / f"asset-{name}.trade"
            source_path.write_bytes(item.strategy.source)
            write_json(
                stage / f"asset-{name}-strategy-spec.json", item.strategy.public()
            )
            replay = dict(
                strategy=source_path.name,
                **copy_input(stage, f"asset-{name}", item.primary),
            )
            if item.strategy.run_settings is not None:
                replay["settings"] = item.strategy.run_settings
            elif item.strategy.parameter_overrides:
                replay["settings"] = {
                    "parameters": dict(item.strategy.parameter_overrides)
                }
            if item.profile is not None:
                replay["profile"] = copy_input(
                    stage, f"asset-{name}-profile", item.profile
                )
            if item.feeds:
                replay["feeds"] = {
                    feed: copy_input(stage, f"asset-{name}-feed-{feed}", data)
                    for feed, data in sorted(item.feeds.items())
                }
            leg["inputs"] = replay
            leg["decision_inspection"] = {
                "schema_version": decisions[name].version,
                "artifact": f"asset-{name}-decisions.parquet",
                "events_artifact": f"asset-{name}-events.jsonl",
            }
            leg["decision_counts"] = decisions[name].counts()
            replay_assets[name] = replay
        write_json(
            stage / "run-config.json", dict(schema_version=1, assets=replay_assets)
        )
        write_json(stage / "summary.json", result["summary"])
        write_json(stage / "diagnostics.json", result["diagnostics"])
        write_json(stage / "environment.json", environment)
        write_table(stage, "equity", result["equity"])
        write_table(stage, "asset-marks", result["asset_marks"])
        write_csv(
            stage / "trades.csv",
            ["asset", *TRADE_FIELDS, *SHORT_TRADE_FIELDS],
            result["trades"],
        )
        offsets = {name: [0] for name in spec.assets}
        with ExitStack() as stack:
            stream = stack.enter_context((stage / "events.jsonl").open("wb"))
            asset_streams = {
                name: stack.enter_context(
                    (stage / f"asset-{name}-events.jsonl").open("wb")
                )
                for name in spec.assets
            }
            for event in result["events"]:
                line = (canonical(event) + "\n").encode("utf-8")
                stream.write(line)
                name = event["asset"]
                offsets[name].append(
                    offsets[name][-1] + asset_streams[name].write(line)
                )
        for name, item, _ in prepared.assets:
            decisions[name].write(
                stage / f"asset-{name}-decisions.parquet",
                item.primary.times,
                offsets[name],
            )
        logical = hashlib.sha256()
        for name, item in result.items():
            logical.update(name.encode() + b"\n")
            for row in item if isinstance(item, list) else [item]:
                logical.update(canonical(row).encode() + b"\n")
        result_digest = logical.hexdigest()
        manifest = dict(
            **signature,
            **environment,
            schema_version=PORTFOLIO_ARTIFACT_SCHEMA_VERSION,
            engine_name="portfolio-bar-event-v1",
            run_id=run_id or str(uuid.uuid4()),
            run_fingerprint=fingerprint,
            result_digest=result_digest,
            source_hash=digest(spec.source),
            assets=legs,
            resolved_policy=PORTFOLIO_POLICY,
            resolved_window=portfolio_inspection(spec, prepared)["resolved_window"],
            workload=prepared.workload,
            created_at=started,
            finished_at=now(),
            artifact_files=[
                dict(
                    name=path.name,
                    sha256=digest(path.read_bytes()),
                    bytes=path.stat().st_size,
                )
                for path in sorted(stage.iterdir())
            ],
        )
        write_json(stage / "manifest.json", manifest)
        os.replace(stage, out)
        return dict(
            run_id=manifest["run_id"],
            run_fingerprint=fingerprint,
            result_digest=result_digest,
            artifact_directory=str(out.resolve()),
            summary=result["summary"],
        )
    except BaseException:
        shutil.rmtree(stage, ignore_errors=True)
        raise


def portfolio_command(
    source: bytes, command: str, run_config: Path | None, out: Path | None
):
    spec = compile_portfolio(source)
    prepared = (
        prepare_portfolio(spec, load_portfolio_inputs(spec, run_config))
        if run_config
        else None
    )
    if command == "backtest":
        if prepared is None or out is None:
            raise Problem(
                "E305_PORTFOLIO", "A portfolio backtest requires --run-config and --out"
            )
        return publish_portfolio(prepared, out)
    if out is not None:
        raise Problem("E305_PORTFOLIO", "--out applies to backtest")
    return portfolio_inspection(spec, prepared)
