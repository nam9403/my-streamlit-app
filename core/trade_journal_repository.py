from __future__ import annotations

from typing import Any, Callable


def insert_trade(
    *,
    conn_factory: Callable[[], Any],
    user_id: str,
    decision_id: int | None,
    symbol: str,
    side: str,
    quantity: float,
    entry_price: float,
    entry_fee: float,
    entry_note: str,
    now_iso: str,
) -> None:
    with conn_factory() as c:
        c.execute(
            """
            INSERT INTO trades(user_id, decision_id, symbol, side, quantity, entry_price, entry_fee, entry_note, opened_at, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'OPEN')
            """,
            (user_id, decision_id, symbol, side, quantity, entry_price, entry_fee, entry_note, now_iso),
        )


def get_open_trade_row(*, conn_factory: Callable[[], Any], user_id: str, trade_id: int) -> Any:
    with conn_factory() as c:
        return c.execute(
            "SELECT id, quantity, entry_price FROM trades WHERE id=? AND user_id=? AND status='OPEN'",
            (trade_id, user_id),
        ).fetchone()


def close_trade_row(
    *,
    conn_factory: Callable[[], Any],
    user_id: str,
    trade_id: int,
    exit_price: float,
    exit_fee: float,
    exit_note: str,
    now_iso: str,
) -> None:
    with conn_factory() as c:
        c.execute(
            """
            UPDATE trades
            SET status='CLOSED', exit_price=?, exit_fee=?, exit_note=?, closed_at=?
            WHERE id=? AND user_id=? AND status='OPEN'
            """,
            (exit_price, exit_fee, exit_note, now_iso, trade_id, user_id),
        )


def fetch_trades(*, conn_factory: Callable[[], Any], user_id: str, limit: int) -> list[Any]:
    cap = max(1, min(int(limit), 2000))
    with conn_factory() as c:
        rows: list[Any] = c.execute(
            """
            SELECT id, decision_id, symbol, side, quantity, entry_price, entry_fee, entry_note,
                   opened_at, status, exit_price, exit_fee, exit_note, closed_at
            FROM trades WHERE user_id=?
            ORDER BY id DESC LIMIT ?
            """,
            (user_id, cap),
        ).fetchall()
    return rows


def decision_exists(*, conn_factory: Callable[[], Any], user_id: str, decision_id: int) -> bool:
    with conn_factory() as c:
        d = c.execute("SELECT id FROM decisions WHERE id=? AND user_id=?", (decision_id, user_id)).fetchone()
    return d is not None

