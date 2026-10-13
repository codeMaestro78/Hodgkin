from functools import lru_cache
from typing import Literal

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", case_sensitive=True)

    APP_ENV: Literal["development", "test", "staging", "production"] = "development"
    DATABASE_URL: str = "postgresql+psycopg://research_app:research_app@localhost:55432/research"
    DATABASE_ADMIN_URL: str | None = None
    DATABASE_POOL_SIZE: int = 5
    REDIS_URL: str = "redis://localhost:56379/0"
    LLM_PROVIDER: Literal["openai"] = "openai"
    LLM_MODEL_NAME: str = "gpt-4o-mini"
    OPENAI_API_KEY: SecretStr | None = None
    TAVILY_API_KEY: SecretStr | None = None
    OBJECT_STORAGE_ENDPOINT: str = "http://localhost:54566"
    OBJECT_STORAGE_BUCKET: str = "research-artifacts"
    OBJECT_STORAGE_ACCESS_KEY: SecretStr = SecretStr("test")
    OBJECT_STORAGE_SECRET_KEY: SecretStr = SecretStr("test")
    OBJECT_STORAGE_REGION: str = "us-east-1"
    ARTIFACT_RETENTION_DAYS: int = 30
    INTERNAL_SERVICE_AUTH: SecretStr | None = None
    SUPABASE_URL: str | None = None
    SUPABASE_PUBLISHABLE_KEY: str | None = None
    DEVELOPMENT_TENANT_ID: str | None = None
    DEVELOPMENT_USER_ID: str | None = None


@lru_cache
def get_settings() -> Settings:
    return Settings()
