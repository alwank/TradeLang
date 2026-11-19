"""Create the immutable strategy and import library."""

import sqlalchemy as sa
from alembic import op

revision = "001_library"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "strategies",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("current_revision", sa.Integer(), nullable=False),
        sa.Column("etag", sa.String(70), nullable=False),
        sa.Column("created_at", sa.String(32), nullable=False),
        sa.Column("updated_at", sa.String(32), nullable=False),
        sa.Column("deleted_at", sa.String(32)),
    )
    op.create_index("strategies_list", "strategies", ["created_at", "id"])
    op.create_table(
        "strategy_revisions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "strategy_id", sa.String(36), sa.ForeignKey("strategies.id"), nullable=False
        ),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("source_hash", sa.String(64), nullable=False),
        sa.Column("created_at", sa.String(32), nullable=False),
        sa.UniqueConstraint("strategy_id", "revision"),
    )
    op.create_table(
        "dataset_contents",
        sa.Column("dataset_hash", sa.String(64), primary_key=True),
        sa.Column("semantic_metadata_json", sa.Text(), nullable=False),
        sa.Column("normalized_path", sa.Text(), nullable=False),
        sa.Column("normalized_sha256", sa.String(64), nullable=False),
        sa.Column("preview_json", sa.Text(), nullable=False),
        sa.Column("quality_json", sa.Text(), nullable=False),
        sa.Column("row_count", sa.Integer(), nullable=False),
    )
    op.create_table(
        "dataset_imports",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("import_key", sa.String(64), nullable=False, unique=True),
        sa.Column(
            "dataset_hash",
            sa.String(64),
            sa.ForeignKey("dataset_contents.dataset_hash"),
            nullable=False,
        ),
        sa.Column("raw_source_hash", sa.String(64), nullable=False),
        sa.Column("metadata_json", sa.Text(), nullable=False),
        sa.Column("filename", sa.Text(), nullable=False),
        sa.Column("created_at", sa.String(32), nullable=False),
        sa.Column("as_of_utc", sa.String(32), nullable=False),
    )
    op.create_index("dataset_imports_list", "dataset_imports", ["created_at", "id"])


def downgrade():
    op.drop_table("dataset_imports")
    op.drop_table("dataset_contents")
    op.drop_table("strategy_revisions")
    op.drop_table("strategies")
