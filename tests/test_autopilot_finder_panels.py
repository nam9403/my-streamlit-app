from __future__ import annotations

from contextlib import contextmanager
from typing import Any

import pandas as pd
import streamlit as st


@contextmanager
def _ctx():
    yield


def _columns(spec) -> list[Any]:
    if isinstance(spec, int):
        n = spec
    elif isinstance(spec, list):
        n = len(spec)
    else:
        n = 2
    return [_ctx() for _ in range(max(1, n))]


def test_render_autopilot_panel_disabled_returns_inputs() -> None:
    import core.app_autopilot_panel as m

    t, r = m.render_autopilot_panel(
        autopilot_mode=False,
        autopilot_refresh=False,
        profile="growth",
        autopilot_limit=20,
        total_capital_vnd=100_000_000.0,
        effective_quick_mode=True,
        plan={"llm_live": False},
        plan_id="free",
        user_id="u1",
        ticker="FPT",
        run_analysis=False,
        profit_focus_mode=False,
        load_autopilot_board=lambda *a, **k: pd.DataFrame(),
        build_autopilot_simple_view=lambda *a, **k: pd.DataFrame(),
        build_profit_focus_board=lambda *a, **k: pd.DataFrame(),
        simple_view_for_plan=lambda *a, **k: pd.DataFrame(),
        can_auto_execute_symbol=lambda *a, **k: (True, ""),
        add_decision=lambda *a, **k: (True, ""),
        can_use_feature=lambda *a, **k: (True, ""),
        add_alert=lambda *a, **k: None,
        log_event=lambda *a, **k: None,
    )
    assert t == "FPT"
    assert r is False


def test_render_autopilot_panel_smoke_with_profit_focus(monkeypatch) -> None:
    import core.app_autopilot_panel as m

    st.session_state.clear()
    called: list[str] = []

    monkeypatch.setattr(m.st, "markdown", lambda *a, **k: None)
    monkeypatch.setattr(m.st, "caption", lambda *a, **k: None)
    monkeypatch.setattr(m.st, "info", lambda *a, **k: None)
    monkeypatch.setattr(m.st, "warning", lambda *a, **k: None)
    monkeypatch.setattr(m.st, "error", lambda *a, **k: None)
    monkeypatch.setattr(m.st, "success", lambda *a, **k: None)
    monkeypatch.setattr(m.st, "dataframe", lambda *a, **k: None)
    monkeypatch.setattr(m.st, "columns", _columns)
    monkeypatch.setattr(m.st, "selectbox", lambda *a, **k: "FPT")

    def _button(label: str, **kwargs) -> bool:
        key = str(kwargs.get("key") or "")
        if "Execute Top 3 Profit Focus" in label:
            return True
        if key == "cta_unlock_simple_view":
            return False
        return False

    monkeypatch.setattr(m.st, "button", _button)

    ap_df = pd.DataFrame([{"Mã": "FPT"}, {"Mã": "VCB"}])
    simple_df = pd.DataFrame(
        [
            {"Mã": "FPT", "Hành động": "BUY", "Giá vào": 100.0, "SL": 95.0, "TP": 115.0, "Decision readiness": "MEDIUM"},
            {"Mã": "VCB", "Hành động": "WATCH", "Giá vào": 80.0, "SL": 76.0, "TP": 92.0, "Decision readiness": "MEDIUM"},
        ]
    )
    pf_df = pd.DataFrame(
        [
            {"Mã": "FPT", "Entry": 100.0, "SL": 95.0, "TP": 116.0, "Hành động": "BUY", "Decision readiness": "MEDIUM"},
            {"Mã": "VCB", "Entry": 80.0, "SL": 76.0, "TP": 92.0, "Hành động": "WATCH", "Decision readiness": "MEDIUM"},
            {"Mã": "HPG", "Entry": 50.0, "SL": 48.0, "TP": 58.0, "Hành động": "BUY", "Decision readiness": "LOW"},
        ]
    )

    def _add_decision(*args, **kwargs):
        called.append("decision")
        return True, ""

    t, r = m.render_autopilot_panel(
        autopilot_mode=True,
        autopilot_refresh=False,
        profile="growth",
        autopilot_limit=20,
        total_capital_vnd=100_000_000.0,
        effective_quick_mode=True,
        plan={"llm_live": False},
        plan_id="expert",
        user_id="u1",
        ticker="OLD",
        run_analysis=False,
        profit_focus_mode=True,
        load_autopilot_board=lambda *a, **k: ap_df,
        build_autopilot_simple_view=lambda *a, **k: simple_df,
        build_profit_focus_board=lambda *a, **k: pf_df,
        simple_view_for_plan=lambda df, plan_id: df,
        can_auto_execute_symbol=lambda *a, **k: (True, ""),
        add_decision=_add_decision,
        can_use_feature=lambda *a, **k: (True, ""),
        add_alert=lambda *a, **k: called.append("alert"),
        log_event=lambda *a, **k: called.append("event"),
    )

    assert t == "OLD"
    assert r is False
    assert "autopilot_df" in st.session_state
    assert called.count("decision") >= 1
    assert "event" in called


def test_render_finder_panel_cache_miss_then_hit(monkeypatch) -> None:
    import core.app_finder_panel as m

    st.session_state.clear()
    build_calls = {"n": 0}

    monkeypatch.setattr(m.st, "markdown", lambda *a, **k: None)
    monkeypatch.setattr(m.st, "caption", lambda *a, **k: None)
    monkeypatch.setattr(m.st, "metric", lambda *a, **k: None)
    monkeypatch.setattr(m.st, "dataframe", lambda *a, **k: None)
    monkeypatch.setattr(m.st, "download_button", lambda *a, **k: None)
    monkeypatch.setattr(m.st, "columns", _columns)
    monkeypatch.setattr(m.st, "expander", lambda *a, **k: _ctx())
    monkeypatch.setattr(m.st, "radio", lambda *a, **k: "quick")
    monkeypatch.setattr(m.st, "rerun", lambda *a, **k: None)
    monkeypatch.setattr(m.st, "slider", lambda *a, **k: 30 if "Số mã quét Finder" in str(a[0]) else 40)
    monkeypatch.setattr(m.st, "multiselect", lambda *a, **k: ["Tất cả ngành con"])
    monkeypatch.setattr(m.st, "number_input", lambda *a, **k: 0.0)
    monkeypatch.setattr(m.st, "toggle", lambda *a, **k: False)
    monkeypatch.setattr(m.st, "spinner", lambda *a, **k: _ctx())
    monkeypatch.setattr(m, "day_cache_load", lambda *a, **k: None)
    monkeypatch.setattr(m, "day_cache_save", lambda *a, **k: None)

    opp_df = pd.DataFrame(
        [
            {
                "Mã": "FPT",
                "Ngành con": "tech",
                "Điểm cơ hội (hiệu chỉnh ngành)": 82.0,
                "Xác suất tăng 3M %": 66.0,
                "Data Quality %": 78.0,
                "Hệ số ngành (KT/CB)": "1.1/0.9",
                "Ghi chú hiệu chỉnh ngành": "ưu tiên kỹ thuật",
                "Trạng thái": "CƠ HỘI CAO",
                "Catalyst Score": 80.0,
                "Catalyst Pass": True,
                "Điểm kỹ thuật": 75.0,
                "Điểm cơ bản": 70.0,
                "Điểm cơ hội": 77.0,
                "Khuyến nghị theo profile": "BUY",
                "Lý do khuyến nghị": "đạt chuẩn",
            }
        ]
    )

    def _build(*args, **kwargs):
        build_calls["n"] += 1
        return opp_df

    m.render_finder_panel(
        user_id="u_test",
        profile="growth",
        total_capital_vnd=100_000_000.0,
        effective_quick_mode=True,
        plan={"llm_live": False},
        subtype_label_to_id={"Công nghệ": "tech"},
        universe_subtype_map=lambda: {"FPT": "tech"},
        list_universe_symbols=lambda **k: ["FPT", "VCB"],
        build_opportunity_3m_board=_build,
        load_benchmark_return_3m=lambda: (5.0, "VNINDEX"),
    )
    m.render_finder_panel(
        user_id="u_test",
        profile="growth",
        total_capital_vnd=100_000_000.0,
        effective_quick_mode=True,
        plan={"llm_live": False},
        subtype_label_to_id={"Công nghệ": "tech"},
        universe_subtype_map=lambda: {"FPT": "tech"},
        list_universe_symbols=lambda **k: ["FPT", "VCB"],
        build_opportunity_3m_board=_build,
        load_benchmark_return_3m=lambda: (5.0, "VNINDEX"),
    )

    assert build_calls["n"] == 1


def test_finder_preset_apply_quick() -> None:
    import core.app_finder_panel as m

    st.session_state.clear()
    m._apply_finder_preset("quick")
    assert st.session_state["finder_preset_id"] == "quick"
    assert st.session_state["finder_opp_limit"] == 30
    assert st.session_state["finder_min_catalyst_score"] == 0.0
    assert st.session_state["finder_only_actionable"] is False

    m._apply_finder_preset("quality")
    assert st.session_state["finder_min_avg_vol20"] == 300_000.0
    assert st.session_state["finder_min_catalyst_score"] == 70.0
    assert st.session_state["finder_only_actionable"] is True


def test_render_finder_panel_handles_empty_board(monkeypatch) -> None:
    import core.app_finder_panel as m

    st.session_state.clear()
    monkeypatch.setattr(m.st, "markdown", lambda *a, **k: None)
    monkeypatch.setattr(m.st, "caption", lambda *a, **k: None)
    monkeypatch.setattr(m.st, "radio", lambda *a, **k: "quick")
    monkeypatch.setattr(m.st, "rerun", lambda *a, **k: None)
    monkeypatch.setattr(m.st, "slider", lambda *a, **k: 30 if "Số mã quét Finder" in str(a[0]) else 40)
    monkeypatch.setattr(m.st, "multiselect", lambda *a, **k: ["Tất cả ngành con"])
    monkeypatch.setattr(m.st, "number_input", lambda *a, **k: 0.0)
    monkeypatch.setattr(m.st, "toggle", lambda *a, **k: False)
    monkeypatch.setattr(m.st, "spinner", lambda *a, **k: _ctx())
    monkeypatch.setattr(m.st, "info", lambda *a, **k: None)
    monkeypatch.setattr(m, "day_cache_load", lambda *a, **k: None)
    monkeypatch.setattr(m, "day_cache_save", lambda *a, **k: None)

    m.render_finder_panel(
        user_id="u_test",
        profile="growth",
        total_capital_vnd=100_000_000.0,
        effective_quick_mode=True,
        plan={"llm_live": False},
        subtype_label_to_id={},
        universe_subtype_map=lambda: {},
        list_universe_symbols=lambda **k: [],
        build_opportunity_3m_board=lambda *a, **k: pd.DataFrame(),
        load_benchmark_return_3m=lambda: (None, None),
    )


def test_render_autopilot_panel_one_click_and_top_symbol(monkeypatch) -> None:
    import core.app_autopilot_panel as m

    st.session_state.clear()
    events: list[str] = []

    monkeypatch.setattr(m.st, "markdown", lambda *a, **k: None)
    monkeypatch.setattr(m.st, "caption", lambda *a, **k: None)
    monkeypatch.setattr(m.st, "info", lambda *a, **k: None)
    monkeypatch.setattr(m.st, "warning", lambda *a, **k: None)
    monkeypatch.setattr(m.st, "error", lambda *a, **k: None)
    monkeypatch.setattr(m.st, "success", lambda *a, **k: None)
    monkeypatch.setattr(m.st, "dataframe", lambda *a, **k: None)
    monkeypatch.setattr(m.st, "columns", _columns)
    monkeypatch.setattr(m.st, "selectbox", lambda *a, **k: "FPT")

    def _button(label: str, **kwargs) -> bool:
        if "Áp dụng kế hoạch 1-click" in label:
            return True
        if "Dùng mã #1 để phân tích ngay" in label:
            return True
        return False

    monkeypatch.setattr(m.st, "button", _button)

    ap_df = pd.DataFrame([{"Mã": "FPT"}])
    simple_df = pd.DataFrame(
        [{"Mã": "FPT", "Hành động": "BUY", "Giá vào": 100.0, "SL": 95.0, "TP": 120.0, "Decision readiness": "MEDIUM"}]
    )

    t, r = m.render_autopilot_panel(
        autopilot_mode=True,
        autopilot_refresh=True,
        profile="growth",
        autopilot_limit=20,
        total_capital_vnd=100_000_000.0,
        effective_quick_mode=True,
        plan={"llm_live": False},
        plan_id="pro",
        user_id="u1",
        ticker="OLD",
        run_analysis=False,
        profit_focus_mode=False,
        load_autopilot_board=lambda *a, **k: ap_df,
        build_autopilot_simple_view=lambda *a, **k: simple_df,
        build_profit_focus_board=lambda *a, **k: pd.DataFrame(),
        simple_view_for_plan=lambda df, plan_id: df,
        can_auto_execute_symbol=lambda *a, **k: (True, ""),
        add_decision=lambda *a, **k: (True, ""),
        can_use_feature=lambda *a, **k: (True, ""),
        add_alert=lambda *a, **k: events.append("alert"),
        log_event=lambda *a, **k: events.append("event"),
    )

    assert t == "FPT"
    assert r is True
    assert events.count("alert") == 2
    assert "event" in events
