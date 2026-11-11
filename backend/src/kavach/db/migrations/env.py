"""Alembic environment: migrations run only as the migration-owner role."""

import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import create_engine, pool
from sqlalchemy.engine import make_url

from kavach.db.models import Base

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name, disable_existing_loggers=False)

target_metadata = Base.metadata


def migration_url() -> str:
    # Tests pass the URL programmatically; operators use the environment. Never alembic.ini.
    url = config.attributes.get("database_url") or os.environ.get("MIGRATION_DATABASE_URL")
    if not url:
        raise RuntimeError("Set MIGRATION_DATABASE_URL to the migration-owner connection URL")
    if make_url(url).drivername != "postgresql+psycopg":
        raise RuntimeError("MIGRATION_DATABASE_URL must use the postgresql+psycopg scheme")
    return url


def run_migrations_offline() -> None:
    context.configure(
        url=migration_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    engine = create_engine(
        migration_url(),
        poolclass=pool.NullPool,
        hide_parameters=True,
        connect_args={"connect_timeout": 5, "application_name": "kavach-migrations"},
    )
    with engine.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            compare_server_default=True,
            transaction_per_migration=True,
        )
        with context.begin_transaction():
            context.run_migrations()
    engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
