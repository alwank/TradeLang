"""Submission and lifecycle API for exact saved strategy revisions."""

from functools import cache
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Header, Response
from pydantic import Field

from ..compiler import is_portfolio_source
from ..data import digest, hash_json, prepare_window
from ..model import Problem
from ..persistence import LibraryError
from ..persistence.runs import RUN_SECONDS, Runs, RunStatus
from ..portfolio import PORTFOLIO_POLICY, compile_portfolio, prepare_portfolio
from ..portfolio_library import require_portfolio_selection, resolve_portfolio_assets
from ..portfolio_report import portfolio_identity, portfolio_inspection
from ..report import environment_snapshot, run_identity
from ..run_config import Gap, configuration_view, configured_strategy
from ..workload import Workload
from .contracts import (
    Closed,
    Error,
    ErrorEnvelope,
    Hash,
    ResolvedWindow,
    RunSelection,
    UuidText,
)
from .library import Cursor, Limit, Page, RevisionNumber
from .limits import failure
from .presets import resolve_feed_ids, select_run
from .run_results import PortfolioSummary, ResultSummary, result_routes


class RequestPolicy(Closed):
    gap_policy: Gap = "reject"


class BacktestRequest(RunSelection):
    strategy_id: UuidText
    strategy_revision: RevisionNumber
    policy: RequestPolicy = Field(default_factory=RequestPolicy)


class Empty(Closed):
    pass


class RunProgress(Closed):
    completed_bars: int
    total_bars: int


class RunHeadline(Closed):
    final_equity: float
    total_return: float
    max_drawdown: float


class RunSummary(Closed):
    id: UuidText
    strategy_id: UuidText
    strategy_name: str
    strategy_revision: RevisionNumber
    dataset_id: UuidText | None
    dataset_name: str
    profile_dataset_id: UuidText | None
    dataset_hash: Hash
    source_hash: Hash
    raw_source_hash: Hash
    raw_dataset_hash: Hash
    spec_hash: Hash
    run_fingerprint: Hash
    result_digest: Hash | None
    status: RunStatus
    created_at: str
    started_at: str | None
    finished_at: str | None
    cancel_requested: bool
    progress: RunProgress
    resolved_window: ResolvedWindow
    headline: RunHeadline | None


class RunView(RunSummary):
    policy: dict[str, Any]
    configuration: dict[str, Any]
    error: Error | None
    summary: ResultSummary | PortfolioSummary | None
    time_limit: int
    workload: Workload | None = None


@cache
def local_environment():
    with TemporaryDirectory() as directory:
        return environment_snapshot(Path(directory))


def render_run(row, *, detail=False):
    snapshot = row["snapshot"]
    summary = row["summary"]
    result = {
        key: row[key]
        for key in (
            "id",
            "strategy_id",
            "dataset_id",
            "profile_dataset_id",
            "status",
            "created_at",
            "started_at",
            "finished_at",
            "result_digest",
        )
    }
    result.update(
        {
            key: snapshot[key]
            for key in (
                "strategy_name",
                "strategy_revision",
                "dataset_name",
                "dataset_hash",
                "source_hash",
                "raw_source_hash",
                "raw_dataset_hash",
                "spec_hash",
                "run_fingerprint",
                "resolved_window",
            )
        }
    )
    if "portfolio_assets" in snapshot:
        result["dataset_id"] = None
    result.update(
        cancel_requested=row["cancel_requested_at"] is not None,
        progress={
            "completed_bars": row["completed_bars"],
            "total_bars": row["total_bars"],
        },
        headline=None
        if summary is None
        else dict(
            final_equity=summary["final_equity"],
            total_return=summary["metrics"]["total_return"],
            max_drawdown=summary["metrics"]["max_drawdown"],
        ),
    )
    if detail:
        result.update(
            policy=snapshot["policy"],
            configuration=snapshot["configuration"],
            error=row["error"],
            summary=summary,
            time_limit=RUN_SECONDS,
            workload=snapshot.get("workload"),
        )
    return result


def backtests(runs: Runs, worker_available, presets):
    library = runs.library
    router = APIRouter(prefix="/api/v1/backtests")
    errors: dict[int | str, dict[str, Any]] = {
        status: {"model": ErrorEnvelope}
        for status in (400, 403, 404, 409, 422, 500, 503)
    }

    @router.post("", status_code=202, response_model=RunView, responses=errors)
    def submit(
        body: BacktestRequest,
        response: Response,
        key: Annotated[UUID | None, Header(alias="Idempotency-Key")] = None,
    ):
        request = body.model_dump()
        if body.portfolio_assets is None:
            request.pop("portfolio_assets")
        if not body.feed_ids:
            request.pop("feed_ids")
        else:
            request["feed_ids"] = {
                name: str(UUID(ident)) for name, ident in sorted(body.feed_ids.items())
            }
        if body.preset_id is not None:
            for field in ("dataset_id", "profile_dataset_id"):
                if field not in body.model_fields_set:
                    request.pop(field)
        if (
            body.preset_id is not None or body.settings is not None
        ) and "policy" not in body.model_fields_set:
            request.pop("policy")
        for field in ("preset_id", "preset_revision", "settings"):
            if request[field] is None:
                request.pop(field)
        if not body.parameters:
            request.pop("parameters")
        for field in ("strategy_id", "dataset_id", "profile_dataset_id", "preset_id"):
            if request.get(field) is not None:
                request[field] = str(UUID(request[field]))
        key_text = str(key) if key is not None else None
        previous = runs.prior(key_text, request)
        if previous is not None:
            response.headers["Location"] = f"/api/v1/backtests/{previous['id']}"
            return render_run(previous, detail=True)
        strategy = library.strategy(request["strategy_id"])
        if strategy["current_revision"] != body.strategy_revision:
            raise LibraryError(
                409, "E_REVISION_CONFLICT", "The strategy has a newer saved revision"
            )
        revision = library.revision(request["strategy_id"], body.strategy_revision)
        portfolio = is_portfolio_source(revision["source"].encode())
        if portfolio or body.portfolio_assets is not None:
            try:
                require_portfolio_selection(body)
                if not portfolio:
                    raise Problem(
                        "E305_PORTFOLIO", "Asset bindings require a DSL 9 portfolio"
                    )
                if body.portfolio_assets is None:
                    raise Problem(
                        "E305_PORTFOLIO",
                        "Supply the saved strategy and dataset for every asset",
                    )
                if not worker_available():
                    raise LibraryError(
                        503, "E_WORKER", "The backtest worker is unavailable"
                    )
                spec = compile_portfolio(revision["source"])
                bindings = request["portfolio_assets"]
                inputs, descriptions = resolve_portfolio_assets(library, spec, bindings)
                prepared = prepare_portfolio(spec, inputs)
                signature, legs = portfolio_identity(prepared, local_environment())
                resolved = portfolio_inspection(spec, prepared)["resolved_window"]
            except Problem as error:
                return failure(
                    422,
                    error.diagnostic["code"],
                    str(error),
                    diagnostics=[error.diagnostic],
                )
            source_hash = digest(spec.source)
            markets = sorted(item["market"] for item in descriptions.values())
            snapshot = {
                "source": revision["source"],
                "strategy_revision": body.strategy_revision,
                "dataset_name": f"{len(markets)} assets",
                "dataset_hash": signature["dataset_hash"],
                "source_hash": source_hash,
                "spec_hash": signature["spec_hash"],
                "raw_source_hash": source_hash,
                "raw_dataset_hash": hash_json(
                    [leg["import_source_hash"] for leg in legs]
                ),
                "resolved_window": resolved,
                "workload": prepared.workload,
                "run_fingerprint": hash_json(signature),
                "portfolio_assets": bindings,
                "policy": PORTFOLIO_POLICY,
                "configuration": {
                    "portfolio_assets": list(descriptions.values()),
                    "market": ", ".join(markets),
                    "currency": spec.currency,
                    "timeframe_seconds": None,
                    "calendar": "portfolio",
                    "capital": spec.capital,
                    "max_positions": spec.max_positions,
                    "fee_rate": None,
                    "slippage_rate": None,
                    "semantics_version": signature["semantics_version"],
                    "engine_version": local_environment()["engine_version"],
                    "first_open": resolved["first_open"],
                    "last_close_at": resolved["last_close_at"],
                    "gap_policy": None,
                    "dataset_hash": signature["dataset_hash"],
                    "profile_dataset_hash": None,
                },
            }
            row = runs.enqueue(
                request,
                key_text,
                snapshot,
                revision["id"],
                prepared.workload["execution_rows"],
                worker_available,
                dataset_id=bindings[spec.assets[0]]["dataset_id"],
                profile_dataset_id=None,
            )
            response.headers["Location"] = f"/api/v1/backtests/{row['id']}"
            return render_run(row, detail=True)
        selection = select_run(body, presets)
        if selection.dataset_id is None:
            raise LibraryError(
                422, "E_RUN_DATA", "Choose a primary dataset for the run"
            )
        if not worker_available():
            raise LibraryError(503, "E_WORKER", "The backtest worker is unavailable")
        dataset = library.dataset(selection.dataset_id)
        primary = library.resolve_dataset(UUID(selection.dataset_id))
        profile = (
            library.resolve_dataset(UUID(selection.profile_dataset_id))
            if selection.profile_dataset_id is not None
            else None
        )
        if primary is None or (
            selection.profile_dataset_id is not None and profile is None
        ):
            raise LibraryError(
                404, "E_DATASET_NOT_FOUND", "A selected dataset does not exist"
            )
        try:
            settings, origins = selection.settings, selection.origins
            if (
                settings is None or "policy" in body.model_fields_set
            ) and primary.meta.gap_policy != body.policy.gap_policy:
                raise Problem(
                    "E402_WINDOW", "Run gap policy must match the selected import"
                )
            if settings is not None and "policy" in body.model_fields_set:
                settings = settings.model_copy(
                    update={"gap_policy": body.policy.gap_policy}
                )
                origins = {**origins, "gap_policy": "override"}
            compiled = configured_strategy(
                revision["source"],
                settings,
                parameters=body.parameters,
                origins=origins,
                dataset=primary,
            )
            feeds = resolve_feed_ids(body.feed_ids, library.resolve_dataset)
            window = prepare_window(compiled, primary, profile, feeds=feeds)
        except Problem as exc:
            return failure(
                422, exc.diagnostic["code"], str(exc), diagnostics=[exc.diagnostic]
            )
        policy, resolved, ids, signature = run_identity(
            compiled, primary, window, profile, local_environment()
        )
        snapshot = {
            **ids,
            "source": revision["source"],
            "strategy_revision": body.strategy_revision,
            "dataset_name": dataset["filename"],
            "dataset_hash": primary.dataset_hash,
            "raw_source_hash": ids["source_hash"],
            "raw_dataset_hash": dataset["raw_source_hash"],
            "resolved_window": resolved,
            "workload": window.workload,
            "run_fingerprint": hash_json(signature),
            "policy": policy,
            "configuration": {
                "market": primary.meta.symbol,
                "currency": compiled.config.currency,
                "timeframe_seconds": window.timeframe_seconds,
                "calendar": compiled.config.calendar,
                "capital": compiled.config.capital,
                "fee_rate": compiled.config.fee_rate,
                "slippage_rate": compiled.config.slippage_rate,
                "semantics_version": signature["semantics_version"],
                "engine_version": local_environment()["engine_version"],
                "first_open": resolved["first_open"],
                "last_close_at": resolved["last_close_at"],
                "gap_policy": policy["gap_policy"],
                "dataset_hash": primary.dataset_hash,
                "profile_dataset_hash": profile.dataset_hash
                if profile is not None
                else None,
            },
        }
        if compiled.version >= 2:
            snapshot["parameter_overrides"] = dict(compiled.parameter_overrides)
            snapshot["configuration"]["parameters"] = {
                parameter.name: parameter.value for parameter in compiled.parameters
            }
        if primary.grid is not None:
            snapshot["configuration"]["session_calendar"] = policy["session_calendar"]
            snapshot["configuration"]["price_basis"] = primary.meta.price_basis
        if "short_margin" in policy:
            snapshot["configuration"]["short_margin"] = policy["short_margin"]
        if "feeds" in signature:
            snapshot["feed_ids"] = request["feed_ids"]
            snapshot["configuration"]["feeds"] = signature["feeds"]
        if compiled.run_settings is not None:
            snapshot["run_settings"] = compiled.run_settings
            snapshot["settings_origins"] = compiled.settings_origins
            snapshot["configuration"]["effective"] = configuration_view(
                compiled, primary, profile
            )
            if selection.preset is not None:
                snapshot["configuration"]["preset"] = selection.preset
        row = runs.enqueue(
            request,
            key_text,
            snapshot,
            revision["id"],
            window.last - window.first + 1,
            worker_available,
            dataset_id=selection.dataset_id,
            profile_dataset_id=selection.profile_dataset_id,
        )
        response.headers["Location"] = f"/api/v1/backtests/{row['id']}"
        return render_run(row, detail=True)

    @router.get("", response_model=Page[RunSummary], responses=errors)
    def history(
        limit: Limit = 50,
        cursor: Cursor = None,
        strategy_id: UUID | None = None,
        dataset_id: UUID | None = None,
        status: RunStatus | None = None,
    ):
        rows, next_cursor, snapshot = runs.list(
            limit,
            cursor,
            {
                "strategy_id": str(strategy_id) if strategy_id is not None else None,
                "dataset_id": str(dataset_id) if dataset_id is not None else None,
                "status": status,
            },
        )
        return dict(
            items=[render_run(row) for row in rows],
            next_cursor=next_cursor,
            snapshot=snapshot,
        )

    result_routes(router, runs, errors, local_environment)

    @router.get("/{ident}", response_model=RunView, responses=errors)
    def run_detail(ident: UUID, response: Response):
        row = runs.row(str(ident))
        response.headers["Cache-Control"] = "no-store"
        return render_run(row, detail=True)

    @router.post("/{ident}/cancel", response_model=RunView, responses=errors)
    def cancel(ident: UUID, body: Empty, response: Response):
        row = runs.cancel(str(ident))
        response.status_code = 202 if row["status"] == "running" else 200
        return render_run(row, detail=True)

    return router
