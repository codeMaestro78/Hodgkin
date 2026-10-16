from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", case_sensitive=True)

    APP_ENV: Literal["development", "test", "staging", "production"] = "development"
    RESEARCH_LOG_LEVEL: Literal["INFO", "DEBUG"] = "INFO"
    DATABASE_SLOW_STATEMENT_MS: int = Field(default=1000, ge=100, le=60000)
    DATABASE_URL: str = "postgresql+psycopg://research_app:research_app@localhost:55432/research"
    DATABASE_ADMIN_URL: str | None = None
    DATABASE_POOL_SIZE: int = 5
    WORKER_CONCURRENCY: int = Field(default=2, ge=1, le=8)
    WORKER_LEASE_SECONDS: int = Field(default=60, ge=30, le=300)
    MAX_PENDING_RUNS_PER_TENANT: int = Field(default=32, ge=1, le=100)
    DISPATCHER_ENABLED: bool = True
    REDIS_URL: str = "redis://localhost:56379/0"
    SSE_REDIS_WAKEUPS_ENABLED: bool = True
    LLM_PROVIDER: Literal["openai"] = "openai"
    LLM_MODEL_NAME: str = "gpt-4o-mini"
    PROVIDER_MAX_ATTEMPTS: int = Field(default=3, ge=1, le=3)
    PROVIDER_TIMEOUT_SECONDS: float = Field(default=30, gt=0, le=120)
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
