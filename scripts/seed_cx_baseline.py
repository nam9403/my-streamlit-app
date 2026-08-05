#!/usr/bin/env python3
"""
Seed baseline CX daily scores for staging/demo environments.

Idempotent behavior:
- Uses upsert_daily_cx_score, so rerun updates same (user_id, score_date) rows.

Usage:
  python scripts/seed_cx_baseline.py
  python scripts/seed_cx_baseline.py --users demo_a,demo_b --days 14 --base-score 78 --spread 8
"""
from __future__ import annotations

import argparse
import hashlib
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core import product_layer as pl  # noqa: E402


def _band_for_score(score: int) -> str:
    if score >= 90:
        return "Elite"
    if score >= 75:
        return "Good"
    if score >= 60:
        return "Needs tuning"
    return "Risk"


def _stable_noise(user_id: str, score_date: str, spread: int) -> int:
    if spread <= 0:
        return 0
    key = f"{user_id}|{score_date}".encode()
    digest = hashlib.sha256(key).hexdigest()
    val = int(digest[:8], 16)
    # Map into [-spread, +spread]
    return (val % (2 * spread + 1)) - spread


def _upsert_cx_runtime(*, user_id: str, score_date: str, score: int, band: str, updated_at: str) -> None:
    backend = str(pl._db_backend()).strip().lower()
    if backend == "postgresql":
        sql = """
            INSERT INTO cx_score_daily(user_id, score_date, score, band, updated_at)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT(user_id, score_date)
            DO UPDATE SET score=excluded.score, band=excluded.band, updated_at=excluded.updated_at
        """
    else:
        sql = """
            INSERT INTO cx_score_daily(user_id, score_date, score, band, updated_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(user_id, score_date)
            DO UPDATE SET score=excluded.score, band=excluded.band, updated_at=excluded.updated_at
        """
    with pl._conn() as c:
        c.execute(sql, (user_id, score_date, int(score), str(band), str(updated_at)))


def seed_cx(users: list[str], days: int, base_score: int, spread: int) -> int:
    today = datetime.now(timezone.utc).date()
    written = 0
    for user_id in users:
        uid = str(user_id or "").strip()
        if not uid:
            continue
        for i in range(max(1, int(days))):
            d = today - timedelta(days=i)
            score_date = d.isoformat()
            score = max(0, min(100, int(base_score) + _stable_noise(uid, score_date, int(spread))))
            band = _band_for_score(score)
            _upsert_cx_runtime(
                user_id=uid,
                score_date=score_date,
                score=score,
                band=band,
                updated_at=datetime.now(timezone.utc).isoformat(),
            )
            written += 1
    return written


def _count_cx_rows() -> int:
    with pl._conn() as c:
        row = c.execute("SELECT COUNT(*) AS n FROM cx_score_daily").fetchone()
    if row is None:
        return 0
    try:
        return int(row["n"])
    except Exception:
        return int(row[0])


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--users", default="staging_user_a,staging_user_b", help="Comma-separated user IDs.")
    ap.add_argument("--days", type=int, default=14, help="How many recent days to seed.")
    ap.add_argument("--base-score", type=int, default=78, help="Base CX score before deterministic noise.")
    ap.add_argument("--spread", type=int, default=10, help="Noise spread (+/-) around base score.")
    args = ap.parse_args()

    users = [x.strip() for x in str(args.users).split(",") if x.strip()]
    if not users:
        print("[FAIL] No valid users.")
        return 2

    written = seed_cx(
        users=users,
        days=max(1, int(args.days)),
        base_score=max(0, min(100, int(args.base_score))),
        spread=max(0, int(args.spread)),
    )
    total_rows = _count_cx_rows()
    print(f"[OK] Seeded/updated cx_score_daily rows: {written}")
    print(f"[OK] Total cx_score_daily rows now: {total_rows}")
    print(f"[INFO] Users: {', '.join(users)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
