from __future__ import annotations

from core.ai_logic import _final_action
from core.decision_action_gate import (
    effective_f_score_for_gate,
    quality_offset_conf_boost,
    should_skip_fscore_hard_demote,
)
from core.probabilistic_forecast_service import signal_alignment_summary
from core.valuation import evaluate_quality_offset, value_investing_summary


def test_quality_offset_triggers_on_f4_roe_cfo() -> None:
    out = evaluate_quality_offset(
        f_score=4,
        roe_pct=22.0,
        cfo=1_200.0,
        net_income=1_000.0,
    )
    assert out["is_quality_compensated"] is True
    assert 5.0 <= float(out["conf_boost"]) <= 10.0
    assert "F-Score 4 được bù trừ" in str(out.get("note_vi") or "")
    assert int(out["effective_f_score_for_buy_gate"]) == 6


def test_quality_offset_rejects_weak_cfo_or_roe() -> None:
    weak_roe = evaluate_quality_offset(f_score=4, roe_pct=15.0, cfo=1200.0, net_income=1000.0)
    assert weak_roe["is_quality_compensated"] is False
    weak_cfo = evaluate_quality_offset(f_score=4, roe_pct=25.0, cfo=500.0, net_income=1000.0)
    assert weak_cfo["is_quality_compensated"] is False
    other_f = evaluate_quality_offset(f_score=5, roe_pct=25.0, cfo=1200.0, net_income=1000.0)
    assert other_f["is_quality_compensated"] is False


def test_value_investing_summary_sets_quality_flag(monkeypatch) -> None:
    import core.valuation as valuation_mod

    monkeypatch.setattr(
        valuation_mod,
        "piotroski_f_score",
        lambda pio: (4, ["forced"]),
    )
    monkeypatch.setattr(
        valuation_mod,
        "_bank_quality_score",
        lambda pio: (4, ["forced"]),
    )
    snap = {
        "symbol": "T",
        "price": 50_000.0,
        "eps": 5_000.0,
        "book_value_per_share": 25_000.0,
        "growth_rate_pct": 8.0,
        "debt_to_equity": 0.3,
        "current_ratio": 2.0,
        "roe": 22.0,
        "operating_cash_flow": 1_200_000_000.0,
        "net_income": 1_000_000_000.0,
        "industry_cluster": "energy_manufacturing",
        "piotroski": {
            "net_income": 1_000_000_000.0,
            "operating_cash_flow": 1_200_000_000.0,
        },
        "source": "test",
    }
    val = value_investing_summary(snap, include_extensions=False)
    assert int(val.get("piotroski_score") or 0) == 4
    assert val.get("is_quality_compensated") is True
    assert "bù trừ" in str(val.get("quality_offset_note_vi") or "")
    assert float((val.get("quality_offset") or {}).get("conf_boost") or 0) >= 5.0


def test_gate_helpers_and_no_hard_demote() -> None:
    val = {
        "piotroski_score": 4,
        "is_quality_compensated": True,
        "quality_offset": {
            "is_quality_compensated": True,
            "conf_boost": 8.0,
            "effective_f_score_for_buy_gate": 6,
            "note_vi": "F-Score 4 được bù trừ nhờ ROE cao & CFO khỏe.",
        },
        "margin_of_safety_composite_pct": 18.0,
        "legend_scorecard": {"graham_pass": True, "buffett_pass": True},
    }
    assert effective_f_score_for_gate(val) >= 6
    assert quality_offset_conf_boost(val) == 8.0
    assert should_skip_fscore_hard_demote(val) is True

    action = _final_action(val, {"phase": "breakout"}, confidence=70.0)
    assert action == "BUY"


def test_signal_alignment_does_not_mark_f4_compensated_as_negative_fund() -> None:
    plain = signal_alignment_summary(
        phase_name="neutral",
        f_score=4,
        mos_pct=10.0,
        news=[],
        quality_compensated=False,
    )
    assert plain["fundamental_signal"] == -1

    compensated = signal_alignment_summary(
        phase_name="neutral",
        f_score=4,
        mos_pct=10.0,
        news=[],
        quality_compensated=True,
    )
    assert compensated["fundamental_signal"] == 0
    assert compensated.get("quality_compensated") is True
