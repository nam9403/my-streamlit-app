from __future__ import annotations

from datetime import date

from core.decision_card_panel import build_decision_card_payload
from core.event_calendar_gate import (
    apply_event_blackout_to_action,
    assess_event_blackout,
    vn_earnings_season_windows,
)
from core.proprietary_signal import compute_blend_signal


def test_earnings_season_window_contains_known_dates() -> None:
    windows = vn_earnings_season_windows(2025)
    assert any(a <= date(2025, 2, 1) <= b for a, b, _ in windows)


def test_news_dividend_triggers_blackout() -> None:
    bo = assess_event_blackout(
        as_of=date(2025, 6, 10),
        news=[{"title": "FPT chốt quyền cổ tức bằng tiền", "date": "2025-06-09"}],
        use_season=False,
    )
    assert bo["blackout"] is True
    assert any("dividend" in r for r in bo["reasons"])


def test_apply_blackout_demotes_buy() -> None:
    act, notes = apply_event_blackout_to_action(
        "BUY", {"blackout": True, "severity": "high", "note_vi": "test"}
    )
    assert act == "HOLD"
    assert notes
    soft, _ = apply_event_blackout_to_action(
        "BUY", {"blackout": True, "severity": "medium", "note_vi": "season"}
    )
    assert soft == "CONDITIONAL_BUY"


def test_flow_weight_low_when_sm_unreliable() -> None:
    sig = compute_blend_signal(
        {
            "final_action": "WATCH",
            "valuation": {"margin_of_safety_composite_pct": 10, "piotroski_score": 5},
            "phase": {"phase": "neutral", "metrics": {}},
            "deep_insight": {"smart_money_flow": {"bias": "bullish", "score": 1.0, "structured_event_count": 0}},
            "smart_money_reliability": "LOW",
            "confidence_score": 50,
        }
    )
    assert float(sig.get("flow_weight") or 0) <= 0.15


def test_decision_card_why_not_buy() -> None:
    card = build_decision_card_payload(
        {
            "final_action": "HOLD",
            "valuation": {"price": 100, "margin_of_safety_composite_pct": 12},
            "phase": {"phase": "accumulation"},
            "decision_playbook": {
                "recommended_action": "HOLD",
                "thesis": {"grade": "B", "attractive": False},
                "setup": {"status": "WAIT"},
                "trigger": {"status": "PENDING"},
                "summary_vi": "test",
                "event_blackout": {"blackout": False},
            },
        },
        symbol="FPT",
    )
    assert card.get("why_not_buy")
    assert "BUY" not in str(card.get("action") or "").upper() or card["action"] != "BUY"


def test_journal_draft_from_card() -> None:
    from core.decision_card_panel import build_journal_draft_from_card

    draft = build_journal_draft_from_card(
        {
            "final_action": "BUY",
            "gate_passed": True,
            "output_gate_passed": True,
            "decision_readiness": "HIGH",
            "analysis_verdict": "GO",
            "valuation": {
                "price": 100000,
                "margin_of_safety_composite_pct": 20,
                "instant_conclusion": "attractive",
            },
            "risk_plan": {
                "entry_price": 99000,
                "stop_loss_price": 90000,
                "take_profit_price": 115000,
            },
            "decision_alignment": {"unified_action": "BUY", "note_vi": ""},
            "decision_playbook": {
                "recommended_action": "BUY",
                "thesis": {"grade": "A", "attractive": True},
                "setup": {"status": "ARMED"},
                "trigger": {"status": "READY"},
                "summary_vi": "Vào khi giữ pha tích lũy",
            },
        },
        symbol="FPT",
        horizon_days=40,
    )
    assert draft["symbol"] == "FPT"
    assert draft["side"] == "BUY"
    assert draft["ready"] is True
    assert draft["entry_price"] == 99000
    assert draft["horizon_days"] == 40
    assert "Vào khi" in draft["thesis"]
