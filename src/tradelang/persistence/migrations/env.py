"""Run local migrations in the caller's configured SQLite connection."""

from alembic import context

context.configure(
    connection=context.config.attributes["connection"], transactional_ddl=True
)
with context.begin_transaction():
    context.run_migrations()
