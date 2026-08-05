"""Tests for core.state_manager session-state helpers."""

from __future__ import annotations

import streamlit as st

from core import state_manager as sm


def test_selected_ticker_roundtrip() -> None:
    st.session_state.clear()
    assert sm.get_selected_ticker() == ""
    sm.set_selected_ticker("fpt")
    assert sm.get_selected_ticker() == "FPT"


def test_force_sync_consume_once() -> None:
    st.session_state.clear()
    sm.request_force_sync_analysis()
    assert sm.consume_force_sync_analysis() is True
    assert sm.consume_force_sync_analysis() is False


def test_fast_shell_flags_defer(monkeypatch) -> None:
    st.session_state.clear()
    monkeypatch.setenv("II_FAST_SHELL_DEFAULT", "1")
    monkeypatch.setenv("II_DEFER_AUTOPILOT_DEFAULT", "1")
    flags = sm.resolve_fast_shell_flags(run_analysis=False, autopilot_refresh=False)
    assert flags.fast_shell is True
    assert flags.should_defer_autopilot is True
    sm.request_autopilot_load()
    flags2 = sm.resolve_fast_shell_flags(run_analysis=False, autopilot_refresh=False)
    assert flags2.should_defer_autopilot is False


def test_refresh_vn_universe_total_ttl(monkeypatch) -> None:
    st.session_state.clear()
    monkeypatch.setenv("II_VN_UNIVERSE_TOTAL_REFRESH_SEC", "9999")
    calls = {"n": 0}

    def _count() -> int:
        calls["n"] += 1
        return 42

    assert sm.refresh_vn_universe_total(_count) == 42
    assert sm.refresh_vn_universe_total(_count) == 42
    assert calls["n"] == 1
    assert sm.get_vn_universe_total() == 42
