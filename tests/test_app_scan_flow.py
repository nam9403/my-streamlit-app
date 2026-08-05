from __future__ import annotations

import pandas as pd
import pytest
import streamlit as st

from core.app_scan_flow import run_scan_flow


def test_run_scan_flow_noop_when_disabled() -> None:
    st.session_state.clear()
    run_scan_flow(
        run_scan=False,
        universe_limit=20,
        plan={"scan_limit": 20},
        plan_label="Free",
        subtype_labels=[],
        subtype_label_to_id={},
        user_id="u1",
        plan_id="free",
        profile="growth",
        total_capital_vnd=100_000_000.0,
        min_avg_volume_20=0.0,
        list_universe_symbols=lambda **kwargs: [],
        universe_subtype_map=lambda: {},
        can_use_feature=lambda *a, **k: (True, ""),
        log_event=lambda *a, **k: None,
        scan_potential_stocks=lambda *a, **k: pd.DataFrame(),
        build_portfolio_options=lambda *a, **k: [],
    )
    assert "scan_candidates" not in st.session_state


def test_run_scan_flow_sets_session_state_for_successful_scan() -> None:
    st.session_state.clear()

    def _scan(*args, **kwargs):
        return pd.DataFrame([{"symbol": "FPT"}])

    run_scan_flow(
        run_scan=True,
        universe_limit=20,
        plan={"scan_limit": 20},
        plan_label="Free",
        subtype_labels=[],
        subtype_label_to_id={},
        user_id="u1",
        plan_id="free",
        profile="growth",
        total_capital_vnd=100_000_000.0,
        min_avg_volume_20=1000.0,
        list_universe_symbols=lambda **kwargs: ["FPT"],
        universe_subtype_map=lambda: {"FPT": "other"},
        can_use_feature=lambda *a, **k: (True, ""),
        log_event=lambda *a, **k: None,
        scan_potential_stocks=_scan,
        build_portfolio_options=lambda candidates, capital: [{"n": len(candidates), "c": capital}],
    )
    assert "scan_candidates" in st.session_state
    assert isinstance(st.session_state["scan_candidates"], pd.DataFrame)
    assert st.session_state["scan_profile"] == "growth"
    assert st.session_state["scan_capital"] == 100_000_000.0


def test_run_scan_flow_uses_cache_on_same_inputs() -> None:
    st.session_state.clear()
    call_count = {"n": 0}

    def _scan(*args, **kwargs):
        call_count["n"] += 1
        return pd.DataFrame([{"symbol": "FPT"}])

    common_kwargs = dict(
        run_scan=True,
        universe_limit=20,
        plan={"scan_limit": 20},
        plan_label="Free",
        subtype_labels=[],
        subtype_label_to_id={},
        user_id="u1",
        plan_id="free",
        profile="growth",
        total_capital_vnd=100_000_000.0,
        min_avg_volume_20=1000.0,
        list_universe_symbols=lambda **kwargs: ["FPT"],
        universe_subtype_map=lambda: {"FPT": "other"},
        can_use_feature=lambda *a, **k: (True, ""),
        log_event=lambda *a, **k: None,
        scan_potential_stocks=_scan,
        build_portfolio_options=lambda candidates, capital: [{"n": len(candidates), "c": capital}],
    )
    run_scan_flow(**common_kwargs)
    run_scan_flow(**common_kwargs)
    assert call_count["n"] == 1


def test_run_scan_flow_applies_flow_rerank_when_enabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Khi II_SCANNER_FLOW_RERANK_ENABLED=1 và journal có signal, DataFrame
    đầu ra phải có cột ``Flow boost`` + confidence của mã match được điều chỉnh."""
    st.session_state.clear()
    monkeypatch.setenv("II_SCANNER_FLOW_RERANK_ENABLED", "1")

    # Mock journal reader thông qua module import bên trong run_scan_flow
    import core.scanner_flow_integration as sfi

    fake_signals = [
        {
            "symbol": "FPT",
            "is_big_boy": True,
            "delta_status": "bullish",
            "intensity_score": 8.5,
            "z_volume": 3.0,
            "journaled_at_utc": "2026-05-11T10:00:00+00:00",
        }
    ]
    monkeypatch.setattr(sfi, "read_recent_flow_signals", lambda **_: fake_signals)

    def _scan(*args, **kwargs):
        return pd.DataFrame(
            [
                {"Mã": "FPT", "Confidence %": 60.0, "Hành động hôm nay": "BUY"},
                {"Mã": "HPG", "Confidence %": 55.0, "Hành động hôm nay": "HOLD"},
            ]
        )

    run_scan_flow(
        run_scan=True,
        universe_limit=20,
        plan={"scan_limit": 20},
        plan_label="Free",
        subtype_labels=[],
        subtype_label_to_id={},
        user_id="u1",
        plan_id="free",
        profile="growth",
        total_capital_vnd=100_000_000.0,
        min_avg_volume_20=1000.0,
        list_universe_symbols=lambda **kwargs: ["FPT", "HPG"],
        universe_subtype_map=lambda: {"FPT": "other", "HPG": "other"},
        can_use_feature=lambda *a, **k: (True, ""),
        log_event=lambda *a, **k: None,
        scan_potential_stocks=_scan,
        build_portfolio_options=lambda candidates, capital: [],
    )
    out = st.session_state["scan_candidates"]
    assert isinstance(out, pd.DataFrame)
    assert "Flow boost" in out.columns
    assert "Flow note" in out.columns
    fpt_conf = float(out.loc[out["Mã"] == "FPT", "Confidence %"].iloc[0])
    assert fpt_conf > 60.0


def test_run_scan_flow_skips_rerank_when_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Default OFF: dù journal có signal, DataFrame không thêm cột Flow boost."""
    st.session_state.clear()
    monkeypatch.delenv("II_SCANNER_FLOW_RERANK_ENABLED", raising=False)

    import core.scanner_flow_integration as sfi

    monkeypatch.setattr(
        sfi,
        "read_recent_flow_signals",
        lambda **_: [
            {
                "symbol": "FPT",
                "is_big_boy": True,
                "delta_status": "bullish",
                "intensity_score": 8.5,
                "journaled_at_utc": "2026-05-11T10:00:00+00:00",
            }
        ],
    )

    def _scan(*args, **kwargs):
        return pd.DataFrame(
            [{"Mã": "FPT", "Confidence %": 60.0, "Hành động hôm nay": "BUY"}]
        )

    run_scan_flow(
        run_scan=True,
        universe_limit=20,
        plan={"scan_limit": 20},
        plan_label="Free",
        subtype_labels=[],
        subtype_label_to_id={},
        user_id="u1",
        plan_id="free",
        profile="growth",
        total_capital_vnd=100_000_000.0,
        min_avg_volume_20=1000.0,
        list_universe_symbols=lambda **kwargs: ["FPT"],
        universe_subtype_map=lambda: {"FPT": "other"},
        can_use_feature=lambda *a, **k: (True, ""),
        log_event=lambda *a, **k: None,
        scan_potential_stocks=_scan,
        build_portfolio_options=lambda candidates, capital: [],
    )
    out = st.session_state["scan_candidates"]
    assert "Flow boost" not in out.columns

