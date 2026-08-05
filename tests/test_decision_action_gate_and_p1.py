from __future__ import annotations

from core.decision_action_gate import normalize_action, resolve_display_action


def test_normalize_action_aliases() -> None:
    assert normalize_action("MUA") == "BUY"
    assert normalize_action("quan sát") == "WATCH"
    assert normalize_action("MUA CÓ ĐIỀU KIỆN") == "CONDITIONAL_BUY"
    assert normalize_action("bogus", default="AVOID") == "AVOID"


def test_resolve_display_action_downgrades_buy_without_gate() -> None:
    rep = {
        "final_action": "BUY",
        "gate_passed": False,
        "output_gate_passed": True,
        "valuation": {"instant_conclusion": "Mua mạnh"},
        "phase": {"phase": "accumulation"},
        "decision_alignment": {
            "unified_action": "BUY",
            "note_vi": "aligned",
            "alignment": "aligned",
        },
    }
    out = resolve_display_action(rep)
    assert out["display_action"] == "WATCH"
    assert "gate" in out["note_vi"].lower()


def test_resolve_display_action_caps_high_severity_completeness() -> None:
    rep = {
        "final_action": "BUY",
        "gate_passed": True,
        "output_gate_passed": True,
        "decision_completeness": {"severity": "high", "missing_items": ["eps", "cfo"]},
        "decision_alignment": {"unified_action": "BUY", "note_vi": ""},
    }
    out = resolve_display_action(rep)
    assert out["display_action"] == "WATCH"
    assert out["missing_summary"] == "eps, cfo"


def test_resolve_display_unifies_playbook_hold_over_watch_alignment() -> None:
    """ACB-style: playbook HOLD must show as HOLD/GIỮ, not WATCH/QUAN SÁT."""
    from core.decision_action_gate import action_display_vi

    rep = {
        "final_action": "HOLD",
        "gate_passed": True,
        "output_gate_passed": True,
        "decision_readiness": "MEDIUM",
        "decision_alignment": {
            "unified_action": "WATCH",
            "note_vi": "Legend=Theo dõi; action=HOLD; pha=neutral.",
            "alignment": "soft_divergence",
        },
        "decision_playbook": {
            "recommended_action": "HOLD",
            "thesis": {"grade": "A", "attractive": True},
            "setup": {"status": "WAIT"},
            "trigger": {"status": "PENDING"},
        },
        "decision_completeness": {"severity": "low", "missing_items": []},
    }
    out = resolve_display_action(rep)
    assert out["display_action"] == "HOLD"
    assert action_display_vi(out["display_action"]) == "GIỮ"


def test_align_report_locks_to_autopilot_board_action(tmp_path, monkeypatch) -> None:
    """Deep card must show the same action as Autopilot Top for that symbol."""
    from core.decision_action_gate import (
        action_display_vi,
        align_report_action_with_autopilot_board,
        resolve_display_action,
    )
    from core.decision_card_panel import build_decision_card_payload

    board = {
        "updated_at": "2099-01-01T00:00:00+00:00",
        "rows": {
            "ACB": {"Mã": "ACB", "Khuyến nghị": "HOLD", "gate_action": "HOLD"},
        },
    }
    monkeypatch.setattr("core.autopilot_nightly_board.load_board", lambda path=None: board)

    live_watch = {
        "final_action": "WATCH",
        "gate_passed": True,
        "output_gate_passed": True,
        "decision_alignment": {"unified_action": "WATCH", "note_vi": ""},
        "decision_playbook": {"recommended_action": "WATCH"},
        "valuation": {"price": 22500, "margin_of_safety_composite_pct": 34},
    }
    synced = align_report_action_with_autopilot_board(live_watch, symbol="ACB")
    assert synced["final_action"] == "HOLD"
    gate = resolve_display_action(synced)
    assert gate["display_action"] == "HOLD"
    card = build_decision_card_payload(live_watch, symbol="ACB")
    assert card["action"] == "HOLD"
    assert card["action_vi"] == "GIỮ"
    assert action_display_vi("HOLD") == action_display_vi(card["action"])


def test_hitrate_report_extended_by_action(tmp_path) -> None:
    from datetime import datetime, timedelta, timezone

    from core import paper_trade_ledger as ptl

    path = tmp_path / "ledger.json"
    now = datetime.now(timezone.utc)
    ledger = ptl.empty_ledger()
    ledger["trades"] = [
        {
            "status": "CLOSED",
            "closed_at": (now - timedelta(days=5)).isoformat(),
            "direction_hit": 1,
            "realized_pct": 5.0,
            "action": "WATCH",
            "symbol": "AAA",
        },
        {
            "status": "CLOSED",
            "closed_at": (now - timedelta(days=10)).isoformat(),
            "direction_hit": 0,
            "realized_pct": -2.0,
            "action": "WATCH",
            "symbol": "BBB",
        },
    ]
    ptl.save_ledger(ledger, path)
    ext = ptl.hitrate_report_extended(horizons=(30,), path=path)
    assert ext["windows"]["30"]["samples"] == 2
    assert ext["by_action"]["WATCH"]["hit_rate_pct"] == 50.0
    md = ptl.format_hitrate_markdown(ext)
    assert "Paper-trade accountability" in md
