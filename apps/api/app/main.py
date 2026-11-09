from uuid import UUID
from fastapi import FastAPI, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.config import settings
from app.db import get_db
from app.models import Project, TimelineVersion
from app.schemas import SaveTimelineRequest, RestoreRequest
from app.versioning import (
    save_timeline, list_versions, compare_versions, restore_version,
    VersionConflict, ProjectNotFound,
)

app = FastAPI(title=settings.api_title, version="0.1.0")

@app.get("/health")
async def health():
    return {"status": "ok"}

@app.post("/v1/projects/{project_id}/timeline")
async def save_project_timeline(project_id: UUID, payload: SaveTimelineRequest, db: AsyncSession = Depends(get_db)):
    try:
        async with db.begin():
            row, created = await save_timeline(
                db, project_id, payload.timeline, payload.expected_version,
                payload.message,
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
