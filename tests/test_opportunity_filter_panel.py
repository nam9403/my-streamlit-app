from __future__ import annotations

from contextlib import contextmanager
from typing import Any


@contextmanager
def _ctx():
    yield


def _render(monkeypatch, *, plan_scan_limit: int, universe_total: int = 100) -> dict[str, Any]:
    import streamlit as st

    import core.opportunity_filter_panel as m
    import core.ui_widgets as widgets

    st.session_state.clear()
    calls: dict[str, int] = {"slider": 0, "number_input": 0}

    def _slider(*args, **kwargs):
        calls["slider"] += 1
        min_v = kwargs.get("min_value")
        max_v = kwargs.get("max_value")
        if min_v is not None and max_v is not None and not (min_v < max_v):
            raise RuntimeError(f"Slider min_value must be less than the max_value. The values were {min_v} and {max_v}.")
        return int(kwargs.get("max_value") or 40)

    def _number_input(*args, **kwargs):
        calls["number_input"] += 1
        if "Số mã quét từ universe" in str(args[0] if args else ""):
            return int(kwargs.get("value") or 20)
        return float(kwargs.get("value") or 0.0)

    monkeypatch.setattr(m.st, "markdown", lambda *a, **k: None)
    monkeypatch.setattr(m.st, "button", lambda *a, **k: False)
    monkeypatch.setattr(m.st, "caption", lambda *a, **k: None)
    monkeypatch.setattr(m.st, "dataframe", lambda *a, **k: None)
    monkeypatch.setattr(m.st, "columns", lambda *a, **k: (_ctx(), _ctx()))
    monkeypatch.setattr(m.st, "multiselect", lambda *a, **k: [])
    monkeypatch.setattr(m.st, "slider", _slider)
    monkeypatch.setattr(m.st, "number_input", _number_input)
    monkeypatch.setattr(widgets.st, "slider", _slider)
    monkeypatch.setattr(widgets.st, "number_input", _number_input)
    monkeypatch.setattr(widgets.st, "session_state", st.session_state)

    out = m.render_opportunity_filter_panel(
        watchlist=["FPT"],
        watchlist_default=["FPT"],
        profile="growth",
        total_capital_vnd=100_000_000.0,
        subtype_label_to_id={},
        compute_top5_for_profile=lambda *a, **k: None,
        plan_scan_limit=plan_scan_limit,
        universe_total=universe_total,
    )
    return {"out": out, "calls": calls}


def test_universe_limit_uses_disabled_number_input_when_max_equals_min(monkeypatch) -> None:
    """plan_scan_limit=20 → max_limit=20; slider would crash (min==max)."""
    result = _render(monkeypatch, plan_scan_limit=20)
    out = result["out"]
    calls = result["calls"]
    assert calls["slider"] == 0
    assert calls["number_input"] >= 1
    assert isinstance(out["universe_limit"], int)
    assert out["universe_limit"] == 20


def test_universe_limit_keeps_slider_when_max_above_min(monkeypatch) -> None:
    result = _render(monkeypatch, plan_scan_limit=100)
    out = result["out"]
    calls = result["calls"]
    assert calls["slider"] == 1
    assert isinstance(out["universe_limit"], int)
    assert out["universe_limit"] >= 20
