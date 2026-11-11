import pytest
from uuid import uuid4

from app.auth import create_access_token, decode_access_token, hash_password, verify_password


def test_password_hash_uses_salted_pbkdf2_and_verifies():
    encoded = hash_password("correct horse battery staple")
    assert encoded.startswith("pbkdf2_sha256$600000$")
    assert verify_password("correct horse battery staple", encoded)
    assert not verify_password("incorrect password", encoded)
    assert hash_password("correct horse battery staple") != encoded


def test_access_token_round_trip_and_tamper_detection(monkeypatch):
    from app.config import settings
    monkeypatch.setattr(settings, "auth_secret", "test-secret-that-is-long-enough-for-hmac-256")
    user_id = uuid4()
    token = create_access_token(user_id)
    assert decode_access_token(token) == user_id
    header, payload, signature = token.split(".")
    tampered = f"{header}.{payload}.{chr(ord(signature[0]) ^ 1)}{signature[1:]}"
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as error:
        decode_access_token(tampered)
    assert error.value.status_code == 401


def test_auth_secret_must_be_configured(monkeypatch):
    from app.config import settings
    from fastapi import HTTPException
    monkeypatch.setattr(settings, "auth_secret", None)
    with pytest.raises(HTTPException) as error:
        create_access_token(uuid4())
    assert error.value.status_code == 503


@pytest.mark.asyncio
async def test_register_and_login_issue_tokens_for_normalized_email(db_session, monkeypatch):
    from app.config import settings
    from app.main import register_account, login_account
    from app.schemas import AuthRegisterRequest, AuthLoginRequest

    monkeypatch.setattr(settings, "auth_secret", "test-secret-that-is-long-enough-for-hmac-256")
    monkeypatch.setattr(settings, "auth_access_token_seconds", 900)
    registered = await register_account(
        AuthRegisterRequest(email="  Editor@Example.com ", password="correct horse battery staple"),
        db_session,
    )
    assert registered["user"]["email"] == "editor@example.com"
    assert len(registered["refresh_token"]) >= 32
    assert registered["token_type"] == "bearer"
    assert registered["expires_in"] == 900
    assert decode_access_token(registered["access_token"]) == __import__("uuid").UUID(registered["user"]["id"])

    logged_in = await login_account(
        AuthLoginRequest(email="EDITOR@example.com", password="correct horse battery staple"),
        db_session,
    )
    assert logged_in["user"]["id"] == registered["user"]["id"]
    assert logged_in["refresh_token"] != registered["refresh_token"]
    assert decode_access_token(logged_in["access_token"]) == __import__("uuid").UUID(registered["user"]["id"])


@pytest.mark.asyncio
async def test_project_access_is_scoped_to_authenticated_owner(db_session):
    from uuid import uuid4
    from fastapi import HTTPException
    from app.main import require_owned_project
    from app.models import Project, User

    owner = User(email="owner@example.com", password_hash=hash_password("owner password long"))
    other = User(email="other@example.com", password_hash=hash_password("other password long"))
    db_session.add_all([owner, other])
    await db_session.flush()
    project = Project(title="Private project", owner_id=owner.id)
    db_session.add(project)
    await db_session.flush()

    assert await require_owned_project(
        project.id, db=db_session, current_user=owner
    ) is project

    with pytest.raises(HTTPException) as error:
        await require_owned_project(
            project.id, db=db_session, current_user=other
        )
    assert error.value.status_code == 404

    with pytest.raises(HTTPException) as missing:
        await require_owned_project(
            uuid4(), db=db_session, current_user=owner
        )
    assert missing.value.status_code == 404


@pytest.mark.asyncio
async def test_viewer_can_read_project_but_cannot_mutate(db_session):
    from uuid import uuid4
    from fastapi import HTTPException
    from app.main import require_project_access, require_project_editor
    from app.models import Project, ProjectMember, User

    owner = User(email="role-owner@example.com", password_hash=hash_password("owner password long"))
    viewer = User(email="role-viewer@example.com", password_hash=hash_password("viewer password long"))
    db_session.add_all([owner, viewer])
    await db_session.flush()
    project = Project(title="Viewer project", owner_id=owner.id)
    db_session.add(project)
    await db_session.flush()
    db_session.add(ProjectMember(project_id=project.id, user_id=viewer.id, role="viewer"))
    await db_session.flush()

    assert await require_project_access(
        project.id, db=db_session, current_user=viewer
    ) is project
    with pytest.raises(HTTPException) as error:
        await require_project_editor(
            project=project, db=db_session, current_user=viewer
        )
    assert error.value.status_code == 403


@pytest.mark.asyncio
async def test_editor_can_mutate_and_nonmember_cannot_access(db_session):
    from uuid import uuid4
    from fastapi import HTTPException
    from app.main import require_project_access, require_project_editor
    from app.models import Project, ProjectMember, User

    owner = User(email="editor-owner@example.com", password_hash=hash_password("owner password long"))
    editor = User(email="editor@example.com", password_hash=hash_password("editor password long"))
    outsider = User(email="outsider@example.com", password_hash=hash_password("outsider password long"))
    db_session.add_all([owner, editor, outsider])
    await db_session.flush()
    project = Project(title="Editor project", owner_id=owner.id)
    db_session.add(project)
    await db_session.flush()
    db_session.add(ProjectMember(project_id=project.id, user_id=editor.id, role="editor"))
    await db_session.flush()

    assert await require_project_editor(
        project=project, db=db_session, current_user=editor
    ) is project
    with pytest.raises(HTTPException) as error:
        await require_project_access(
            project.id, db=db_session, current_user=outsider
        )
    assert error.value.status_code == 404


@pytest.mark.asyncio
async def test_owner_can_assign_update_and_remove_project_member(db_session):
    from app.main import upsert_project_member, list_project_members, remove_project_member
    from app.models import Project, User
    from app.schemas import ProjectMemberUpsert

    owner = User(email="sharing-owner@example.com", password_hash=hash_password("owner password long"))
    member = User(email="sharing-user@example.com", password_hash=hash_password("member password long"))
    db_session.add_all([owner, member])
    await db_session.flush()
    project = Project(title="Shared project", owner_id=owner.id)
    db_session.add(project)
    await db_session.flush()

    assigned = await upsert_project_member(
        project.id,
        ProjectMemberUpsert(email=member.email, role="viewer"),
        db_session,
        _owned_project=project,
    )
    assert assigned["role"] == "viewer"

    updated = await upsert_project_member(
        project.id,
        ProjectMemberUpsert(email=member.email, role="editor"),
        db_session,
        _owned_project=project,
    )
    assert updated["role"] == "editor"

    members = await list_project_members(project.id, db_session, _owned_project=project)
    assert {item["role"] for item in members} == {"owner", "editor"}

    await remove_project_member(project.id, member.id, db_session, _owned_project=project)
    members = await list_project_members(project.id, db_session, _owned_project=project)
    assert [item["role"] for item in members] == ["owner"]


@pytest.mark.asyncio
async def test_refresh_token_rotation_and_reuse_revokes_session_family(db_session, monkeypatch):
    from app.config import settings
    from app.main import register_account, refresh_account
    from app.schemas import AuthRegisterRequest, RefreshTokenRequest
    from fastapi import HTTPException

    monkeypatch.setattr(settings, "auth_secret", "test-secret-that-is-long-enough-for-hmac-256")
    registered = await register_account(
        AuthRegisterRequest(email="rotate@example.com", password="rotation password long"),
        db_session,
    )
    rotated = await refresh_account(
        RefreshTokenRequest(refresh_token=registered["refresh_token"]),
        db_session,
    )
    assert rotated["refresh_token"] != registered["refresh_token"]
    assert decode_access_token(rotated["access_token"]) == __import__("uuid").UUID(rotated["user"]["id"])

    with pytest.raises(HTTPException) as reused:
        await refresh_account(
            RefreshTokenRequest(refresh_token=registered["refresh_token"]),
            db_session,
        )
    assert reused.value.status_code == 401

    with pytest.raises(HTTPException) as family_revoked:
        await refresh_account(
            RefreshTokenRequest(refresh_token=rotated["refresh_token"]),
            db_session,
        )
    assert family_revoked.value.status_code == 401


@pytest.mark.asyncio
async def test_logout_revokes_refresh_session_family(db_session, monkeypatch):
    from app.config import settings
    from app.main import register_account, logout_account, refresh_account
    from app.schemas import AuthRegisterRequest, RefreshTokenRequest
    from fastapi import HTTPException

    monkeypatch.setattr(settings, "auth_secret", "test-secret-that-is-long-enough-for-hmac-256")
    registered = await register_account(
        AuthRegisterRequest(email="logout@example.com", password="logout password long"),
        db_session,
    )
    result = await logout_account(
        RefreshTokenRequest(refresh_token=registered["refresh_token"]),
        db_session,
    )
    assert result == {"revoked": True}
    with pytest.raises(HTTPException) as revoked:
        await refresh_account(
            RefreshTokenRequest(refresh_token=registered["refresh_token"]),
            db_session,
        )
    assert revoked.value.status_code == 401


@pytest.mark.asyncio
async def test_auth_rate_limit_is_persistent_and_returns_retry_after(db_session, monkeypatch):
    from app.config import settings
    from app.rate_limit import enforce_rate_limit
    from app.models import RateLimitBucket
    from sqlalchemy import select
    from fastapi import HTTPException

    monkeypatch.setattr(settings, "auth_secret", "test-secret-that-is-long-enough-for-hmac-256")
    await enforce_rate_limit(db_session, ["login:ip:203.0.113.10"], 2, 900)
    await enforce_rate_limit(db_session, ["login:ip:203.0.113.10"], 2, 900)

    with pytest.raises(HTTPException) as limited:
        await enforce_rate_limit(db_session, ["login:ip:203.0.113.10"], 2, 900)
    assert limited.value.status_code == 429
    assert int(limited.value.headers["Retry-After"]) > 0

    rows = (await db_session.execute(select(RateLimitBucket))).scalars().all()
    assert len(rows) == 1
    assert rows[0].scope_key != "login:ip:203.0.113.10"
    assert rows[0].request_count == 3


@pytest.mark.asyncio
async def test_auth_rate_limits_are_isolated_by_scope(db_session, monkeypatch):
    from app.config import settings
    from app.rate_limit import enforce_rate_limit

    monkeypatch.setattr(settings, "auth_secret", "test-secret-that-is-long-enough-for-hmac-256")
    await enforce_rate_limit(db_session, ["login:ip:203.0.113.11"], 1, 900)
    await enforce_rate_limit(db_session, ["login:ip:203.0.113.12"], 1, 900)
