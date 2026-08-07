from __future__ import annotations

from typing import Any

import pandas as pd
import streamlit as st


def _as_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def render_macro_micro_outlook(report: dict) -> None:
    val = report.get("valuation") or {}
    phase = report.get("phase") or {}
    fin = report.get("financials") or {}
    news = report.get("news") or []
    industry = str(val.get("industry_subtype_label_vi") or val.get("industry_cluster_label_vi") or "Khác")
    phase_name = str(phase.get("phase") or "neutral")
    vol_mult = float((phase.get("metrics") or {}).get("vol_multiple") or 0)
    rev = fin.get("revenue_growth_yoy")
    rev_num = float(rev) if isinstance(rev, (float, int)) else None
    macro_hint = "trung tính"
    if len(news) >= 3:
        macro_hint = "tin tức dày hơn bình thường"
    if phase_name == "distribution":
        macro_hint = "áp lực thị trường ngắn hạn đang tăng"
    elif phase_name == "breakout":
        macro_hint = "dòng tiền thị trường đang ủng hộ xu hướng tăng"
    micro_hint = "nội tại ổn định"
    if rev_num is not None:
        if rev_num >= 15:
            micro_hint = "nội tại tăng trưởng tốt"
        elif rev_num < 0:
            micro_hint = "nội tại suy yếu, cần thận trọng"
    st.markdown("#### 🌐 Góc nhìn vi mô/vĩ mô ảnh hưởng giá thời gian tới")
    st.caption(
        f"Vĩ mô/ngắn hạn: {macro_hint}. "
        f"Vi mô/ngành: {industry} - {micro_hint}. "
        f"Xung lực kỹ thuật hiện tại: phase={phase_name}, volume multiple={vol_mult:.2f}."
    )
    if news:
        top_news = " | ".join([str(x.get("title") or "") for x in news[:2]])
        st.caption(f"Headline tác động gần nhất: {top_news}")


def render_probabilistic_forecast(report: dict) -> None:
    fc = report.get("probabilistic_forecast") or {}
    rel = report.get("forecast_reliability") or {}
    cal = report.get("forecast_calibration") or {}
    scenarios = fc.get("scenarios") or []
    fr = fc.get("forecast_range") or {}
    warn = str(report.get("signal_conflict_warning") or "")
    st.markdown("#### 🔮 Dự phóng xác suất giá")
    exp_px = fc.get("expected_price")
    exp_ret = fc.get("expected_return_pct")
    hz = int(fc.get("horizon_days") or 90)
    if not scenarios or exp_px is None:
        st.info("Chưa đủ dữ liệu để tạo dự phóng xác suất.")
        return
    c1, c2 = st.columns(2)
    with c1:
        st.metric(f"Giá kỳ vọng {hz} ngày", f"{float(exp_px):,.0f} VND")
    with c2:
        st.metric("Lợi suất kỳ vọng", f"{_as_float(exp_ret):.2f}%")
    df = pd.DataFrame(scenarios)
    if not df.empty:
        df["probability"] = df["probability"].map(lambda x: f"{float(x) * 100:.1f}%")
        df["target_price"] = df["target_price"].map(lambda x: f"{float(x):,.0f}")
        df["return_pct"] = df["return_pct"].map(lambda x: f"{float(x):.2f}%")
        df = df.rename(
            columns={
                "name": "Kịch bản",
                "probability": "Xác suất",
                "target_price": "Giá mục tiêu",
                "return_pct": "Lợi suất",
            }
        )
        st.dataframe(df, use_container_width=True, hide_index=True)
    if fr:
        st.caption(
            "Forecast range (Monte Carlo): "
            f"P10={_as_float(fr.get('p10_price')):,.0f} | "
            f"P50={_as_float(fr.get('p50_price')):,.0f} | "
            f"P90={_as_float(fr.get('p90_price')):,.0f} VND | "
            f"P(đạt target)={_as_float(fr.get('prob_reach_target_pct')):.1f}% "
            f"({int(_as_float(fr.get('simulations'), 0))} mô phỏng)."
        )
    st.caption(str(fc.get("summary") or ""))
    if warn:
        st.warning(warn)
    hit = rel.get("hit_rate_proxy_pct")
    err = rel.get("expected_abs_error_pct")
    quality = str(rel.get("quality_label") or "insufficient_data").upper()
    if isinstance(hit, (float, int)) and isinstance(err, (float, int)):
        st.caption(f"Độ tin cậy dự phóng (proxy): {hit:.1f}% | Sai số kỳ vọng: ±{err:.1f}% | Mức: {quality}")
    notes = str(rel.get("notes") or "")
    if notes:
        st.caption(notes)
    if cal.get("applied"):
        st.caption(
            "Calibrated theo dữ liệu thực tế: "
            f"bias={float(cal.get('bias_pct') or 0):.2f}% | "
            f"factor={float(cal.get('factor') or 0):.2f} | "
            f"resolved={int(cal.get('resolved_records') or 0)}."
        )
