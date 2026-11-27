"""Stable preset identity and revision-checked updates."""

from uuid import uuid4

import sqlalchemy as sa

from . import LibraryError, now, paginate


class Presets:
    def __init__(self, library):
        self.library = library
        self.table = library.run_presets

    def read(self, ident, conn=None):
        if conn is None:
            with self.library.db.connect() as connection:
                return self.read(ident, connection)
        row = (
            conn.execute(sa.select(self.table).where(self.table.c.id == ident))
            .mappings()
            .one_or_none()
        )
        if row is None:
            raise LibraryError(404, "E_PRESET_NOT_FOUND", "Unknown run preset")
        return dict(row)

    def list(self, limit, cursor):
        with self.library.db.connect() as connection:
            rows, next_cursor, snapshot = paginate(
                connection,
                sa.select(self.table),
                self.table,
                limit,
                cursor,
                ["run_presets"],
            )
        return dict(
            items=[dict(row) for row in rows],
            next_cursor=next_cursor,
            snapshot=snapshot,
        )

    def write(self, fields, *, ident=None, expected_revision=None):
        with self.library.writer() as connection:
            for key in ("dataset_id", "profile_dataset_id"):
                if (
                    fields[key] is not None
                    and connection.scalar(
                        sa.select(self.library.imports.c.id).where(
                            self.library.imports.c.id == fields[key]
                        )
                    )
                    is None
                ):
                    raise LibraryError(
                        404, "E_DATASET_NOT_FOUND", f"Unknown preset {key}"
                    )
            stamp = now()
            if ident is None:
                ident = str(uuid4())
                connection.execute(
                    self.table.insert().values(
                        id=ident,
                        revision=1,
                        created_at=stamp,
                        updated_at=stamp,
                        **fields,
                    )
                )
            else:
                previous = self.read(ident, connection)
                if previous["revision"] != expected_revision:
                    raise LibraryError(
                        409, "E_PRESET_CONFLICT", "The run preset has a newer revision"
                    )
                connection.execute(
                    self.table.update()
                    .where(self.table.c.id == ident)
                    .values(
                        revision=previous["revision"] + 1, updated_at=stamp, **fields
                    )
                )
            return self.read(ident, connection)
