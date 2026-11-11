"""Allow audited claims of legacy projects with no owner.

Revision ID: 0011_legacy_project_claims
"""
from alembic import op
import sqlalchemy as sa

revision = "0011_legacy_project_claims"
down_revision = "0010_email_and_invitations"
branch_labels = None
depends_on = None


def upgrade():
    op.drop_constraint("ck_project_audit_action", "project_audit_events", type_="check")
    op.create_check_constraint(
        "ck_project_audit_action",
        "project_audit_events",
        "action IN ('member.added','member.role_changed','member.removed','ownership.claimed')",
    )
    op.add_column("project_audit_events", sa.Column("details", sa.Text(), nullable=True))


def downgrade():
    op.drop_column("project_audit_events", "details")
    op.drop_constraint("ck_project_audit_action", "project_audit_events", type_="check")
    op.create_check_constraint(
        "ck_project_audit_action",
        "project_audit_events",
        "action IN ('member.added','member.role_changed','member.removed')",
    )
