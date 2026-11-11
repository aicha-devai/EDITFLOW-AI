"""Add persistent authentication rate-limit buckets.

Revision ID: 0008_auth_rate_limits
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0008_auth_rate_limits"
down_revision = "0007_user_sessions"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "rate_limit_buckets",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("scope_key", sa.String(64), nullable=False),
        sa.Column("window_started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("request_count", sa.Integer(), nullable=False, server_default="0"),
        sa.UniqueConstraint("scope_key", name="uq_rate_limit_scope_key"),
    )


def downgrade():
    op.drop_table("rate_limit_buckets")
