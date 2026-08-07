from __future__ import annotations

from typing import Any, Callable

import pandas as pd
import streamlit as st


def _as_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def render_forecast_accuracy(
    user_id: str,
    ticker: str,
    *,
    get_forecast_accuracy_dashboard: Callable[..., dict[str, Any]],
) -> None:
    st.markdown("#### 🎯 Độ chính xác dự báo thực tế")
    acc = get_forecast_accuracy_dashboard(user_id, ticker)
    total = int(acc.get("records") or 0)
    resolved = int(acc.get("resolved") or 0)
    hit = acc.get("hit_rate_pct")
    mape = acc.get("mape_pct")
    bias = acc.get("bias_pct")
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        st.metric("Tổng bản ghi", total)
    with c2:
        st.metric("Đã đối chiếu", resolved)
    with c3:
        st.metric("Hit-rate thực tế", f"{float(hit):.1f}%" if isinstance(hit, (float, int)) else "N/A")
    with c4:
        st.metric("Sai số TB (MAPE proxy)", f"{float(mape):.1f}%" if isinstance(mape, (float, int)) else "N/A")
    if isinstance(bias, (float, int)):
        if bias > 0:
            st.caption(f"Bias: +{float(bias):.2f}% (mô hình đang hơi bảo thủ, thực tế tốt hơn dự báo).")
        elif bias < 0:
            st.caption(f"Bias: {float(bias):.2f}% (mô hình đang hơi lạc quan, cần thận trọng).")
        else:
            st.caption("Bias: gần 0% (khá cân bằng giữa kỳ vọng và thực tế).")


def render_forecast_benchmark(
    user_id: str,
    ticker: str,
    *,
    get_forecast_benchmark_by_horizon: Callable[..., list[dict[str, Any]]],
) -> None:
    st.markdown("#### 🧪 Benchmark thực chiến 30/60/90 ngày")
    rows = get_forecast_benchmark_by_horizon(user_id, ticker, horizons=(30, 60, 90))
    if not rows:
        st.caption("Chưa có dữ liệu benchmark.")
        return
    df = pd.DataFrame(rows)
    if df.empty:
        st.caption("Chưa có dữ liệu benchmark.")
        return
    view = df.copy()
    for col in (
        "hit_rate_pct",
        "mape_pct",
        "expected_return_pct_avg",
        "realized_return_pct_avg",
        "alpha_pct",
        "beat_expected_pct",
    ):
        if col in view.columns:
            view[col] = view[col].map(lambda x: f"{float(x):.2f}%" if isinstance(x, (float, int)) else "N/A")
    view = view.rename(
        columns={
            "horizon_days": "Horizon",
            "samples": "Mẫu",
            "hit_rate_pct": "Hit-rate",
            "mape_pct": "Sai số TB",
            "expected_return_pct_avg": "Dự báo TB",
            "realized_return_pct_avg": "Thực tế TB",
            "alpha_pct": "Alpha (thực tế-dự báo)",
            "beat_expected_pct": "Tỷ lệ vượt dự báo",
        }
    )
    st.dataframe(view, use_container_width=True, hide_index=True)
    st.caption("Alpha dương: thực tế tốt hơn dự báo trung bình. Alpha âm: mô hình đang hơi lạc quan.")


def render_model_drift_panel(
    user_id: str,
    ticker: str,
    *,
    get_forecast_drift_signal: Callable[..., dict[str, Any]],
    get_forecast_drift_streak: Callable[..., dict[str, Any]],
) -> None:
    st.markdown("#### 📉 Theo dõi model drift")
    d = get_forecast_drift_signal(user_id, ticker, recent_n=20, baseline_n=60)
    status = str(d.get("status") or "unknown")
    msg = str(d.get("message") or "")
    dh = d.get("delta_hit_pct")
    dm = d.get("delta_mape_pct")
    if status == "drift_down":
        st.warning(msg)
    elif status == "improving":
        st.success(msg)
    else:
        st.caption(msg)
    if isinstance(dh, (float, int)) and isinstance(dm, (float, int)):
        st.caption(f"So với baseline: delta hit-rate = {float(dh):+.2f}% | delta sai số = {float(dm):+.2f}%")
    h_th = d.get("hit_drop_threshold_pct")
    m_th = d.get("mape_rise_threshold_pct")
    if isinstance(h_th, (float, int)) and isinstance(m_th, (float, int)):
        st.caption(f"Ngưỡng drift thích ứng: hit <= -{float(h_th):.2f}% hoặc sai số >= +{float(m_th):.2f}%")
    streak = get_forecast_drift_streak(user_id, ticker, checks=3)
    st.caption(
        f"Drift down streak: {int(streak.get('drift_down_streak') or 0)}/{int(streak.get('checks') or 0)} kỳ gần nhất."
    )


def render_forecast_portfolio_dashboard(
    user_id: str,
    *,
    get_forecast_portfolio_dashboard: Callable[..., dict[str, Any]],
) -> None:
    st.markdown("#### 📊 Dashboard hiệu năng danh mục")
    d = get_forecast_portfolio_dashboard(user_id)
    w = d.get("weekly") or {}
    m = d.get("monthly") or {}
    o = d.get("overall") or {}
    c1, c2, c3 = st.columns(3)
    with c1:
        st.metric(
            "Weekly hit-rate",
            f"{_as_float(w.get('hit_rate_pct')):.1f}%" if isinstance(w.get("hit_rate_pct"), (float, int)) else "N/A",
        )
        st.caption(f"Mẫu: {int(w.get('samples') or 0)}")
    with c2:
        st.metric(
            "Monthly hit-rate",
            f"{_as_float(m.get('hit_rate_pct')):.1f}%" if isinstance(m.get("hit_rate_pct"), (float, int)) else "N/A",
        )
        st.caption(f"Mẫu: {int(m.get('samples') or 0)}")
    with c3:
        st.metric("Overall MAPE", f"{_as_float(o.get('mape_pct')):.1f}%" if isinstance(o.get("mape_pct"), (float, int)) else "N/A")
        st.caption(
            f"Alpha tổng: {_as_float(o.get('alpha_pct')):+.2f}%"
            if isinstance(o.get("alpha_pct"), (float, int))
            else "Alpha tổng: N/A"
        )


def render_forecast_regime_dashboard(
    user_id: str,
    *,
    get_forecast_regime_dashboard: Callable[..., dict[str, Any]],
) -> None:
    st.markdown("#### 🌦️ Hiệu năng theo regime thị trường")
    d = get_forecast_regime_dashboard(user_id)

    def _fmt(metric: dict[str, Any], key: str) -> str:
        val = metric.get(key)
        return f"{float(val):.1f}%" if isinstance(val, (float, int)) else "N/A"

    bull = d.get("bull") or {}
    side = d.get("sideway") or {}
    bear = d.get("bear") or {}
    c1, c2, c3 = st.columns(3)
    with c1:
        st.metric("Bull samples", int(bull.get("samples") or 0))
        st.caption(f"Hit {_fmt(bull, 'hit_rate_pct')} | Alpha {_fmt(bull, 'alpha_pct')}")
    with c2:
        st.metric("Sideway samples", int(side.get("samples") or 0))
        st.caption(f"Hit {_fmt(side, 'hit_rate_pct')} | Alpha {_fmt(side, 'alpha_pct')}")
    with c3:
        st.metric("Bear samples", int(bear.get("samples") or 0))
        st.caption(f"Hit {_fmt(bear, 'hit_rate_pct')} | Alpha {_fmt(bear, 'alpha_pct')}")


def render_forecast_backtesting_report(
    user_id: str,
    *,
    get_forecast_backtesting_report: Callable[..., dict[str, Any]],
) -> None:
    st.markdown("#### 🧾 Backtesting 1 năm (commercial report)")
    rep = get_forecast_backtesting_report(user_id, lookback_days=365)
    st.caption(str(rep.get("summary_vi") or ""))
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        st.metric("Forecast resolved", int(rep.get("samples") or 0))
    with c2:
        st.metric("Dự báo tăng", int(rep.get("predicted_up_samples") or 0))
    with c3:
        wr = rep.get("win_rate_pct")
        st.metric("Win/Loss rate", f"{float(wr):.2f}%" if isinstance(wr, (float, int)) else "N/A")
    with c4:
        ar = rep.get("avg_realized_return_predicted_up_pct")
        st.metric("Realized TB (mã dự báo tăng)", f"{float(ar):.2f}%" if isinstance(ar, (float, int)) else "N/A")
    rows = rep.get("by_horizon") or []
    if rows:
        df = pd.DataFrame(rows).rename(
            columns={
                "horizon_days": "Horizon",
                "samples": "Mẫu",
                "win_rate_pct": "Win rate %",
                "avg_realized_return_pct": "Realized TB %",
                "avg_abs_error_pct": "Sai số TB %",
            }
        )
        st.dataframe(df, use_container_width=True, hide_index=True)


def render_dss_readiness_panel(
    user_id: str,
    report: dict[str, Any],
    *,
    get_dss_readiness_report: Callable[..., dict[str, Any]],
) -> None:
    st.markdown("#### 🚦 DSS Readiness Gate")
    gate = get_dss_readiness_report(report, user_id, lookback_days=365)
    st.caption(str(gate.get("summary_vi") or ""))
    c1, c2 = st.columns(2)
    with c1:
        st.metric("Commercial Score", f"{float(gate.get('commercial_score') or 0):.2f}")
    with c2:
        st.metric("Decision", str(gate.get("decision") or "UNKNOWN"))
    checks = gate.get("checks") or {}
    if checks:
        rows = [{"Check": k, "Pass": bool(v)} for k, v in checks.items()]
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
    missing = gate.get("missing_items") or []
    if missing:
        st.caption("Thiếu: " + ", ".join(str(x) for x in missing))
    bt_src = gate.get("backtesting_source")
    if bt_src:
        st.caption(f"Backtesting source: `{bt_src}`")


def render_forecast_leaderboard(
    user_id: str,
    *,
    get_forecast_leaderboard: Callable[..., list[dict[str, Any]]],
) -> None:
    st.markdown("#### 🏆 Leaderboard hiệu suất dự báo")
    rows = get_forecast_leaderboard(user_id, limit=12)
    if not rows:
        st.caption("Chưa đủ dữ liệu resolved để xếp hạng.")
        return
    df = pd.DataFrame(rows)
    view = df.copy()
    for col in ("hit_rate_pct", "mape_pct", "alpha_pct"):
        if col in view.columns:
            view[col] = view[col].map(lambda x: f"{float(x):.2f}%")
    view = view.rename(
        columns={
            "symbol": "Mã",
            "samples": "Mẫu",
            "hit_rate_pct": "Hit-rate",
            "mape_pct": "Sai số TB",
            "alpha_pct": "Alpha",
            "score": "Điểm tổng hợp",
        }
    )
    st.dataframe(view, use_container_width=True, hide_index=True)


def render_sector_mode_suggestions(
    user_id: str,
    *,
    get_forecast_leaderboard: Callable[..., list[dict[str, Any]]],
    universe_subtype_map: Callable[[], dict[str, str]],
) -> None:
    st.markdown("#### 🧭 Gợi ý mode theo ngành")
    lb = get_forecast_leaderboard(user_id, limit=50)
    if not lb:
        st.caption("Chưa đủ dữ liệu leaderboard để gợi ý theo ngành.")
        return
    s_map = universe_subtype_map()
    by_subtype: dict[str, list[dict[str, Any]]] = {}
    for row in lb:
        sym = str(row.get("symbol") or "").upper()
        stype = str(s_map.get(sym, "other"))
        by_subtype.setdefault(stype, []).append(row)
    out: list[dict[str, Any]] = []
    for stype, grp in by_subtype.items():
        n = len(grp)
        if n < 2:
            continue
        hit = sum(float(x.get("hit_rate_pct") or 0.0) for x in grp) / n
        mape = sum(float(x.get("mape_pct") or 0.0) for x in grp) / n
        alpha = sum(float(x.get("alpha_pct") or 0.0) for x in grp) / n
        if hit >= 62 and mape <= 9 and alpha >= -1:
            mode = "speed"
        elif hit < 52 or mape > 14 or alpha < -3:
            mode = "quality"
        else:
            mode = "balanced"
        out.append(
            {
                "Ngành con": stype,
                "Mẫu": n,
                "Hit-rate TB": f"{hit:.2f}%",
                "Sai số TB": f"{mape:.2f}%",
                "Alpha TB": f"{alpha:+.2f}%",
                "Mode gợi ý": mode,
            }
        )
    if not out:
        st.caption("Chưa đủ dữ liệu theo ngành để gợi ý mode.")
        return
    st.dataframe(pd.DataFrame(out), use_container_width=True, hide_index=True)
