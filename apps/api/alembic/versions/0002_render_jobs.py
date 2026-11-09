"""Pinned render jobs.

Revision ID: 0002_render_jobs
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0002_render_jobs"
down_revision = "0001_initial"
branch_labels = None
depends_on = None

def upgrade():
    op.create_table(
        "render_jobs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("timeline_version_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("timeline_versions.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("timeline_snapshot", postgresql.JSONB(), nullable=False),
        sa.Column("timeline_hash", sa.String(64), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="queued"),
        sa.Column("render_profile", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("output_object_key", sa.Text(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("request_key", sa.String(128), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("project_id", "request_key", name="uq_render_job_request_key"),
        sa.CheckConstraint("status IN ('queued','running','succeeded','failed','cancelled')", name="ck_render_jobs_status"),
    )
    op.execute("""
    CREATE FUNCTION prevent_render_snapshot_mutation() RETURNS trigger AS $$
    BEGIN
      IF NEW.project_id IS DISTINCT FROM OLD.project_id
         OR NEW.timeline_version_id IS DISTINCT FROM OLD.timeline_version_id
         OR NEW.timeline_snapshot IS DISTINCT FROM OLD.timeline_snapshot
         OR NEW.timeline_hash IS DISTINCT FROM OLD.timeline_hash
         OR NEW.render_profile IS DISTINCT FROM OLD.render_profile THEN
        RAISE EXCEPTION 'render job timeline pin is immutable';
      END IF;
      RETURN NEW;
    END;
    $$ LANGUAGE plpgsql
    """)
    op.execute("""
    CREATE TRIGGER trg_render_job_snapshot_immutable
    BEFORE UPDATE ON render_jobs
    FOR EACH ROW EXECUTE FUNCTION prevent_render_snapshot_mutation()
    """)
    op.create_index("ix_render_jobs_status_created", "render_jobs", ["status", "created_at"])
    op.create_index("ix_render_jobs_project_created", "render_jobs", ["project_id", "created_at"])

def downgrade():
    op.execute("DROP TRIGGER IF EXISTS trg_render_job_snapshot_immutable ON render_jobs")
    op.execute("DROP FUNCTION IF EXISTS prevent_render_snapshot_mutation()")
    op.drop_index("ix_render_jobs_project_created", table_name="render_jobs")
    op.drop_index("ix_render_jobs_status_created", table_name="render_jobs")
    op.drop_table("render_jobs")
