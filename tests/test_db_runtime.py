from __future__ import annotations

from pathlib import Path

import pytest

from core.db_runtime import require_sqlite_backend, resolve_db_runtime


def test_resolve_db_runtime_defaults_to_sqlite(tmp_path: Path) -> None:
    cfg = resolve_db_runtime(root=tmp_path, default_sqlite_path=tmp_path / "data" / "app.db", env={})
    assert cfg.backend == "sqlite"
    assert cfg.sqlite_path == tmp_path / "data" / "app.db"


def test_resolve_db_runtime_supports_sqlite_url_relative_path(tmp_path: Path) -> None:
    cfg = resolve_db_runtime(
        root=tmp_path,
        default_sqlite_path=tmp_path / "default.db",
        env={"II_DB_URL": "sqlite:///data/new_state.db"},
    )
    assert cfg.backend == "sqlite"
    assert cfg.sqlite_path == (tmp_path / "data" / "new_state.db").resolve()


def test_resolve_db_runtime_supports_postgresql_dsn(tmp_path: Path) -> None:
    cfg = resolve_db_runtime(
        root=tmp_path,
        default_sqlite_path=tmp_path / "default.db",
        env={"II_DB_URL": "postgresql://u:p@localhost:5432/app"},
    )
    assert cfg.backend == "postgresql"
    assert cfg.dsn.startswith("postgresql://")


def test_require_sqlite_backend_rejects_non_sqlite(tmp_path: Path) -> None:
    cfg = resolve_db_runtime(
        root=tmp_path,
        default_sqlite_path=tmp_path / "default.db",
        env={"II_DB_URL": "postgres://u:p@localhost:5432/app"},
    )
    with pytest.raises(RuntimeError):
        require_sqlite_backend(cfg)

