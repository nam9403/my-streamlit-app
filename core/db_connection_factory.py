from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

from core.db_runtime import DbRuntimeConfig


class PgCompatConnection:
    def __init__(self, conn: Any):
        self._conn = conn

    @staticmethod
    def _rewrite_sql(sql: str) -> str:
        # Keep repository SQL mostly unchanged by rewriting sqlite placeholders.
        return sql.replace("?", "%s")

    def execute(self, sql: str, params: Any = None) -> Any:
        if params is None:
            return self._conn.execute(sql)
        return self._conn.execute(self._rewrite_sql(sql), params)

    def executemany(self, sql: str, params_seq: Any) -> Any:
        return self._conn.executemany(self._rewrite_sql(sql), params_seq)

    def __enter__(self) -> PgCompatConnection:
        self._conn.__enter__()
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> Any:
        return self._conn.__exit__(exc_type, exc, tb)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._conn, name)


def connect_runtime_db(config: DbRuntimeConfig, *, sqlite_default_path: Path) -> Any:
    if config.backend == "sqlite":
        db_path = config.sqlite_path or sqlite_default_path
        db_path.parent.mkdir(parents=True, exist_ok=True)
        c = sqlite3.connect(db_path)
        c.row_factory = sqlite3.Row
        return c

    if config.backend == "postgresql":
        import psycopg
        from psycopg.rows import dict_row

        conn = psycopg.connect(config.dsn, row_factory=dict_row)
        return PgCompatConnection(conn)

    raise RuntimeError(f"Unsupported DB backend: {config.backend}")

