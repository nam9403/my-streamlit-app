"""P2 product surface — onboarding, digest playbook, trust, Free/Pro, card."""

from __future__ import annotations

import pandas as pd

from core.app_onboarding_helpers import plan_autopilot_limit_cap, plan_feature_matrix, plan_packaging_caption, p2_onboarding_done_score
from core.decision_playbook import compact_playbook_fields
from core.morning_digest_service import build_decision_card_lines, build_morning_digest_text
from core.scanner_service import simple_view_for_plan
from core.slo_ops_panel import collect_slo_snapshot


def test_plan_autopilot_cap_free() -> None:
    assert plan_autopilot_limit_cap({"scan_limit": 20}, 80) == 20
    assert plan_autopilot_limit_cap({"scan_limit": 800}, 40) == 40
    assert plan_autopilot_limit_cap(None, 15) == 15


def test_p2_onboarding_score() -> None:
    assert p2_onboarding_done_score(profile_ready=True, autopilot_ready=False, deep_analysis_ready=False) == 1
    assert p2_onboarding_done_score(profile_ready=True, autopilot_ready=True, deep_analysis_ready=True) == 3


def test_plan_packaging_caption_mentions_free() -> None:
    text = plan_packaging_caption("free", {"scan_limit": 20, "alerts": 3, "llm_live": False})
    assert "Free" in text
    assert "20" in text


def test_plan_feature_matrix_matches_plan_features() -> None:
    from core.product_layer import PLAN_FEATURES

    rows = plan_feature_matrix()
    assert len(rows) == 3
    assert rows[0]["Gói"] == "Free"
    assert str(PLAN_FEATURES["free"]["scan_limit"]) in rows[0]["Quét Autopilot"]
    assert rows[0]["LLM"] == "Tắt"
    assert rows[1]["LLM"] == "Bật"


def test_morning_digest_cards() -> None:
    df = pd.DataFrame(
        [
            {
                "Mã": "SHB",
                "Khuyến nghị": "WATCH",
                "Giá": 12000.0,
                "MOS%": 50.0,
                "Expected Return %": 20.0,
                "Risk % (ước tính)": 18.0,
                "Khung thời gian": "Trung hạn (2-6 tháng)",
            }
        ]
    )
    text = build_morning_digest_text(df, board_meta={"coverage_pct": 90, "scanned_count": 360, "target_count": 400})
    assert "Morning Digest" in text
    assert "SHB" in text
    assert "90%" in text
    lines = build_decision_card_lines(dict(df.iloc[0]), rank=1)
    assert lines[0].startswith("1. SHB")


def test_morning_digest_includes_readiness_fields() -> None:
    df = pd.DataFrame(
        [
            {
                "Mã": "PNJ",
                "Khuyến nghị": "WATCH",
                "Readiness": "MEDIUM",
                "Thiếu DL": "cfo",
                "Ghi chú Legend": "Legend hấp dẫn nhưng pha chưa pass.",
                "Giá": 35500.0,
                "MOS%": 40.0,
            }
        ]
    )
    lines = build_decision_card_lines(dict(df.iloc[0]), rank=1)
    joined = "\n".join(lines)
    assert "ready MEDIUM" in joined
    assert "cfo" in joined
    assert "note:" in joined


def test_morning_digest_includes_playbook_conditional() -> None:
    row = {
        "Mã": "ACB",
        "Khuyến nghị": "CONDITIONAL_BUY",
        "Giá": 22500.0,
        "MOS%": 34.0,
        "Readiness": "MEDIUM",
        "Thesis": "A",
        "Setup": "WAIT",
        "Trigger": "PENDING",
        "Regime": "neutral",
        "Playbook": "MUA CÓ ĐIỀU KIỆN: chờ giá vào vùng 21700–23100.",
        "Cancel if": "Hủy nếu đóng cửa dưới 20800 hoặc pha phân phối.",
    }
    lines = build_decision_card_lines(row, rank=1)
    joined = "\n".join(lines)
    assert "CONDITIONAL_BUY" in joined
    assert "thesis A" in joined
    assert "setup WAIT" in joined
    assert "playbook:" in joined
    assert "cancel:" in joined


def test_morning_digest_includes_paper_pnl() -> None:
    from core.morning_digest_service import format_paper_pnl_digest_lines

    lines = format_paper_pnl_digest_lines(
        {"samples": 12, "hit_rate_pct": 58.3, "avg_realized_pct": 1.25, "open_count": 3, "lookback_days": 40}
    )
    joined = "\n".join(lines)
    assert "Paper ledger" in joined
    assert "40d" in joined
    assert "closed=12" in joined
    assert "58.3%" in joined
    empty = "\n".join(format_paper_pnl_digest_lines({"samples": 0, "open_count": 2, "lookback_days": 40}))
    assert "closed=0" in empty

    df = pd.DataFrame([{"Mã": "FPT", "Khuyến nghị": "WATCH", "Giá": 100.0}])
    text = build_morning_digest_text(
        df,
        board_meta={"coverage_pct": 80},
        paper_report={"samples": 5, "hit_rate_pct": 60.0, "avg_realized_pct": 2.0, "open_count": 1, "lookback_days": 40},
    )
    assert "Paper ledger" in text
    assert "FPT" in text


def test_morning_digest_why_not_and_event() -> None:
    row = {
        "Mã": "SHB",
        "Khuyến nghị": "HOLD",
        "Giá": 12000.0,
        "Thesis": "B",
        "Setup": "WAIT",
        "Trigger": "PENDING",
        "Why not BUY": "thesis chưa attractive · setup WAIT",
        "EventBlackout": True,
    }
    joined = "\n".join(build_decision_card_lines(row, rank=1))
    assert "why_not:" in joined
    assert "event: blackout" in joined


def test_compact_playbook_why_not_buy() -> None:
    fields = compact_playbook_fields(
        {
            "final_action": "HOLD",
            "decision_playbook": {
                "recommended_action": "HOLD",
                "thesis": {"grade": "B", "attractive": False},
                "setup": {"status": "WAIT"},
                "trigger": {"status": "PENDING"},
                "summary_vi": "Chờ setup",
                "event_blackout": {"blackout": True},
            },
        }
    )
    assert fields.get("EventBlackout") is True
    assert "Why not BUY" in fields
    assert "setup WAIT" in fields["Why not BUY"]


def test_compact_playbook_fields_from_report() -> None:
    rep = {
        "decision_playbook": {
            "thesis": {"grade": "B"},
            "setup": {"status": "WAIT"},
            "trigger": {
                "status": "PENDING",
                "entry_hint_vi": "Chờ vùng mua",
                "cancel_if_vi": "Hủy nếu mất 9000",
                "invalidation_price": 9000.0,
            },
            "regime": {"label": "neutral"},
            "user_instruction_vi": "MUA CÓ ĐIỀU KIỆN: chờ pha.",
            "size_cap_pct": 10.0,
        }
    }
    fields = compact_playbook_fields(rep)
    assert fields["Thesis"] == "B"
    assert fields["Setup"] == "WAIT"
    assert fields["Trigger"] == "PENDING"
    assert "Playbook" in fields


def test_decision_card_payload_includes_playbook() -> None:
    from core.decision_card_panel import build_decision_card_payload

    rep = {
        "final_action": "CONDITIONAL_BUY",
        "gate_passed": True,
        "output_gate_passed": True,
        "analysis_verdict": "CAUTION",
        "valuation": {
            "instant_conclusion": "Mua mạnh",
            "margin_of_safety_composite_pct": 35.0,
            "price": 100.0,
        },
        "phase": {"phase": "neutral"},
        "confidence_score": 70,
        "decision_readiness": "MEDIUM",
        "decision_alignment": {"unified_action": "CONDITIONAL_BUY", "note_vi": ""},
        "decision_playbook": {
            "thesis": {"grade": "A", "attractive": True},
            "setup": {"status": "WAIT"},
            "trigger": {
                "status": "PENDING",
                "entry_hint_vi": "Chờ giá vào vùng",
                "cancel_if_vi": "Hủy nếu mất 90",
                "invalidation_price": 90.0,
            },
            "summary_vi": "Thesis A · Setup WAIT · Trigger PENDING · Regime neutral → CONDITIONAL_BUY.",
            "user_instruction_vi": "MUA CÓ ĐIỀU KIỆN: chờ vùng.",
        },
        "risk_plan": {"entry_price": 100.0, "stop_loss_price": 90.0},
    }
    card = build_decision_card_payload(rep, symbol="ACB")
    assert card["symbol"] == "ACB"
    assert card["action"] == "CONDITIONAL_BUY"
    assert card["thesis_grade"] == "A"
    assert card["setup_status"] == "WAIT"
    assert card["is_conditional"] is True
    assert card["playbook_summary"]


def test_decision_card_payload_from_report() -> None:
    from core.decision_card_panel import build_decision_card_payload

    rep = {
        "final_action": "WATCH",
        "gate_passed": False,
        "valuation": {"instant_conclusion": "Theo dõi", "margin_of_safety_composite_pct": 25.0, "price": 100.0},
        "phase": {"phase": "accumulation"},
        "confidence_score": 55,
        "decision_readiness": "MEDIUM",
        "missing_items": ["cfo"],
    }
    card = build_decision_card_payload(rep, symbol="TEST")
    assert card["symbol"] == "TEST"
    assert card["action"] == "WATCH"
    assert card["readiness"] == "MEDIUM"


def test_simple_view_free_keeps_readiness_drops_sl() -> None:
    df = pd.DataFrame(
        [
            {
                "Mã": "FPT",
                "Hành động": "CONDITIONAL_BUY",
                "Readiness": "MEDIUM",
                "Thiếu DL": "—",
                "Ghi chú Legend": "ok",
                "Giá hiện tại": 60000.0,
                "Entry": 59000.0,
                "SL": 55000.0,
                "TP": 70000.0,
                "Thesis": "A",
                "Playbook": "chờ vùng",
            }
        ]
    )
    free = simple_view_for_plan(df, "free")
    assert "Readiness" in free.columns
    assert "Thesis" in free.columns
    assert "Entry" not in free.columns
    assert "SL" not in free.columns
    pro = simple_view_for_plan(df, "pro")
    assert "Entry" in pro.columns


def test_export_public_trust_page_builds() -> None:
    from scripts import export_public_trust_page as etp

    md = etp.build_trust_markdown()
    assert "Disclaimer" in md
    assert "Paper-trade" in md
    assert "Forecast accountability" in md


def test_collect_slo_snapshot_includes_fail_rate() -> None:
    snap = collect_slo_snapshot()
    assert "fail_rate_pct" in snap
    assert "generated_at" in snap
    assert "paper_accountability" in snap


def test_can_use_feature_blocks_llm_on_free(tmp_path, monkeypatch) -> None:
    import core.product_layer as pl

    monkeypatch.setattr(pl, "DB_PATH", tmp_path / "app_state.db")
    monkeypatch.setattr(pl, "SECRETS_PATH", tmp_path / "secrets.json")
    monkeypatch.setattr(pl, "APP_SECRET_PATH", tmp_path / ".app_secret.key")
    pl._init_db()
    uid = "llm_gate_user"
    pl.set_user_plan(uid, "free")
    ok, msg = pl.can_use_feature(uid, "llm", requested=1)
    assert ok is False
    assert "LLM" in msg or "llm" in msg.lower()
    pl.set_user_plan(uid, "pro")
    ok2, _ = pl.can_use_feature(uid, "llm_live", requested=1)
    assert ok2 is True
