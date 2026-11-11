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
