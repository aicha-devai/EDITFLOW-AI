from urllib.parse import urlsplit

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str = "postgresql+asyncpg://editflow:editflow@localhost:5432/editflow"
    api_title: str = "EDITFLOW AI API"
    environment: str = Field(default="development", validation_alias="EDITFLOW_ENV")
    auth_secret: str | None = Field(default=None, validation_alias="EDITFLOW_AUTH_SECRET")
    auth_access_token_seconds: int = Field(default=900, ge=300, le=3600, validation_alias="EDITFLOW_AUTH_ACCESS_TOKEN_SECONDS")
    auth_refresh_token_days: int = Field(default=30, ge=1, le=90, validation_alias="EDITFLOW_AUTH_REFRESH_TOKEN_DAYS")
    auth_login_limit: int = Field(default=10, ge=1, le=100, validation_alias="EDITFLOW_AUTH_LOGIN_LIMIT")
    auth_register_limit: int = Field(default=5, ge=1, le=50, validation_alias="EDITFLOW_AUTH_REGISTER_LIMIT")
    auth_login_window_seconds: int = Field(default=900, ge=60, le=86400, validation_alias="EDITFLOW_AUTH_LOGIN_WINDOW_SECONDS")
    auth_register_window_seconds: int = Field(default=3600, ge=60, le=86400, validation_alias="EDITFLOW_AUTH_REGISTER_WINDOW_SECONDS")
    email_smtp_host: str | None = Field(default=None, validation_alias="EDITFLOW_EMAIL_SMTP_HOST")
    email_smtp_port: int = Field(default=587, ge=1, le=65535, validation_alias="EDITFLOW_EMAIL_SMTP_PORT")
    email_smtp_username: str | None = Field(default=None, validation_alias="EDITFLOW_EMAIL_SMTP_USERNAME")
    email_smtp_password: str | None = Field(default=None, validation_alias="EDITFLOW_EMAIL_SMTP_PASSWORD")
    email_from: str | None = Field(default=None, validation_alias="EDITFLOW_EMAIL_FROM")
    email_use_ssl: bool = Field(default=False, validation_alias="EDITFLOW_EMAIL_USE_SSL")
    email_starttls: bool = Field(default=True, validation_alias="EDITFLOW_EMAIL_STARTTLS")
    email_public_url: str = Field(default="http://localhost:5173", validation_alias="EDITFLOW_EMAIL_PUBLIC_URL")
    storage_backend: str = Field(default="local", validation_alias="EDITFLOW_STORAGE_BACKEND")
    storage_root: str = Field(default="/var/lib/editflow", validation_alias="EDITFLOW_STORAGE_ROOT")
    s3_bucket: str | None = None
    s3_region: str = "us-east-1"
    s3_endpoint_url: str | None = None
    s3_access_key_id: str | None = None
    s3_secret_access_key: str | None = None
    evidence_asr_api_key: str | None = Field(default=None, validation_alias="EDITFLOW_ASR_API_KEY")
    evidence_asr_endpoint: str = Field(
        default="https://api.openai.com/v1/audio/transcriptions",
        validation_alias="EDITFLOW_ASR_ENDPOINT",
    )
    evidence_asr_model: str = Field(default="whisper-1", validation_alias="EDITFLOW_ASR_MODEL")
    evidence_vision_api_key: str | None = Field(default=None, validation_alias="EDITFLOW_VISION_API_KEY")
    evidence_vision_endpoint: str = Field(
        default="https://api.openai.com/v1/chat/completions",
        validation_alias="EDITFLOW_VISION_ENDPOINT",
    )
    evidence_vision_model: str = Field(default="gpt-4o-mini", validation_alias="EDITFLOW_VISION_MODEL")
    evidence_extraction_timeout_seconds: int = Field(
        default=900, ge=30, le=3600, validation_alias="EDITFLOW_EVIDENCE_TIMEOUT_SECONDS"
    )
    cors_origins: str = Field(
        default="http://localhost:5173,http://127.0.0.1:5173,http://localhost:4173,http://127.0.0.1:4173",
        validation_alias="EDITFLOW_CORS_ORIGINS",
    )

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()


def validate_production_settings() -> None:
    """Fail closed when a production deployment is missing security-critical settings."""
    if settings.environment.strip().lower() not in {"production", "prod"}:
        return

    problems: list[str] = []
    if not settings.auth_secret or len(settings.auth_secret.encode("utf-8")) < 32:
        problems.append("EDITFLOW_AUTH_SECRET must contain at least 32 characters")

    public_url = urlsplit(settings.email_public_url)
    if public_url.scheme != "https" or not public_url.hostname or public_url.username or public_url.password:
        problems.append("EDITFLOW_EMAIL_PUBLIC_URL must be an HTTPS origin")
    if not settings.email_smtp_host or not settings.email_from:
        problems.append("SMTP host and sender address must be configured")
    if settings.email_use_ssl == settings.email_starttls:
        problems.append("Configure exactly one SMTP transport mode: SSL or STARTTLS")
    if not settings.email_smtp_username or not settings.email_smtp_password:
        problems.append("SMTP username and password must both be configured")

    origins = [item.strip() for item in settings.cors_origins.split(",") if item.strip()]
    if not origins:
        problems.append("EDITFLOW_CORS_ORIGINS must contain the production frontend origin")
    for origin in origins:
        parsed = urlsplit(origin)
        if parsed.scheme != "https" or not parsed.hostname or parsed.hostname in {"localhost", "127.0.0.1", "::1"} or "*" in origin:
            problems.append("EDITFLOW_CORS_ORIGINS must contain only explicit HTTPS origins")
            break

    if settings.storage_backend.strip().lower() != "s3" or not settings.s3_bucket:
        problems.append("Production storage must use S3-compatible object storage with S3_BUCKET configured")

    db_url = urlsplit(settings.database_url)
    if not db_url.hostname or db_url.hostname in {"localhost", "127.0.0.1", "::1"}:
        problems.append("DATABASE_URL must point to a non-local production database")

    if problems:
        raise RuntimeError("Production configuration rejected: " + "; ".join(problems))
