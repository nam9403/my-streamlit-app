"""Tests for chat-first UI helpers (presentation only)."""

from __future__ import annotations

from core.app_chat_interface import (
    _action_badge_vi,
    _cfo_line_vi,
    _cfo_status,
    _disp,
    _dividend_line_vi,
    _fmt,
    _fscore_provisional,
    _fscore_text,
    _mos_comment_vi,
    _mos_header_bits,
    _readiness_vi,
    _strip_dividend_label,
    _verdict_vi,
    chat_first_ui_enabled,
)
from core.decision_action_gate import apply_trade_plan_visibility, resolve_display_action


def test_chat_first_ui_enabled_default(monkeypatch) -> None:
    monkeypatch.delenv("II_CHAT_FIRST_UI", raising=False)
    assert chat_first_ui_enabled() is True
    monkeypatch.setenv("II_CHAT_FIRST_UI", "0")
    assert chat_first_ui_enabled() is False


def test_cfo_status_and_fmt() -> None:
    assert _fmt(None) == "—"
    assert "1,000" in _fmt(1000, money=True) or "1000" in _fmt(1000, money=True).replace(",", "")
    label, lvl = _cfo_status(-100)
    assert "âm" in label.lower()
    assert lvl == "bad"
    label2, lvl2 = _cfo_status(1_000_000)
    assert "dương" in label2.lower()
    assert lvl2 == "ok"


def test_decision_card_vietnamese_labels() -> None:
    assert "Đang cập nhật" in _cfo_line_vi(None)
    assert "Thấp" == _readiness_vi("LOW")
    assert "CHƯA ĐẠT" in _verdict_vi("NO-GO")
    assert "Yếu" in _fscore_text(2)
    assert _action_badge_vi("BUY") == "MUA"
    assert _action_badge_vi("HOLD") == "GIỮ"
    assert _action_badge_vi("WATCH") == "QUAN SÁT"
    assert _disp(None, missing="Đang cập nhật") == "Đang cập nhật"
    assert "None" not in _disp(None)


def test_dividend_no_label_duplication() -> None:
    line = _dividend_line_vi({}, {}, {})
    assert line == "Đang cập nhật"
    assert not line.lower().startswith("cổ tức")
    assert _strip_dividend_label("Cổ tức: Đang cập nhật") == "Đang cập nhật"
    assert _strip_dividend_label("Cổ tức: Cổ tức: Đang cập nhật") == "Đang cập nhật"
    # Khi ghép UI: không còn "Cổ tức: Cổ tức:"
    rendered = f"Cổ tức: {_strip_dividend_label(line)}"
    assert rendered == "Cổ tức: Đang cập nhật"
    assert "Cổ tức: Cổ tức:" not in rendered


def test_fscore_provisional_when_bctc_incomplete() -> None:
    assert _fscore_provisional(cfo=None, cr=1.5) is True
    assert _fscore_provisional(cfo=1e9, cr=None) is True
    assert _fscore_provisional(cfo=1e9, cr=1.2) is False
    txt = _fscore_text(2, provisional=True)
    assert "Tạm tính" in txt
    assert "Đang chờ nạp BCTC" in txt
    assert "Yếu" not in txt


def test_mos_header_colors_and_comments() -> None:
    assert "Thị giá cao hơn định giá" in _mos_comment_vi(-17.6)
    emoji, cls, comment = _mos_header_bits(-17.6)
    assert emoji == "🔴"
    assert "neg" in cls
    assert "Thị giá" in comment
    emoji2, cls2, comment2 = _mos_header_bits(22.0)
    assert emoji2 == "🟢"
    assert "pos" in cls2
    assert "rộng" in comment2.lower()


def test_watch_recommendation_banner_single_label() -> None:
    badge = _action_badge_vi("WATCH")
    warn = f"Mua/Cắt lỗ (Khuyến nghị: {badge})."
    assert warn == "Mua/Cắt lỗ (Khuyến nghị: QUAN SÁT)."
    assert "QUAN SÁT /" not in warn
    assert warn.count("QUAN SÁT") == 1


def test_watch_hides_trade_plan_for_card() -> None:
    rep = apply_trade_plan_visibility(
        {
            "final_action": "WATCH",
            "gate_passed": True,
            "output_gate_passed": True,
            "analysis_verdict": "CAUTION",
            "valuation": {"instant_conclusion": "Theo dõi"},
            "phase": {"phase": "distribution"},
            "risk_plan": {"entry_price": 10, "stop_loss_price": 9, "take_profit_price": 12},
        }
    )
    gate = resolve_display_action(rep)
    assert gate["display_action"] == "WATCH"
    assert gate["show_trade_plan"] is False
    assert rep["risk_plan"].get("trade_plan_active") is False
