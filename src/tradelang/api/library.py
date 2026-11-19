"""HTTP transport for the local strategy and dataset library."""

import asyncio
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Generic, TypeVar
from uuid import UUID

import anyio
from fastapi import APIRouter, Header, Query, Request, Response
from pydantic import Field, field_validator
from starlette.responses import JSONResponse

from ..data import Metadata
from ..model import Problem
from ..persistence import Library, LibraryError, protected
from .contracts import Closed, Diagnostic, ErrorEnvelope, Hash, UuidText
from .limits import failure
from .upload import TOTAL_SECONDS, receive_upload

RevisionNumber = Annotated[int, Field(ge=1)]
Limit = Annotated[int, Query(ge=1, le=500)]
Cursor = Annotated[str | None, Query(max_length=1024)]
IfMatch = Annotated[str | None, Header(alias="If-Match")]
T = TypeVar("T")


class Page(Closed, Generic[T]):
    items: list[T]
    next_cursor: str | None
    snapshot: str


class StrategyCreate(Closed):
    name: Annotated[str, Field(min_length=1, max_length=120)]
    source: str

    @field_validator("name")
    @classmethod
    def visible_name(cls, value):
        if not value.strip() or not value.isprintable():
            raise ValueError("Expected a visible strategy name")
        return value


class StrategyUpdate(StrategyCreate):
    expected_revision: RevisionNumber


class StrategyRecord(Closed):
    id: UuidText
    name: str
    current_revision: RevisionNumber
    current_source: str
    source_hash: Hash
    created_at: str
    updated_at: str
    etag: str
    deleted_at: str | None


class Revision(Closed):
    id: UuidText
    strategy_id: UuidText
    revision: RevisionNumber
    source: str
    source_hash: Hash
    created_at: str


class Quality(Closed):
    zero_volume_count: int
    missing_bar_count: int
    largest_gap_seconds: int


class DatasetRow(Closed):
    row: int
    timestamp: str
    open: float
    high: float
    low: float
    close: float
    volume: float


class DatasetSummary(Closed):
    id: UuidText
    dataset_hash: Hash
    metadata: Metadata
    filename: str
    row_count: int
    first_open: str
    last_open: str
    last_close_at: str
    quality: Quality
    warnings: list[Diagnostic]
    created_at: str


class DatasetRecord(DatasetSummary):
    preview: Annotated[list[DatasetRow], Field(max_length=10)]


class Imported(Closed):
    dataset: DatasetRecord
    deduplicated: bool


def source_limit(source: str):
    try:
        size = len(source.encode("utf-8"))
    except UnicodeError as exc:
        raise LibraryError(
            422, "E_SOURCE_ENCODING", "Source must be valid UTF-8"
        ) from exc
    if size > 65536:
        raise LibraryError(413, "E_SOURCE_SIZE", "Source exceeds 64 KiB")


def required_etag(tag: str | None) -> str:
    if tag is None:
        raise LibraryError(428, "E_PRECONDITION", "If-Match is required")
    return tag


def library_routes(library: Library) -> APIRouter:
    router = APIRouter(
        prefix="/api/v1",
        responses={
            status: {"model": ErrorEnvelope}
            for status in (400, 403, 404, 409, 413, 415, 422, 428, 429, 500)
        },
    )
    active_import = asyncio.Lock()
    admitted = 0

    @router.get("/strategies", response_model=Page[StrategyRecord])
    def list_strategies(
        limit: Limit = 50,
        cursor: Cursor = None,
        q: Annotated[str | None, Query(max_length=120)] = None,
    ):
        return library.strategies_page(limit, cursor, q)

    @router.post("/strategies", response_model=StrategyRecord, status_code=201)
    def create_strategy(body: StrategyCreate, response: Response):
        source_limit(body.source)
        result = library.create_strategy(body.name, body.source)
        response.headers["Location"] = f"/api/v1/strategies/{result['id']}"
        response.headers["ETag"] = result["etag"]
        return result

    @router.get("/strategies/{ident}", response_model=StrategyRecord)
    def read_strategy(ident: UUID, response: Response):
        result = library.strategy(str(ident))
        response.headers["ETag"] = result["etag"]
        return result

    @router.put("/strategies/{ident}", response_model=StrategyRecord)
    def update_strategy(
        ident: UUID, body: StrategyUpdate, response: Response, if_match: IfMatch = None
    ):
        tag = required_etag(if_match)
        source_limit(body.source)
        result = library.update_strategy(
            str(ident), tag, body.expected_revision, body.name, body.source
        )
        response.headers["ETag"] = result["etag"]
        return result

    @router.delete("/strategies/{ident}", status_code=204)
    def delete_strategy(ident: UUID, if_match: IfMatch = None):
        library.delete_strategy(str(ident), required_etag(if_match))
        return Response(status_code=204)

    @router.get("/strategies/{ident}/revisions", response_model=Page[Revision])
    def list_revisions(ident: UUID, limit: Limit = 50, cursor: Cursor = None):
        return library.revisions_page(str(ident), limit, cursor)

    @router.get("/strategies/{ident}/revisions/{revision}", response_model=Revision)
    def read_revision(ident: UUID, revision: Annotated[int, Field(ge=1)]):
        return library.revision(str(ident), revision)

    @router.get("/datasets", response_model=Page[DatasetSummary])
    def list_datasets(limit: Limit = 50, cursor: Cursor = None):
        return library.datasets_page(limit, cursor)

    @router.post(
        "/datasets/import",
        response_model=Imported,
        status_code=201,
        responses={200: {"model": Imported}},
        openapi_extra={
            "requestBody": {
                "required": True,
                "content": {
                    "multipart/form-data": {
                        "schema": {
                            "type": "object",
                            "additionalProperties": False,
                            "required": ["file", "metadata"],
                            "properties": {
                                "file": {"type": "string", "format": "binary"},
                                "metadata": {
                                    "type": "string",
                                    "description": "UTF-8 JSON DatasetMetadata",
                                },
                            },
                        }
                    }
                },
            }
        },
    )
    async def import_dataset(request: Request):
        nonlocal admitted
        if admitted >= 2:
            return failure(
                429,
                "E_IMPORT_BUSY",
                "Local import capacity is full",
                {"Retry-After": "1"},
            )
        admitted += 1
        started = datetime.now(UTC)
        deadline = time.monotonic() + TOTAL_SECONDS
        locked = False
        workspace = None
        job = None

        def finish(directory, path, filename, metadata):
            try:
                return library.import_dataset(
                    path, filename, metadata, started, deadline
                )
            finally:
                directory.cleanup()

        def release(completed=None):
            nonlocal admitted
            if completed is not None and not completed.cancelled():
                completed.exception()
            if locked:
                active_import.release()
            admitted -= 1

        try:
            with anyio.fail_after(TOTAL_SECONDS):
                await active_import.acquire()
                locked = True
                workspace = tempfile.TemporaryDirectory(
                    prefix="import-", dir=protected(library.staging)
                )
                path, filename, metadata = await receive_upload(
                    request, Path(workspace.name)
                )
                job = asyncio.get_running_loop().run_in_executor(
                    None, finish, workspace, path, filename, metadata
                )
                row, reused = await asyncio.shield(job)
            result = Imported(
                dataset=DatasetRecord.model_validate(library.describe_dataset(row)),
                deduplicated=reused,
            )
            return JSONResponse(
                result.model_dump(mode="json"), status_code=200 if reused else 201
            )
        except TimeoutError:
            return failure(422, "E_IMPORT_TIMEOUT", "The import timed out")
        except Problem as exc:
            status = 413 if exc.diagnostic["code"] == "E_DATA_LIMIT" else 422
            return failure(
                status, exc.diagnostic["code"], str(exc), diagnostics=[exc.diagnostic]
            )
        finally:
            if job is not None and not job.done():
                # A timed-out normalizer still owns the stage and the import slot.
                job.add_done_callback(release)
            else:
                try:
                    if job is None and workspace is not None:
                        workspace.cleanup()
                finally:
                    release(job)

    @router.get("/datasets/{ident}", response_model=DatasetRecord)
    def read_dataset(ident: UUID):
        return library.describe_dataset(library.dataset(str(ident)))

    return router
