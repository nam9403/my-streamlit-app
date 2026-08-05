"""Autopilot ranking must respect decision gate + negative CFO (PNJ-style traps)."""

from __future__ import annotations

from core import autopilot_nightly_board as nb
from core.decision_action_gate import (
    apply_gate_fields_to_scan_row,
    classify_cfo_status,
    evaluate_autopilot_gate_restriction,
)


def _ready_row(
    sym: str,
    *,
    mos: float,
    exp: float,
    action: str = "WATCH",
    cfo_status: str = "POSITIVE",
    restricted: bool = False,
    verdict: str = "CAUTION",
) -> dict:
    return {
        "Mã": sym,
        "Tiểu ngành": "Bán lẻ",
        "Khuyến nghị": action,
        "gate_action": action,
        "cfo_status": cfo_status,
        "is_gate_restricted": restricted,
        "score_penalty_mult": 0.5 if restricted else 1.0,
        "analysis_verdict": verdict,
        "Khung thời gian": "Trung hạn (2-6 tháng)",
        "Giá": 30000.0,
        "MOS%": mos,
        "Expected Return %": exp,
        "Risk % (ước tính)": 18.0,
        "Trạng thái": "Sẵn sàng",
        "Readiness": "LOW" if restricted else "MEDIUM",
    }


def test_classify_cfo_negative() -> None:
    assert classify_cfo_status(-302_139_905_578) == "NEGATIVE"
    assert classify_cfo_status(1_000_000) == "POSITIVE"
    assert classify_cfo_status(None) == "UNKNOWN"
    assert classify_cfo_status(-1, is_bank=True) == "UNKNOWN"


def test_evaluate_restriction_on_negative_cfo_report() -> None:
    rep = {
        "final_action": "WATCH",
        "gate_passed": False,
        "output_gate_passed": True,
        "analysis_verdict": "NO-GO",
        "decision_readiness": "LOW",
        "valuation": {"instant_conclusion": "Bỏ qua", "is_bank_sector": False},
        "financials": {"operating_cash_flow": -302_139_905_578.0},
        "phase": {"phase": "distribution"},
    }
    flags = evaluate_autopilot_gate_restriction(rep)
    assert flags["cfo_status"] == "NEGATIVE"
    assert flags["is_gate_restricted"] is True
    assert flags["score_penalty_mult"] == 0.5
    assert "cfo_negative" in flags["gate_restrict_reasons"]


def test_pnj_negative_cfo_not_in_top3_recommended_board() -> None:
    """
    Regression: high MOS/ER alone must not put negative-CFO PNJ into Top 3
    recommended Autopilot board (align with full decision gate / chat deep dive).
    """
    board = nb.empty_board(profile="growth", universe_mode="dynamic_liquid")
    board["target_symbols"] = ["PNJ", "ACB", "SHB", "CTG", "TPB"]
    board["rows"] = {
        "PNJ": _ready_row(
            "PNJ",
            mos=67.5,
            exp=41.0,
            action="WATCH",
            cfo_status="NEGATIVE",
            restricted=True,
            verdict="NO-GO",
        ),
        "ACB": _ready_row("ACB", mos=49.0, exp=39.0, action="HOLD", cfo_status="POSITIVE"),
        "SHB": _ready_row("SHB", mos=63.0, exp=40.0, action="WATCH", cfo_status="POSITIVE"),
        "CTG": _ready_row("CTG", mos=51.0, exp=38.0, action="WATCH", cfo_status="POSITIVE"),
        "TPB": _ready_row("TPB", mos=57.0, exp=36.0, action="WATCH", cfo_status="POSITIVE"),
    }
    top = nb.top_n_from_board(board, top_n=3, ready_only=True, recommended_only=True)
    symbols = list(top["Mã"])
    assert "PNJ" not in symbols
    assert len(symbols) == 3
    # Title should not claim "Khuyên Mua" when no BUY present
    assert "Theo Dõi" in str(top.attrs.get("board_title_vi") or "") or "Giữ" in str(
        top.attrs.get("board_title_vi") or ""
    )


def test_apply_gate_fields_persists_cfo_and_gate_action() -> None:
    rep = {
        "final_action": "WATCH",
        "gate_passed": True,
        "output_gate_passed": True,
        "analysis_verdict": "NO-GO",
        "decision_readiness": "LOW",
        "valuation": {"instant_conclusion": "Theo dõi", "is_bank_sector": False, "price": 32650},
        "financials": {"operating_cash_flow": -1.0},
        "phase": {"phase": "distribution"},
        "decision_completeness": {"completeness_score": 40, "severity": "medium", "missing_items": []},
    }
    row = apply_gate_fields_to_scan_row({}, rep, financials=rep["financials"], valuation=rep["valuation"])
    assert row["cfo_status"] == "NEGATIVE"
    assert row["gate_action"] == "WATCH"
    assert row["is_gate_restricted"] is True
    assert row["Khuyến nghị"] == "WATCH"


def test_score_rows_penalizes_restricted_half() -> None:
    rows = [
        _ready_row("OK1", mos=50, exp=30, action="WATCH", restricted=False),
        _ready_row("BAD", mos=90, exp=60, action="WATCH", cfo_status="NEGATIVE", restricted=True),
    ]
    scored = nb.score_rows(rows)
    # Restricted sorts after non-restricted regardless of raw MOS
    assert list(scored["Mã"])[0] == "OK1"
    bad = scored.loc[scored["Mã"] == "BAD"].iloc[0]
    ok = scored.loc[scored["Mã"] == "OK1"].iloc[0]
    assert float(bad["__score"]) < float(ok["__score"])
