from __future__ import annotations

from core.deep_insight_service import analyze_earnings_quality, analyze_smart_money_flow


def test_analyze_earnings_quality_warns_when_profit_vs_cfo_mismatch() -> None:
    snap = {
        "net_income": 120.0,
        "operating_cash_flow": -20.0,
        "net_income_prior": 90.0,
        "operating_cash_flow_prior": 40.0,
    }
    out = analyze_earnings_quality(snap, {"piotroski_score": 4})
    assert out["warning"] is True
    assert out["severity"] == "high"


def test_analyze_smart_money_flow_bias_bullish() -> None:
    news = [
        {"title": "Khối ngoại mua ròng mạnh cổ phiếu ABC"},
        {"title": "Cổ đông lớn đăng ký mua thêm và tăng sở hữu"},
    ]
    out = analyze_smart_money_flow(news)
    assert out["bias"] == "bullish"
    assert out["score"] >= 2


def test_analyze_smart_money_flow_prefers_structured_events() -> None:
    news = [{"title": "Tin trung tính"}]
    events = [
        {
            "symbol": "ABC",
            "actor_type": "insider",
            "actor_name": "Nguyen Van A",
            "side": "buy",
            "net_value_vnd": 12_000_000_000,
            "confidence": 0.9,
            "source": "exchange",
        },
        {
            "symbol": "ABC",
            "actor_type": "foreign",
            "actor_name": "Khoi ngoai",
            "side": "buy",
            "net_value_vnd": 4_000_000_000,
            "confidence": 0.8,
            "source": "exchange",
        },
    ]
    out = analyze_smart_money_flow(news, symbol="ABC", structured_events=events)
    assert out["bias"] == "bullish"
    assert out["data_mode"] in ("structured", "hybrid")
    assert int(out["structured_event_count"]) == 2
    assert float(out["avg_event_confidence"]) > 0.0
    assert len(out["top_actors"]) >= 1
