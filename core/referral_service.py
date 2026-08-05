"""
Referral + growth loop helpers (P3). Event-backed — no separate billing integration.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Callable


def referral_code_for_user(user_id: str) -> str:
    uid = str(user_id or "").strip().lower()
    if not uid:
        return ""
    digest = hashlib.sha256(f"ii-ref:{uid}".encode()).hexdigest()
    return digest[:8].upper()


def referral_link_hint(user_id: str, *, base_url: str = "") -> str:
    code = referral_code_for_user(user_id)
    if not code:
        return ""
    base = str(base_url or "").strip().rstrip("/")
    if base:
        return f"{base}?ref={code}"
    return f"Mã giới thiệu: {code} (nhập khi đăng ký hoặc ghi event referral_signup)"


def record_referral_signup(
    *,
    conn_factory: Callable[[], Any],
    utcnow_iso: Callable[[], str],
    new_user_id: str,
    referrer_code: str,
) -> dict[str, Any]:
    code = str(referrer_code or "").strip().upper()
    uid = str(new_user_id or "").strip()
    if not code or not uid:
        return {"recorded": False, "reason": "missing"}
    from core import analytics_repository

    analytics_repository.log_event(
        conn_factory=conn_factory,
        user_id=uid,
        event_type="referral_signup",
        meta={"referrer_code": code},
        now_iso=utcnow_iso(),
    )
    return {"recorded": True, "referrer_code": code, "new_user_id": uid}


def fetch_referral_stats(*, conn_factory: Callable[[], Any], days: int = 30) -> dict[str, Any]:
    from datetime import datetime, timedelta, timezone

    since = (datetime.now(timezone.utc) - timedelta(days=max(1, int(days)))).isoformat()
    with conn_factory() as c:
        rows = c.execute(
            """
            SELECT meta_json, ts
            FROM events
            WHERE event='referral_signup' AND ts>=?
            ORDER BY ts DESC
            LIMIT 5000
            """,
            (since,),
        ).fetchall()
    by_code: dict[str, int] = {}
    for r in rows:
        try:
            meta = json.loads(str(r["meta_json"] or "{}"))
        except Exception:
            meta = {}
        code = str(meta.get("referrer_code") or "UNKNOWN").upper()
        by_code[code] = by_code.get(code, 0) + 1
    top = sorted(by_code.items(), key=lambda x: -x[1])[:20]
    return {
        "window_days": int(days),
        "signups": len(rows),
        "unique_codes": len(by_code),
        "top_referrers": [{"code": k, "signups": v} for k, v in top],
    }
