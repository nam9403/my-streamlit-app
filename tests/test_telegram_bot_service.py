from __future__ import annotations

from pathlib import Path

from core.telegram_bot_service import (
    add_to_watchlist,
    format_mini_decision_card_html,
    format_top5_html,
    load_watchlist,
    remove_from_watchlist,
    save_watchlist,
)


def test_watchlist_roundtrip(tmp_path: Path) -> None:
    p = tmp_path / "local_telegram_watchlist.json"
    save_watchlist(["PNJ", "acb", "BAD!"], path=p)
    assert load_watchlist(p) == ["PNJ", "ACB"]
    lst, added = add_to_watchlist("FPT", path=p)
    assert added and "FPT" in lst
    lst2, added2 = add_to_watchlist("FPT", path=p)
    assert not added2
    lst3, removed = remove_from_watchlist("ACB", path=p)
    assert removed and "ACB" not in lst3


def test_format_mini_decision_card_html_buy_shows_plan() -> None:
    analysis = {
        "symbol": "FPT",
        "company_name": "FPT Corp",
        "report": {
            "final_action": "BUY",
            "valuation": {
                "price": 120000,
                "margin_of_safety_composite_pct": 22.5,
                "piotroski_score": 7,
                "is_bank_sector": False,
            },
            "phase": {"phase": "accumulation"},
            "earnings_quality": {"operating_cash_flow": 1e12},
            "risk_plan": {
                "entry_price": 118000,
                "stop_loss_price": 110000,
                "take_profit_price": 140000,
                "trade_plan_active": True,
            },
            "decision_gate": {"display_action": "BUY", "show_trade_plan": True},
            "show_trade_plan": True,
        },
    }
    html = format_mini_decision_card_html(analysis)
    assert "FPT" in html
    assert "KHUYẾN NGHỊ" in html
    assert "Entry" in html or "Kế hoạch" in html


def test_format_mini_decision_card_hides_plan_on_watch() -> None:
    analysis = {
        "symbol": "PNJ",
        "report": {
            "final_action": "WATCH",
            "valuation": {"price": 35500, "margin_of_safety_composite_pct": 5.0, "piotroski_score": 4},
            "phase": {"phase": "distribution"},
            "risk_plan": {"entry_price": 35000, "stop_loss_price": 33000, "take_profit_price": 40000},
            "show_trade_plan": False,
        },
    }
    html = format_mini_decision_card_html(analysis)
    assert "PNJ" in html
    assert "Không đề xuất Entry" in html


def test_format_top5_html() -> None:
    rows = [
        {"Mã": "AAA", "Khuyến nghị": "BUY", "MOS%": 30, "Proprietary Score": 55, "Giá": 10000},
        {"Mã": "BBB", "Khuyến nghị": "HOLD", "MOS%": 12, "blend_score": 40, "Giá": 20000},
    ]
    html = format_top5_html(rows, board_meta={"updated_at": "2026-07-29T01:00:00+00:00"})
    assert "AAA" in html and "BBB" in html
    assert "Top 5" in html
