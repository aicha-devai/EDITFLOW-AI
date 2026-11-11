from uuid import UUID
from fastapi import FastAPI, Depends, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession
from app.config import settings
from app.db import get_db
from app.rendering import create_render_job, get_render_job, request_render_cancellation, RenderJobNotFound
from sqlalchemy import select, or_, delete
from sqlalchemy.exc import IntegrityError
from app.models import Project, RenderJob, User, ProjectMember
from app.schemas import (
    ProjectCreate, SaveTimelineRequest, RestoreRequest, CreateRenderRequest,
    QCCriticApprovalRequest, AuthRegisterRequest, AuthLoginRequest, ProjectMemberUpsert,
)
from app.qc_critic import (
    generate_qc_critic_proposals, approve_qc_intent_proposals,
    QCCriticNotFound, QCCriticNotReady, StaleQCCriticBase,
)
from app.versioning import (
    save_timeline, list_versions, compare_versions, restore_version,
    VersionConflict, ProjectNotFound,
)
from app.storage import create_object_storage, LocalObjectStorage, S3ObjectStorage, StorageError
from app.auth import get_current_user, hash_password, verify_password, create_access_token

app = FastAPI(title=settings.api_title, version="0.1.0")
_allowed_origins = [origin.strip() for origin in settings.cors_origins.split(",") if origin.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Accept", "Content-Type", "Authorization"],
)

@app.get("/health")
async def health():
    return {"status": "ok"}


async def require_owned_project(
    project_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Project:
    project = await db.scalar(select(Project).where(
        Project.id == project_id,
        Project.owner_id == current_user.id,
    ))
    if project is None:
        # Do not reveal whether another user's project exists.
        raise HTTPException(404, "Project not found")
    return project



async def require_project_access(
    project_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Project:
    project = await db.scalar(
        select(Project)
        .outerjoin(ProjectMember, ProjectMember.project_id == Project.id)
        .where(
            Project.id == project_id,
            or_(Project.owner_id == current_user.id, ProjectMember.user_id == current_user.id),
        )
    )
    if project is None:
        raise HTTPException(404, "Project not found")
    return project


async def require_project_editor(
    project: Project = Depends(require_project_access),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Project:
    if project.owner_id == current_user.id:
        return project
    role = await db.scalar(select(ProjectMember.role).where(
        ProjectMember.project_id == project.id,
        ProjectMember.user_id == current_user.id,
    ))
    if role != "editor":
        raise HTTPException(403, "Editor role is required for this operation")
    return project


@app.post("/v1/auth/register", status_code=201)
async def register_account(payload: AuthRegisterRequest, db: AsyncSession = Depends(get_db)):
    if not settings.auth_secret or len(settings.auth_secret.encode("utf-8")) < 32:
        raise HTTPException(503, "Authentication is not configured")
    existing = await db.scalar(select(User).where(User.email == payload.email))
    if existing is not None:
        raise HTTPException(409, "An account with this email already exists")
    user = User(email=payload.email, password_hash=hash_password(payload.password))
    db.add(user)
    try:
        await db.flush()
        access_token = create_access_token(user.id)
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(409, "An account with this email already exists")
    except Exception:
        await db.rollback()
        raise
    return {
        "user": {"id": str(user.id), "email": user.email},
        "access_token": access_token,
        "token_type": "bearer",
        "expires_in": settings.auth_access_token_seconds,
    }


@app.post("/v1/auth/login")
async def login_account(payload: AuthLoginRequest, db: AsyncSession = Depends(get_db)):
    user = await db.scalar(select(User).where(User.email == payload.email))
    if user is None or not user.is_active or not verify_password(payload.password, user.password_hash):
        raise HTTPException(401, "Invalid email or password", headers={"WWW-Authenticate": "Bearer"})
    return {
        "user": {"id": str(user.id), "email": user.email},
        "access_token": create_access_token(user.id),
        "token_type": "bearer",
        "expires_in": settings.auth_access_token_seconds,
    }


@app.get("/v1/auth/me")
async def get_authenticated_account(current_user: User = Depends(get_current_user)):
    return {"id": str(current_user.id), "email": current_user.email, "is_active": current_user.is_active}

@app.post("/v1/projects", status_code=201)
async def create_project(payload: ProjectCreate, db: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_user)):
    project = Project(title=payload.title.strip(), owner_id=current_user.id)
    db.add(project)
    await db.commit()
    await db.refresh(project)
    return {"id": str(project.id), "title": project.title, "current_version_id": None}


@app.get("/v1/projects/{project_id}/members")
async def list_project_members(
    project_id: UUID,
    db: AsyncSession = Depends(get_db),
    _owned_project: Project = Depends(require_owned_project),
):
    owner = await db.scalar(select(User).where(User.id == _owned_project.owner_id))
    members = (await db.execute(
        select(ProjectMember, User)
        .join(User, User.id == ProjectMember.user_id)
        .where(ProjectMember.project_id == project_id)
        .order_by(User.email)
    )).all()
    result = []
    if owner is not None:
        result.append({"user_id": str(owner.id), "email": owner.email, "role": "owner"})
    result.extend({
        "user_id": str(member.user_id),
        "email": user.email,
        "role": member.role,
        "created_at": member.created_at,
    } for member, user in members)
    return result


@app.post("/v1/projects/{project_id}/members", status_code=200)
async def upsert_project_member(
    project_id: UUID,
    payload: ProjectMemberUpsert,
    db: AsyncSession = Depends(get_db),
    _owned_project: Project = Depends(require_owned_project),
):
    user = await db.scalar(select(User).where(User.email == payload.email, User.is_active.is_(True)))
    if user is None:
        raise HTTPException(404, "An active account with this email was not found")
    if user.id == _owned_project.owner_id:
        raise HTTPException(409, "The project owner already has full access")
    member = await db.scalar(select(ProjectMember).where(
        ProjectMember.project_id == project_id,
        ProjectMember.user_id == user.id,
    ))
    if member is None:
        member = ProjectMember(project_id=project_id, user_id=user.id, role=payload.role)
        db.add(member)
    else:
        member.role = payload.role
    await db.commit()
    await db.refresh(member)
    return {"user_id": str(user.id), "email": user.email, "role": member.role}


@app.delete("/v1/projects/{project_id}/members/{member_user_id}", status_code=204)
async def remove_project_member(
    project_id: UUID,
    member_user_id: UUID,
    db: AsyncSession = Depends(get_db),
    _owned_project: Project = Depends(require_owned_project),
):
    result = await db.execute(delete(ProjectMember).where(
        ProjectMember.project_id == project_id,
        ProjectMember.user_id == member_user_id,
    ))
    if result.rowcount == 0:
        raise HTTPException(404, "Project member not found")
    await db.commit()
    return None

@app.post("/v1/projects/{project_id}/timeline")
async def save_project_timeline(project_id: UUID, payload: SaveTimelineRequest, db: AsyncSession = Depends(get_db), _owned_project: Project = Depends(require_project_editor)):
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
async def get_versions(project_id: UUID, db: AsyncSession = Depends(get_db), _owned_project: Project = Depends(require_project_access)):
    rows = await list_versions(db, project_id)
    return [{
        "id": str(r.id), "version": r.version, "parent_version_id": str(r.parent_version_id) if r.parent_version_id else None,
        "restored_from_version_id": str(r.restored_from_version_id) if r.restored_from_version_id else None,
        "message": r.message, "content_hash": r.content_hash, "created_at": r.created_at,
    } for r in rows]

@app.get("/v1/projects/{project_id}/versions/compare")
async def compare_project_versions(project_id: UUID, from_version: int, to_version: int, db: AsyncSession = Depends(get_db), _owned_project: Project = Depends(require_project_access)):
    try:
        return await compare_versions(db, project_id, from_version, to_version)
    except LookupError as exc:
        raise HTTPException(404, str(exc))

@app.post("/v1/projects/{project_id}/versions/{source_version}/restore")
async def restore_project_version(project_id: UUID, source_version: int, payload: RestoreRequest, db: AsyncSession = Depends(get_db), _owned_project: Project = Depends(require_project_editor)):
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
async def create_project_render(project_id: UUID, payload: CreateRenderRequest, db: AsyncSession = Depends(get_db), _owned_project: Project = Depends(require_project_editor)):
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
async def get_project_render(project_id: UUID, job_id: UUID, db: AsyncSession = Depends(get_db), _owned_project: Project = Depends(require_project_access)):
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



@app.get("/v1/projects/{project_id}/renders/{job_id}/media")
async def stream_project_render_media(project_id: UUID, job_id: UUID, db: AsyncSession = Depends(get_db), _owned_project: Project = Depends(require_project_access)):
    """Serve the immutable rendered MP4 with browser seeking / HTTP range support."""
    job = await db.scalar(select(RenderJob).where(
        RenderJob.id == job_id, RenderJob.project_id == project_id
    ))
    if job is None:
        raise HTTPException(404, "Render job not found")
    if job.status != "succeeded" or not job.output_object_key:
        raise HTTPException(409, "Rendered media is not available until the job succeeds")
    try:
        storage = create_object_storage(settings)
        if isinstance(storage, S3ObjectStorage):
            return RedirectResponse(
                url=storage.create_download_url(job.output_object_key, expires_seconds=900),
                status_code=307,
                headers={"Cache-Control": "private, no-store"},
            )
        if isinstance(storage, LocalObjectStorage):
            path = storage.resolve_path(job.output_object_key)
            if not path.is_file() or path.stat().st_size <= 0:
                raise HTTPException(404, "Rendered media file is missing")
            return FileResponse(
                path=path,
                media_type="video/mp4",
                headers={"Cache-Control": "private, no-store", "Accept-Ranges": "bytes"},
            )
        raise HTTPException(500, "Unsupported object storage backend")
    except StorageError as exc:
        raise HTTPException(404, "Rendered media could not be resolved") from exc

@app.post("/v1/projects/{project_id}/renders/{job_id}/cancel")
async def cancel_project_render(project_id: UUID, job_id: UUID, db: AsyncSession = Depends(get_db), _owned_project: Project = Depends(require_project_editor)):
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


@app.get("/v1/projects/{project_id}/renders/{job_id}/qc-critic")
async def get_qc_critic_suggestions(project_id: UUID, job_id: UUID, db: AsyncSession = Depends(get_db), _owned_project: Project = Depends(require_project_access)):
    job = await db.scalar(select(RenderJob).where(
        RenderJob.id == job_id, RenderJob.project_id == project_id
    ))
    if job is None:
        raise HTTPException(404, "Render job not found")
    if job.status != "succeeded":
        raise HTTPException(409, "QC Critic suggestions are available only after a successful render")
    return {
        "job_id": str(job.id),
        "timeline_version_id": str(job.timeline_version_id),
        **generate_qc_critic_proposals(job.quality_report, job.timeline_snapshot),
    }


@app.get("/v1/projects/{project_id}/renders/{job_id}/story-continuity")
async def get_story_continuity_graph(project_id: UUID, job_id: UUID, db: AsyncSession = Depends(get_db), _owned_project: Project = Depends(require_project_access)):
    job = await db.scalar(select(RenderJob).where(
        RenderJob.id == job_id, RenderJob.project_id == project_id
    ))
    if job is None:
        raise HTTPException(404, "Render job not found")
    if job.status != "succeeded":
        raise HTTPException(409, "Story Continuity Graph is available only after a successful render")
    report = job.quality_report if isinstance(job.quality_report, dict) else {}
    graph = report.get("story_continuity_graph")
    if not isinstance(graph, dict):
        raise HTTPException(404, "Story Continuity Graph is not available for this render")
    return {
        "job_id": str(job.id),
        "timeline_version_id": str(job.timeline_version_id),
        "timeline_hash": job.timeline_hash,
        "media_available": bool(job.output_object_key),
        "media_url": f"/v1/projects/{project_id}/renders/{job_id}/media" if job.output_object_key else None,
        "graph": graph,
    }


@app.post("/v1/projects/{project_id}/renders/{job_id}/qc-critic/approve")
async def approve_qc_critic_suggestions(
    project_id: UUID, job_id: UUID, payload: QCCriticApprovalRequest,
    db: AsyncSession = Depends(get_db),
    _owned_project: Project = Depends(require_owned_project),
):
    try:
        async with db.begin():
            row, created, approved_count = await approve_qc_intent_proposals(
                db, project_id, job_id, payload.proposal_ids, payload.expected_version
            )
        return {
            "created": created,
            "approved_count": approved_count,
            "version": row.version,
            "version_id": str(row.id),
            "content_hash": row.content_hash,
            "message": "Approved intent annotations were saved as a new immutable timeline version."
            if created else "The approved annotations already match the current timeline.",
        }
    except QCCriticNotFound:
        raise HTTPException(404, "Render job not found")
    except QCCriticNotReady:
        raise HTTPException(409, "QC Critic approval requires a succeeded render with a QC report")
    except StaleQCCriticBase as exc:
        raise HTTPException(409, str(exc))
    except VersionConflict as exc:
        raise HTTPException(409, str(exc))
    except ValueError as exc:
        raise HTTPException(422, str(exc))
