"""
Pure onboarding helper utilities (P2 funnel: profile → Autopilot → deep analysis).
"""

from __future__ import annotations


def is_watch_seed_ready(seed_value: str, minimum_symbols: int = 3) -> bool:
    symbols = [item.strip() for item in str(seed_value or "").split(",") if item.strip()]
    return len(symbols) >= int(minimum_symbols)


def onboarding_done_score(*, auth_ready: bool, channel_ready: bool, watch_seed_ready: bool) -> int:
    """Legacy 3-step score (auth / channel / watch)."""
    return int(bool(auth_ready)) + int(bool(channel_ready)) + int(bool(watch_seed_ready))


def onboarding_progress_text(done_score: int, total_steps: int = 3) -> str:
    safe_total = max(1, int(total_steps))
    safe_done = max(0, min(int(done_score), safe_total))
    return f"Onboarding progress: {safe_done}/{safe_total}"


def p2_onboarding_done_score(
    *,
    profile_ready: bool,
    autopilot_ready: bool,
    deep_analysis_ready: bool,
) -> int:
    """P2 funnel: hồ sơ → Autopilot → phân tích 1 mã."""
    return int(bool(profile_ready)) + int(bool(autopilot_ready)) + int(bool(deep_analysis_ready))


def p2_onboarding_progress_text(done_score: int) -> str:
    return onboarding_progress_text(done_score, total_steps=3)


def plan_autopilot_limit_cap(plan: dict | None, requested: int) -> int:
    """Clamp Autopilot window to plan.scan_limit (Free≈20)."""
    scan_cap = 80
    if isinstance(plan, dict):
        try:
            scan_cap = int(plan.get("scan_limit") or 80)
        except (TypeError, ValueError):
            scan_cap = 80
    # Autopilot board hard-cap is 120 in scanner; product Free should feel limited.
    hard = min(120, max(10, scan_cap))
    try:
        req = int(requested)
    except (TypeError, ValueError):
        req = 30
    return max(10, min(hard, req))


def plan_packaging_caption(plan_id: str, plan: dict | None) -> str:
    pid = str(plan_id or "free").lower()
    p = plan if isinstance(plan, dict) else {}
    scan = p.get("scan_limit", "?")
    alerts = p.get("alerts", "?")
    analysis = p.get("analysis_per_day", "?")
    llm = "có" if p.get("llm_live") else "không"
    journal = p.get("journal_one_click_per_day", "?")
    if pid == "free":
        tip = (
            "Free: Autopilot≤20, Simple View, LLM tắt, journal 1-click hạn chế; "
            "edge/peer sâu + digest gửi kênh + paper weekly = Pro."
        )
    elif pid == "pro":
        tip = "Pro: quét rộng, trade plan full, LLM, digest/paper weekly, journal rộng."
    else:
        tip = "Expert: hạn mức cao nhất cho vận hành chuyên sâu."
    return (
        f"{tip} | scan≤{scan} | alerts≤{alerts} | phân tích/ngày≤{analysis} | "
        f"journal/ngày≤{journal} | LLM: {llm}"
    )


def plan_feature_matrix() -> list[dict[str, str]]:
    """Comparison table rows for billing / upgrade UI — derived from PLAN_FEATURES."""
    try:
        from core.product_layer import PLAN_FEATURES
    except Exception:
        PLAN_FEATURES = {
            "free": {
                "scan_limit": 20,
                "llm_live": False,
                "alerts": 3,
                "analysis_per_day": 30,
                "journal_one_click_per_day": 3,
                "edge_detail": False,
                "morning_digest": False,
                "paper_weekly": False,
            },
            "pro": {
                "scan_limit": 800,
                "llm_live": True,
                "alerts": 20,
                "analysis_per_day": 200,
                "journal_one_click_per_day": 50,
                "edge_detail": True,
                "morning_digest": True,
                "paper_weekly": True,
            },
            "expert": {
                "scan_limit": 4000,
                "llm_live": True,
                "alerts": 100,
                "analysis_per_day": 1000,
                "journal_one_click_per_day": 500,
                "edge_detail": True,
                "morning_digest": True,
                "paper_weekly": True,
            },
        }
    rows: list[dict[str, str]] = []
    labels = {"free": "Free", "pro": "Pro", "expert": "Expert"}
    for pid in ("free", "pro", "expert"):
        p = PLAN_FEATURES.get(pid) or {}
        rows.append(
            {
                "Gói": labels.get(pid, pid.title()),
                "Quét Autopilot": f"≤{p.get('scan_limit', '?')}",
                "Simple View": "Rút gọn" if pid == "free" else "Full",
                "LLM": "Bật" if p.get("llm_live") else "Tắt",
                "Alert": str(p.get("alerts", "?")),
                "Phân tích/ngày": str(p.get("analysis_per_day", "?")),
                "Journal 1-click/ngày": str(p.get("journal_one_click_per_day", "?")),
                "Edge/peer sâu": "Có" if p.get("edge_detail") else "Không",
                "Digest gửi kênh": "Có" if p.get("morning_digest") else "Không",
                "Paper weekly": "Có" if p.get("paper_weekly") else "Không",
            }
        )
    return rows


def plan_usage_caption(
    *,
    plan_id: str,
    plan: dict | None,
    alerts_used: int = 0,
    analysis_used: int = 0,
) -> str:
    p = plan if isinstance(plan, dict) else {}
    alert_lim = int(p.get("alerts") or 0)
    analysis_lim = int(p.get("analysis_per_day") or 0)
    parts = [f"Gói {str(plan_id or 'free').upper()}"]
    if alert_lim > 0:
        parts.append(f"alert {alerts_used}/{alert_lim}")
    if analysis_lim > 0:
        parts.append(f"phân tích hôm nay {analysis_used}/{analysis_lim}")
    return " · ".join(parts)

