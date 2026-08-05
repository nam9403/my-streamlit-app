from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path


def _conn_factory(db_path: Path):
    def _conn() -> sqlite3.Connection:
        c = sqlite3.connect(db_path)
        c.row_factory = sqlite3.Row
        return c

    return _conn


def test_get_admin_kpi_enriched_includes_queue_observability(tmp_path: Path) -> None:
    import core.admin_runtime_service as ars

    db_path = tmp_path / "state.db"
    conn_factory = _conn_factory(db_path)

    # Minimal tables required by analytics + notification observability.
    with conn_factory() as c:
        c.executescript(
            """
            CREATE TABLE users (user_id TEXT PRIMARY KEY, plan_id TEXT NOT NULL, updated_at TEXT NOT NULL);
            CREATE TABLE alerts (id TEXT PRIMARY KEY, user_id TEXT NOT NULL, symbol TEXT NOT NULL, type TEXT NOT NULL, threshold REAL NOT NULL, note TEXT NOT NULL, created_at TEXT NOT NULL);
            CREATE TABLE holdings (user_id TEXT NOT NULL, symbol TEXT NOT NULL, quantity REAL NOT NULL, avg_cost REAL NOT NULL, updated_at TEXT NOT NULL, PRIMARY KEY(user_id,symbol));
            CREATE TABLE decisions (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id TEXT NOT NULL, symbol TEXT NOT NULL, side TEXT NOT NULL, entry_price REAL NOT NULL, stop_loss REAL NOT NULL, take_profit REAL NOT NULL, thesis TEXT NOT NULL DEFAULT '', horizon_days INTEGER NOT NULL DEFAULT 30, created_at TEXT NOT NULL);
            CREATE TABLE trades (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id TEXT NOT NULL, decision_id INTEGER, symbol TEXT NOT NULL, side TEXT NOT NULL DEFAULT 'LONG', quantity REAL NOT NULL, entry_price REAL NOT NULL, entry_fee REAL NOT NULL DEFAULT 0, entry_note TEXT NOT NULL DEFAULT '', opened_at TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'OPEN', exit_price REAL, exit_fee REAL, exit_note TEXT, closed_at TEXT);
            CREATE TABLE events (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id TEXT NOT NULL, ts TEXT NOT NULL, event TEXT NOT NULL, meta_json TEXT NOT NULL DEFAULT '{}');
            CREATE TABLE notification_queue (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id TEXT NOT NULL, kind TEXT NOT NULL, payload_json TEXT NOT NULL, attempts INTEGER NOT NULL DEFAULT 0, status TEXT NOT NULL DEFAULT 'pending', last_error TEXT NOT NULL DEFAULT '', next_retry_at TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
            """
        )
    now = datetime.now(timezone.utc).isoformat()
    with conn_factory() as c:
        c.execute(
            """
            INSERT INTO notification_queue(user_id, kind, payload_json, attempts, status, last_error, next_retry_at, created_at, updated_at)
            VALUES (?, ?, ?, 4, 'failed', 'smtp_text:timeout', ?, ?, ?)
            """,
            ("u1", "text", "{}", now, now, now),
        )

    admin = ars.get_admin_kpi_enriched(conn_factory=conn_factory, days=30)
    assert "notification_observability" in admin
    obs = admin["notification_observability"]
    assert isinstance(obs.get("fail_reasons"), list)
    assert isinstance(obs.get("retry_tiers"), list)
    assert isinstance(obs.get("runtime_health"), dict)
    assert float(obs["runtime_health"].get("high_retry_ratio") or 0.0) >= 0.0

