from __future__ import annotations

import json
from typing import Any, Callable

from core import analytics_repository


def log_event(
    *,
    conn_factory: Callable[[], Any],
    utcnow_iso: Callable[[], str],
    user_id: str,
    event_type: str,
    meta: dict[str, Any] | None = None,
) -> None:
    analytics_repository.log_event(
        conn_factory=conn_factory,
        user_id=user_id,
        event_type=event_type,
        meta=meta or {},
        now_iso=utcnow_iso(),
    )


def get_admin_cx_kpi(*, conn_factory: Callable[[], Any], days: int = 14) -> dict[str, Any]:
    avg_row, band_rows, trend_rows = analytics_repository.fetch_cx_kpi_rows(conn_factory=conn_factory, days=days)
    cap = max(1, min(int(days), 90))
    return {
        "window_days": cap,
        "avg_score": float(avg_row["avg_score"] or 0.0),
        "samples": int(avg_row["n"] or 0),
        "bands": [{"band": str(r["band"] or ""), "count": int(r["n"] or 0)} for r in band_rows],
        "trend": [
            {
                "score_date": str(r["score_date"] or ""),
                "avg_score": round(float(r["avg_score"] or 0.0), 2),
                "samples": int(r["samples"] or 0),
            }
            for r in trend_rows
        ],
    }


def get_kpi_dashboard(
    *,
    conn_factory: Callable[[], Any],
    user_id: str,
    days: int,
    get_user_plan_func: Callable[[str], str],
) -> dict[str, Any]:
    ev_rows, alerts_total, holdings_total, events_total = analytics_repository.fetch_kpi_dashboard_rows(
        conn_factory=conn_factory,
        user_id=user_id,
        days=days,
    )
    counts: dict[str, int] = {}
    for r in ev_rows:
        counts[str(r["event"])] = int(r["n"])
    return {
        "events_total": events_total,
        "by_event": counts,
        "alerts_total": alerts_total,
        "holdings_total": holdings_total,
        "plan_id": get_user_plan_func(user_id),
    }


def get_cohort_kpi(*, conn_factory: Callable[[], Any], user_id: str) -> dict[str, Any]:
    ev7, ev30 = analytics_repository.fetch_cohort_events(conn_factory=conn_factory, user_id=user_id)

    def _count(rows: list[Any], name: str) -> int:
        return sum(1 for r in rows if str(r["event"]) == name)

    active_days_7 = len({str(r["ts"])[:10] for r in ev7 if r["ts"]})
    active_days_30 = len({str(r["ts"])[:10] for r in ev30 if r["ts"]})
    return {
        "active_days_7": active_days_7,
        "active_days_30": active_days_30,
        "analysis_7": _count(ev7, "analysis_completed"),
        "analysis_30": _count(ev30, "analysis_completed"),
        "alerts_created_7": _count(ev7, "alert_created"),
        "alerts_created_30": _count(ev30, "alert_created"),
        "alerts_dispatched_7": _count(ev7, "alert_dispatched"),
        "alerts_dispatched_30": _count(ev30, "alert_dispatched"),
        "upgrade_intent_7": _count(ev7, "upgrade_intent"),
        "upgrade_intent_30": _count(ev30, "upgrade_intent"),
        "upgrade_success_7": _count(ev7, "upgrade_success"),
        "upgrade_success_30": _count(ev30, "upgrade_success"),
    }


def get_admin_kpi(*, conn_factory: Callable[[], Any], days: int = 30) -> dict[str, Any]:
    users, alerts, holdings, decisions, trades, events, active_users, plan_rows, ev_rows, q_rows = (
        analytics_repository.fetch_admin_kpi_rows(conn_factory=conn_factory, days=days)
    )
    return {
        "users_total": users,
        "active_users_period": active_users,
        "events_period": events,
        "alerts_total": alerts,
        "holdings_total": holdings,
        "decisions_total": decisions,
        "trades_total": trades,
        "plans": [{"plan_id": str(r["plan_id"]), "count": int(r["n"])} for r in plan_rows],
        "events_by_type": [{"event": str(r["event"]), "count": int(r["n"])} for r in ev_rows],
        "notification_queue": [{"status": str(r["status"]), "count": int(r["n"])} for r in q_rows],
    }


def get_upgrade_funnel(*, conn_factory: Callable[[], Any], days: int = 30) -> list[dict[str, Any]]:
    rows = analytics_repository.fetch_upgrade_funnel_events(conn_factory=conn_factory, days=days)
    bucket: dict[str, dict[str, int]] = {}

    def _inc(var: str, key: str) -> None:
        if var not in bucket:
            bucket[var] = {"views": 0, "info_clicks": 0, "cta_clicks": 0, "success": 0}
        bucket[var][key] += 1

    for r in rows:
        ev = str(r["event"] or "")
        try:
            meta = json.loads(str(r["meta_json"] or "{}"))
            if not isinstance(meta, dict):
                meta = {}
        except ValueError:
            meta = {}
        var = str(meta.get("variant") or "unknown")
        if ev == "upgrade_prompt_view":
            _inc(var, "views")
        elif ev == "upgrade_info_click":
            _inc(var, "info_clicks")
        elif ev == "upgrade_cta_click":
            _inc(var, "cta_clicks")
        elif ev == "upgrade_success":
            _inc(var, "success")

    out: list[dict[str, Any]] = []
    for var, v in sorted(bucket.items(), key=lambda x: x[0]):
        views = int(v["views"])
        cta = int(v["cta_clicks"])
        suc = int(v["success"])
        out.append(
            {
                "variant": var,
                "views": views,
                "info_clicks": int(v["info_clicks"]),
                "cta_clicks": cta,
                "success": suc,
                "CTR %": round((cta / views * 100.0), 1) if views > 0 else 0.0,
                "CVR %": round((suc / cta * 100.0), 1) if cta > 0 else 0.0,
            }
        )
    return out


def select_upgrade_variant_auto(*, days: int, get_upgrade_funnel_func: Callable[[int], list[dict[str, Any]]]) -> dict[str, Any]:
    rows = get_upgrade_funnel_func(days)
    if not rows:
        return {"variant": "high_engagement", "reason": "cold_start"}
    best = None
    best_score = -1.0
    for r in rows:
        cta = int(r.get("cta_clicks") or 0)
        views = int(r.get("views") or 0)
        success = int(r.get("success") or 0)
        ctr = float(r.get("CTR %") or 0.0) / 100.0
        cvr = float(r.get("CVR %") or 0.0) / 100.0
        cvr_smooth = (success + 1.0) / (cta + 2.0) if cta >= 0 else 0.0
        ctr_smooth = (cta + 1.0) / (views + 2.0) if views >= 0 else 0.0
        score = cvr_smooth * 0.7 + ctr_smooth * 0.3 + cvr * 0.2 + ctr * 0.1
        if score > best_score:
            best_score = score
            best = str(r.get("variant") or "high_engagement")
    return {"variant": best or "high_engagement", "reason": "funnel_optimized", "score": round(best_score, 4)}
