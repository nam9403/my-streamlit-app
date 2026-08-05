from __future__ import annotations

from typing import Any, Callable


def insert_forecast_record(
    *,
    conn_factory: Callable[[], Any],
    user_id: str,
    symbol: str,
    created_at: str,
    horizon_days: int,
    base_price: float,
    expected_price: float,
    expected_return_pct: float,
) -> None:
    with conn_factory() as c:
        c.execute(
            """
            INSERT INTO forecast_records(
                user_id, symbol, created_at, horizon_days, base_price, expected_price, expected_return_pct, status
            ) VALUES (?, ?, ?, ?, ?, ?, ?, 'pending')
            """,
            (user_id, symbol, created_at, horizon_days, base_price, expected_price, expected_return_pct),
        )
        c.execute(
            """
            DELETE FROM forecast_records
            WHERE id IN (
                SELECT id FROM forecast_records
                WHERE user_id=? AND symbol=?
                ORDER BY id DESC LIMIT -1 OFFSET 1000
            )
            """,
            (user_id, symbol),
        )


def fetch_pending_forecasts(*, conn_factory: Callable[[], Any], user_id: str, symbol: str, limit: int = 80) -> list[Any]:
    with conn_factory() as c:
        rows: list[Any] = c.execute(
            """
            SELECT id, created_at, horizon_days, base_price, expected_price
            FROM forecast_records
            WHERE user_id=? AND symbol=? AND status='pending'
            ORDER BY id ASC LIMIT ?
            """,
            (user_id, symbol, int(limit)),
        ).fetchall()
    return rows


def mark_forecast_resolved(
    *,
    conn_factory: Callable[[], Any],
    row_id: int,
    realized_price: float,
    realized_return_pct: float,
    abs_error_pct: float,
    direction_hit: int,
) -> None:
    with conn_factory() as c:
        c.execute(
            """
            UPDATE forecast_records
            SET realized_price=?, realized_return_pct=?, abs_error_pct=?, direction_hit=?, status='resolved'
            WHERE id=?
            """,
            (realized_price, realized_return_pct, abs_error_pct, direction_hit, int(row_id)),
        )


def fetch_forecast_rows_by_symbol(
    *,
    conn_factory: Callable[[], Any],
    user_id: str,
    symbol: str,
    since_iso: str,
    limit: int,
) -> list[Any]:
    with conn_factory() as c:
        rows: list[Any] = c.execute(
            """
            SELECT created_at, horizon_days, base_price, expected_price, expected_return_pct,
                   realized_price, realized_return_pct, abs_error_pct, direction_hit, status
            FROM forecast_records
            WHERE user_id=? AND symbol=? AND created_at>=?
            ORDER BY created_at DESC LIMIT ?
            """,
            (user_id, symbol, since_iso, int(limit)),
        ).fetchall()
    return rows


def fetch_resolved_rows_for_benchmark(
    *,
    conn_factory: Callable[[], Any],
    user_id: str,
    symbol: str,
    since_iso: str,
    limit: int,
) -> list[Any]:
    with conn_factory() as c:
        rows: list[Any] = c.execute(
            """
            SELECT horizon_days, expected_return_pct, realized_return_pct, abs_error_pct, direction_hit, status
            FROM forecast_records
            WHERE user_id=? AND symbol=? AND created_at>=?
            ORDER BY created_at DESC LIMIT ?
            """,
            (user_id, symbol, since_iso, int(limit)),
        ).fetchall()
    return rows


def fetch_resolved_rows_for_leaderboard(
    *,
    conn_factory: Callable[[], Any],
    user_id: str,
    since_iso: str,
    limit: int,
) -> list[Any]:
    with conn_factory() as c:
        rows: list[Any] = c.execute(
            """
            SELECT symbol, expected_return_pct, realized_return_pct, abs_error_pct, direction_hit
            FROM forecast_records
            WHERE user_id=? AND status='resolved' AND created_at>=?
            ORDER BY created_at DESC LIMIT ?
            """,
            (user_id, since_iso, int(limit)),
        ).fetchall()
    return rows


def fetch_resolved_rows_for_dashboard(
    *,
    conn_factory: Callable[[], Any],
    user_id: str,
    since_iso: str,
    limit: int,
) -> list[Any]:
    with conn_factory() as c:
        rows: list[Any] = c.execute(
            """
            SELECT created_at, expected_return_pct, realized_return_pct, abs_error_pct, direction_hit
            FROM forecast_records
            WHERE user_id=? AND status='resolved' AND created_at>=?
            ORDER BY created_at DESC LIMIT ?
            """,
            (user_id, since_iso, int(limit)),
        ).fetchall()
    return rows


def fetch_resolved_rows_for_commercial_report(
    *,
    conn_factory: Callable[[], Any],
    user_id: str,
    since_iso: str,
    limit: int,
) -> list[Any]:
    with conn_factory() as c:
        rows: list[Any] = c.execute(
            """
            SELECT symbol, created_at, horizon_days, expected_return_pct, realized_return_pct, abs_error_pct, direction_hit
            FROM forecast_records
            WHERE user_id=? AND status='resolved' AND created_at>=?
            ORDER BY created_at DESC LIMIT ?
            """,
            (user_id, since_iso, int(limit)),
        ).fetchall()
    return rows


def fetch_group_benchmark_rows(
    *,
    conn_factory: Callable[[], Any],
    user_id: str,
    since_iso: str,
    symbols: list[str],
    limit: int,
) -> list[Any]:
    placeholders = ",".join(["?"] * len(symbols))
    params: list[Any] = [user_id, since_iso, *symbols]
    with conn_factory() as c:
        rows: list[Any] = c.execute(
            f"""
            SELECT expected_return_pct, realized_return_pct, abs_error_pct, direction_hit
            FROM forecast_records
            WHERE user_id=? AND status='resolved' AND created_at>=? AND symbol IN ({placeholders})
            ORDER BY created_at DESC LIMIT {int(limit)}
            """,
            tuple(params),
        ).fetchall()
    return rows


def fetch_resolved_drift_rows(
    *,
    conn_factory: Callable[[], Any],
    user_id: str,
    symbol: str,
    limit: int = 400,
) -> list[Any]:
    with conn_factory() as c:
        rows: list[Any] = c.execute(
            """
            SELECT direction_hit, abs_error_pct
            FROM forecast_records
            WHERE user_id=? AND symbol=? AND status='resolved'
            ORDER BY created_at DESC LIMIT ?
            """,
            (user_id, symbol, int(limit)),
        ).fetchall()
    return rows
