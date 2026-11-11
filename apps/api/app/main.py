from uuid import UUID, uuid4
from datetime import datetime, timedelta, timezone
import hashlib
import secrets
from fastapi import FastAPI, Depends, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession
from app.config import settings
from app.db import get_db
from app.rendering import create_render_job, get_render_job, request_render_cancellation, RenderJobNotFound
from sqlalchemy import select, or_, delete, update
from sqlalchemy.exc import IntegrityError
from app.models import Project, RenderJob, User, ProjectMember, UserSession, ProjectAuditEvent, AuthActionToken, ProjectInvitation
from app.schemas import (
    ProjectCreate, SaveTimelineRequest, RestoreRequest, CreateRenderRequest,
    QCCriticApprovalRequest, AuthRegisterRequest, AuthLoginRequest, ProjectMemberUpsert, RefreshTokenRequest,
    EmailOnlyRequest, ActionTokenRequest, PasswordResetRequest, ProjectInvitationCreate,
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
from app.auth import get_current_user, hash_password, verify_password, create_access_token, generate_refresh_token, hash_refresh_token
from app.rate_limit import enforce_rate_limit
from app.emailer import send_email

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



def _new_refresh_session(user_id: UUID, family_id: UUID | None = None):
    raw_token = generate_refresh_token()
    session = UserSession(
        user_id=user_id,
        family_id=family_id or uuid4(),
        refresh_token_hash=hash_refresh_token(raw_token),
        expires_at=datetime.now(timezone.utc) + timedelta(days=settings.auth_refresh_token_days),
    )
    return raw_token, session


def _new_action_token(user_id: UUID, purpose: str, lifetime: timedelta):
    raw = secrets.token_urlsafe(40)
    row = AuthActionToken(
        user_id=user_id,
        purpose=purpose,
        token_hash=hashlib.sha256(raw.encode("utf-8")).hexdigest(),
        expires_at=datetime.now(timezone.utc) + lifetime,
    )
    return raw, row


def _email_link(path: str, token: str) -> str:
    return f"{settings.email_public_url.rstrip('/')}{path}?token={token}"


@app.post("/v1/auth/register", status_code=202)
async def register_account(payload: AuthRegisterRequest, db: AsyncSession = Depends(get_db), request: Request = None):
    if not settings.auth_secret or len(settings.auth_secret.encode("utf-8")) < 32:
        raise HTTPException(503, "Authentication is not configured")
    client_ip = request.client.host if request and request.client else "unknown"
    await enforce_rate_limit(db, [f"register:ip:{client_ip}"], settings.auth_register_limit, settings.auth_register_window_seconds)
    existing = await db.scalar(select(User).where(User.email == payload.email))
    if existing is not None:
        raise HTTPException(409, "An account with this email already exists")
    user = User(email=payload.email, password_hash=hash_password(payload.password), is_email_verified=False)
    db.add(user)
    try:
        await db.flush()
        raw_token, token_row = _new_action_token(user.id, "email_verification", timedelta(hours=24))
        db.add(token_row)
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(409, "An account with this email already exists")
    await send_email(
        user.email,
        "Verify your EDITFLOW AI email",
        "Verify your email address using this link (valid for 24 hours):\n"
        + _email_link("/verify-email", raw_token)
        + "\nIf you did not create this account, you can ignore this message.",
    )
    return {"message": "Verification email sent. Verify your email before signing in."}


@app.post("/v1/auth/verify-email")
async def verify_email(payload: ActionTokenRequest, db: AsyncSession = Depends(get_db)):
    token_hash = hashlib.sha256(payload.token.encode("utf-8")).hexdigest()
    row = await db.scalar(select(AuthActionToken).where(
        AuthActionToken.token_hash == token_hash,
        AuthActionToken.purpose == "email_verification",
    ).with_for_update())
    now = datetime.now(timezone.utc)
    if row is None or row.consumed_at is not None or row.expires_at <= now:
        raise HTTPException(400, "Verification link is invalid or expired")
    user = await db.scalar(select(User).where(User.id == row.user_id, User.is_active.is_(True)))
    if user is None:
        raise HTTPException(400, "Verification link is invalid or expired")
    user.is_email_verified = True
    row.consumed_at = now
    await db.execute(update(AuthActionToken).where(
        AuthActionToken.user_id == user.id,
        AuthActionToken.purpose == "email_verification",
        AuthActionToken.consumed_at.is_(None),
    ).values(consumed_at=now))
    await db.commit()
    return {"verified": True}


@app.post("/v1/auth/resend-verification")
async def resend_verification(payload: EmailOnlyRequest, db: AsyncSession = Depends(get_db), request: Request = None):
    client_ip = request.client.host if request and request.client else "unknown"
    await enforce_rate_limit(db, [f"verify-resend:ip:{client_ip}", f"verify-resend:email:{payload.email}"], 5, 3600)
    user = await db.scalar(select(User).where(User.email == payload.email, User.is_active.is_(True)))
    if user is not None and not user.is_email_verified:
        await db.execute(update(AuthActionToken).where(
            AuthActionToken.user_id == user.id,
            AuthActionToken.purpose == "email_verification",
            AuthActionToken.consumed_at.is_(None),
        ).values(consumed_at=datetime.now(timezone.utc)))
        raw, row = _new_action_token(user.id, "email_verification", timedelta(hours=24))
        db.add(row)
        await db.commit()
        await send_email(user.email, "Verify your EDITFLOW AI email",
            "Use this link within 24 hours:\n" + _email_link("/verify-email", raw))
    return {"message": "If the account needs verification, an email will be sent."}


@app.post("/v1/auth/request-password-reset")
async def request_password_reset(payload: EmailOnlyRequest, db: AsyncSession = Depends(get_db), request: Request = None):
    client_ip = request.client.host if request and request.client else "unknown"
    await enforce_rate_limit(db, [f"password-reset:ip:{client_ip}", f"password-reset:email:{payload.email}"], 5, 3600)
    user = await db.scalar(select(User).where(User.email == payload.email, User.is_active.is_(True)))
    if user is not None and user.is_email_verified:
        await db.execute(update(AuthActionToken).where(
            AuthActionToken.user_id == user.id,
            AuthActionToken.purpose == "password_reset",
            AuthActionToken.consumed_at.is_(None),
        ).values(consumed_at=datetime.now(timezone.utc)))
        raw, row = _new_action_token(user.id, "password_reset", timedelta(minutes=30))
        db.add(row)
        await db.commit()
        await send_email(user.email, "Reset your EDITFLOW AI password",
            "Use this link within 30 minutes:\n" + _email_link("/reset-password", raw)
            + "\nIf you did not request a reset, ignore this message.")
    return {"message": "If the account exists and is verified, a reset email will be sent."}


@app.post("/v1/auth/reset-password")
async def reset_password(payload: PasswordResetRequest, db: AsyncSession = Depends(get_db)):
    token_hash = hashlib.sha256(payload.token.encode("utf-8")).hexdigest()
    row = await db.scalar(select(AuthActionToken).where(
        AuthActionToken.token_hash == token_hash,
        AuthActionToken.purpose == "password_reset",
    ).with_for_update())
    now = datetime.now(timezone.utc)
    if row is None or row.consumed_at is not None or row.expires_at <= now:
        raise HTTPException(400, "Password reset link is invalid or expired")
    user = await db.scalar(select(User).where(User.id == row.user_id, User.is_active.is_(True)))
    if user is None:
        raise HTTPException(400, "Password reset link is invalid or expired")
    user.password_hash = hash_password(payload.new_password)
    row.consumed_at = now
    await db.execute(update(UserSession).where(
        UserSession.user_id == user.id,
        UserSession.revoked_at.is_(None),
    ).values(revoked_at=now))
    await db.execute(update(AuthActionToken).where(
        AuthActionToken.user_id == user.id,
        AuthActionToken.purpose == "password_reset",
        AuthActionToken.consumed_at.is_(None),
    ).values(consumed_at=now))
    await db.commit()
    return {"password_reset": True, "sessions_revoked": True}


@app.post("/v1/auth/login")
async def login_account(payload: AuthLoginRequest, db: AsyncSession = Depends(get_db), request: Request = None):
    client_ip = request.client.host if request and request.client else "unknown"
    await enforce_rate_limit(
        db,
        [f"login:ip:{client_ip}", f"login:identity:{client_ip}:{payload.email}"],
        settings.auth_login_limit,
        settings.auth_login_window_seconds,
    )
    user = await db.scalar(select(User).where(User.email == payload.email))
    if user is None or not user.is_active or not verify_password(payload.password, user.password_hash):
        raise HTTPException(401, "Invalid email or password", headers={"WWW-Authenticate": "Bearer"})
    if not user.is_email_verified:
        raise HTTPException(403, "Verify your email before signing in")
    access_token = create_access_token(user.id)
    refresh_token, session = _new_refresh_session(user.id)
    db.add(session)
    await db.commit()
    return {
        "user": {"id": str(user.id), "email": user.email},
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_type": "bearer",
        "expires_in": settings.auth_access_token_seconds,
    }


@app.post("/v1/auth/refresh")
async def refresh_account(payload: RefreshTokenRequest, db: AsyncSession = Depends(get_db)):
    token_hash = hash_refresh_token(payload.refresh_token)
    session = await db.scalar(
        select(UserSession).where(UserSession.refresh_token_hash == token_hash).with_for_update()
    )
    if session is None:
        raise HTTPException(401, "Invalid refresh token")
    now = datetime.now(timezone.utc)
    if session.revoked_at is not None:
        # Reuse of a rotated token compromises the whole session family.
        await db.execute(update(UserSession).where(
            UserSession.family_id == session.family_id,
            UserSession.revoked_at.is_(None),
        ).values(revoked_at=now))
        await db.commit()
        raise HTTPException(401, "Refresh token reuse detected; sign in again")
    if session.expires_at <= now:
        session.revoked_at = now
        await db.commit()
        raise HTTPException(401, "Refresh token expired; sign in again")
    user = await db.scalar(select(User).where(User.id == session.user_id, User.is_active.is_(True)))
    if user is None:
        session.revoked_at = now
        await db.commit()
        raise HTTPException(401, "User account is unavailable")
    session.revoked_at = now
    access_token = create_access_token(user.id)
    refresh_token, replacement = _new_refresh_session(user.id, session.family_id)
    db.add(replacement)
    await db.commit()
    return {
        "user": {"id": str(user.id), "email": user.email},
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_type": "bearer",
        "expires_in": settings.auth_access_token_seconds,
    }


@app.post("/v1/auth/logout")
async def logout_account(payload: RefreshTokenRequest, db: AsyncSession = Depends(get_db)):
    session = await db.scalar(
        select(UserSession).where(
            UserSession.refresh_token_hash == hash_refresh_token(payload.refresh_token)
        ).with_for_update()
    )
    if session is not None and session.revoked_at is None:
        now = datetime.now(timezone.utc)
        await db.execute(update(UserSession).where(
            UserSession.family_id == session.family_id,
            UserSession.revoked_at.is_(None),
        ).values(revoked_at=now))
        await db.commit()
    return {"revoked": True}


@app.get("/v1/auth/me")
async def get_authenticated_account(current_user: User = Depends(get_current_user)):
    return {"id": str(current_user.id), "email": current_user.email, "is_active": current_user.is_active, "is_email_verified": current_user.is_email_verified}

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


@app.get("/v1/projects/{project_id}/audit-log")
async def list_project_audit_events(
    project_id: UUID,
    db: AsyncSession = Depends(get_db),
    _owned_project: Project = Depends(require_owned_project),
):
    events = (await db.execute(
        select(ProjectAuditEvent)
        .where(ProjectAuditEvent.project_id == project_id)
        .order_by(ProjectAuditEvent.created_at.desc(), ProjectAuditEvent.id.desc())
    )).scalars().all()
    return [{
        "id": str(event.id),
        "actor_user_id": str(event.actor_user_id) if event.actor_user_id else None,
        "actor_email": event.actor_email,
        "target_user_id": str(event.target_user_id) if event.target_user_id else None,
        "target_email": event.target_email,
        "action": event.action,
        "previous_role": event.previous_role,
        "new_role": event.new_role,
        "created_at": event.created_at,
    } for event in events]


@app.post("/v1/projects/{project_id}/invitations", status_code=202)
async def create_project_invitation(
    project_id: UUID,
    payload: ProjectInvitationCreate,
    db: AsyncSession = Depends(get_db),
    _owned_project: Project = Depends(require_owned_project),
):
    if payload.email == (await db.scalar(select(User.email).where(User.id == _owned_project.owner_id))):
        raise HTTPException(409, "The project owner already has full access")
    raw = secrets.token_urlsafe(40)
    invitation = ProjectInvitation(
        project_id=project_id,
        inviter_user_id=_owned_project.owner_id,
        invited_email=payload.email,
        role=payload.role,
        token_hash=hashlib.sha256(raw.encode("utf-8")).hexdigest(),
        expires_at=datetime.now(timezone.utc) + timedelta(days=7),
    )
    db.add(invitation)
    await db.commit()
    await send_email(
        payload.email,
        "You are invited to collaborate in EDITFLOW AI",
        f"You were invited as {payload.role}. Sign in or create an account with this email, verify it, then accept the invitation using this link (valid for 7 days):\n"
        + _email_link("/accept-invitation", raw),
    )
    return {"message": "Invitation sent", "expires_in_seconds": 604800}


@app.post("/v1/invitations/accept")
async def accept_project_invitation(
    payload: ActionTokenRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if not current_user.is_email_verified:
        raise HTTPException(403, "Verify your email before accepting invitations")
    digest = hashlib.sha256(payload.token.encode("utf-8")).hexdigest()
    invitation = await db.scalar(select(ProjectInvitation).where(
        ProjectInvitation.token_hash == digest,
    ).with_for_update())
    now = datetime.now(timezone.utc)
    if (invitation is None or invitation.accepted_at is not None
        or invitation.revoked_at is not None or invitation.expires_at <= now):
        raise HTTPException(400, "Invitation is invalid or expired")
    if invitation.invited_email != current_user.email:
        raise HTTPException(403, "This invitation belongs to a different email address")
    project = await db.scalar(select(Project).where(Project.id == invitation.project_id))
    if project is None:
        raise HTTPException(404, "Project not found")
    if project.owner_id == current_user.id:
        raise HTTPException(409, "Project owner already has full access")
    member = await db.scalar(select(ProjectMember).where(
        ProjectMember.project_id == project.id,
        ProjectMember.user_id == current_user.id,
    ))
    previous_role = member.role if member is not None else None
    if member is None:
        member = ProjectMember(project_id=project.id, user_id=current_user.id, role=invitation.role)
        db.add(member)
        action = "member.added"
    elif member.role != invitation.role:
        member.role = invitation.role
        action = "member.role_changed"
    else:
        action = None
    if action:
        owner = await db.scalar(select(User).where(User.id == project.owner_id))
        db.add(ProjectAuditEvent(
            project_id=project.id,
            actor_user_id=project.owner_id,
            actor_email=owner.email if owner else "unknown",
            target_user_id=current_user.id,
            target_email=current_user.email,
            action=action,
            previous_role=previous_role,
            new_role=invitation.role,
        ))
    invitation.accepted_at = now
    await db.commit()
    return {"accepted": True, "project_id": str(project.id), "role": invitation.role}


@app.post("/v1/projects/{project_id}/members", status_code=200)
async def upsert_project_member(
    project_id: UUID,
    payload: ProjectMemberUpsert,
    db: AsyncSession = Depends(get_db),
    _owned_project: Project = Depends(require_owned_project),
):
    owner = await db.scalar(select(User).where(User.id == _owned_project.owner_id))
    user = await db.scalar(select(User).where(User.email == payload.email, User.is_active.is_(True)))
    if user is None:
        raise HTTPException(404, "An active account with this email was not found")
    if user.id == _owned_project.owner_id:
        raise HTTPException(409, "The project owner already has full access")
    member = await db.scalar(select(ProjectMember).where(
        ProjectMember.project_id == project_id,
        ProjectMember.user_id == user.id,
    ))
    previous_role = member.role if member is not None else None
    if member is None:
        member = ProjectMember(project_id=project_id, user_id=user.id, role=payload.role)
        db.add(member)
        action = "member.added"
    elif member.role != payload.role:
        member.role = payload.role
        action = "member.role_changed"
    else:
        action = None
    if action is not None:
        db.add(ProjectAuditEvent(
            project_id=project_id,
            actor_user_id=_owned_project.owner_id,
            actor_email=owner.email if owner else "unknown",
            target_user_id=user.id,
            target_email=user.email,
            action=action,
            previous_role=previous_role,
            new_role=payload.role,
        ))
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
    owner = await db.scalar(select(User).where(User.id == _owned_project.owner_id))
    member = await db.scalar(select(ProjectMember).where(
        ProjectMember.project_id == project_id,
        ProjectMember.user_id == member_user_id,
    ))
    if member is None:
        raise HTTPException(404, "Project member not found")
    target = await db.scalar(select(User).where(User.id == member_user_id))
    if target is None:
        raise HTTPException(404, "Project member not found")
    db.add(ProjectAuditEvent(
        project_id=project_id,
        actor_user_id=_owned_project.owner_id,
        actor_email=owner.email if owner else "unknown",
        target_user_id=target.id,
        target_email=target.email,
        action="member.removed",
        previous_role=member.role,
        new_role=None,
    ))
    await db.delete(member)
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
