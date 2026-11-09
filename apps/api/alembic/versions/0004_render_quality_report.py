"""Persist perceptual render QC report.

Revision ID: 0004_render_quality_report
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0004_render_quality_report"
down_revision = "0003_render_reliability"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "render_jobs",
        sa.Column("quality_report", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )


def downgrade():
    op.drop_column("render_jobs", "quality_report")
