import uuid
import copy
from datetime import datetime, timezone, timedelta
from sqlalchemy import select, or_, and_, update
from sqlalchemy.ext.asyncio import AsyncSession
from app.models import Project, TimelineVersion, RenderJob
from app.versioning import timeline_hash, ProjectNotFound, VersionConflict


class RenderJobNotFound(Exception):
    pass


class InvalidRenderTransition(Exception):
    pass


class LeaseLost(Exception):
    pass


class RenderCancelled(Exception):
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
    project = await session.scalar(select(Project).where(Project.id == project_id).with_for_update())
    if project is None:
        raise ProjectNotFound()
    if request_key:
        if len(request_key) > 128:
            raise ValueError("request_key must be at most 128 characters")
        existing = await session.scalar(select(RenderJob).where(
            RenderJob.project_id == project_id, RenderJob.request_key == request_key
        ))
        if existing:
            if timeline_version is not None:
                requested = await session.scalar(select(TimelineVersion).where(
                    TimelineVersion.project_id == project_id, TimelineVersion.version == timeline_version
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
            TimelineVersion.id == project.current_version_id, TimelineVersion.project_id == project_id
        ))
    else:
        version_row = await session.scalar(select(TimelineVersion).where(
            TimelineVersion.project_id == project_id, TimelineVersion.version == timeline_version
        ))
    if version_row is None:
        raise LookupError("Timeline version does not exist")
    snapshot = copy.deepcopy(version_row.timeline_json)
    digest = timeline_hash(snapshot)
    if digest != version_row.content_hash:
        raise ValueError("Stored timeline snapshot hash does not match its immutable version")
    job = RenderJob(
        project_id=project_id, timeline_version_id=version_row.id,
        timeline_snapshot=snapshot, timeline_hash=version_row.content_hash,
        status="queued", render_profile=render_profile or {}, request_key=request_key,
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


async def claim_next_render_job(session: AsyncSession, lease_seconds: int = 90):
    if lease_seconds < 1 or lease_seconds > 3600:
        raise ValueError("lease_seconds must be between 1 and 3600")
    now = datetime.now(timezone.utc)
    # Expired final attempts cannot be retried; close them before selecting work.
    exhausted = (await session.scalars(select(RenderJob).where(
        RenderJob.status == "running",
        RenderJob.lease_expires_at <= now,
        RenderJob.attempts >= RenderJob.max_attempts,
    ).with_for_update(skip_locked=True))).all()
    for item in exhausted:
        item.status = "failed"
        item.error_message = "Worker lease expired after the final attempt"
        item.completed_at = now
        item.lease_token = None
        item.lease_expires_at = None

    job = await session.scalar(
        select(RenderJob).where(
            RenderJob.attempts < RenderJob.max_attempts,
            or_(
                and_(RenderJob.status == "queued", or_(RenderJob.next_attempt_at.is_(None), RenderJob.next_attempt_at <= now)),
                and_(RenderJob.status == "running", RenderJob.lease_expires_at <= now),
            ),
        ).order_by(RenderJob.created_at.asc(), RenderJob.id.asc())
        .with_for_update(skip_locked=True).limit(1)
    )
    if job is None:
        return None
    if timeline_hash(job.timeline_snapshot) != job.timeline_hash:
        job.status = "failed"
        job.error_message = "Pinned timeline snapshot hash verification failed"
        job.completed_at = now
        job.lease_token = None
        job.lease_expires_at = None
        await session.flush()
        return job
    if job.cancel_requested:
        job.status = "cancelled"
        job.completed_at = now
        job.lease_token = None
        job.lease_expires_at = None
        await session.flush()
        return job
    job.status = "running"
    job.attempts += 1
    job.lease_token = uuid.uuid4()
    job.lease_expires_at = now + timedelta(seconds=lease_seconds)
    job.heartbeat_at = now
    job.started_at = job.started_at or now
    job.next_attempt_at = None
    job.error_message = None
    await session.flush()
    return job


async def heartbeat_render_job(
    session: AsyncSession, job_id: uuid.UUID, lease_token: uuid.UUID,
    lease_seconds: int = 90, progress_percent: int | None = None,
):
    job = await session.scalar(select(RenderJob).where(RenderJob.id == job_id).with_for_update())
    if job is None:
        raise RenderJobNotFound()
    now = datetime.now(timezone.utc)
    if job.status != "running" or job.lease_token != lease_token or job.lease_expires_at is None or job.lease_expires_at <= now:
        raise LeaseLost("Worker lease is no longer valid")
    if job.cancel_requested:
        raise RenderCancelled("Render cancellation was requested")
    job.heartbeat_at = now
    job.lease_expires_at = now + timedelta(seconds=lease_seconds)
    if progress_percent is not None:
        if not 0 <= progress_percent <= 99:
            raise ValueError("progress_percent must be between 0 and 99 while rendering")
        job.progress_percent = max(job.progress_percent, progress_percent)
    await session.flush()
    return job


async def complete_render_job(session: AsyncSession, job_id: uuid.UUID, output_object_key: str, lease_token: uuid.UUID):
    job = await session.scalar(select(RenderJob).where(RenderJob.id == job_id).with_for_update())
    if job is None:
        raise RenderJobNotFound()
    now = datetime.now(timezone.utc)
    if job.status != "running" or job.lease_token != lease_token or job.lease_expires_at is None or job.lease_expires_at <= now:
        raise LeaseLost("Worker lease is no longer valid")
    if job.cancel_requested:
        job.status = "cancelled"
        job.completed_at = datetime.now(timezone.utc)
        job.lease_token = None
        job.lease_expires_at = None
        await session.flush()
        return job
    if not output_object_key.strip():
        raise ValueError("output_object_key is required")
    job.output_object_key = output_object_key
    job.status = "succeeded"
    job.progress_percent = 100
    job.completed_at = datetime.now(timezone.utc)
    job.lease_token = None
    job.lease_expires_at = None
    await session.flush()
    return job


async def fail_render_job(
    session: AsyncSession, job_id: uuid.UUID, error_message: str, lease_token: uuid.UUID,
    retry_delay_seconds: int | None = None,
):
    job = await session.scalar(select(RenderJob).where(RenderJob.id == job_id).with_for_update())
    if job is None:
        raise RenderJobNotFound()
    now = datetime.now(timezone.utc)
    if job.status != "running" or job.lease_token != lease_token or job.lease_expires_at is None or job.lease_expires_at <= now:
        raise LeaseLost("Worker lease is no longer valid")
    job.error_message = error_message[:4000]
    job.lease_token = None
    job.lease_expires_at = None
    if job.cancel_requested:
        job.status = "cancelled"
        job.completed_at = now
    elif job.attempts < job.max_attempts:
        delay = retry_delay_seconds if retry_delay_seconds is not None else min(300, 2 ** job.attempts)
        job.status = "queued"
        job.next_attempt_at = now + timedelta(seconds=max(0, delay))
    else:
        job.status = "failed"
        job.completed_at = now
    await session.flush()
    return job


async def request_render_cancellation(session: AsyncSession, project_id: uuid.UUID, job_id: uuid.UUID):
    job = await get_render_job(session, project_id, job_id)
    job = await session.scalar(select(RenderJob).where(RenderJob.id == job_id).with_for_update())
    if job.status == "queued":
        job.status = "cancelled"
        job.completed_at = datetime.now(timezone.utc)
    elif job.status == "running":
        job.cancel_requested = True
    return job
