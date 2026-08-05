"""Alembic environment — reads II_DB_URL for PostgreSQL migrations."""

from __future__ import annotations

import os
from logging.config import fileConfig

from sqlalchemy import engine_from_config, pool

from alembic import context

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = None


def _database_url() -> str:
    url = str(os.environ.get("II_DB_URL") or "").strip()
    if not url:
        url = str(config.get_main_option("sqlalchemy.url") or "").strip()
    if not url or url.startswith("driver://"):
        raise RuntimeError(
            "Set II_DB_URL=postgresql://... before running alembic "
            "(or configure sqlalchemy.url in alembic.ini)."
        )
    # SQLAlchemy 2 prefers postgresql+psycopg:// for psycopg3
    if url.startswith("postgresql://") and "+psycopg" not in url and "+psycopg2" not in url:
        url = "postgresql+psycopg://" + url[len("postgresql://") :]
    return url


def run_migrations_offline() -> None:
    url = _database_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    configuration = config.get_section(config.config_ini_section) or {}
    configuration["sqlalchemy.url"] = _database_url()
    connectable = engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
