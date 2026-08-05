from __future__ import annotations

import importlib.util
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping


@dataclass(frozen=True)
class DbRuntimeConfig:
    backend: str
    sqlite_path: Path | None = None
    dsn: str = ""


def resolve_db_runtime(
    *,
    root: Path,
    default_sqlite_path: Path,
    env: Mapping[str, str] | None = None,
) -> DbRuntimeConfig:
    values = env if env is not None else os.environ
    db_url = str(values.get("II_DB_URL") or "").strip()
    if not db_url:
        return DbRuntimeConfig(backend="sqlite", sqlite_path=default_sqlite_path)

    lower_url = db_url.lower()
    if lower_url.startswith("sqlite:///"):
        raw_path = db_url[10:]
        candidate = Path(raw_path)
        sqlite_path = candidate if candidate.is_absolute() else (root / candidate)
        return DbRuntimeConfig(backend="sqlite", sqlite_path=sqlite_path.resolve())

    if lower_url.startswith("postgres://") or lower_url.startswith("postgresql://"):
        return DbRuntimeConfig(backend="postgresql", dsn=db_url)

    raise ValueError(f"Unsupported II_DB_URL backend: {db_url}")


def require_sqlite_backend(config: DbRuntimeConfig) -> Path:
    if config.backend != "sqlite" or config.sqlite_path is None:
        raise RuntimeError(
            "Current runtime only supports sqlite connections. "
            "Set II_DB_URL to sqlite:///... or unset it."
        )
    return config.sqlite_path


def postgres_driver_available() -> bool:
    return importlib.util.find_spec("psycopg") is not None or importlib.util.find_spec("psycopg2") is not None

