"""Persist uploaded source media metadata.

Revision ID: 0012_asset_metadata
"""
from alembic import op
import sqlalchemy as sa

revision = "0012_asset_metadata"
down_revision = "0011_legacy_project_claims"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("assets", sa.Column("original_filename", sa.String(length=255), nullable=True))
    op.add_column("assets", sa.Column("mime_type", sa.String(length=100), nullable=True))
    op.add_column("assets", sa.Column("size_bytes", sa.BigInteger(), nullable=True))
    op.add_column("assets", sa.Column("duration_seconds", sa.Float(), nullable=True))
    op.add_column("assets", sa.Column("width", sa.Integer(), nullable=True))
    op.add_column("assets", sa.Column("height", sa.Integer(), nullable=True))
    op.add_column("assets", sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False))


def downgrade():
    op.drop_column("assets", "created_at")
    op.drop_column("assets", "height")
    op.drop_column("assets", "width")
    op.drop_column("assets", "duration_seconds")
    op.drop_column("assets", "size_bytes")
    op.drop_column("assets", "mime_type")
    op.drop_column("assets", "original_filename")
