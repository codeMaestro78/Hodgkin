import os
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from research_api.model_routing import ModelRole, ModelRoute


def configuration_file() -> str | None:
    """Use one repository environment regardless of the API launch directory."""
    explicit = os.environ.get("RESEARCH_ENV_FILE")
    if explicit is not None:
        return str(Path(explicit).expanduser().resolve()) if explicit else None
    if os.environ.get("APP_ENV") == "test":
        return None
    root = Path(__file__).resolve().parents[4]
    if (root / "pnpm-workspace.yaml").is_file():
        if (root / ".env").is_file():
            return str(root / ".env")
        return str(root / "services/research-api/.env")
    return ".env"


def configuration_files() -> tuple[str, ...]:
    """Keep service-only Auth settings, with root values taking precedence."""
    selected = configuration_file()
    if selected is None:
        return ()
    root = Path(__file__).resolve().parents[4]
    service = root / "services/research-api/.env"
    if (
        "RESEARCH_ENV_FILE" not in os.environ
        and selected == str(root / ".env")
        and service.is_file()
    ):
        return (str(service), selected)
    return (selected,)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=configuration_files(), extra="ignore", case_sensitive=True
    )

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
    LLM_PROVIDER: Literal["openai", "openrouter"] = "openai"
    LLM_MODEL_NAME: str = Field(default="gpt-4o-mini", min_length=1, max_length=200)
    LLM_PLANNER_PROVIDER: Literal["openai", "openrouter"] | None = None
    LLM_PLANNER_MODEL_NAME: str | None = Field(default=None, min_length=1, max_length=200)
    LLM_WRITER_PROVIDER: Literal["openai", "openrouter"] | None = None
    LLM_WRITER_MODEL_NAME: str | None = Field(default=None, min_length=1, max_length=200)
    LLM_CLAIM_REVIEW_PROVIDER: Literal["openai", "openrouter"] | None = None
    LLM_CLAIM_REVIEW_MODEL_NAME: str | None = Field(default=None, min_length=1, max_length=200)
    PROVIDER_MAX_ATTEMPTS: int = Field(default=3, ge=1, le=3)
    PROVIDER_TIMEOUT_SECONDS: float = Field(default=30, gt=0, le=120)
    MODEL_WRITER_TIMEOUT_SECONDS: float = Field(default=45, gt=0, le=120)
    OPENAI_API_KEY: SecretStr | None = None
    OPENROUTER_API_KEY: SecretStr | None = None
    TAVILY_API_KEY: SecretStr | None = None
    # New jobs only; queued/checkpointed runs retain their original discovery route.
    SERPER_DISCOVERY_ENABLED: bool = False
    SERPER_API_KEY: SecretStr | None = None
    # Opt-in for newly queued jobs; the job graph version pins this route.
    OPENALEX_DISCOVERY_ENABLED: bool = False
    OPENALEX_API_KEY: SecretStr | None = None
    # New explicit-mode runs keep bounded repair off unless this is explicitly enabled.
    BOUNDED_GAP_REPAIR_ENABLED: bool = False
    DISCOVERY_RETRY_AFTER_MAX_SECONDS: float = Field(default=5, ge=0, le=30)
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

    @field_validator(
        "OPENAI_API_KEY",
        "OPENROUTER_API_KEY",
        "TAVILY_API_KEY",
        "SERPER_API_KEY",
        "OPENALEX_API_KEY",
        "INTERNAL_SERVICE_AUTH",
        mode="before",
    )
    @classmethod
    def empty_optional_secrets_are_unset(cls, value: object) -> object:
        if isinstance(value, SecretStr):
            return value if value.get_secret_value().strip() else None
        if isinstance(value, str) and not value.strip():
            return None
        return value

    def model_route(self, role: ModelRole) -> ModelRoute:
        provider = getattr(self, f"LLM_{role.upper()}_PROVIDER") or self.LLM_PROVIDER
        model = getattr(self, f"LLM_{role.upper()}_MODEL_NAME") or self.LLM_MODEL_NAME
        return ModelRoute(provider=provider, model=model)

    def model_routing_snapshot(self) -> dict[str, dict[str, str]]:
        return {
            role: self.model_route(role).as_dict() for role in ("planner", "writer", "claim_review")
        }

    def legacy_model_routing_snapshot(self) -> dict[str, dict[str, str]]:
        route = ModelRoute(provider=self.LLM_PROVIDER, model=self.LLM_MODEL_NAME)
        return {role: route.as_dict() for role in ("planner", "writer", "claim_review")}

    def model_api_key(self, provider: Literal["openai", "openrouter"]) -> SecretStr | None:
        return self.OPENAI_API_KEY if provider == "openai" else self.OPENROUTER_API_KEY


@lru_cache
def get_settings() -> Settings:
    return Settings()
