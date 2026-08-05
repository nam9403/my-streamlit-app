from __future__ import annotations

from pathlib import Path


def test_generate_report_forces_watch_when_verdict_no_go(monkeypatch) -> None:
    import core.ai_logic as ai

    tmp_audit = Path(".pytest_tmp") / "ai_logic_audit_test.jsonl"
    monkeypatch.setattr(ai, "RECOMMENDATION_AUDIT_PATH", tmp_audit)
    monkeypatch.setattr(
        ai,
        "build_investment_context",
        lambda *args, **kwargs: {
            "technical": {"market_phase": {"phase": "breakout", "reason": "x", "metrics": {"vol_multiple": 1.4}}, "ohlcv": []},
            "valuation": {
                "symbol": "FPT",
                "price": 100.0,
                "composite_target_price": 120.0,
                "margin_of_safety_composite_pct": 20.0,
                "piotroski_score": 8,
            },
            "financials": {"source": "vndirect", "data_quality_score": 4},
            "news": [{"title": "x", "url": "u", "source": "s"}],
        },
    )
    monkeypatch.setattr(ai, "backtest_action_strategy", lambda *args, **kwargs: {"samples": 100, "buy_signals": 10, "buy_win_rate_pct": 60.0})
    monkeypatch.setattr(ai, "_try_parse_json", lambda text: None)
    monkeypatch.setattr(
        ai,
        "_build_fallback_7whys",
        lambda *args, **kwargs: {
            "buy_zone": {"low": 98.0, "high": 102.0},
            "take_profit": 125.0,
            "stop_loss": 95.0,
            "analysis_text": "x",
        },
    )
    monkeypatch.setattr(ai, "_output_quality_gate", lambda *args, **kwargs: {"passed": False, "reasons": ["invalid_price_structure"]})
    monkeypatch.setattr(ai, "_confidence_score", lambda *args, **kwargs: 90.0)
    monkeypatch.setattr(ai, "_final_action", lambda *args, **kwargs: "BUY")

    report = ai.generate_strategic_report("FPT", {"symbol": "FPT", "price": 100.0}, enable_llm=False)
    assert str(report.get("analysis_verdict") or "") == "NO-GO"
    assert str(report.get("final_action") or "") == "WATCH"
    assert isinstance(report.get("data_provenance"), dict)
    assert isinstance(report.get("confidence_explanation"), dict)
    assert isinstance(report.get("do_not_act_reasons"), list)
    assert str(report.get("recommendation_audit_log") or "").endswith("ai_logic_audit_test.jsonl")


def test_generate_report_downgrades_buy_when_smart_money_low_reliability(monkeypatch) -> None:
    import core.ai_logic as ai

    monkeypatch.setattr(
        ai,
        "build_investment_context",
        lambda *args, **kwargs: {
            "technical": {"market_phase": {"phase": "breakout", "reason": "x", "metrics": {"vol_multiple": 1.6}}, "ohlcv": []},
            "valuation": {
                "symbol": "FPT",
                "price": 100.0,
                "composite_target_price": 120.0,
                "margin_of_safety_composite_pct": 20.0,
                "piotroski_score": 8,
            },
            "financials": {"source": "vndirect", "data_quality_score": 4},
            "news": [{"title": "x", "url": "u", "source": "s"}],
        },
    )
    monkeypatch.setattr(ai, "backtest_action_strategy", lambda *args, **kwargs: {"samples": 100, "buy_signals": 10, "buy_win_rate_pct": 60.0})
    monkeypatch.setattr(ai, "_try_parse_json", lambda text: None)
    monkeypatch.setattr(
        ai,
        "_build_fallback_7whys",
        lambda *args, **kwargs: {
            "buy_zone": {"low": 98.0, "high": 102.0},
            "take_profit": 125.0,
            "stop_loss": 95.0,
            "analysis_text": "x",
        },
    )
    monkeypatch.setattr(ai, "_output_quality_gate", lambda *args, **kwargs: {"passed": True, "reasons": []})
    monkeypatch.setattr(ai, "_confidence_score", lambda *args, **kwargs: 88.0)
    monkeypatch.setattr(ai, "_final_action", lambda *args, **kwargs: "BUY")
    monkeypatch.setattr(
        ai,
        "analyze_smart_money_flow",
        lambda *args, **kwargs: {
            "bias": "bullish",
            "score": 3.0,
            "signals": ["+ flow"],
            "label": "ok",
            "data_mode": "heuristic",
            "structured_event_count": 0,
            "avg_event_confidence": 0.0,
        },
    )

    report = ai.generate_strategic_report("FPT", {"symbol": "FPT", "price": 100.0}, enable_llm=False)
    assert str(report.get("smart_money_reliability") or "") == "LOW"
    assert str(report.get("final_action") or "") == "HOLD"

