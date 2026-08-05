"""
Wave 6 — growth / commercial conversion helpers (event-backed, no billing vendor).
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable


def _count_events(rows: list[dict[str, Any]], event: str) -> int:
    ev = str(event or "").strip().lower()
    return sum(1 for r in rows if str(r.get("event") or r.get("event_type") or "").lower() == ev)


def compute_onboarding_conversion(events: list[dict[str, Any]] | None) -> dict[str, Any]:
    """
    Funnel rates from logged events.
    Steps: autopilot_seen → deep_analysis → onboarding_complete → upgrade_intent → upgrade_success.
    """
    rows = list(events or [])
    n_ap = _count_events(rows, "onboarding_autopilot_seen") + _count_events(rows, "autopilot_onboarding_seen")
    n_deep = _count_events(rows, "onboarding_deep_done") + _count_events(rows, "onboarding_deep_analysis_done")
    n_done = _count_events(rows, "onboarding_p2_done") + _count_events(rows, "onboarding_complete")
    n_intent = _count_events(rows, "upgrade_intent")
    n_success = _count_events(rows, "upgrade_success")
    n_waitlist = _count_events(rows, "waitlist_join")
    n_ref = _count_events(rows, "referral_signup")

    def _rate(num: int, den: int) -> float | None:
        if den <= 0:
            return None
        return round(100.0 * float(num) / float(den), 1)

    return {
        "autopilot_seen": n_ap,
        "deep_analysis": n_deep,
        "onboarding_complete": n_done,
        "upgrade_intent": n_intent,
        "upgrade_success": n_success,
        "waitlist_join": n_waitlist,
        "referral_signup": n_ref,
        "rate_deep_given_autopilot_pct": _rate(n_deep, n_ap),
        "rate_complete_given_deep_pct": _rate(n_done, n_deep),
        "rate_intent_given_complete_pct": _rate(n_intent, n_done),
        "rate_pay_given_intent_pct": _rate(n_success, n_intent),
        "rate_pay_given_complete_pct": _rate(n_success, n_done),
    }


def compute_pilot_readiness(
    *,
    active_users_30d: int,
    upgrade_success_30d: int,
    waitlist_joins: int,
    paper_closed_40d: int,
    target_mau: int = 50,
    target_pay_pct: float = 10.0,
) -> dict[str, Any]:
    """Wave 6.4 — honest pilot gate vs 50 MAU / ~10% pay or clear waitlist."""
    mau = max(0, int(active_users_30d or 0))
    pays = max(0, int(upgrade_success_30d or 0))
    wait = max(0, int(waitlist_joins or 0))
    pay_pct = round(100.0 * pays / mau, 1) if mau > 0 else None
    mau_ok = mau >= int(target_mau)
    pay_ok = pay_pct is not None and pay_pct >= float(target_pay_pct)
    waitlist_ok = wait >= max(10, int(target_mau) // 5)
    paper_note = (
        "paper edge live chưa đủ mẫu"
        if int(paper_closed_40d or 0) < 40
        else "paper đủ mẫu để hỗ trợ trust"
    )
    if mau_ok and pay_ok:
        status = "PILOT_PASS"
        note_vi = f"Đạt MAU≥{target_mau} và pay≈{pay_pct}% (≥{target_pay_pct}%)."
    elif mau_ok and waitlist_ok:
        status = "WAITLIST_OK"
        note_vi = f"MAU đạt; pay chưa đủ nhưng waitlist={wait} — giữ waitlist rõ."
    elif mau_ok:
        status = "MAU_ONLY"
        note_vi = f"MAU={mau} đạt nhưng pay/waitlist chưa đủ — tiếp tục nurture."
    else:
        status = "BUILDING"
        note_vi = f"MAU={mau}/{target_mau} — tiếp tục acquisition + onboarding."
    return {
        "status": status,
        "active_users_30d": mau,
        "upgrade_success_30d": pays,
        "pay_pct": pay_pct,
        "waitlist_joins": wait,
        "target_mau": int(target_mau),
        "target_pay_pct": float(target_pay_pct),
        "mau_ok": mau_ok,
        "pay_ok": pay_ok,
        "waitlist_ok": waitlist_ok,
        "paper_closed_40d": int(paper_closed_40d or 0),
        "paper_note": paper_note,
        "note_vi": note_vi,
    }


def load_recent_events(
    *,
    conn_factory: Callable[[], Any],
    days: int = 30,
    limit: int = 5000,
) -> list[dict[str, Any]]:
    since = (datetime.now(timezone.utc) - timedelta(days=max(1, int(days)))).isoformat()
    out: list[dict[str, Any]] = []
    with conn_factory() as c:
        rows = c.execute(
            """
            SELECT user_id, event, meta_json, ts
            FROM events
            WHERE ts>=?
            ORDER BY ts DESC
            LIMIT ?
            """,
            (since, int(limit)),
        ).fetchall()
    for r in rows:
        meta: dict[str, Any] = {}
        try:
            meta = json.loads(str(r["meta_json"] or "{}"))
        except Exception:
            meta = {}
        out.append(
            {
                "user_id": str(r["user_id"] or ""),
                "event": str(r["event"] or ""),
                "meta": meta,
                "ts": str(r["ts"] or ""),
            }
        )
    return out


def build_growth_conversion_snapshot(
    *,
    conn_factory: Callable[[], Any] | None = None,
    days: int = 30,
    get_admin_kpi: Callable[..., dict[str, Any]] | None = None,
    paper_closed_40d: int | None = None,
) -> dict[str, Any]:
    events: list[dict[str, Any]] = []
    if conn_factory is not None:
        try:
            events = load_recent_events(conn_factory=conn_factory, days=days)
        except Exception:
            events = []
    funnel = compute_onboarding_conversion(events)
    admin: dict[str, Any] = {}
    if get_admin_kpi is not None:
        try:
            admin = dict(get_admin_kpi(days=days) or {})
        except Exception:
            admin = {}
    closed = paper_closed_40d
    if closed is None:
        try:
            from core.paper_trade_ledger import hitrate_report

            closed = int((hitrate_report(lookback_days=40) or {}).get("samples") or 0)
        except Exception:
            closed = 0
    pilot = compute_pilot_readiness(
        active_users_30d=int(admin.get("active_users_period") or 0),
        upgrade_success_30d=int(funnel.get("upgrade_success") or 0),
        waitlist_joins=int(funnel.get("waitlist_join") or 0),
        paper_closed_40d=int(closed or 0),
    )
    return {
        "updated_at_utc": datetime.now(timezone.utc).isoformat(),
        "window_days": int(days),
        "onboarding_funnel": funnel,
        "pilot": pilot,
        "admin_users_total": admin.get("users_total"),
        "admin_active_users_period": admin.get("active_users_period"),
    }


def write_growth_conversion_snapshot(payload: dict[str, Any], path: Path | str) -> Path:
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return out
