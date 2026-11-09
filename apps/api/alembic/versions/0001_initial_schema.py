"""Initial EDITFLOW persistence schema.

Revision ID: 0001_initial
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None

def upgrade():
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")
    op.create_table(
        "projects",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("current_version_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_table(
        "assets",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("object_key", sa.Text(), nullable=False),
        sa.Column("checksum_sha256", sa.String(64), nullable=True),
    )
    op.create_table(
        "timeline_versions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("parent_version_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("timeline_versions.id"), nullable=True),
        sa.Column("timeline_json", postgresql.JSONB(), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("idempotency_key", sa.String(128), nullable=True),
        sa.Column("restored_from_version_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("timeline_versions.id"), nullable=True),
        sa.Column("message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("version > 0", name="ck_timeline_versions_version_positive"),
        sa.UniqueConstraint("project_id", "version", name="uq_timeline_version_number"),
        sa.UniqueConstraint("project_id", "idempotency_key", name="uq_timeline_version_idempotency"),
    )
    op.create_index("ix_timeline_versions_project_version", "timeline_versions", ["project_id", sa.text("version DESC")])
    op.create_index("ix_timeline_versions_content_hash", "timeline_versions", ["project_id", "content_hash"])
    op.create_table(
        "timeline_asset_references",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("timeline_version_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("timeline_versions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("asset_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("assets.id", ondelete="RESTRICT"), nullable=False),
        sa.UniqueConstraint("timeline_version_id", "asset_id", name="uq_timeline_asset_reference"),
    )
    op.create_foreign_key(
        "fk_projects_current_version", "projects", "timeline_versions",
        ["current_version_id"], ["id"], deferrable=True, initially="DEFERRED",
    )

def downgrade():
    op.drop_constraint("fk_projects_current_version", "projects", type_="foreignkey")
    op.drop_table("timeline_asset_references")
    op.drop_index("ix_timeline_versions_content_hash", table_name="timeline_versions")
    op.drop_index("ix_timeline_versions_project_version", table_name="timeline_versions")
    op.drop_table("timeline_versions")
    op.drop_table("assets")
    op.drop_table("projects")
