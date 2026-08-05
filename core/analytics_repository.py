from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any, Callable


def log_event(*, conn_factory: Callable[[], Any], user_id: str, event_type: str, meta: dict[str, Any], now_iso: str) -> None:
    with conn_factory() as c:
        c.execute(
            "INSERT INTO events(user_id, ts, event, meta_json) VALUES (?, ?, ?, ?)",
            (user_id, now_iso, str(event_type or "unknown"), json.dumps(meta or {}, ensure_ascii=False)),
        )
        c.execute(
            """
            DELETE FROM events
            WHERE id IN (
                SELECT id
                FROM (
                    SELECT id, ROW_NUMBER() OVER (ORDER BY id DESC) AS rn
                    FROM events
                    WHERE user_id=?
                ) ranked
                WHERE rn > 5000
            )
            """,
            (user_id,),
        )


def fetch_cx_kpi_rows(*, conn_factory: Callable[[], Any], days: int) -> tuple[Any, list[Any], list[Any]]:
    cap = max(1, min(int(days), 90))
    since_date = (datetime.now(timezone.utc).date() - timedelta(days=cap - 1)).isoformat()
    with conn_factory() as c:
        avg_row = c.execute(
            "SELECT AVG(score) AS avg_score, COUNT(*) AS n FROM cx_score_daily WHERE score_date>=?",
            (since_date,),
        ).fetchone()
        band_rows = c.execute(
            """
            SELECT band, COUNT(*) AS n
            FROM cx_score_daily
            WHERE score_date>=?
            GROUP BY band
            ORDER BY n DESC, band ASC
            """,
            (since_date,),
        ).fetchall()
        trend_rows = c.execute(
            """
            SELECT score_date, AVG(score) AS avg_score, COUNT(*) AS samples
            FROM cx_score_daily
            WHERE score_date>=?
            GROUP BY score_date
            ORDER BY score_date DESC
            """,
            (since_date,),
        ).fetchall()
    return avg_row, band_rows, trend_rows


def fetch_kpi_dashboard_rows(*, conn_factory: Callable[[], Any], user_id: str, days: int) -> tuple[list[Any], int, int, int]:
    since = (datetime.now(timezone.utc) - timedelta(days=max(1, int(days)))).isoformat()
    with conn_factory() as c:
        ev_rows = c.execute(
            "SELECT event, COUNT(*) AS n FROM events WHERE user_id=? AND ts>=? GROUP BY event",
            (user_id, since),
        ).fetchall()
        alerts_total = int(c.execute("SELECT COUNT(*) AS n FROM alerts WHERE user_id=?", (user_id,)).fetchone()["n"])
        holdings_total = int(c.execute("SELECT COUNT(*) AS n FROM holdings WHERE user_id=?", (user_id,)).fetchone()["n"])
        events_total = int(
            c.execute("SELECT COUNT(*) AS n FROM events WHERE user_id=? AND ts>=?", (user_id, since)).fetchone()["n"]
        )
    return ev_rows, alerts_total, holdings_total, events_total


def fetch_cohort_events(*, conn_factory: Callable[[], Any], user_id: str) -> tuple[list[Any], list[Any]]:
    now = datetime.now(timezone.utc)
    since7 = (now - timedelta(days=7)).isoformat()
    since30 = (now - timedelta(days=30)).isoformat()
    with conn_factory() as c:
        ev7 = c.execute("SELECT event, ts FROM events WHERE user_id=? AND ts>=?", (user_id, since7)).fetchall()
        ev30 = c.execute("SELECT event, ts FROM events WHERE user_id=? AND ts>=?", (user_id, since30)).fetchall()
    return ev7, ev30


def fetch_admin_kpi_rows(*, conn_factory: Callable[[], Any], days: int) -> tuple[int, int, int, int, int, int, int, list[Any], list[Any], list[Any]]:
    since = (datetime.now(timezone.utc) - timedelta(days=max(1, int(days)))).isoformat()
    with conn_factory() as c:
        users = int(c.execute("SELECT COUNT(*) AS n FROM users").fetchone()["n"])
        alerts = int(c.execute("SELECT COUNT(*) AS n FROM alerts").fetchone()["n"])
        holdings = int(c.execute("SELECT COUNT(*) AS n FROM holdings").fetchone()["n"])
        decisions = int(c.execute("SELECT COUNT(*) AS n FROM decisions").fetchone()["n"])
        trades = int(c.execute("SELECT COUNT(*) AS n FROM trades").fetchone()["n"])
        events = int(c.execute("SELECT COUNT(*) AS n FROM events WHERE ts>=?", (since,)).fetchone()["n"])
        active_users = int(c.execute("SELECT COUNT(DISTINCT user_id) AS n FROM events WHERE ts>=?", (since,)).fetchone()["n"])
        plan_rows = c.execute("SELECT plan_id, COUNT(*) AS n FROM users GROUP BY plan_id").fetchall()
        ev_rows = c.execute("SELECT event, COUNT(*) AS n FROM events WHERE ts>=? GROUP BY event", (since,)).fetchall()
        q_rows = c.execute("SELECT status, COUNT(*) AS n FROM notification_queue GROUP BY status ORDER BY status ASC").fetchall()
    return users, alerts, holdings, decisions, trades, events, active_users, plan_rows, ev_rows, q_rows


def fetch_upgrade_funnel_events(*, conn_factory: Callable[[], Any], days: int) -> list[Any]:
    since = (datetime.now(timezone.utc) - timedelta(days=max(1, int(days)))).isoformat()
    with conn_factory() as c:
        rows: list[Any] = c.execute(
            """
            SELECT event, meta_json
            FROM events
            WHERE ts>=?
              AND event IN ('upgrade_prompt_view','upgrade_info_click','upgrade_cta_click','upgrade_success')
            """,
            (since,),
        ).fetchall()
    return rows
