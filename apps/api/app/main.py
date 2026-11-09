from uuid import UUID
from fastapi import FastAPI, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from app.config import settings
from app.db import get_db
from app.rendering import create_render_job, get_render_job, request_render_cancellation, RenderJobNotFound
from app.models import Project
from app.schemas import ProjectCreate, SaveTimelineRequest, RestoreRequest, CreateRenderRequest
from app.versioning import (
    save_timeline, list_versions, compare_versions, restore_version,
    VersionConflict, ProjectNotFound,
)

app = FastAPI(title=settings.api_title, version="0.1.0")

@app.get("/health")
async def health():
    return {"status": "ok"}

@app.post("/v1/projects", status_code=201)
async def create_project(payload: ProjectCreate, db: AsyncSession = Depends(get_db)):
    project = Project(title=payload.title.strip())
    db.add(project)
    await db.commit()
    await db.refresh(project)
    return {"id": str(project.id), "title": project.title, "current_version_id": None}

@app.post("/v1/projects/{project_id}/timeline")
async def save_project_timeline(project_id: UUID, payload: SaveTimelineRequest, db: AsyncSession = Depends(get_db)):
    try:
        async with db.begin():
            row, created = await save_timeline(
                db, project_id, payload.timeline, payload.expected_version,
                payload.message,
                idempotency_key=payload.idempotency_key,
            )
        return {"created": created, "version": row.version, "version_id": str(row.id), "content_hash": row.content_hash}
    except ProjectNotFound:
        raise HTTPException(404, "Project not found")
    except VersionConflict as exc:
        raise HTTPException(409, str(exc))
    except ValueError as exc:
        raise HTTPException(422, str(exc))

@app.get("/v1/projects/{project_id}/versions")
async def get_versions(project_id: UUID, db: AsyncSession = Depends(get_db)):
    rows = await list_versions(db, project_id)
    return [{
        "id": str(r.id), "version": r.version, "parent_version_id": str(r.parent_version_id) if r.parent_version_id else None,
        "restored_from_version_id": str(r.restored_from_version_id) if r.restored_from_version_id else None,
        "message": r.message, "content_hash": r.content_hash, "created_at": r.created_at,
    } for r in rows]

@app.get("/v1/projects/{project_id}/versions/compare")
async def compare_project_versions(project_id: UUID, from_version: int, to_version: int, db: AsyncSession = Depends(get_db)):
    try:
        return await compare_versions(db, project_id, from_version, to_version)
    except LookupError as exc:
        raise HTTPException(404, str(exc))

@app.post("/v1/projects/{project_id}/versions/{source_version}/restore")
async def restore_project_version(project_id: UUID, source_version: int, payload: RestoreRequest, db: AsyncSession = Depends(get_db)):
    try:
        async with db.begin():
            row, created = await restore_version(
                db, project_id, source_version, payload.expected_version, payload.message
            )
        return {"created": created, "version": row.version, "version_id": str(row.id),
                "restored_from_version_id": str(row.restored_from_version_id) if row.restored_from_version_id else None}
    except LookupError as exc:
        raise HTTPException(404, str(exc))
    except VersionConflict as exc:
        raise HTTPException(409, str(exc))
    except ValueError as exc:
        raise HTTPException(422, str(exc))


@app.post("/v1/projects/{project_id}/renders", status_code=202)
async def create_project_render(project_id: UUID, payload: CreateRenderRequest, db: AsyncSession = Depends(get_db)):
    try:
        async with db.begin():
            job, created = await create_render_job(
                db, project_id, payload.timeline_version,
                payload.render_profile, payload.request_key,
            )
        return {
            "created": created,
            "job_id": str(job.id),
            "status": job.status,
            "timeline_version_id": str(job.timeline_version_id),
            "timeline_hash": job.timeline_hash,
            "created_at": job.created_at,
        }
    except ProjectNotFound:
        raise HTTPException(404, "Project not found")
    except LookupError as exc:
        raise HTTPException(404, str(exc))
    except VersionConflict as exc:
        raise HTTPException(409, str(exc))
    except ValueError as exc:
        raise HTTPException(422, str(exc))

@app.get("/v1/projects/{project_id}/renders/{job_id}")
async def get_project_render(project_id: UUID, job_id: UUID, db: AsyncSession = Depends(get_db)):
    try:
        job = await get_render_job(db, project_id, job_id)
        return {
            "job_id": str(job.id),
            "status": job.status,
            "timeline_version_id": str(job.timeline_version_id),
            "timeline_hash": job.timeline_hash,
            "render_profile": job.render_profile,
            "output_object_key": job.output_object_key,
            "error_message": job.error_message,
            "quality_report": job.quality_report,
            "attempts": job.attempts,
            "max_attempts": job.max_attempts,
            "progress_percent": job.progress_percent,
            "cancel_requested": job.cancel_requested,
            "created_at": job.created_at,
            "started_at": job.started_at,
            "completed_at": job.completed_at,
        }
    except RenderJobNotFound:
        raise HTTPException(404, "Render job not found")


@app.post("/v1/projects/{project_id}/renders/{job_id}/cancel")
async def cancel_project_render(project_id: UUID, job_id: UUID, db: AsyncSession = Depends(get_db)):
    try:
        async with db.begin():
            job = await request_render_cancellation(db, project_id, job_id)
        return {
            "job_id": str(job.id),
            "status": job.status,
            "cancel_requested": job.cancel_requested,
        }
    except RenderJobNotFound:
        raise HTTPException(404, "Render job not found")
