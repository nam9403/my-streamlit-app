"""P1 decision playbook — Thesis/Setup/Trigger, regime, CONDITIONAL_BUY, MC sanity."""

from __future__ import annotations

from datetime import date

import pandas as pd

from core.decision_action_gate import (
    action_display_vi,
    apply_trade_plan_visibility,
    normalize_action,
    resolve_display_action,
)
from core.decision_playbook import (
    apply_playbook_to_action,
    build_decision_playbook,
    evaluate_setup,
    evaluate_thesis,
    evaluate_trigger,
    resolve_playbook_action,
)
from core.forecast_range_sanity import assess_forecast_range_sanity, estimate_atr_pct
from core.market_regime import assess_market_regime, assess_vnindex_tape


def _val(**kwargs):
    base = {
        "margin_of_safety_composite_pct": 30.0,
        "piotroski_score": 6,
        "instant_conclusion": "Mua mạnh",
        "legend_scorecard": {"graham_pass": True, "buffett_pass": True, "lynch_pass": True},
        "is_bank_sector": False,
        "price": 10000.0,
        "mos_integrity_blocked": False,
    }
    base.update(kwargs)
    return base


def _phase(name: str = "neutral", **metrics):
    m = {"vol_multiple": 1.0, "ma50": 9500.0, "rsi_indicator_fail": False}
    m.update(metrics)
    return {"phase": name, "reason": "t", "metrics": m}


def test_normalize_conditional_buy() -> None:
    assert normalize_action("CONDITIONAL_BUY") == "CONDITIONAL_BUY"
    assert normalize_action("MUA CÓ ĐIỀU KIỆN") == "CONDITIONAL_BUY"
    assert action_display_vi("CONDITIONAL_BUY") == "MUA CÓ ĐIỀU KIỆN"


def test_thesis_grades_attractive_vs_weak() -> None:
    strong = evaluate_thesis(_val())
    assert strong["grade"] in ("A", "B")
    assert strong["attractive"] is True
    weak = evaluate_thesis(
        _val(
            margin_of_safety_composite_pct=-40.0,
            piotroski_score=1,
            instant_conclusion="Bỏ qua",
            legend_scorecard={"graham_pass": False, "buffett_pass": False, "lynch_pass": False},
        )
    )
    assert weak["grade"] == "C"


def test_setup_abort_on_distribution_and_integrity() -> None:
    abort = evaluate_setup(_phase("distribution"))
    assert abort["status"] == "ABORT"
    wait = evaluate_setup(_phase("neutral"), market_regime={"label": "risk_on"})
    assert wait["status"] == "WAIT"
    armed = evaluate_setup(_phase("accumulation"), market_regime={"label": "risk_on"})
    assert armed["status"] == "ARMED"
    fail = evaluate_setup(
        _phase("accumulation"),
        ohlcv_integrity={"critical": True, "block_phase": True},
    )
    assert fail["status"] == "ABORT"


def test_trigger_ready_when_price_in_zone_and_armed() -> None:
    rp = {"buy_zone_low": 9800.0, "buy_zone_high": 10200.0, "entry_price": 10000.0, "stop_loss_price": 9200.0}
    ready = evaluate_trigger(price=10000.0, risk_plan=rp, phase=_phase("accumulation"), setup_status="ARMED")
    assert ready["status"] == "READY"
    assert ready["in_buy_zone"] is True
    pending = evaluate_trigger(price=11000.0, risk_plan=rp, phase=_phase("neutral"), setup_status="WAIT")
    assert pending["status"] == "PENDING"
    invalid = evaluate_trigger(price=10000.0, risk_plan=rp, phase=_phase("distribution"), setup_status="ABORT")
    assert invalid["status"] == "INVALID"


def test_playbook_hold_when_attractive_but_timing_wait() -> None:
    """Tune: MOS hấp dẫn + phase neutral (WAIT) → HOLD, không COND sớm."""
    pb = build_decision_playbook(
        valuation=_val(margin_of_safety_composite_pct=35.0, piotroski_score=5),
        phase=_phase("neutral"),
        financials={"revenue_growth_yoy": 12.0},
        confidence=70.0,
        risk_plan={"buy_zone_low": 9800.0, "buy_zone_high": 10200.0, "entry_price": 10000.0, "stop_loss_price": 9200.0, "max_position_pct": 20.0},
        market_regime={"label": "neutral", "size_mult": 0.7, "allow_hard_buy": False},
        data_trust={"band": "HIGH", "score": 85},
    )
    assert pb["recommended_action"] == "HOLD"
    assert pb["thesis"]["grade"] in ("A", "B")
    assert pb["setup"]["status"] == "WAIT"
    assert float(pb["size_cap_pct"]) == 0.0


def test_playbook_conditional_requires_armed_ready() -> None:
    pb = build_decision_playbook(
        valuation=_val(margin_of_safety_composite_pct=28.0, piotroski_score=6),
        phase=_phase("accumulation", vol_multiple=1.0),
        financials={"revenue_growth_yoy": 10.0},
        confidence=68.0,
        risk_plan={"buy_zone_low": 9800.0, "buy_zone_high": 10200.0, "entry_price": 10000.0, "stop_loss_price": 9200.0},
        market_regime={"label": "neutral", "size_mult": 0.7, "allow_hard_buy": False},
        data_trust={"band": "HIGH", "score": 85},
        as_of=date(2025, 3, 15),  # outside earnings season
    )
    assert pb["setup"]["status"] == "ARMED"
    assert pb["trigger"]["status"] == "READY"
    assert pb["recommended_action"] in ("CONDITIONAL_BUY", "BUY")


def test_playbook_hard_buy_when_all_layers_and_risk_on() -> None:
    pb = build_decision_playbook(
        valuation=_val(margin_of_safety_composite_pct=40.0, piotroski_score=7),
        phase=_phase("breakout", vol_multiple=1.8),
        financials={"revenue_growth_yoy": 20.0},
        confidence=80.0,
        risk_plan={"buy_zone_low": 9800.0, "buy_zone_high": 10200.0, "entry_price": 10000.0, "stop_loss_price": 9200.0, "max_position_pct": 20.0},
        market_regime={"label": "risk_on", "size_mult": 1.0, "allow_hard_buy": True},
        data_trust={"band": "HIGH", "score": 90},
        deep_insight={"smart_money_flow": {"bias": "bullish"}, "earnings_quality": {"warning": False}},
        as_of=date(2025, 3, 15),  # outside earnings season
    )
    assert pb["recommended_action"] == "BUY"
    assert pb["setup"]["status"] == "ARMED"
    assert pb["trigger"]["status"] == "READY"


def test_risk_off_blocks_hard_buy() -> None:
    resolved = resolve_playbook_action(
        thesis={"grade": "A", "attractive": True, "mos_pct": 30, "f_score": 7},
        setup={"status": "ARMED"},
        trigger={"status": "READY"},
        confidence=80.0,
        market_regime={"label": "risk_off", "size_mult": 0.35, "allow_hard_buy": False},
    )
    assert resolved["recommended_action"] == "CONDITIONAL_BUY"
    assert float(resolved["size_cap_pct"]) <= 12.0


def test_apply_playbook_upgrades_watch_to_conditional() -> None:
    pb = {"recommended_action": "CONDITIONAL_BUY", "setup": {"status": "WAIT"}}
    assert apply_playbook_to_action("WATCH", pb) == "CONDITIONAL_BUY"
    assert apply_playbook_to_action("AVOID", {"recommended_action": "BUY", "setup": {"status": "ARMED"}}) == "AVOID"


def test_resolve_display_shows_conditional_trade_plan() -> None:
    rep = {
        "final_action": "CONDITIONAL_BUY",
        "gate_passed": True,
        "output_gate_passed": True,
        "analysis_verdict": "CAUTION",
        "decision_playbook": {
            "thesis": {"grade": "A", "attractive": True},
            "setup": {"status": "WAIT"},
            "trigger": {
                "entry_hint_vi": "Chờ giá vào vùng",
                "cancel_if_vi": "Hủy nếu mất 9000",
                "invalidation_price": 9000.0,
            },
            "size_cap_pct": 10.0,
        },
        "decision_alignment": {"unified_action": "CONDITIONAL_BUY", "note_vi": ""},
        "risk_plan": {"entry_price": 10000.0, "stop_loss_price": 9200.0, "take_profit_price": 12000.0},
    }
    gate = resolve_display_action(rep)
    assert gate["display_action"] == "CONDITIONAL_BUY"
    assert gate["show_trade_plan"] is True
    assert gate["is_conditional"] is True
    out = apply_trade_plan_visibility(rep)
    assert out["show_trade_plan"] is True
    assert out["is_conditional_buy"] is True
    assert "điều kiện" in str(out["risk_plan"].get("display_note_vi") or "").lower() or out["risk_plan"].get("cancel_if_vi")


def test_market_regime_from_synthetic_tape() -> None:
    rows = []
    for i in range(40):
        c = 1000.0 + i * 2.0  # uptrend
        rows.append({"open": c - 1, "high": c + 2, "low": c - 2, "close": c, "volume": 1_000_000})
    tape = assess_vnindex_tape(pd.DataFrame(rows))
    assert tape["ok"] is True
    regime = assess_market_regime(vnindex_ohlcv=pd.DataFrame(rows), macro={"market_bias": 0.3, "source": "test"})
    assert regime["label"] in ("risk_on", "neutral", "risk_off")
    assert "size_mult" in regime


def test_forecast_range_sanity_rejects_absurd_p10() -> None:
    ok = assess_forecast_range_sanity(price=22000.0, p10=20000.0, p50=22000.0, p90=25000.0, atr_pct=2.0, horizon_days=90)
    assert ok["ok"] is True
    bad = assess_forecast_range_sanity(price=22000.0, p10=6429.0, p50=16251.0, p90=40923.0, atr_pct=2.0, horizon_days=90)
    assert bad["ok"] is False
    assert bad["issues"]


def test_atr_pct_on_clean_series() -> None:
    rows = []
    for i in range(40):
        c = 100.0 + i * 0.1
        rows.append({"open": c, "high": c + 1, "low": c - 1, "close": c, "volume": 1000})
    atr = estimate_atr_pct(pd.DataFrame(rows))
    assert atr is not None and atr > 0


def test_bank_thesis_uses_quality_not_industrial_only() -> None:
    t = evaluate_thesis(
        _val(
            is_bank_sector=True,
            piotroski_score=5,
            roe_5y_avg=18.0,
            margin_of_safety_composite_pct=25.0,
        ),
        {"roe": 18.0},
    )
    assert t["is_bank"] is True
    assert t["grade"] in ("A", "B")
