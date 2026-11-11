"""Add project membership audit events.

Revision ID: 0009_project_audit_log
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0009_project_audit_log"
down_revision = "0008_auth_rate_limits"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "project_audit_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("actor_user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("actor_email", sa.String(320), nullable=False),
        sa.Column("target_user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("target_email", sa.String(320), nullable=False),
        sa.Column("action", sa.String(40), nullable=False),
        sa.Column("previous_role", sa.String(20), nullable=True),
        sa.Column("new_role", sa.String(20), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint(
            "action IN ('member.added','member.role_changed','member.removed')",
            name="ck_project_audit_action",
        ),
    )
    op.create_index("ix_project_audit_events_project_id", "project_audit_events", ["project_id"])
    op.create_index("ix_project_audit_events_project_created", "project_audit_events", ["project_id", "created_at"])


def downgrade():
    op.drop_index("ix_project_audit_events_project_created", table_name="project_audit_events")
    op.drop_index("ix_project_audit_events_project_id", table_name="project_audit_events")
    op.drop_table("project_audit_events")
