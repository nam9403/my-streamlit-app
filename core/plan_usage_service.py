from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Callable

from core import plan_usage_repository


def get_plan_features(plan_id: str, *, plan_features: dict[str, dict[str, Any]]) -> dict[str, Any]:
    return dict(plan_features.get(plan_id, plan_features["free"]))


def set_user_plan(
    *,
    conn_factory: Callable[[], Any],
    utcnow_iso: Callable[[], str],
    user_id: str,
    plan_id: str,
    plan_features: dict[str, dict[str, Any]],
) -> None:
    pid = str(plan_id or "free").strip().lower()
    if pid not in plan_features:
        pid = "free"
    plan_usage_repository.set_user_plan(
        conn_factory=conn_factory,
        user_id=user_id,
        plan_id=pid,
        now_iso=utcnow_iso(),
    )


def get_user_plan(
    *,
    conn_factory: Callable[[], Any],
    user_id: str,
    default_plan: str,
    plan_features: dict[str, dict[str, Any]],
) -> str:
    pid = plan_usage_repository.get_user_plan(conn_factory=conn_factory, user_id=user_id) or default_plan
    pid = str(pid or default_plan).strip().lower()
    return pid if pid in plan_features else "free"


def get_trial_state(
    *,
    conn_factory: Callable[[], Any],
    parse_ts: Callable[[str], datetime | None],
    user_id: str,
) -> dict[str, Any]:
    uid = (user_id or "").strip()
    if not uid:
        return {"trial_consumed": 0, "trial_active": False}
    row = plan_usage_repository.get_trial_state_row(conn_factory=conn_factory, user_id=uid)
    if row is None:
        return {"trial_consumed": 0, "trial_active": False}
    end_at = parse_ts(str(row.get("trial_end_at") or ""))
    active = bool(end_at and datetime.now(timezone.utc) <= end_at)
    return {
        "trial_start_at": str(row.get("trial_start_at") or ""),
        "trial_end_at": str(row.get("trial_end_at") or ""),
        "trial_consumed": int(row.get("trial_consumed") or 0),
        "trial_active": active,
    }


def start_premium_trial_7d(
    *,
    conn_factory: Callable[[], Any],
    utcnow_iso: Callable[[], str],
    parse_ts: Callable[[str], datetime | None],
    user_id: str,
) -> tuple[bool, str]:
    uid = (user_id or "").strip()
    if not uid:
        return False, "User rỗng."
    state = get_trial_state(conn_factory=conn_factory, parse_ts=parse_ts, user_id=uid)
    if int(state.get("trial_consumed") or 0) >= 1:
        return False, "Đã dùng trial trước đó."
    plan_usage_repository.upsert_trial_7d(conn_factory=conn_factory, user_id=uid, now_iso=utcnow_iso())
    return True, "Đã kích hoạt trial 7 ngày."


def trial_is_active(*, trial_state: dict[str, Any]) -> bool:
    return bool(trial_state.get("trial_active"))


def premium_features_unlocked(*, user_id: str, plan_id: str, trial_is_active_func: Callable[[str], bool]) -> bool:
    pid = str(plan_id or "free").strip().lower()
    if pid in ("pro", "expert"):
        return True
    return trial_is_active_func(user_id)


def record_usage(*, conn_factory: Callable[[], Any], user_id: str, feature: str, count: int = 1) -> None:
    if count <= 0:
        return
    plan_usage_repository.record_usage(conn_factory=conn_factory, user_id=user_id, feature=feature, count=int(count))


def get_usage_today(*, conn_factory: Callable[[], Any], user_id: str, feature: str) -> int:
    return plan_usage_repository.get_usage_today(conn_factory=conn_factory, user_id=user_id, feature=feature)


def can_use_feature(
    *,
    user_id: str,
    feature: str,
    requested: int,
    plan_id: str | None,
    get_user_plan_func: Callable[[str, str], str],
    get_plan_features_func: Callable[[str], dict[str, Any]],
    get_usage_today_func: Callable[[str, str], int],
    list_alerts_func: Callable[[str], list[dict[str, Any]]],
) -> tuple[bool, str]:
    pid = (plan_id or get_user_plan_func(user_id, "free")).strip().lower()
    plan = get_plan_features_func(pid)
    if feature == "analysis":
        used = get_usage_today_func(user_id, "analysis")
        limit = int(plan.get("analysis_per_day") or 0)
        if used + requested > limit:
            return False, f"Vượt giới hạn phân tích/ngày của gói ({used}/{limit})."
    if feature == "scan":
        limit = int(plan.get("scan_limit") or 0)
        if requested > limit:
            return False, f"Gói hiện tại chỉ cho quét tối đa {limit} mã."
    if feature == "alert":
        current = len(list_alerts_func(user_id))
        limit = int(plan.get("alerts") or 0)
        if current + requested > limit:
            return False, f"Đã chạm giới hạn cảnh báo ({current}/{limit})."
    if feature in ("llm", "llm_live"):
        if not bool(plan.get("llm_live")):
            return False, "Gói hiện tại không có LLM live (Free). Nâng Pro/Expert để bật."
    # Wave 6 — edge features gắn Free vs Pro
    if feature in ("morning_digest", "digest_send"):
        if not bool(plan.get("morning_digest")):
            return False, "Morning digest gửi kênh chỉ có trên Pro/Expert."
    if feature in ("paper_weekly", "weekly_report"):
        if not bool(plan.get("paper_weekly")):
            return False, "Báo cáo tuần paper đầy đủ chỉ có trên Pro/Expert."
    if feature in ("edge_detail", "sector_peer_detail"):
        if not bool(plan.get("edge_detail")):
            return False, "Chi tiết edge (peer/sector sâu) chỉ có trên Pro/Expert."
    if feature in ("journal_one_click", "journal"):
        limit = int(plan.get("journal_one_click_per_day") or 0)
        used = get_usage_today_func(user_id, "journal_one_click")
        if used + requested > limit:
            return False, f"Vượt giới hạn journal 1-click/ngày của gói ({used}/{limit})."
    if feature in ("trade_plan_full",):
        if not bool(plan.get("trade_plan_full")):
            return False, "Full Entry/SL/TP trên bảng chỉ có trên Pro/Expert (Free dùng Simple View)."
    return True, "ok"


def require_feature(
    *,
    user_id: str,
    feature: str,
    requested: int,
    plan_id: str | None,
    get_user_plan_func: Callable[[str, str], str],
    get_plan_features_func: Callable[[str], dict[str, Any]],
    get_usage_today_func: Callable[[str, str], int],
    list_alerts_func: Callable[[str], list[dict[str, Any]]],
) -> None:
    """Raise InsufficientQuotaError when the plan cannot cover ``requested`` usage."""
    from core.exceptions import InsufficientQuotaError

    ok, msg = can_use_feature(
        user_id=user_id,
        feature=feature,
        requested=requested,
        plan_id=plan_id,
        get_user_plan_func=get_user_plan_func,
        get_plan_features_func=get_plan_features_func,
        get_usage_today_func=get_usage_today_func,
        list_alerts_func=list_alerts_func,
    )
    if not ok:
        raise InsufficientQuotaError(msg)
