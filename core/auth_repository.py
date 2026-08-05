from __future__ import annotations

from typing import Any, Callable


def get_pin_hash(*, conn_factory: Callable[[], Any], user_id: str) -> str | None:
    with conn_factory() as c:
        row = c.execute("SELECT pin_hash FROM auth_users WHERE user_id=?", (user_id,)).fetchone()
    if row is None:
        return None
    return str(row["pin_hash"] or "")


def has_auth_user(*, conn_factory: Callable[[], Any], user_id: str) -> bool:
    with conn_factory() as c:
        return c.execute("SELECT 1 FROM auth_users WHERE user_id=?", (user_id,)).fetchone() is not None


def insert_auth_user(
    *,
    conn_factory: Callable[[], Any],
    user_id: str,
    pin_hash: str,
    now_iso: str,
) -> None:
    with conn_factory() as c:
        c.execute(
            "INSERT INTO auth_users(user_id, pin_hash, created_at, updated_at) VALUES (?, ?, ?, ?)",
            (user_id, pin_hash, now_iso, now_iso),
        )


def upsert_auth_user(
    *,
    conn_factory: Callable[[], Any],
    user_id: str,
    pin_hash: str,
    now_iso: str,
) -> None:
    with conn_factory() as c:
        c.execute(
            """
            INSERT INTO auth_users(user_id, pin_hash, created_at, updated_at) VALUES (?, ?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET pin_hash=excluded.pin_hash, updated_at=excluded.updated_at
            """,
            (user_id, pin_hash, now_iso, now_iso),
        )
