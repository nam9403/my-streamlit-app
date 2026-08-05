from __future__ import annotations

import os
from typing import Any, Callable


def recommend_task_mode(
    user_id: str,
    ticker: str,
    quick_mode: bool,
    *,
    get_forecast_benchmark_by_horizon: Callable[..., list[dict[str, Any]]],
    universe_subtype_map: Callable[[], dict[str, str]],
    get_forecast_group_benchmark: Callable[..., dict[str, Any]],
) -> str:
    if quick_mode:
        return "speed"
    bench_rows = get_forecast_benchmark_by_horizon(user_id, ticker, horizons=(30, 60, 90))
    valid = [x for x in bench_rows if int(x.get("samples") or 0) >= 3]
    # Sector-aware fallback when single-symbol history is thin.
    if len(valid) < 2:
        s_map = universe_subtype_map()
        subtype = str(s_map.get(str(ticker or "").strip().upper(), "other"))
        peers = [s for s, st in s_map.items() if str(st) == subtype][:25]
        gb = get_forecast_group_benchmark(user_id, peers)
        if int(gb.get("samples") or 0) >= 8:
            hit = float(gb.get("hit_rate_pct") or 0.0)
            mape = float(gb.get("mape_pct") or 99.0)
            alpha = float(gb.get("alpha_pct") or 0.0)
            if hit >= 62 and mape <= 9 and alpha >= -1:
                return "speed"
            if hit < 52 or mape > 14 or alpha < -3:
                return "quality"
            return "balanced"
    if not valid:
        return "balanced"
    hit = sum(float(x.get("hit_rate_pct") or 0.0) for x in valid) / len(valid)
    mape = sum(float(x.get("mape_pct") or 0.0) for x in valid) / len(valid)
    alpha = sum(float(x.get("alpha_pct") or 0.0) for x in valid) / len(valid)
    if hit >= 62 and mape <= 9 and alpha >= -1:
        return "speed"
    if hit < 52 or mape > 14 or alpha < -3:
        return "quality"
    return "balanced"


def apply_drift_guardrails(
    user_id: str,
    ticker: str,
    report: dict[str, Any],
    task_mode: str,
    *,
    get_forecast_drift_signal: Callable[..., dict[str, Any]],
    get_forecast_drift_streak: Callable[..., dict[str, Any]],
    get_forecast_accuracy_dashboard: Callable[..., dict[str, Any]] | None = None,
) -> tuple[dict[str, Any], str]:
    from core.forecast_metrics import mape_safety_should_downgrade

    d = get_forecast_drift_signal(user_id, ticker, recent_n=20, baseline_n=60)
    streak = get_forecast_drift_streak(user_id, ticker, checks=3)
    drift_streak = int(streak.get("drift_down_streak") or 0)
    forced_mode = task_mode
    applied_drift = str(d.get("status")) == "drift_down" or drift_streak >= 2
    if applied_drift:
        # Auto reaction: escalate mode and reduce risk sizing.
        forced_mode = "quality"
        rp = dict(report.get("risk_plan") or {})
        orig_pct = float(rp.get("max_position_pct") or 20.0)
        new_pct = max(5.0, round(orig_pct * 0.75, 2))
        if rp:
            rp["max_position_pct"] = new_pct
            alloc = float(rp.get("allocated_capital_vnd") or 0.0)
            if alloc > 0:
                rp["allocated_capital_vnd"] = round(alloc * 0.75, 2)
            report["risk_plan"] = rp
        report["drift_guardrails"] = {
            "applied": True,
            "status": "drift_down",
            "drift_streak": drift_streak,
            "forced_task_mode": forced_mode,
            "max_position_pct_before": orig_pct,
            "max_position_pct_after": new_pct,
        }
    else:
        report["drift_guardrails"] = {"applied": False, "status": d.get("status")}

    # Safety Gate: MAPE chuẩn → hạ BUY xuống HOLD/WATCH khi sai số vượt ngưỡng.
    mape_gate: dict[str, Any] = {"applied": False}
    if get_forecast_accuracy_dashboard is not None:
        try:
            acc = get_forecast_accuracy_dashboard(user_id, ticker) or {}
        except Exception:
            acc = {}
        mape = acc.get("mape_pct")
        samples = int(acc.get("resolved") or 0)
        downgrade = mape_safety_should_downgrade(mape_pct=mape if isinstance(mape, (int, float)) else None, samples=samples)
        if downgrade:
            prev_action = str(report.get("final_action") or "WATCH").upper()
            if prev_action in ("BUY", "STRONG_BUY", "HOLD") and (
                downgrade == "WATCH" or (downgrade == "HOLD" and prev_action in ("BUY", "STRONG_BUY"))
            ):
                report["final_action"] = downgrade
                report["gate_passed"] = False if downgrade == "WATCH" else report.get("gate_passed", True)
                note = (
                    f"Safety Gate MAPE: sai số trung bình {float(mape):.1f}% trên {samples} mẫu "
                    f"(ngưỡng HOLD>9% / WATCH>14%) → hạ từ {prev_action} xuống {downgrade}."
                )
                prev_notes = str(report.get("action_reason") or "").strip()
                report["action_reason"] = f"{prev_notes} {note}".strip() if prev_notes else note
                mape_gate = {
                    "applied": True,
                    "mape_pct": float(mape),
                    "samples": samples,
                    "from_action": prev_action,
                    "to_action": downgrade,
                }
    report["mape_safety_gate"] = mape_gate
    return report, forced_mode


def calibrate_report_forecast_with_history(
    user_id: str,
    ticker: str,
    report: dict[str, Any],
    *,
    get_forecast_accuracy_dashboard: Callable[..., dict[str, Any]],
) -> dict[str, Any]:
    fc = dict((report or {}).get("probabilistic_forecast") or {})
    scenarios = list(fc.get("scenarios") or [])
    if not fc or not scenarios:
        report["forecast_calibration"] = {"applied": False, "reason": "missing_forecast"}
        return report

    acc = get_forecast_accuracy_dashboard(user_id, ticker)
    resolved = int(acc.get("resolved") or 0)
    bias = acc.get("bias_pct")
    min_records_raw = os.environ.get("AI_FORECAST_CALIB_MIN_RECORDS", "8").strip()
    try:
        min_records = max(3, min(100, int(min_records_raw)))
    except ValueError:
        min_records = 8
    if not isinstance(bias, (float, int)) or resolved < min_records:
        report["forecast_calibration"] = {
            "applied": False,
            "reason": "insufficient_history",
            "resolved_records": resolved,
            "min_required": min_records,
        }
        return report

    # realized - expected = bias; move forecast toward realized partially (shrink to avoid overfit).
    factor_raw = os.environ.get("AI_FORECAST_BIAS_FACTOR", "0.35").strip()
    try:
        factor = float(factor_raw)
    except ValueError:
        factor = 0.35
    factor = max(0.1, min(0.8, factor))
    shift_pct = float(bias) * factor

    base_price = float((report.get("valuation") or {}).get("price") or 0.0)
    if base_price <= 0:
        report["forecast_calibration"] = {"applied": False, "reason": "missing_base_price"}
        return report

    exp_ret = fc.get("expected_return_pct")
    if isinstance(exp_ret, (float, int)):
        new_exp_ret = float(exp_ret) + shift_pct
        fc["expected_return_pct"] = round(new_exp_ret, 2)
        fc["expected_price"] = round(base_price * (1.0 + new_exp_ret / 100.0), 2)

    new_scenarios: list[dict[str, Any]] = []
    for row in scenarios:
        r = dict(row)
        r_ret = r.get("return_pct")
        if isinstance(r_ret, (float, int)):
            r_ret = float(r_ret) + shift_pct
            r["return_pct"] = round(r_ret, 2)
            r["target_price"] = round(base_price * (1.0 + r_ret / 100.0), 2)
        new_scenarios.append(r)
    fc["scenarios"] = new_scenarios
    fc["summary"] = str(fc.get("summary") or "") + f" (đã hiệu chỉnh bias {shift_pct:+.2f}%)."
    report["probabilistic_forecast"] = fc
    report["forecast_calibration"] = {
        "applied": True,
        "bias_pct": round(float(bias), 2),
        "shift_pct": round(shift_pct, 2),
        "factor": round(factor, 2),
        "resolved_records": resolved,
    }
    return report
