from __future__ import annotations

from core.decision_action_gate import apply_trade_plan_visibility, trade_plan_is_active
from core.deep_insight_service import _dedupe_structured_events, analyze_smart_money_flow


def test_trade_plan_hidden_when_watch() -> None:
    rep = {
        "final_action": "WATCH",
        "gate_passed": True,
        "output_gate_passed": True,
        "valuation": {"instant_conclusion": "Bỏ qua"},
        "phase": {"phase": "distribution"},
        "risk_plan": {
            "entry_price": 100.0,
            "stop_loss_price": 90.0,
            "take_profit_price": 120.0,
        },
        "decision_alignment": {"unified_action": "WATCH", "note_vi": ""},
    }
    out = apply_trade_plan_visibility(rep)
    assert out["show_trade_plan"] is False
    assert out["risk_plan"]["trade_plan_active"] is False
    note = str(out["risk_plan"].get("display_note_vi") or "").lower()
    assert out["entry_allowed"] is False
    assert out["risk_management_visible"] is False
    assert "khóa toàn bộ" in note or "không đề xuất" in note
    assert trade_plan_is_active(out) is False


def test_trade_plan_active_when_buy() -> None:
    rep = {
        "final_action": "BUY",
        "gate_passed": True,
        "output_gate_passed": True,
        "valuation": {"instant_conclusion": "Mua mạnh"},
        "phase": {"phase": "accumulation"},
        "risk_plan": {"entry_price": 100.0},
        "decision_alignment": {"unified_action": "BUY", "note_vi": "", "alignment": "aligned"},
        "analysis_verdict": "GO",
    }
    out = apply_trade_plan_visibility(rep)
    assert out["show_trade_plan"] is True
    assert out["entry_allowed"] is True
    assert out["risk_management_visible"] is True
    assert trade_plan_is_active(out) is True


def test_hold_shows_risk_locks_entry() -> None:
    from core.decision_action_gate import (
        resolve_display_action,
        trade_plan_entry_allowed,
        trade_plan_risk_visible,
    )

    rep = {
        "final_action": "HOLD",
        "gate_passed": True,
        "output_gate_passed": True,
        "risk_plan": {
            "entry_price": 100.0,
            "stop_loss_price": 90.0,
            "take_profit_price": 120.0,
        },
        "decision_alignment": {"unified_action": "HOLD", "note_vi": ""},
    }
    gate = resolve_display_action(rep)
    assert gate["entry_allowed"] is False
    assert gate["risk_management_visible"] is True
    out = apply_trade_plan_visibility(rep)
    assert trade_plan_entry_allowed(out) is False
    assert trade_plan_risk_visible(out) is True
    assert "Không mở mua mới" in str(out["risk_plan"].get("entry_hint_vi") or "")


def test_smart_money_dedupe_collapses_duplicate_sells() -> None:
    events = [
        {
            "actor_type": "foreign",
            "actor_name": "Khoi ngoai",
            "side": "sell",
            "net_value_vnd": 400_000_000_000,
            "confidence": 1.0,
            "source": "disk",
        }
        for _ in range(8)
    ]
    deduped = _dedupe_structured_events(events)
    assert len(deduped) == 1
    assert int(deduped[0].get("_dup_count") or 0) == 8
    out = analyze_smart_money_flow([], symbol="FPT", structured_events=events)
    assert out["bias"] == "bearish"
    assert len(out["signals"]) <= 3
    assert any("×" in s for s in out["signals"])
