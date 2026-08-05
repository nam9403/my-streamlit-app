from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Callable


def set_user_plan(*, conn_factory: Callable[[], Any], user_id: str, plan_id: str, now_iso: str) -> None:
    with conn_factory() as c:
        c.execute(
            """
            INSERT INTO users(user_id, plan_id, updated_at) VALUES (?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET plan_id=excluded.plan_id, updated_at=excluded.updated_at
            """,
            (user_id, plan_id, now_iso),
        )


def get_user_plan(*, conn_factory: Callable[[], Any], user_id: str) -> str | None:
    with conn_factory() as c:
        row = c.execute("SELECT plan_id FROM users WHERE user_id=?", (user_id,)).fetchone()
    if row is None:
        return None
    return str(row["plan_id"] or "")


def get_trial_state_row(*, conn_factory: Callable[[], Any], user_id: str) -> dict[str, Any] | None:
    with conn_factory() as c:
        row = c.execute(
            "SELECT trial_start_at, trial_end_at, trial_consumed FROM premium_trials WHERE user_id=?",
            (user_id,),
        ).fetchone()
    return dict(row) if row is not None else None


def upsert_trial_7d(*, conn_factory: Callable[[], Any], user_id: str, now_iso: str) -> None:
    now = datetime.now(timezone.utc)
    end_at = now + timedelta(days=7)
    with conn_factory() as c:
        c.execute(
            """
            INSERT INTO premium_trials(user_id, trial_start_at, trial_end_at, trial_consumed, updated_at)
            VALUES (?, ?, ?, 1, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                trial_start_at=excluded.trial_start_at,
                trial_end_at=excluded.trial_end_at,
                trial_consumed=1,
                updated_at=excluded.updated_at
            """,
            (user_id, now.isoformat(), end_at.isoformat(), now_iso),
        )


def record_usage(*, conn_factory: Callable[[], Any], user_id: str, feature: str, count: int) -> None:
    day = datetime.now(timezone.utc).date().isoformat()
    with conn_factory() as c:
        c.execute(
            """
            INSERT INTO usage_daily(user_id, usage_date, feature, count) VALUES (?, ?, ?, ?)
            ON CONFLICT(user_id, usage_date, feature) DO UPDATE SET count = usage_daily.count + excluded.count
            """,
            (user_id, day, feature, int(count)),
        )


def get_usage_today(*, conn_factory: Callable[[], Any], user_id: str, feature: str) -> int:
    day = datetime.now(timezone.utc).date().isoformat()
    with conn_factory() as c:
        row = c.execute(
            "SELECT count FROM usage_daily WHERE user_id=? AND usage_date=? AND feature=?",
            (user_id, day, feature),
        ).fetchone()
    return int(row["count"]) if row else 0
