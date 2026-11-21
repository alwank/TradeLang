"""Loopback HTTP interface to the shared TradeLang compiler."""

import json
from collections.abc import Callable
from typing import Any
from uuid import UUID

from fastapi import FastAPI, Response
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException

from ..application import inspect_source
from ..data import Dataset
from ..persistence import Library, LibraryError
from .contracts import (
    AST_SCHEMA,
    CompilationResponse,
    ErrorEnvelope,
    ExplainResponse,
    Health,
    SourceRequest,
)
from .library import library_routes
from .limits import EditorLimits, failure

DatasetResolver = Callable[[UUID], Dataset | None]


def create_app(
    resolve_dataset: DatasetResolver = lambda key: None,
    *,
    worker_available: Callable[[], bool] = lambda: False,
    library: Library | None = None,
) -> FastAPI:
    app = FastAPI(title="TradeLang editor", version="1", docs_url=None, redoc_url=None)
    app.add_middleware(EditorLimits)

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
        return Health(
            schema_version=1,
            status="ok" if available else "degraded",
            worker_available=available,
            queue_depth=0,
        )

    def inspect(body, command):
        try:
            source = body.source.encode("utf-8")
        except UnicodeEncodeError:
            return failure(422, "E_SOURCE_ENCODING", "Source must be valid UTF-8")
        if len(source) > 65536:
            return failure(413, "E_SOURCE_SIZE", "Source exceeds 64 KiB")
        dataset = profile = None
        resolver = library.resolve_dataset if library is not None else resolve_dataset
        if body.dataset_id is not None:
            dataset = resolver(UUID(body.dataset_id))
            if dataset is None:
                return failure(404, "E_DATASET_NOT_FOUND", "Unknown dataset ID")
        if body.profile_dataset_id is not None:
            profile = resolver(UUID(body.profile_dataset_id))
            if profile is None:
                return failure(404, "E_DATASET_NOT_FOUND", "Unknown profile dataset ID")
        return inspect_source(source, command, dataset, profile=profile)

    @app.post(
        "/api/v1/strategies/validate",
        response_model=CompilationResponse,
        responses=errors,
    )
    def validate(body: SourceRequest):
        return inspect(body, "validate")

    @app.post(
        "/api/v1/strategies/explain", response_model=ExplainResponse, responses=errors
    )
    def explain(body: SourceRequest):
        return inspect(body, "explain")

    if library is not None:
        app.include_router(library_routes(library))

    # Publish the compiler's versioned AST schema in the same OpenAPI document.
    # Namespace its recursive references to avoid collisions with transport models.
    document = app.openapi()
    components = document["components"]["schemas"]
    raw = json.dumps(AST_SCHEMA)
    spec = json.loads(raw.replace("#/$defs/", "#/components/schemas/AST_"))
    for name, definition in spec.pop("$defs").items():
        components["AST_" + name] = definition
    spec.pop("$id")
    components["StrategySpec"] = spec
    components["CompilationResponse"]["properties"]["spec"] = {
        "anyOf": [{"$ref": "#/components/schemas/StrategySpec"}, {"type": "null"}]
    }
    return app


def main():
    import uvicorn

    uvicorn.run(create_app(), host="127.0.0.1", port=8000, proxy_headers=False)
