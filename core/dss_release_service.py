from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


def _as_float(v: Any, default: float = 0.0) -> float:
    try:
        if v is None:
            return default
        return float(v)
    except (TypeError, ValueError):
        return default


def evaluate_dss_readiness(
    report: dict[str, Any],
    backtesting_report: dict[str, Any] | None = None,
    *,
    engine_backtest: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Đánh giá mức sẵn sàng thương mại DSS dựa trên report runtime.

    Ưu tiên forecast accountability backtest; nếu thiếu thì fallback
    ``engine_backtest`` (buy_win_rate_pct / buy_signals từ OHLCV strategy).
    """
    fc = (report or {}).get("probabilistic_forecast") or {}
    fr = fc.get("forecast_range") or {}
    pp = (report or {}).get("portfolio_protector") or {}
    deep = (report or {}).get("deep_insight") or {}
    eq = deep.get("earnings_quality") or {}
    sm = deep.get("smart_money_flow") or {}
    bt = dict(backtesting_report or {})
    bt_source = "forecast_accountability"
    if bt.get("win_rate_pct") is None and isinstance(engine_backtest, dict) and engine_backtest:
        # Map schema engine → DSS checks (fallback, không thay forecast accountability).
        wr = engine_backtest.get("buy_win_rate_pct")
        samples = engine_backtest.get("buy_signals")
        if samples is None:
            samples = engine_backtest.get("samples")
        if wr is not None:
            bt["win_rate_pct"] = wr
        if samples is not None:
            bt["predicted_up_samples"] = samples
        bt_source = "engine_action_backtest_fallback"

    checks = {
        "forecast_range_available": all(fr.get(k) is not None for k in ("p10_price", "p50_price", "p90_price")),
        "forecast_probability_available": fr.get("prob_reach_target_pct") is not None,
        "portfolio_optimizer_available": bool(pp.get("optimized_weights")),
        "stress_test_available": isinstance(pp.get("stress_test"), list) and len(pp.get("stress_test")) >= 2,
        "earnings_quality_guard_available": eq.get("label") is not None,
        "smart_money_bias_available": sm.get("bias") is not None,
        "smart_money_structured_available": str(sm.get("data_mode") or "heuristic") in ("structured", "hybrid"),
        "backtesting_winloss_available": bt.get("win_rate_pct") is not None,
        "backtesting_sample_sufficient": int(bt.get("predicted_up_samples") or 0) >= 10,
    }

    score = 0.0
    score += 16.0 if checks["forecast_range_available"] else 0.0
    score += 10.0 if checks["forecast_probability_available"] else 0.0
    score += 14.0 if checks["portfolio_optimizer_available"] else 0.0
    score += 10.0 if checks["stress_test_available"] else 0.0
    score += 10.0 if checks["earnings_quality_guard_available"] else 0.0
    score += 5.0 if checks["smart_money_bias_available"] else 0.0
    score += 5.0 if checks["smart_money_structured_available"] else 0.0
    score += 15.0 if checks["backtesting_winloss_available"] else 0.0
    score += 15.0 if checks["backtesting_sample_sufficient"] else 0.0
    score = round(score, 2)

    if score >= 85:
        decision = "COMMERCIAL_READY"
    elif score >= 65:
        decision = "NEAR_READY"
    else:
        decision = "NOT_READY"

    missing = [k for k, ok in checks.items() if not ok]
    return {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "decision": decision,
        "commercial_score": score,
        "checks": checks,
        "missing_items": missing,
        "backtesting_source": bt_source,
        "summary_vi": (
            f"DSS commercial score={score:.2f}. "
            f"Trạng thái={decision}. "
            + ("Đã sẵn sàng thương mại hóa." if decision == "COMMERCIAL_READY" else "Cần bổ sung một số hạng mục trước khi scale trả phí.")
        ),
    }
