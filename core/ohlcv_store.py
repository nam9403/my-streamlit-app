"""
Local SQLite store for daily OHLCV with incremental updates.
"""

from __future__ import annotations

import os
import sqlite3
from datetime import date, datetime, timezone
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "data" / "ohlcv_store.db"
_EPOCH = pd.Timestamp("1970-01-01")


def _max_rows_per_symbol() -> int:
    try:
        return max(800, int(os.environ.get("II_OHLCV_STORE_MAX_ROWS_PER_SYMBOL", "2600")))
    except ValueError:
        return 2600


def _to_day_int(ts: pd.Timestamp) -> int:
    t = pd.Timestamp(ts)
    if t.tzinfo is not None:
        t = t.tz_convert("UTC").tz_localize(None)
    return int((t.normalize() - _EPOCH).days)


def _day_int_to_date(day_int: int) -> pd.Timestamp:
    return _EPOCH + pd.Timedelta(days=int(day_int))


def _ensure_schema(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS ohlcv_daily (
            symbol TEXT NOT NULL,
            date_int INTEGER NOT NULL,
            open REAL NOT NULL,
            high REAL NOT NULL,
            low REAL NOT NULL,
            close REAL NOT NULL,
            volume REAL NOT NULL,
            source TEXT NOT NULL DEFAULT '',
            updated_at TEXT NOT NULL,
            PRIMARY KEY(symbol, date_int)
        ) WITHOUT ROWID
        """
    )
    cols = [str(r["name"]) for r in conn.execute("PRAGMA table_info(ohlcv_daily)").fetchall()]
    # One-time migration from old schema using TEXT date.
    if "date_int" in cols:
        return
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS ohlcv_daily_v2 (
            symbol TEXT NOT NULL,
            date_int INTEGER NOT NULL,
            open REAL NOT NULL,
            high REAL NOT NULL,
            low REAL NOT NULL,
            close REAL NOT NULL,
            volume REAL NOT NULL,
            source TEXT NOT NULL DEFAULT '',
            updated_at TEXT NOT NULL,
            PRIMARY KEY(symbol, date_int)
        ) WITHOUT ROWID
        """
    )
    conn.execute(
        """
        INSERT OR REPLACE INTO ohlcv_daily_v2(symbol, date_int, open, high, low, close, volume, source, updated_at)
        SELECT
            symbol,
            CAST((julianday(date) - 2440587.5) AS INTEGER) AS date_int,
            open, high, low, close, volume,
            source,
            updated_at
        FROM ohlcv_daily
        WHERE date IS NOT NULL
        """
    )
    conn.execute("DROP TABLE IF EXISTS ohlcv_daily")
    conn.execute("ALTER TABLE ohlcv_daily_v2 RENAME TO ohlcv_daily")


def _conn() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(DB_PATH)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA journal_mode=WAL")
    c.execute("PRAGMA synchronous=NORMAL")
    c.execute("PRAGMA temp_store=MEMORY")
    c.execute("PRAGMA cache_size=-12000")
    c.execute("PRAGMA auto_vacuum=INCREMENTAL")
    _ensure_schema(c)
    return c


def upsert_ohlcv(symbol: str, df: pd.DataFrame, source: str = "") -> int:
    if df is None or df.empty:
        return 0
    sym = (symbol or "").strip().upper()
    if not sym:
        return 0
    d = df.copy()
    d["date"] = pd.to_datetime(d["date"], errors="coerce")
    for col in ("open", "high", "low", "close", "volume"):
        d[col] = pd.to_numeric(d[col], errors="coerce")
    d = d.dropna(subset=["date", "open", "high", "low", "close", "volume"]).sort_values("date")
    if d.empty:
        return 0
    # P0: never persist structurally invalid bars
    bad = (
        (d["low"] <= 0)
        | (d["high"] < d["low"])
        | (d["close"] < d["low"])
        | (d["close"] > d["high"])
        | (d["volume"] < 0)
    )
    d = d.loc[~bad]
    if d.empty:
        return 0
    now = datetime.now(timezone.utc).isoformat()
    rows = [
        (
            sym,
            _to_day_int(pd.Timestamp(r["date"])),
            float(r["open"]),
            float(r["high"]),
            float(r["low"]),
            float(r["close"]),
            float(r["volume"]),
            str(source or ""),
            now,
        )
        for _, r in d.iterrows()
    ]
    with _conn() as c:
        c.executemany(
            """
            INSERT INTO ohlcv_daily(symbol, date_int, open, high, low, close, volume, source, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(symbol, date_int) DO UPDATE SET
                open=excluded.open, high=excluded.high, low=excluded.low,
                close=excluded.close, volume=excluded.volume,
                source=excluded.source, updated_at=excluded.updated_at
            """,
            rows,
        )
        c.execute(
            """
            DELETE FROM ohlcv_daily
            WHERE symbol=?
              AND date_int < (
                    SELECT COALESCE(MIN(date_int), -999999)
                    FROM (
                        SELECT date_int
                        FROM ohlcv_daily
                        WHERE symbol=?
                        ORDER BY date_int DESC
                        LIMIT ?
                    )
              )
            """,
            (sym, sym, _max_rows_per_symbol()),
        )
        c.execute("PRAGMA incremental_vacuum")
    return len(rows)


def load_recent_ohlcv(symbol: str, sessions: int = 80) -> pd.DataFrame:
    sym = (symbol or "").strip().upper()
    if not sym:
        return pd.DataFrame(columns=["date", "open", "high", "low", "close", "volume"])
    lim = max(50, int(sessions))
    with _conn() as c:
        rows = c.execute(
            """
            SELECT date_int, open, high, low, close, volume
            FROM ohlcv_daily
            WHERE symbol=?
            ORDER BY date_int DESC
            LIMIT ?
            """,
            (sym, lim),
        ).fetchall()
    if not rows:
        return pd.DataFrame(columns=["date", "open", "high", "low", "close", "volume"])
    d = pd.DataFrame([dict(r) for r in rows]).sort_values("date_int").reset_index(drop=True)
    d["date"] = d["date_int"].map(lambda x: _day_int_to_date(int(x)))
    d = d.drop(columns=["date_int"])
    return d.dropna(subset=["date"])


def last_ohlcv_date(symbol: str) -> str | None:
    sym = (symbol or "").strip().upper()
    if not sym:
        return None
    with _conn() as c:
        r = c.execute("SELECT MAX(date_int) AS d FROM ohlcv_daily WHERE symbol=?", (sym,)).fetchone()
    if not r or r["d"] is None:
        return None
    return str(_day_int_to_date(int(r["d"])).date())


def get_close_on_or_before(symbol: str, as_of: str | date | datetime | pd.Timestamp) -> tuple[float | None, str | None]:
    """
    Giá đóng cửa tại đúng ngày ``as_of`` hoặc phiên giao dịch gần nhất trước đó.

    Dùng cho nghiệm thu forecast (anti look-ahead): không bao giờ lấy giá \"hôm nay\"
    nếu due date nằm trong quá khứ.
    """
    sym = (symbol or "").strip().upper()
    if not sym:
        return None, None
    if isinstance(as_of, str):
        try:
            target = datetime.fromisoformat(as_of.replace("Z", "+00:00")).date()
        except ValueError:
            try:
                target = datetime.strptime(as_of[:10], "%Y-%m-%d").date()
            except ValueError:
                return None, None
    elif isinstance(as_of, datetime):
        target = as_of.date()
    elif isinstance(as_of, pd.Timestamp):
        if pd.isna(as_of):
            return None, None
        target = as_of.date()
    elif isinstance(as_of, date):
        target = as_of
    else:
        return None, None

    day_int = _to_day_int(pd.Timestamp(target))
    with _conn() as c:
        r = c.execute(
            """
            SELECT date_int, close
            FROM ohlcv_daily
            WHERE symbol=? AND date_int<=?
            ORDER BY date_int DESC
            LIMIT 1
            """,
            (sym, day_int),
        ).fetchone()
    if not r:
        return None, None
    close = float(r["close"] or 0.0)
    if close <= 0:
        return None, None
    return close, str(_day_int_to_date(int(r["date_int"])).date())


def top_symbols_by_avg_volume(
    *,
    limit: int = 400,
    sessions: int = 20,
    min_sessions: int = 5,
    candidates: list[str] | None = None,
) -> list[tuple[str, float]]:
    """Rank symbols by average daily volume (recent sessions) — P3 dynamic liquid universe."""
    lim = max(1, min(int(limit), 2000))
    win = max(5, int(sessions))
    min_n = max(3, int(min_sessions))
    cand = [str(s).strip().upper() for s in (candidates or []) if str(s).strip()]
    with _conn() as c:
        max_row = c.execute("SELECT MAX(date_int) AS m FROM ohlcv_daily").fetchone()
        if not max_row or max_row["m"] is None:
            return []
        min_day = int(max_row["m"]) - win
        if cand:
            placeholders = ",".join("?" for _ in cand)
            rows = c.execute(
                f"""
                SELECT symbol, AVG(volume) AS avg_vol, COUNT(*) AS n
                FROM ohlcv_daily
                WHERE date_int >= ? AND symbol IN ({placeholders})
                GROUP BY symbol
                HAVING COUNT(*) >= ?
                ORDER BY avg_vol DESC
                LIMIT ?
                """,
                (min_day, *cand, min_n, lim),
            ).fetchall()
        else:
            rows = c.execute(
                """
                SELECT symbol, AVG(volume) AS avg_vol, COUNT(*) AS n
                FROM ohlcv_daily
                WHERE date_int >= ?
                GROUP BY symbol
                HAVING COUNT(*) >= ?
                ORDER BY avg_vol DESC
                LIMIT ?
                """,
                (min_day, min_n, lim),
            ).fetchall()
    out: list[tuple[str, float]] = []
    for r in rows:
        sym = str(r["symbol"] or "").upper()
        if not sym:
            continue
        try:
            out.append((sym, float(r["avg_vol"] or 0.0)))
        except (TypeError, ValueError):
            continue
    return out

