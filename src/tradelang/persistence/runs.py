"""Durable queue with transactional claims and result publication."""

import os
import shutil
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Literal
from uuid import UUID, uuid4

import sqlalchemy as sa

from ..data import hash_json
from . import Library, LibraryError, not_found, now, paginate, protected

RUN_SECONDS = 120
MAX_QUEUED = 20
RunStatus = Literal["queued", "running", "succeeded", "failed", "cancelled"]


def process_alive(pid):
    if pid is None:
        return False
    if sys.platform == "win32":
        import ctypes
        from ctypes import wintypes

        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel.OpenProcess.restype = wintypes.HANDLE
        kernel.GetExitCodeProcess.argtypes = [
            wintypes.HANDLE,
            ctypes.POINTER(wintypes.DWORD),
        ]
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        handle = kernel.OpenProcess(0x1000, False, pid)
        if not handle:
            return ctypes.get_last_error() != 87
        try:
            code = wintypes.DWORD()
            return (
                not kernel.GetExitCodeProcess(handle, ctypes.byref(code))
                or code.value == 259
            )
        finally:
            kernel.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def run_error(code, message, diagnostics=()):
    return dict(
        code=code, message=message, diagnostics=list(diagnostics), retryable=False
    )


class Runs:
    def __init__(self, library: Library):
        self.library = library
        self.table = library.runs
        self.artifacts = protected(library.root / "runs")
        self.work = protected(library.root / "run-staging")
        self.artifacts.mkdir(exist_ok=True)
        self.work.mkdir(exist_ok=True)

    def directory(self, ident: str, *, staging=False) -> Path:
        if str(UUID(ident)) != ident:
            raise not_found()
        return protected(protected(self.work if staging else self.artifacts) / ident)

    def row(self, ident, conn=None):
        if conn is None:
            with self.library.db.connect() as connection:
                return self.row(ident, connection)
        table = self.table
        result = (
            conn.execute(sa.select(table).where(table.c.id == ident))
            .mappings()
            .one_or_none()
        )
        if result is None:
            raise not_found()
        return dict(result)

    def depth(self, conn=None):
        if conn is None:
            with self.library.db.connect() as connection:
                return self.depth(connection)
        return conn.scalar(
            sa.select(sa.func.count())
            .select_from(self.table)
            .where(self.table.c.status == "queued")
        )

    def replay(self, conn, key, request_hash):
        table = self.table
        cutoff = (datetime.now(UTC) - timedelta(hours=24)).strftime(
            "%Y-%m-%dT%H:%M:%S.%fZ"
        )
        row = (
            conn.execute(
                sa.select(table).where(
                    table.c.idempotency_key == key,
                    table.c.created_at >= cutoff,
                )
            )
            .mappings()
            .one_or_none()
        )
        if row is not None and row["request_hash"] != request_hash:
            raise LibraryError(
                409, "E_IDEMPOTENCY", "This key was used for a different run request"
            )
        return dict(row) if row is not None else None

    def prior(self, key, request):
        if key is None:
            return None
        with self.library.db.connect() as conn:
            return self.replay(conn, key, hash_json(request))

    def enqueue(
        self,
        request,
        key,
        snapshot,
        revision_id,
        total_bars,
        available,
        *,
        dataset_id,
        profile_dataset_id,
    ):
        table = self.table
        with self.library.writer() as conn:
            request_hash = hash_json(request)
            if key is not None:
                previous = self.replay(conn, key, request_hash)
                if previous is not None:
                    return previous
                conn.execute(
                    table.update()
                    .where(table.c.idempotency_key == key)
                    .values(idempotency_key=None)
                )
            if not available():
                raise LibraryError(
                    503, "E_WORKER", "The backtest worker is unavailable"
                )
            if self.depth(conn) >= MAX_QUEUED:
                raise LibraryError(409, "E_QUEUE_FULL", "The backtest queue is full")
            strategy = self.library.strategy(request["strategy_id"], conn=conn)
            if strategy["current_revision"] != request["strategy_revision"]:
                raise LibraryError(
                    409,
                    "E_REVISION_CONFLICT",
                    "The strategy has a newer saved revision",
                )
            ident = str(uuid4())
            conn.execute(
                table.insert().values(
                    id=ident,
                    strategy_id=strategy["id"],
                    revision_id=revision_id,
                    dataset_id=dataset_id,
                    profile_dataset_id=profile_dataset_id,
                    status="queued",
                    created_at=now(),
                    idempotency_key=key,
                    request_hash=request_hash,
                    snapshot={**snapshot, "strategy_name": strategy["name"]},
                    total_bars=total_bars,
                )
            )
            return self.row(ident, conn)

    def list(self, limit, cursor, filters):
        query = sa.select(self.table)
        for name, value in filters.items():
            if value is not None:
                if name == "dataset_id":
                    assets = sa.func.json_each(self.table.c.snapshot, "$.portfolio_assets").table_valued("value")
                    query = query.where(sa.or_(
                        self.table.c.dataset_id == value,
                        sa.exists(sa.select(1).select_from(assets).where(
                            sa.func.json_extract(assets.c.value, "$.dataset_id") == value
                        )),
                    ))
                else:
                    query = query.where(self.table.c[name] == value)
        with self.library.db.connect() as conn:
            rows, next_cursor, snapshot = paginate(
                conn,
                query,
                self.table,
                limit,
                cursor,
                ["runs", filters],
            )
        return [dict(row) for row in rows], next_cursor, snapshot

    def claim(self):
        table = self.table
        with self.library.writer() as conn:
            active = (
                conn.execute(sa.select(table).where(table.c.status == "running"))
                .mappings()
                .one_or_none()
            )
            if active is not None:
                if process_alive(active["worker_pid"]) or process_alive(
                    active["child_pid"]
                ):
                    return None
                self.finish(
                    conn,
                    active,
                    error=run_error(
                        "E_INTERRUPTED",
                        "The backtest was interrupted before it finished",
                    ),
                )
                self.cleanup(active["id"])
            ident = conn.scalar(
                sa.select(table.c.id)
                .where(table.c.status == "queued")
                .order_by(table.c.created_at, table.c.id)
                .limit(1)
            )
            if ident is None:
                return None
            conn.execute(
                table.update()
                .where(table.c.id == ident)
                .values(
                    status="running",
                    started_at=now(),
                    worker_pid=os.getpid(),
                )
            )
            return self.row(ident, conn)

    def progress(self, ident, *, completed=None, pid=None):
        table = self.table
        values = (
            {"child_pid": pid}
            if pid is not None
            else {
                "completed_bars": sa.func.max(
                    table.c.completed_bars, sa.func.min(completed, table.c.total_bars)
                ),
            }
        )
        with self.library.writer() as conn:
            conn.execute(
                table.update()
                .where(table.c.id == ident, table.c.status == "running")
                .values(**values)
            )

    def cancel(self, ident):
        table = self.table
        with self.library.writer() as conn:
            row = self.row(ident, conn)
            if row["status"] == "queued":
                conn.execute(
                    table.update()
                    .where(table.c.id == ident)
                    .values(
                        status="cancelled",
                        cancel_requested_at=now(),
                        finished_at=now(),
                    )
                )
            elif row["status"] == "running":
                conn.execute(
                    table.update()
                    .where(table.c.id == ident)
                    .values(
                        cancel_requested_at=row["cancel_requested_at"] or now(),
                    )
                )
            elif row["status"] != "cancelled":
                raise LibraryError(
                    409, "E_RUN_TERMINAL", "This backtest has already finished"
                )
            return self.row(ident, conn)

    def finish(self, conn, row, *, result=None, error=None):
        ident = row["id"]
        values = dict(finished_at=now(), child_pid=None, worker_pid=None)
        if row["cancel_requested_at"] is not None:
            values.update(status="cancelled")
        elif result is not None:
            os.replace(
                self.directory(ident, staging=True) / "bundle", self.directory(ident)
            )
            values.update(
                status="succeeded",
                summary=result["summary"],
                result_digest=result["result_digest"],
                completed_bars=row["total_bars"],
            )
        else:
            values.update(status="failed", error=error)
        conn.execute(
            self.table.update()
            .where(self.table.c.id == ident, self.table.c.status == "running")
            .values(**values)
        )

    def cleanup(self, ident):
        shutil.rmtree(self.directory(ident, staging=True), ignore_errors=True)
        if self.row(ident)["status"] != "succeeded":
            shutil.rmtree(self.directory(ident), ignore_errors=True)
