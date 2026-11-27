"""SQLite library and content-addressed local candle storage."""

import base64
import binascii
import json
import re
import shutil
import time
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
import sqlalchemy as sa
from alembic import command
from alembic.config import Config

from ..compiler import seconds
from ..data import COLUMNS, Dataset, canonical, digest, hash_json, instant, load_dataset
from ..model import Problem

HASH = re.compile(r"[a-f0-9]{64}")


class LibraryError(Exception):
    def __init__(self, status: int, code: str, message: str):
        super().__init__(message)
        self.status = status
        self.code = code


def now() -> str:
    return datetime.now(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


def protected(path: Path) -> Path:
    if path.is_symlink():
        raise LibraryError(500, "E_STORAGE", "Invalid storage location")
    return path


def not_found():
    return LibraryError(404, "E_NOT_FOUND", "Resource not found")


def paginate(conn, stmt, table, limit, cursor, scope):
    fingerprint = hash_json(scope)
    watermark = now()
    if cursor is not None:
        try:
            watermark, created_at, ident, query_hash = json.loads(
                base64.urlsafe_b64decode(cursor)
            )
            UUID(ident)
            if (
                query_hash != fingerprint
                or not re.fullmatch(r"[0-9T:.-]{26}Z", watermark)
                or not re.fullmatch(r"[0-9T:.-]{26}Z", created_at)
            ):
                raise ValueError("Invalid cursor payload")
        except (binascii.Error, ValueError, TypeError, AttributeError) as exc:
            raise LibraryError(
                400, "E_CURSOR", "Invalid or incompatible cursor"
            ) from exc
        stmt = stmt.where(
            sa.or_(
                table.c.created_at < created_at,
                sa.and_(table.c.created_at == created_at, table.c.id > ident),
            )
        )
    stmt = (
        stmt.where(table.c.created_at <= watermark)
        .order_by(table.c.created_at.desc(), table.c.id)
        .limit(limit + 1)
    )
    rows = conn.execute(stmt).mappings().all()
    next_cursor = None
    if len(rows) > limit:
        last = rows[limit - 1]
        token = canonical([watermark, last["created_at"], last["id"], fingerprint])
        next_cursor = base64.urlsafe_b64encode(token.encode()).decode()
    return rows[:limit], next_cursor, watermark


class Library:
    def __init__(self, data_root: Path):
        self.root = data_root.resolve()
        self.staging = protected(self.root / "staging")
        self.datasets = protected(self.root / "datasets")
        self.staging.mkdir(parents=True, exist_ok=True)
        self.datasets.mkdir(exist_ok=True)
        path = protected(self.root / "library.sqlite3")
        for suffix in ("-wal", "-shm", "-journal"):
            protected(path.with_name(path.name + suffix))
        self.db = sa.create_engine(sa.URL.create("sqlite", database=str(path)))

        @sa.event.listens_for(self.db, "connect")
        def settings(dbapi, _):
            dbapi.execute("PRAGMA foreign_keys=ON")
            dbapi.execute("PRAGMA busy_timeout=5000")
            dbapi.create_function("casefold", 1, str.casefold, deterministic=True)

        with self.db.connect() as conn:
            conn.exec_driver_sql("PRAGMA journal_mode=WAL")
            conn.commit()
        config = Config()
        config.set_main_option(
            "script_location",
            str(Path(__file__).parent / "migrations").replace("%", "%%"),
        )
        with self.writer() as conn:
            config.attributes["connection"] = conn
            command.upgrade(config, "head")
        meta = sa.MetaData()
        self.strategies = sa.Table("strategies", meta, autoload_with=self.db)
        self.revisions = sa.Table("strategy_revisions", meta, autoload_with=self.db)
        self.contents = sa.Table("dataset_contents", meta, autoload_with=self.db)
        self.imports = sa.Table("dataset_imports", meta, autoload_with=self.db)
        self.runs = sa.Table("runs", meta, autoload_with=self.db)
        self.run_presets = sa.Table("run_presets", meta, autoload_with=self.db)

    @contextmanager
    def writer(self):
        with self.db.begin() as conn:
            conn.exec_driver_sql("BEGIN IMMEDIATE")
            yield conn

    def strategy_query(self):
        st, rev = self.strategies, self.revisions
        latest = (
            sa.select(self.runs.c.status)
            .where(self.runs.c.strategy_id == st.c.id)
            .order_by(self.runs.c.created_at.desc(), self.runs.c.id)
            .limit(1)
            .scalar_subquery()
        )
        return (
            sa.select(
                st,
                rev.c.source.label("current_source"),
                rev.c.source_hash,
                latest.label("last_run_status"),
            )
            .join(
                rev,
                sa.and_(
                    rev.c.strategy_id == st.c.id,
                    rev.c.revision == st.c.current_revision,
                ),
            )
            .where(st.c.deleted_at.is_(None))
        )

    def strategy(self, ident: str, *, conn=None):
        if conn is None:
            with self.db.connect() as read:
                return self.strategy(ident, conn=read)
        row = (
            conn.execute(self.strategy_query().where(self.strategies.c.id == ident))
            .mappings()
            .one_or_none()
        )
        if row is None:
            raise not_found()
        return dict(row)

    def strategies_page(self, limit, cursor, query):
        stmt = self.strategy_query()
        if query:
            stmt = stmt.where(
                sa.func.instr(
                    sa.func.casefold(self.strategies.c.name), query.casefold()
                )
                > 0
            )
        with self.db.connect() as conn:
            rows, next_, stamp = paginate(
                conn, stmt, self.strategies, limit, cursor, ["strategies", query]
            )
        return dict(items=[dict(r) for r in rows], next_cursor=next_, snapshot=stamp)

    def add_revision(self, conn, ident: str, revision: int, source: str, stamp: str):
        conn.execute(
            self.revisions.insert().values(
                id=str(uuid4()),
                strategy_id=ident,
                revision=revision,
                source=source,
                source_hash=digest(source.encode()),
                created_at=stamp,
            )
        )

    def create_strategy(self, name: str, source: str):
        ident, stamp = str(uuid4()), now()
        with self.writer() as conn:
            conn.execute(
                self.strategies.insert().values(
                    id=ident,
                    name=name,
                    current_revision=1,
                    etag=f'"{uuid4()}"',
                    created_at=stamp,
                    updated_at=stamp,
                )
            )
            self.add_revision(conn, ident, 1, source, stamp)
            return self.strategy(ident, conn=conn)

    def update_strategy(self, ident, etag, expected_revision, name, source):
        with self.writer() as conn:
            current = self.strategy(ident, conn=conn)
            if (
                current["etag"] != etag
                or current["current_revision"] != expected_revision
            ):
                raise LibraryError(
                    409, "E_REVISION_CONFLICT", "The strategy changed since it was read"
                )
            changed = current["current_source"] != source
            if not changed and current["name"] == name:
                return current
            revision = expected_revision + int(changed)
            stamp = now()
            if changed:
                self.add_revision(conn, ident, revision, source, stamp)
            conn.execute(
                self.strategies.update()
                .where(self.strategies.c.id == ident)
                .values(
                    name=name,
                    current_revision=revision,
                    updated_at=stamp,
                    etag=f'"{uuid4()}"',
                )
            )
            return self.strategy(ident, conn=conn)

    def delete_strategy(self, ident, etag):
        with self.writer() as conn:
            if self.strategy(ident, conn=conn)["etag"] != etag:
                raise LibraryError(
                    409, "E_REVISION_CONFLICT", "The strategy changed since it was read"
                )
            stamp = now()
            conn.execute(
                self.strategies.update()
                .where(self.strategies.c.id == ident)
                .values(
                    deleted_at=stamp,
                    updated_at=stamp,
                    etag=f'"{uuid4()}"',
                )
            )

    def revisions_page(self, ident, limit, cursor):
        rev = self.revisions
        with self.db.connect() as conn:
            present = conn.execute(
                sa.select(self.strategies.c.id).where(self.strategies.c.id == ident)
            ).scalar_one_or_none()
            if present is None:
                raise not_found()
            rows, next_, stamp = paginate(
                conn,
                sa.select(rev).where(rev.c.strategy_id == ident),
                rev,
                limit,
                cursor,
                ["revisions", ident],
            )
        return dict(items=[dict(r) for r in rows], next_cursor=next_, snapshot=stamp)

    def revision(self, ident, revision):
        rev = self.revisions
        with self.db.connect() as conn:
            row = (
                conn.execute(
                    sa.select(rev).where(
                        rev.c.strategy_id == ident, rev.c.revision == revision
                    )
                )
                .mappings()
                .one_or_none()
            )
        if row is None:
            raise not_found()
        return dict(row)

    def content_path(self, dataset_hash):
        if not HASH.fullmatch(dataset_hash):
            raise LibraryError(500, "E_STORAGE", "Invalid candle storage key")
        directory = protected(protected(self.datasets) / dataset_hash)
        return protected(directory / "candles.parquet")

    def dataset_query(self):
        return sa.select(
            self.imports,
            self.contents.c.normalized_sha256,
            self.contents.c.preview_json,
            self.contents.c.quality_json,
            self.contents.c.row_count,
        ).join(self.contents)

    def dataset(self, ident: str):
        with self.db.connect() as conn:
            row = (
                conn.execute(self.dataset_query().where(self.imports.c.id == ident))
                .mappings()
                .one_or_none()
            )
        if row is None:
            raise not_found()
        self.require_artifact(row)
        return row

    def require_artifact(self, row):
        path = self.content_path(row["dataset_hash"])
        if not path.is_file():
            raise LibraryError(
                500, "E_STORAGE", "Normalized candle artifact is unavailable"
            )
        return path

    @staticmethod
    def describe_dataset(row, *, include_preview=True):
        preview = json.loads(row["preview_json"])
        quality = json.loads(row["quality_json"])
        result = dict(
            id=row["id"],
            dataset_hash=row["dataset_hash"],
            metadata=json.loads(row["metadata_json"]),
            filename=row["filename"],
            row_count=row["row_count"],
            first_open=preview[0]["timestamp"],
            last_open=preview[-1]["timestamp"],
            last_close_at=quality.pop("last_close_at"),
            quality=quality,
            warnings=[],
            created_at=row["created_at"],
        )
        if quality["missing_bar_count"]:
            result["warnings"] = [
                {
                    **Problem(
                        "W_MISSING_BARS", "Dataset contains missing candles"
                    ).diagnostic,
                    "severity": "warning",
                    "details": {"count": quality["missing_bar_count"]},
                }
            ]
        if include_preview:
            result["preview"] = preview
        return result

    def datasets_page(self, limit, cursor):
        with self.db.connect() as conn:
            rows, next_, stamp = paginate(
                conn, self.dataset_query(), self.imports, limit, cursor, ["datasets"]
            )
        items = []
        for row in rows:
            try:
                self.require_artifact(row)
            except LibraryError:
                continue
            items.append(self.describe_dataset(row, include_preview=False))
        return dict(items=items, next_cursor=next_, snapshot=stamp)

    def resolve_dataset(self, ident: UUID) -> Dataset | None:
        try:
            row = self.dataset(str(ident))
        except LibraryError as exc:
            if exc.status == 404:
                return None
            raise
        try:
            result = load_dataset(
                self.content_path(row["dataset_hash"]),
                json.loads(row["metadata_json"]),
                as_of_utc=datetime.fromisoformat(row["as_of_utc"]),
            )
        except (OSError, Problem) as exc:
            raise LibraryError(
                500, "E_STORAGE", "Normalized candle artifact failed validation"
            ) from exc
        if (
            result.dataset_hash != row["dataset_hash"]
            or result.source_hash != row["normalized_sha256"]
        ):
            raise LibraryError(
                500,
                "E_STORAGE",
                "Normalized candle artifact failed its integrity check",
            )
        return result

    def import_dataset(
        self,
        path: Path,
        filename: str,
        metadata: Any,
        as_of: datetime,
        deadline: float | None = None,
    ):
        def check_time():
            if deadline is not None and time.monotonic() >= deadline:
                raise LibraryError(422, "E_IMPORT_TIMEOUT", "The import timed out")

        check_time()
        data = load_dataset(path, metadata, as_of_utc=as_of)
        check_time()
        validated = data.meta.model_dump()
        key = hash_json(
            dict(
                dataset_hash=data.dataset_hash,
                raw_source_hash=data.source_hash,
                metadata=validated,
            )
        )
        existing = self.dataset_query().where(self.imports.c.import_key == key)
        with self.db.connect() as conn:
            row = conn.execute(existing).mappings().one_or_none()
            has_content = (
                conn.execute(
                    sa.select(self.contents.c.dataset_hash).where(
                        self.contents.c.dataset_hash == data.dataset_hash
                    )
                ).scalar_one_or_none()
                is not None
            )
        check_time()
        if row is not None:
            self.require_artifact(row)
            return row, True
        staged = path.with_name("normalized.parquet")
        content_record = (
            self.stage_content(data, staged, as_of) if not has_content else None
        )
        dest = self.content_path(data.dataset_hash)
        published = False
        try:
            with self.writer() as conn:
                check_time()
                row = conn.execute(existing).mappings().one_or_none()
                if row is not None:
                    self.require_artifact(row)
                    return row, True
                present = conn.execute(
                    sa.select(self.contents.c.dataset_hash).where(
                        self.contents.c.dataset_hash == data.dataset_hash
                    )
                ).scalar_one_or_none()
                if present is None:
                    if content_record is None or dest.exists():
                        raise LibraryError(
                            500, "E_STORAGE", "Candle publication state is inconsistent"
                        )
                    dest.parent.mkdir(exist_ok=True)
                    staged.replace(dest)
                    published = True
                    conn.execute(self.contents.insert().values(**content_record))
                elif not dest.is_file():
                    raise LibraryError(
                        500, "E_STORAGE", "Normalized candle artifact is unavailable"
                    )
                ident = str(uuid4())
                conn.execute(
                    self.imports.insert().values(
                        id=ident,
                        import_key=key,
                        dataset_hash=data.dataset_hash,
                        raw_source_hash=data.source_hash,
                        metadata_json=canonical(validated),
                        filename=filename,
                        created_at=now(),
                        as_of_utc=as_of.isoformat(),
                    )
                )
                row = conn.execute(existing).mappings().one()
                check_time()
            return row, False
        except BaseException:
            if published:
                self.discard_orphan(data.dataset_hash)
            raise

    @staticmethod
    def stage_content(data, staged, as_of):
        metadata = data.meta.model_dump(exclude={"schema_version", "gap_policy"})
        metadata["timeframe"] = seconds(data.meta.timeframe)
        stored = data.raw_values if data.raw_values is not None else data.values
        pq.write_table(
            pa.table(
                {
                    "timestamp": pa.array(data.times, type=pa.timestamp("us", "UTC")),
                    **{key: stored[:, index] for index, key in enumerate(COLUMNS[1:])},
                }
            ),
            staged,
        )
        check = load_dataset(staged, data.meta, as_of_utc=as_of)
        if check.dataset_hash != data.dataset_hash:
            raise LibraryError(
                500, "E_STORAGE", "Normalized candle integrity verification failed"
            )
        count = len(data.times)
        indexes = sorted(
            set(range(min(5, count))) | set(range(max(0, count - 5), count))
        )
        preview = [
            dict(
                row=i + 1,
                timestamp=instant(data.times[i]),
                **dict(zip(COLUMNS[1:], data.values[i].tolist())),
            )
            for i in indexes
        ]
        quality = dict(
            zero_volume_count=int(np.count_nonzero(data.column("volume") == 0)),
            missing_bar_count=data.missing,
            largest_gap_seconds=data.largest_gap_seconds(),
            last_close_at=instant(data.close_at(-1)),
        )
        return dict(
            dataset_hash=data.dataset_hash,
            normalized_path=f"datasets/{data.dataset_hash}/candles.parquet",
            normalized_sha256=check.source_hash,
            semantic_metadata_json=canonical(metadata),
            preview_json=canonical(preview),
            quality_json=canonical(quality),
            row_count=count,
        )

    def discard_orphan(self, dataset_hash):
        try:
            with self.writer() as conn:
                exists = conn.execute(
                    sa.select(self.contents.c.dataset_hash).where(
                        self.contents.c.dataset_hash == dataset_hash
                    )
                ).scalar_one_or_none()
                if exists is None:
                    self.content_path(dataset_hash).unlink(missing_ok=True)
        except (OSError, sa.exc.SQLAlchemyError, LibraryError):
            pass  # Leave ambiguous ownership for the next exclusive startup.

    def recover(self):
        """Call with exclusive runner ownership before serving requests."""
        for stage in protected(self.staging).glob("import-*"):
            if (
                not stage.is_symlink()
                and stage.is_dir()
                and re.fullmatch(r"import-[a-z0-9_]{8}", stage.name)
            ):
                shutil.rmtree(stage)
        for child in protected(self.datasets).iterdir():
            if not child.is_symlink() and child.is_dir() and HASH.fullmatch(child.name):
                self.discard_orphan(child.name)
