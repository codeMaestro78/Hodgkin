import os
from logging.config import fileConfig
from pathlib import Path

from alembic import context
from dotenv import dotenv_values
from sqlalchemy import engine_from_config, pool

from research_api.config import get_settings
from research_api.db.assessments import ResearchAssessment  # noqa: F401
from research_api.db.models import Base
from research_api.db.source_relationships import SourceRelationship  # noqa: F401

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata
# Alembic must read the same service .env as the application. DATABASE_ADMIN_URL
# remains optional for deployments that use a distinct migration principal.
settings = get_settings()
private_migration_env = dotenv_values(Path(__file__).resolve().parents[4] / ".env.migrations")
database_url = (
    os.getenv("DATABASE_ADMIN_URL")
    or settings.DATABASE_ADMIN_URL
    or private_migration_env.get("DATABASE_ADMIN_URL")
    or settings.DATABASE_URL
)
config.set_main_option("sqlalchemy.url", database_url)


def run_migrations_offline() -> None:
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata, compare_type=True)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
