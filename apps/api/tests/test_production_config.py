import pytest

from app.config import settings, validate_production_settings


def _set_valid_production(monkeypatch):
    values = {
        "environment": "production",
        "auth_secret": "a" * 48,
        "email_public_url": "https://app.example.com",
        "email_smtp_host": "smtp.example.com",
        "email_smtp_port": 587,
        "email_smtp_username": "smtp-user",
        "email_smtp_password": "smtp-password",
        "email_from": "no-reply@example.com",
        "email_use_ssl": False,
        "email_starttls": True,
        "cors_origins": "https://app.example.com",
        "storage_backend": "s3",
        "s3_bucket": "editflow-production",
        "database_url": "postgresql+asyncpg://editflow:secret@db.example.com/editflow?ssl=require",
    }
    for key, value in values.items():
        monkeypatch.setattr(settings, key, value)


def test_production_configuration_accepts_secure_values(monkeypatch):
    _set_valid_production(monkeypatch)
    validate_production_settings()


@pytest.mark.parametrize(
    ("field", "value", "expected"),
    [
        ("auth_secret", "short", "EDITFLOW_AUTH_SECRET"),
        ("email_public_url", "http://app.example.com", "HTTPS"),
        ("email_starttls", False, "SMTP transport"),
        ("cors_origins", "*", "HTTPS origins"),
        ("storage_backend", "local", "S3-compatible"),
        ("database_url", "postgresql+asyncpg://u:p@localhost/db?ssl=require", "non-local"),
        ("database_url", "postgresql+asyncpg://u:p@db.example.com/db", "require TLS"),
    ],
)
def test_production_configuration_fails_closed(monkeypatch, field, value, expected):
    _set_valid_production(monkeypatch)
    monkeypatch.setattr(settings, field, value)
    with pytest.raises(RuntimeError, match=expected):
        validate_production_settings()


def test_development_configuration_does_not_require_production_secrets(monkeypatch):
    monkeypatch.setattr(settings, "environment", "development")
    monkeypatch.setattr(settings, "auth_secret", None)
    validate_production_settings()
