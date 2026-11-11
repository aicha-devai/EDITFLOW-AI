import pytest

from app.config import settings
from app.emailer import _send_sync


def test_emailer_refuses_plaintext_smtp(monkeypatch):
    monkeypatch.setattr(settings, "email_smtp_host", "smtp.example.com")
    monkeypatch.setattr(settings, "email_from", "no-reply@example.com")
    monkeypatch.setattr(settings, "email_use_ssl", False)
    monkeypatch.setattr(settings, "email_starttls", False)
    with pytest.raises(RuntimeError, match="secure SMTP transport"):
        _send_sync("person@example.com", "Test", "Body")


def test_emailer_requires_username_and_password_together(monkeypatch):
    monkeypatch.setattr(settings, "email_smtp_host", "smtp.example.com")
    monkeypatch.setattr(settings, "email_from", "no-reply@example.com")
    monkeypatch.setattr(settings, "email_use_ssl", False)
    monkeypatch.setattr(settings, "email_starttls", True)
    monkeypatch.setattr(settings, "email_smtp_username", "smtp-user")
    monkeypatch.setattr(settings, "email_smtp_password", None)
    with pytest.raises(RuntimeError, match="configured together"):
        _send_sync("person@example.com", "Test", "Body")
