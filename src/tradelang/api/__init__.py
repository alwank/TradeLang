"""Loopback HTTP interface to the shared TradeLang compiler."""

import json
from collections.abc import Callable
from typing import Any
from uuid import UUID

from fastapi import FastAPI, Response
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException

from ..application import check_draft, inspect_source
from ..compiler import is_portfolio_source
from ..data import Dataset
from ..model import Problem
from ..persistence import Library, LibraryError
from ..persistence.presets import Presets
from ..persistence.runs import Runs
from ..portfolio import compile_portfolio
from ..portfolio_library import require_portfolio_selection, resolve_portfolio_assets
from .backtests import backtests
from .contracts import (
    AST_SCHEMA,
    AST_SCHEMA_V2,
    AST_SCHEMA_V3,
    AST_SCHEMA_V4,
    AST_SCHEMA_V5,
    AST_SCHEMA_V6,
    AST_SCHEMA_V7,
    AST_SCHEMA_V8,
    AST_SCHEMA_V9,
    CompilationResponse,
    DraftCheckResponse,
    DraftRequest,
    ErrorEnvelope,
    ExplainResponse,
    Health,
    SourceRequest,
)
from .library import library_routes
from .limits import HOST, ORIGIN, EditorLimits, failure
from .presets import preset_routes, resolve_feed_ids, select_run

DatasetResolver = Callable[[UUID], Dataset | None]


def create_app(
    resolve_dataset: DatasetResolver = lambda key: None,
    *,
    worker_available: Callable[[], bool] = lambda: False,
    library: Library | None = None,
    host: str = HOST,
    origin: str = ORIGIN,
    instance_id: str | None = None,
) -> FastAPI:
    app = FastAPI(title="TradeLang editor", version="1", docs_url=None, redoc_url=None)
    app.add_middleware(EditorLimits, host=host, origin=origin)
    runs = Runs(library) if library is not None else None
    presets = Presets(library) if library is not None else None

    @app.exception_handler(RequestValidationError)
    async def invalid_request(request, exc):
        if any(err["type"] == "json_invalid" for err in exc.errors()):
            return failure(400, "E_JSON", "Malformed JSON")
        return failure(422, "E_REQUEST", "Invalid request fields")

    @app.exception_handler(HTTPException)
    async def http_error(request, exc):
        if exc.status_code == 404:
            return failure(404, "E_NOT_FOUND", "Resource not found")
        return failure(exc.status_code, "E_HTTP", "Invalid HTTP request")

    @app.exception_handler(Exception)
    async def internal_error(request, exc):
        return failure(500, "E_INTERNAL", "Unable to complete request")

    @app.exception_handler(LibraryError)
    async def library_error(request, exc):
        return failure(exc.status, exc.code, str(exc))

    errors: dict[int | str, dict[str, Any]] = {
        status: {"model": ErrorEnvelope}
        for status in (400, 403, 404, 413, 415, 422, 429, 500)
    }

    @app.get(
        "/health",
        response_model=Health,
        responses={403: {"model": ErrorEnvelope}, 503: {"model": Health}},
    )
    def health(response: Response):
        available = worker_available()
        response.status_code = 200 if available else 503
        response.headers["Cache-Control"] = "no-store"
        if instance_id is not None:
            response.headers["TradeLang-Instance"] = instance_id
        return Health(
            schema_version=1,
            status="ok" if available else "degraded",
            worker_available=available,
            queue_depth=runs.depth() if runs is not None else 0,
        )

    def source_bytes(body):
        try:
            raw = body.source.encode("utf-8")
        except UnicodeEncodeError:
            return failure(422, "E_SOURCE_ENCODING", "Source must be valid UTF-8")
        if len(raw) > 65536:
            return failure(413, "E_SOURCE_SIZE", "Source exceeds 64 KiB")
        return raw

    def inspect(body, command):
        source = source_bytes(body)
        if not isinstance(source, bytes):
            return source
        if is_portfolio_source(source) or body.portfolio_assets is not None:
            assets = None
            try:
                require_portfolio_selection(body)
                if body.portfolio_assets is not None:
                    if not is_portfolio_source(source):
                        raise Problem(
                            "E305_PORTFOLIO", "Asset bindings require a DSL 9 portfolio"
                        )
                    if library is None:
                        raise Problem(
                            "E305_PORTFOLIO", "Asset bindings require a local library"
                        )
                    assets, _ = resolve_portfolio_assets(
                        library,
                        compile_portfolio(source),
                        {
                            name: value.model_dump()
                            for name, value in body.portfolio_assets.items()
                        },
                    )
            except Problem as error:
                return failure(
                    422,
                    error.diagnostic["code"],
                    str(error),
                    diagnostics=[error.diagnostic],
                )
            return inspect_source(source, command, portfolio_assets=assets)
        selection = select_run(body, presets)
        dataset = profile = None
        resolver = library.resolve_dataset if library is not None else resolve_dataset
        if selection.dataset_id is not None:
            dataset = resolver(UUID(selection.dataset_id))
            if dataset is None:
                return failure(404, "E_DATASET_NOT_FOUND", "Unknown dataset ID")
        if selection.profile_dataset_id is not None:
            profile = resolver(UUID(selection.profile_dataset_id))
            if profile is None:
                return failure(404, "E_DATASET_NOT_FOUND", "Unknown profile dataset ID")
        return inspect_source(
            source,
            command,
            dataset,
            profile=profile,
            parameters=body.parameters,
            settings=selection.settings,
            origins=selection.origins,
            feeds=resolve_feed_ids(body.feed_ids, resolver),
        )

    @app.post(
        "/api/v1/strategies/validate",
        response_model=CompilationResponse,
        response_model_exclude_unset=True,
        responses=errors,
    )
    def validate(body: SourceRequest):
        return inspect(body, "validate")

    @app.post(
        "/api/v1/strategies/draft-check",
        response_model=DraftCheckResponse,
        response_model_exclude_unset=True,
        responses=errors,
    )
    def draft_check(body: DraftRequest):
        source = source_bytes(body)
        return check_draft(source) if isinstance(source, bytes) else source

    @app.post(
        "/api/v1/strategies/explain",
        response_model=ExplainResponse,
        response_model_exclude_unset=True,
        responses=errors,
    )
    def explain(body: SourceRequest):
        return inspect(body, "explain")

    if library is not None:
        app.include_router(library_routes(library))
    if presets is not None:
        app.include_router(preset_routes(presets))
    if runs is not None:
        app.include_router(backtests(runs, worker_available, presets))

    # Publish the compiler's versioned AST schema in the same OpenAPI document.
    # Namespace its recursive references to avoid collisions with transport models.
    document = app.openapi()
    components = document["components"]["schemas"]
    for source_schema, prefix, title in (
        (AST_SCHEMA, "AST_", "StrategySpecV1"),
        (AST_SCHEMA_V2, "AST2_", "StrategySpecV2"),
        (AST_SCHEMA_V3, "AST3_", "StrategySpecV3"),
        (AST_SCHEMA_V4, "AST4_", "StrategySpecV4"),
        (AST_SCHEMA_V5, "AST5_", "StrategySpecV5"),
        (AST_SCHEMA_V6, "AST6_", "StrategySpecV6"),
        (AST_SCHEMA_V7, "AST7_", "StrategySpecV7"),
        (AST_SCHEMA_V8, "AST8_", "StrategySpecV8"),
        (AST_SCHEMA_V9, "AST9_", "StrategySpecV9"),
    ):
        spec = json.loads(
            json.dumps(source_schema).replace(
                "#/$defs/", "#/components/schemas/" + prefix
            )
        )
        for name, definition in spec.pop("$defs", {}).items():
            components[prefix + name] = definition
        spec.pop("$id")
        components[title] = spec
    components["StrategySpec"] = {
        "oneOf": [
            {"$ref": f"#/components/schemas/StrategySpecV{version}"}
            for version in (1, 2, 3, 4, 5, 6, 7, 8, 9)
        ]
    }
    for name in ("CompilationResponse", "DraftCheckResponse"):
        components[name]["properties"]["spec"] = {
            "anyOf": [{"$ref": "#/components/schemas/StrategySpec"}, {"type": "null"}]
        }
    return app


def main():
    import uvicorn

    uvicorn.run(create_app(), host="127.0.0.1", port=8000, proxy_headers=False)
