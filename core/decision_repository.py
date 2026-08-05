from __future__ import annotations

from typing import Any, Callable


def insert_decision(
    *,
    conn_factory: Callable[[], Any],
    user_id: str,
    symbol: str,
    side: str,
    entry_price: float,
    stop_loss: float,
    take_profit: float,
    thesis: str,
    horizon_days: int,
    created_at: str,
) -> None:
    with conn_factory() as c:
        c.execute(
            """
            INSERT INTO decisions(user_id, symbol, side, entry_price, stop_loss, take_profit, thesis, horizon_days, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (user_id, symbol, side, entry_price, stop_loss, take_profit, thesis, horizon_days, created_at),
        )


def fetch_decisions(*, conn_factory: Callable[[], Any], user_id: str, limit: int) -> list[Any]:
    lim = max(1, min(int(limit or 100), 500))
    with conn_factory() as c:
        rows: list[Any] = c.execute(
            """
            SELECT id, symbol, side, entry_price, stop_loss, take_profit, thesis, horizon_days, created_at
            FROM decisions
            WHERE user_id=?
            ORDER BY id DESC
            LIMIT ?
            """,
            (user_id, lim),
        ).fetchall()
    return rows
