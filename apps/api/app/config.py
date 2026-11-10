from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str = "postgresql+asyncpg://editflow:editflow@localhost:5432/editflow"
    api_title: str = "EDITFLOW AI API"
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
