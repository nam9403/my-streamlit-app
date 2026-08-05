from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from core import decision_completeness as dc
from core import paper_trade_ledger as ptl


def test_completeness_softens_strong_buy_when_cfo_missing_non_bank() -> None:
    snap = {"price": 100.0, "eps": 10.0, "roe": 18.0, "net_income": 1e9, "is_bank": False}
    val = {"instant_conclusion": "Mua mạnh", "is_bank_sector": False, "advice": "ok"}
    out = dc.apply_completeness_to_valuation(snap, val)
    assert out["instant_conclusion"] == "Theo dõi"
    assert out.get("legend_softened_by_completeness") is True
    assert "cfo" in (out.get("missing_items") or [])


def test_completeness_bank_skips_cfo_penalty() -> None:
    snap = {"price": 22.0, "eps": 3.0, "roe": 17.0, "net_income": 1e12, "is_bank": True}
    val = {"instant_conclusion": "Mua mạnh", "is_bank_sector": True}
    gate = dc.assess_decision_completeness(snap, val)
    assert "cfo" not in gate["missing_items"]
    assert gate["soften_legend"] is False


def test_readiness_cap_never_upgrades() -> None:
    assert dc.cap_readiness_label("HIGH", "MEDIUM") == "MEDIUM"
    assert dc.cap_readiness_label("LOW", "MEDIUM") == "LOW"
    assert dc.cap_readiness_label("MEDIUM", None) == "MEDIUM"


def test_paper_trade_open_and_resolve(tmp_path: Path) -> None:
    path = tmp_path / "ledger.json"
    # P0: WATCH must NOT open LONG
    watch_rows = [
        {"Mã": "SHB", "Giá": 12000.0, "Expected Return %": 20.0, "MOS%": 50.0, "Khuyến nghị": "WATCH"},
        {"Mã": "ACB", "Giá": 22000.0, "Expected Return %": 15.0, "MOS%": 40.0, "Khuyến nghị": "WATCH"},
    ]
    st_watch = ptl.open_paper_trades_from_top(watch_rows, source="test", horizon_days=1, path=path)
    assert st_watch["opened"] == 0
    assert st_watch["skipped_non_buy_action"] == 2

    rows = [
        {"Mã": "SHB", "Giá": 12000.0, "Expected Return %": 20.0, "MOS%": 50.0, "Khuyến nghị": "BUY"},
        {"Mã": "ACB", "Giá": 22000.0, "Expected Return %": 15.0, "MOS%": 40.0, "Khuyến nghị": "BUY"},
    ]
    st = ptl.open_paper_trades_from_top(rows, source="test", horizon_days=1, path=path)
    assert st["opened"] == 2
    # second open same symbols skipped
    st2 = ptl.open_paper_trades_from_top(rows, source="test", horizon_days=1, path=path)
    assert st2["opened"] == 0
    assert st2["skipped"] == 2

    ledger = ptl.load_ledger(path)
    # backdate due
    past = (datetime.now(timezone.utc) - timedelta(days=2)).isoformat()
    for t in ledger["trades"]:
        t["due_at"] = past
    ptl.save_ledger(ledger, path)

    prices = {"SHB": 13200.0, "ACB": 20000.0}
    res = ptl.resolve_due_trades(fetch_price=lambda s: prices.get(s), path=path)
    assert res["resolved"] == 2
    report = ptl.hitrate_report(lookback_days=30, path=path)
    assert report["samples"] == 2
    assert report["hit_rate_pct"] == 50.0  # SHB up, ACB down


def test_paper_trade_skips_negative_growth(tmp_path: Path) -> None:
    path = tmp_path / "ledger_growth.json"
    rows = [
        {
            "Mã": "HPG",
            "Giá": 25000.0,
            "Khuyến nghị": "BUY",
            "Setup": "ARMED",
            "Trigger": "READY",
            "revenue_growth_yoy": -3.0,
            "profit_growth_yoy": 5.0,
        }
    ]
    st = ptl.open_paper_trades_from_top(rows, source="test", horizon_days=20, path=path)
    assert st["opened"] == 0
    assert st["skipped_non_buy_action"] >= 1


def test_paper_trade_skips_gate_restricted_buy(tmp_path: Path) -> None:
    path = tmp_path / "ledger2.json"
    rows = [
        {
            "Mã": "FPT",
            "Giá": 60000.0,
            "Khuyến nghị": "BUY",
            "is_gate_restricted": True,
            "Expected Return %": 10.0,
            "MOS%": 20.0,
        }
    ]
    st = ptl.open_paper_trades_from_top(rows, source="test", path=path)
    assert st["opened"] == 0
    assert st["skipped_non_buy_action"] >= 1
