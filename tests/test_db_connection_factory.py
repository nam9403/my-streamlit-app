from __future__ import annotations

import sqlite3
from pathlib import Path

from core.db_connection_factory import connect_runtime_db
from core.db_runtime import DbRuntimeConfig


def test_connect_runtime_db_sqlite_returns_sqlite_connection(tmp_path: Path) -> None:
    cfg = DbRuntimeConfig(backend="sqlite", sqlite_path=tmp_path / "state.db")
    conn = connect_runtime_db(cfg, sqlite_default_path=tmp_path / "fallback.db")
    try:
        assert isinstance(conn, sqlite3.Connection)
        row = conn.execute("SELECT 1 AS n").fetchone()
        assert int(row["n"]) == 1
    finally:
        conn.close()

