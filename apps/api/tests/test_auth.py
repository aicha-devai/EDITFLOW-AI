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
    tampered = f"{header}.{payload[:-1]}{'A' if payload[-1] != 'A' else 'B'}.{signature}"
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
    assert registered["token_type"] == "bearer"
    assert registered["expires_in"] == 900
    assert decode_access_token(registered["access_token"]) == __import__("uuid").UUID(registered["user"]["id"])

    logged_in = await login_account(
        AuthLoginRequest(email="EDITOR@example.com", password="correct horse battery staple"),
        db_session,
    )
    assert logged_in["user"]["id"] == registered["user"]["id"]
    assert decode_access_token(logged_in["access_token"]) == __import__("uuid").UUID(registered["user"]["id"])


@pytest.mark.asyncio
async def test_project_access_is_scoped_to_authenticated_owner():
    from types import SimpleNamespace
    from uuid import uuid4
    from fastapi import HTTPException
    from app.main import require_owned_project

    owner_id, other_id, project_id = uuid4(), uuid4(), uuid4()
    project = SimpleNamespace(id=project_id, owner_id=owner_id)

    class OwnershipDB:
        async def scalar(self, statement):
            return project if owner_id == requested_owner else None

    requested_owner = owner_id
    assert await require_owned_project(project_id, db=OwnershipDB(), current_user=SimpleNamespace(id=owner_id)) is project

    requested_owner = other_id
    with pytest.raises(HTTPException) as error:
        await require_owned_project(project_id, db=OwnershipDB(), current_user=SimpleNamespace(id=other_id))
    assert error.value.status_code == 404
