"""Persist immutable backtest requests and their lifecycle."""

import sqlalchemy as sa
from alembic import op

revision = "002_runs"
down_revision = "001_library"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "runs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "strategy_id", sa.String(36), sa.ForeignKey("strategies.id"), nullable=False
        ),
        sa.Column(
            "revision_id",
            sa.String(36),
            sa.ForeignKey("strategy_revisions.id"),
            nullable=False,
        ),
        sa.Column(
            "dataset_id",
            sa.String(36),
            sa.ForeignKey("dataset_imports.id"),
            nullable=False,
        ),
        sa.Column(
            "profile_dataset_id", sa.String(36), sa.ForeignKey("dataset_imports.id")
        ),
        sa.Column("snapshot", sa.JSON(), nullable=False),
        sa.Column("idempotency_key", sa.String(36), unique=True),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("status", sa.String(10), nullable=False),
        sa.Column("created_at", sa.String(32), nullable=False),
        sa.Column("started_at", sa.String(32)),
        sa.Column("finished_at", sa.String(32)),
        sa.Column("cancel_requested_at", sa.String(32)),
        sa.Column("worker_pid", sa.Integer()),
        sa.Column("child_pid", sa.Integer()),
        sa.Column("completed_bars", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("total_bars", sa.Integer(), nullable=False),
        sa.Column("error", sa.JSON(none_as_null=True)),
        sa.Column("summary", sa.JSON(none_as_null=True)),
        sa.Column("result_digest", sa.String(64)),
        sa.CheckConstraint(
            "status IN ('queued','running','succeeded','failed','cancelled')"
        ),
    )
    op.create_index("runs_list", "runs", ["created_at", "id"])
    op.create_index("runs_status", "runs", ["status", "created_at", "id"])
    op.create_index("runs_strategy", "runs", ["strategy_id", "created_at", "id"])
    op.create_index(
        "runs_active",
        "runs",
        ["status"],
        unique=True,
        sqlite_where=sa.text("status = 'running'"),
    )


def downgrade():
    op.drop_table("runs")
