from __future__ import annotations

from core.ai_logic import (
    _analysis_verdict,
    _data_reliability_breakdown,
    _data_reliability_score,
    _decision_readiness_label,
)


def test_data_reliability_score_low_when_sources_weak() -> None:
    rel = {
        "technical": {"ok": False},
        "financial": {"quality_score": 1},
        "news": {"count": 0},
        "backtest": {"ok": False},
    }
    score = _data_reliability_score(rel)
    assert score < 55.0


def test_data_reliability_score_high_when_sources_strong() -> None:
    rel = {
        "technical": {"ok": True},
        "financial": {"quality_score": 5},
        "news": {"count": 5},
        "backtest": {"ok": True},
    }
    score = _data_reliability_score(rel)
    assert score >= 80.0


def test_data_reliability_breakdown_maps_to_0_100() -> None:
    rel = {
        "technical": {"ok": True},
        "financial": {"quality_score": 3},
        "news": {"count": 2},
        "backtest": {"ok": False},
    }
    br = _data_reliability_breakdown(rel)
    assert br["technical_score"] == 100.0
    assert br["financial_score"] == 60.0
    assert br["news_score"] == 40.0
    assert br["backtest_score"] == 0.0


def test_decision_readiness_label_requires_all_gates() -> None:
    lv = _decision_readiness_label(
        confidence_score=82.0,
        reliability_score=84.0,
        confidence_gate_passed=True,
        output_gate_passed=True,
        reliability_gate_passed=True,
    )
    assert lv == "HIGH"
    lv2 = _decision_readiness_label(
        confidence_score=82.0,
        reliability_score=84.0,
        confidence_gate_passed=False,
        output_gate_passed=True,
        reliability_gate_passed=True,
    )
    assert lv2 == "LOW"


def test_analysis_verdict_no_go_when_any_gate_fails() -> None:
    verdict = _analysis_verdict(
        final_action="BUY",
        confidence_score=85.0,
        reliability_score=80.0,
        confidence_gate_passed=False,
        output_gate_passed=True,
        reliability_gate_passed=True,
        decision_readiness="HIGH",
    )
    assert verdict == "NO-GO"


def test_analysis_verdict_go_for_strong_buy_setup() -> None:
    verdict = _analysis_verdict(
        final_action="BUY",
        confidence_score=82.0,
        reliability_score=75.0,
        confidence_gate_passed=True,
        output_gate_passed=True,
        reliability_gate_passed=True,
        decision_readiness="HIGH",
    )
    assert verdict == "GO"


def test_analysis_verdict_caution_for_non_buy_actions() -> None:
    verdict = _analysis_verdict(
        final_action="HOLD",
        confidence_score=79.0,
        reliability_score=73.0,
        confidence_gate_passed=True,
        output_gate_passed=True,
        reliability_gate_passed=True,
        decision_readiness="MEDIUM",
    )
    assert verdict == "CAUTION"

