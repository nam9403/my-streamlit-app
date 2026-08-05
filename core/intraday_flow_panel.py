"""UI panel hiển thị tín hiệu dòng tiền (Tier 1 + Tier 2 combined view).

Tách rõ:
- ``build_flow_view_model``: hàm thuần (không streamlit) — dễ unit test.
- ``render_intraday_flow_panel``: orchestration UI dùng streamlit, dựa view-model.

Panel này không tự fetch dữ liệu — caller (analysis tab) chịu trách nhiệm load OHLCV
qua ``analysis_runtime_service`` rồi truyền vào. Tách trách nhiệm để panel có thể test
hoàn toàn offline.
"""

from __future__ import annotations

from typing import Any

import pandas as pd
import streamlit as st

from core.deep_insight_service import confirm_smart_money_flow
from core.intraday_flow_service import (
    FlowConfig,
    FlowSignal,
    IntradayFlowError,
    analyze_flow,
)

_DELTA_BADGE_VI = {
    "bullish": ("🟢 Dòng tiền vào", "success"),
    "absorption": ("🟢 Hấp thụ lực bán", "success"),
    "bearish": ("🔴 Dòng tiền ra", "error"),
    "distribution": ("🔴 Phân phối", "error"),
    "neutral": ("⚪ Trung tính", "info"),
}

_CONFIRMATION_BADGE_VI = {
    "strong": ("🟢 ĐỒNG THUẬN MẠNH", "success"),
    "moderate": ("🟡 Đồng thuận vừa", "info"),
    "weak": ("⚪ Chưa đủ xác nhận", "info"),
    "diverging": ("🔴 NGHỊCH PHA — coi chừng bẫy", "error"),
}


def build_flow_view_model(
    signal: FlowSignal | None,
    smart_money_summary: dict[str, Any] | None = None,
    *,
    error: str | None = None,
) -> dict[str, Any]:
    """Chuẩn hóa FlowSignal + smart-money thành view-model phẳng để render.

    Trả về dict gồm:
    - ``status``: ``ok`` / ``error``
    - ``error_message``: nếu có
    - ``headline_metric``: nhãn chính ("BIG BOY ĐANG MUA", v.v.)
    - ``delta_badge``: (label, kind) cho st.success/error/info
    - ``confirmation_badge``: nếu có Tier 2 confirmation
    - ``metrics``: list dicts cho st.metric
    - ``reasons`` / ``risks`` / ``context_note``
    """
    if error or signal is None:
        return {
            "status": "error",
            "error_message": error or "Không có tín hiệu",
            "headline_metric": "—",
            "delta_badge": ("⚪ Không có dữ liệu", "info"),
            "confirmation_badge": None,
            "metrics": [],
            "reasons": [],
            "risks": [],
            "context_note": "",
            "combined_intensity": None,
            "tier2": None,
        }

    delta_badge = _DELTA_BADGE_VI.get(signal.delta_status, ("⚪ Không xác định", "info"))
    if signal.is_big_boy:
        if signal.delta_status in ("bullish", "absorption"):
            headline = "🐳 BIG BOY ĐANG MUA"
        elif signal.delta_status in ("bearish", "distribution"):
            headline = "🐳 BIG BOY ĐANG BÁN"
        else:
            headline = "🐳 BIG BOY HOẠT ĐỘNG"
    else:
        headline = "Dòng tiền bình thường"

    metrics: list[dict[str, Any]] = [
        {
            "label": "Intensity (1-10)",
            "value": f"{signal.intensity_score:.1f}",
            "delta": f"Z {signal.z_volume:+.2f}σ",
        },
        {
            "label": "Pseudo-Delta",
            "value": f"{signal.pseudo_delta:+.2f}",
            "delta": f"Cumulative Δ {signal.cumulative_delta:,.0f}",
        },
        {
            "label": "Aggregated Volume",
            "value": f"{signal.aggregated_volume:,.0f}",
            "delta": f"Last vol {signal.last_volume:,.0f}",
        },
    ]

    tier2 = None
    confirmation_badge = None
    combined_intensity: float | None = None
    if smart_money_summary is not None:
        tier2 = confirm_smart_money_flow(signal.to_dict(), smart_money_summary)
        confirmation_badge = _CONFIRMATION_BADGE_VI.get(
            str(tier2.get("confirmation_level") or "weak"),
            ("⚪ Chưa rõ", "info"),
        )
        combined_intensity = float(tier2.get("combined_intensity") or signal.intensity_score)

    return {
        "status": "ok",
        "error_message": None,
        "headline_metric": headline,
        "delta_badge": delta_badge,
        "confirmation_badge": confirmation_badge,
        "metrics": metrics,
        "reasons": list(signal.reasons),
        "risks": list(signal.risks),
        "context_note": str(signal.context_note),
        "combined_intensity": combined_intensity,
        "tier2": tier2,
    }


def _kind_to_render(kind: str) -> Any:
    """Map "kind" tới hàm Streamlit phù hợp (success/error/info/warning)."""
    return {
        "success": st.success,
        "error": st.error,
        "info": st.info,
        "warning": st.warning,
    }.get(str(kind or "info"), st.info)


def render_intraday_flow_panel(
    container: Any,
    *,
    symbol: str,
    ohlcv: pd.DataFrame | None,
    smart_money_summary: dict[str, Any] | None = None,
    config: FlowConfig | None = None,
    context: dict[str, Any] | None = None,
    timeframe: str = "1D",
) -> dict[str, Any]:
    """Render panel "Dòng tiền lớn" trên container Streamlit chỉ định.

    Trả về view-model đã sử dụng (giúp caller log/telemetry hoặc test).
    """
    vm: dict[str, Any]
    if ohlcv is None or len(ohlcv) == 0:
        vm = build_flow_view_model(None, None, error="Chưa có OHLCV để phân tích dòng tiền.")
    else:
        try:
            signal = analyze_flow(
                ohlcv,
                symbol=symbol,
                config=config,
                context=context,
                timeframe=timeframe,
            )
            vm = build_flow_view_model(signal, smart_money_summary)
        except IntradayFlowError as exc:
            vm = build_flow_view_model(None, None, error=str(exc))
        except Exception as exc:
            vm = build_flow_view_model(None, None, error=f"Lỗi phân tích dòng tiền: {exc}")

    with container:
        st.markdown(f"### 🐳 Dòng tiền lớn — {symbol} ({timeframe})")
        if vm["status"] == "error":
            st.info(vm["error_message"])
            return vm

        label, kind = vm["delta_badge"]
        _kind_to_render(kind)(f"**{vm['headline_metric']}** · {label}")

        cols = st.columns(len(vm["metrics"]))
        for col, metric in zip(cols, vm["metrics"], strict=False):
            with col:
                st.metric(label=metric["label"], value=metric["value"], delta=metric["delta"])

        if vm["confirmation_badge"]:
            label2, kind2 = vm["confirmation_badge"]
            tier2 = vm["tier2"] or {}
            verdict = str(tier2.get("verdict") or "")
            ci = vm["combined_intensity"]
            ci_text = f" · Combined intensity {ci:.1f}/10" if ci is not None else ""
            _kind_to_render(kind2)(f"**{label2}** — {verdict}{ci_text}")

        if vm["context_note"]:
            st.caption(f"Bối cảnh: {vm['context_note']}")

        if vm["reasons"]:
            with st.expander("Lý do tín hiệu", expanded=False):
                for r in vm["reasons"]:
                    st.markdown(f"- {r}")

        if vm["risks"]:
            with st.expander("Rủi ro / lưu ý", expanded=bool(vm.get("tier2") and vm["tier2"].get("confirmation_level") == "diverging")):
                for r in vm["risks"]:
                    st.markdown(f"- {r}")

    return vm


__all__ = [
    "build_flow_view_model",
    "render_intraday_flow_panel",
]
