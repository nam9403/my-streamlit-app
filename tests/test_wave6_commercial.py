"""Wave 6 — commercial readiness: plan edge gates, conversion, pilot."""

from __future__ import annotations

from core.app_onboarding_helpers import plan_feature_matrix, plan_packaging_caption
from core.growth_conversion_service import compute_onboarding_conversion, compute_pilot_readiness
from core.plan_usage_service import can_use_feature
from core.product_layer import PLAN_FEATURES


def _can(feature: str, plan_id: str, *, used: int = 0) -> tuple[bool, str]:
    return can_use_feature(
        user_id="u_test",
        feature=feature,
        requested=1,
        plan_id=plan_id,
        get_user_plan_func=lambda uid, d: plan_id,
        get_plan_features_func=lambda pid: dict(PLAN_FEATURES.get(pid) or PLAN_FEATURES["free"]),
        get_usage_today_func=lambda uid, feat: used,
        list_alerts_func=lambda uid: [],
    )


def test_plan_edge_features_free_vs_pro() -> None:
    assert PLAN_FEATURES["free"]["edge_detail"] is False
    assert PLAN_FEATURES["pro"]["edge_detail"] is True
    ok_free, msg_free = _can("paper_weekly", "free")
    assert ok_free is False
    assert "Pro" in msg_free or "Expert" in msg_free
    ok_pro, _ = _can("paper_weekly", "pro")
    assert ok_pro is True
    ok_digest_free, _ = _can("morning_digest", "free")
    assert ok_digest_free is False
    ok_j, msg_j = _can("journal_one_click", "free", used=3)
    assert ok_j is False
    assert "journal" in msg_j.lower()
    ok_j2, _ = _can("journal_one_click", "free", used=0)
    assert ok_j2 is True


def test_plan_matrix_includes_edge_columns() -> None:
    rows = plan_feature_matrix()
    assert len(rows) == 3
    assert "Journal 1-click/ngày" in rows[0]
    assert rows[0]["Paper weekly"] == "Không"
    assert rows[1]["Paper weekly"] == "Có"
    cap = plan_packaging_caption("free", PLAN_FEATURES["free"])
    assert "journal" in cap.lower()


def test_onboarding_conversion_rates() -> None:
    events = [
        {"event": "onboarding_autopilot_seen"},
        {"event": "onboarding_autopilot_seen"},
        {"event": "onboarding_deep_done"},
        {"event": "onboarding_p2_done"},
        {"event": "upgrade_intent"},
        {"event": "upgrade_success"},
        {"event": "waitlist_join"},
    ]
    funnel = compute_onboarding_conversion(events)
    assert funnel["autopilot_seen"] == 2
    assert funnel["deep_analysis"] == 1
    assert funnel["rate_deep_given_autopilot_pct"] == 50.0
    assert funnel["upgrade_success"] == 1
    assert funnel["waitlist_join"] == 1


def test_pilot_readiness_statuses() -> None:
    building = compute_pilot_readiness(
        active_users_30d=12,
        upgrade_success_30d=0,
        waitlist_joins=2,
        paper_closed_40d=0,
    )
    assert building["status"] == "BUILDING"
    waitlist = compute_pilot_readiness(
        active_users_30d=55,
        upgrade_success_30d=1,
        waitlist_joins=12,
        paper_closed_40d=10,
    )
    assert waitlist["status"] == "WAITLIST_OK"
    passed = compute_pilot_readiness(
        active_users_30d=60,
        upgrade_success_30d=8,
        waitlist_joins=0,
        paper_closed_40d=45,
    )
    assert passed["status"] == "PILOT_PASS"
    assert passed["pay_ok"] is True
