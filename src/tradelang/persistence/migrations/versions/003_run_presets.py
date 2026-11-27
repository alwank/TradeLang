"""Persist reusable run configuration presets."""

import sqlalchemy as sa
from alembic import op

revision = "003_run_presets"
down_revision = "002_runs"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "run_presets",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("settings", sa.JSON(), nullable=False),
        sa.Column("dataset_id", sa.String(36), sa.ForeignKey("dataset_imports.id")),
        sa.Column(
            "profile_dataset_id", sa.String(36), sa.ForeignKey("dataset_imports.id")
        ),
        sa.Column("created_at", sa.String(32), nullable=False),
        sa.Column("updated_at", sa.String(32), nullable=False),
    )
    op.create_index("run_presets_list", "run_presets", ["created_at", "id"])


def downgrade():
    op.drop_table("run_presets")
