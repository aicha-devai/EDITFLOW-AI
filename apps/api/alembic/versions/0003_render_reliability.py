"""Render worker leases, retries, progress and cancellation.

Revision ID: 0003_render_reliability
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0003_render_reliability"
down_revision = "0002_render_jobs"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("render_jobs", sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("render_jobs", sa.Column("max_attempts", sa.Integer(), nullable=False, server_default="3"))
    op.add_column("render_jobs", sa.Column("lease_token", postgresql.UUID(as_uuid=True), nullable=True))
    op.add_column("render_jobs", sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("render_jobs", sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("render_jobs", sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("render_jobs", sa.Column("progress_percent", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("render_jobs", sa.Column("cancel_requested", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.create_check_constraint("ck_render_jobs_attempts", "render_jobs", "attempts >= 0 AND max_attempts >= 1 AND attempts <= max_attempts")
    op.create_check_constraint("ck_render_jobs_progress", "render_jobs", "progress_percent BETWEEN 0 AND 100")
    op.create_index("ix_render_jobs_lease_expiry", "render_jobs", ["status", "lease_expires_at"])
    op.create_index("ix_render_jobs_next_attempt", "render_jobs", ["status", "next_attempt_at"])


def downgrade():
    op.drop_index("ix_render_jobs_next_attempt", table_name="render_jobs")
    op.drop_index("ix_render_jobs_lease_expiry", table_name="render_jobs")
    op.drop_constraint("ck_render_jobs_progress", "render_jobs", type_="check")
    op.drop_constraint("ck_render_jobs_attempts", "render_jobs", type_="check")
    for column in ("cancel_requested", "progress_percent", "next_attempt_at", "heartbeat_at", "lease_expires_at", "lease_token", "max_attempts", "attempts"):
        op.drop_column("render_jobs", column)
