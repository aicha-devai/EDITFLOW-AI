import uuid
import copy
from datetime import datetime, timezone
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.models import Project, TimelineVersion, RenderJob
from app.versioning import timeline_hash, ProjectNotFound, VersionConflict

class RenderJobNotFound(Exception):
    pass

class InvalidRenderTransition(Exception):
    pass

ACTIVE_STATUSES = {"queued", "running"}
TERMINAL_STATUSES = {"succeeded", "failed", "cancelled"}

async def create_render_job(
    session: AsyncSession,
    project_id: uuid.UUID,
    timeline_version: int | None = None,
    render_profile: dict | None = None,
    request_key: str | None = None,
):
    project = await session.scalar(
        select(Project).where(Project.id == project_id).with_for_update()
    )
    if project is None:
        raise ProjectNotFound()

    if request_key:
        if len(request_key) > 128:
            raise ValueError("request_key must be at most 128 characters")
        existing = await session.scalar(select(RenderJob).where(
            RenderJob.project_id == project_id,
            RenderJob.request_key == request_key,
        ))
        if existing:
            requested_version = timeline_version
            if requested_version is not None:
                requested = await session.scalar(select(TimelineVersion).where(
                    TimelineVersion.project_id == project_id,
                    TimelineVersion.version == requested_version,
                ))
                if requested is None or requested.id != existing.timeline_version_id:
                    raise VersionConflict("Render request key was already used for a different timeline version")
            if render_profile is not None and existing.render_profile != render_profile:
                raise VersionConflict("Render request key was already used with a different render profile")
            return existing, False

    if timeline_version is None:
        if project.current_version_id is None:
            raise LookupError("Project has no saved timeline")
        version_row = await session.scalar(select(TimelineVersion).where(
            TimelineVersion.id == project.current_version_id,
            TimelineVersion.project_id == project_id,
        ))
    else:
        version_row = await session.scalar(select(TimelineVersion).where(
            TimelineVersion.project_id == project_id,
            TimelineVersion.version == timeline_version,
        ))
    if version_row is None:
        raise LookupError("Timeline version does not exist")

    snapshot = copy.deepcopy(version_row.timeline_json)
    digest = timeline_hash(snapshot)
    if digest != version_row.content_hash:
        raise ValueError("Stored timeline snapshot hash does not match its immutable version")

    job = RenderJob(
        project_id=project_id,
        timeline_version_id=version_row.id,
        timeline_snapshot=snapshot,
        timeline_hash=version_row.content_hash,
        status="queued",
        render_profile=render_profile or {},
        request_key=request_key,
    )
    session.add(job)
    await session.flush()
    return job, True

async def get_render_job(session: AsyncSession, project_id: uuid.UUID, job_id: uuid.UUID):
    job = await session.scalar(select(RenderJob).where(
        RenderJob.id == job_id, RenderJob.project_id == project_id
    ))
    if job is None:
        raise RenderJobNotFound()
    return job

async def claim_next_render_job(session: AsyncSession):
    job = await session.scalar(
        select(RenderJob).where(RenderJob.status == "queued")
        .order_by(RenderJob.created_at.asc(), RenderJob.id.asc())
        .with_for_update(skip_locked=True).limit(1)
    )
    if job is None:
        return None
    # Never load the mutable project.current_version_id here. The worker receives only this pinned snapshot.
    if timeline_hash(job.timeline_snapshot) != job.timeline_hash:
        job.status = "failed"
        job.error_message = "Pinned timeline snapshot hash verification failed"
        job.completed_at = datetime.now(timezone.utc)
        await session.flush()
        return job
    job.status = "running"
    job.started_at = datetime.now(timezone.utc)
    await session.flush()
    return job

async def complete_render_job(
    session: AsyncSession,
    job_id: uuid.UUID,
    output_object_key: str,
):
    job = await session.scalar(select(RenderJob).where(RenderJob.id == job_id).with_for_update())
    if job is None:
        raise RenderJobNotFound()
    if job.status != "running":
        raise InvalidRenderTransition(f"Cannot complete a job in status {job.status}")
    if not output_object_key.strip():
        raise ValueError("output_object_key is required")
    job.output_object_key = output_object_key
    job.status = "succeeded"
    job.completed_at = datetime.now(timezone.utc)
    await session.flush()
    return job

async def fail_render_job(session: AsyncSession, job_id: uuid.UUID, error_message: str):
    job = await session.scalar(select(RenderJob).where(RenderJob.id == job_id).with_for_update())
    if job is None:
        raise RenderJobNotFound()
    if job.status != "running":
        raise InvalidRenderTransition(f"Cannot fail a job in status {job.status}")
    job.status = "failed"
    job.error_message = error_message[:4000]
    job.completed_at = datetime.now(timezone.utc)
    await session.flush()
    return job
