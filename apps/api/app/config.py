from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    database_url: str = "postgresql+asyncpg://editflow:editflow@localhost:5432/editflow"
    api_title: str = "EDITFLOW AI API"
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

settings = Settings()
