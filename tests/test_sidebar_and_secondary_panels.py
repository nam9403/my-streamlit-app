from __future__ import annotations

from contextlib import contextmanager
from types import SimpleNamespace
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


def test_render_sidebar_account_sections_smoke(monkeypatch) -> None:
    import core.app_sidebar_account_panel as m

    st.session_state.clear()
    m.start_authenticated_session("u1")

    monkeypatch.setattr(m.st, "expander", lambda *a, **k: _ctx())
    monkeypatch.setattr(m.st, "text_input", lambda label, **k: "u1" if "Mã khách hàng" in label else "1234")
    monkeypatch.setattr(m.st, "columns", _columns)
    monkeypatch.setattr(m.st, "button", lambda *a, **k: False)
    monkeypatch.setattr(m.st, "selectbox", lambda label, options, **k: options[0] if "Gói dịch vụ" in label else options[1])
    monkeypatch.setattr(m.st, "number_input", lambda *a, **k: 100_000_000.0)
    monkeypatch.setattr(m.st, "caption", lambda *a, **k: None)
    monkeypatch.setattr(m.st, "radio", lambda *a, **k: "B1: Tài khoản")
    monkeypatch.setattr(m.st, "progress", lambda *a, **k: None)
    monkeypatch.setattr(m.st, "info", lambda *a, **k: None)
    monkeypatch.setattr(m.st, "success", lambda *a, **k: None)
    monkeypatch.setattr(m.st, "warning", lambda *a, **k: None)
    monkeypatch.setattr(m.st, "error", lambda *a, **k: None)

    notify_cfg = SimpleNamespace(
        tg_bot="b",
        tg_chat="c",
        webhook_url="w",
        email_to="e",
        smtp_host="h",
        smtp_port=587,
        smtp_user="u",
        smtp_password="p",
        smtp_from="f",
        has_any_channel=lambda: True,
    )

    out = m.render_sidebar_account_sections(
        user_id="u1",
        profile_options={"An toàn": "safe_dividend", "Tăng trưởng": "growth"},
        watchlist_default=["FPT", "VCB"],
        has_auth_user=lambda uid: True,
        get_user_plan=lambda *a, **k: "pro",
        get_plan_features=lambda plan_id: {"scan_limit": 50, "alerts": 10, "llm_live": True},
        set_user_plan=lambda *a, **k: None,
        render_notification_settings=lambda *a, **k: notify_cfg,
        load_secret=lambda *a, **k: "",
        save_secret=lambda *a, **k: None,
        dispatch_text_notifications=lambda *a, **k: {"sent": 0, "failed": 0},
        log_event=lambda *a, **k: None,
        process_notification_queue=lambda *a, **k: {"processed": 0, "sent": 0, "retried": 0, "failed": 0},
        migrate_legacy_json_to_sqlite=lambda: {"users": 0, "holdings": 0, "alerts": 0, "events": 0},
        run_background_cycle=lambda *a, **k: {"prefetch": {"ok": 0, "total": 0}, "queue": {"processed": 0}},
    )
    assert out.user_id == "u1"
    assert out.plan_id in ("free", "pro", "expert")
    assert out.profile in ("safe_dividend", "growth")


def test_render_sidebar_auth_success_binds_identity_and_token(monkeypatch) -> None:
    import core.app_sidebar_account_panel as m

    st.session_state.clear()
    monkeypatch.setattr(m.st, "expander", lambda *a, **k: _ctx())
    monkeypatch.setattr(m.st, "text_input", lambda label, **k: "u-login" if "Mã khách hàng" in label else "1234")
    monkeypatch.setattr(m.st, "columns", _columns)
    monkeypatch.setattr(m.st, "button", lambda label, **k: label == "Đăng nhập")
    monkeypatch.setattr(m.st, "success", lambda *a, **k: None)
    monkeypatch.setattr(m.st, "warning", lambda *a, **k: None)
    monkeypatch.setattr(m.st, "error", lambda *a, **k: None)
    monkeypatch.setattr(m.st, "caption", lambda *a, **k: None)

    selected = m.render_sidebar_auth_section(
        has_auth_user=lambda uid: uid == "u-login",
        verify_user_pin=lambda uid, pin: uid == "u-login" and pin == "1234",
        register_user_pin=lambda *a, **k: (False, ""),
    )

    assert selected == "u-login"
    assert st.session_state["auth_ok"] is True
    assert st.session_state["user_id"] == "u-login"
    assert len(st.session_state["session_token"]) >= 32


def test_render_sidebar_auth_failed_pin_clears_previous_identity(monkeypatch) -> None:
    import core.app_sidebar_account_panel as m

    st.session_state.clear()
    m.start_authenticated_session("old-user")
    monkeypatch.setattr(m.st, "expander", lambda *a, **k: _ctx())
    monkeypatch.setattr(m.st, "text_input", lambda label, **k: "new-user" if "Mã khách hàng" in label else "wrong")
    monkeypatch.setattr(m.st, "columns", _columns)
    monkeypatch.setattr(m.st, "button", lambda label, **k: label == "Đăng nhập")
    monkeypatch.setattr(m.st, "success", lambda *a, **k: None)
    monkeypatch.setattr(m.st, "warning", lambda *a, **k: None)
    monkeypatch.setattr(m.st, "error", lambda *a, **k: None)
    monkeypatch.setattr(m.st, "caption", lambda *a, **k: None)

    m.render_sidebar_auth_section(
        has_auth_user=lambda uid: True,
        verify_user_pin=lambda uid, pin: False,
        register_user_pin=lambda *a, **k: (False, ""),
    )

    assert st.session_state["auth_ok"] is False
    assert "user_id" not in st.session_state
    assert "session_token" not in st.session_state


def test_render_sidebar_runtime_sections_smoke(monkeypatch) -> None:
    import streamlit as st

    import core.app_sidebar_runtime_panel as m

    st.session_state.clear()
    st.session_state["vn_universe_total"] = 100
    st.session_state["report_cache"] = {}

    monkeypatch.setattr(m.st, "expander", lambda *a, **k: _ctx())
    monkeypatch.setattr(m.st, "divider", lambda *a, **k: None)

    runtime_cfg = SimpleNamespace(
        watchlist=["FPT", "VCB"],
        ticker="FPT",
        autopilot_mode=True,
        profit_focus_mode=False,
        autopilot_limit=30,
        autopilot_refresh=False,
        quick_mode=True,
        run_analysis=False,
    )

    monkeypatch.setattr(m, "render_watchlist_controls", lambda **k: runtime_cfg)
    monkeypatch.setattr(m, "render_experience_panel", lambda **k: None)
    monkeypatch.setattr(m, "render_portfolio_alert_panel", lambda **k: None)
    monkeypatch.setattr(m, "render_decision_trade_panel", lambda **k: None)
    monkeypatch.setattr(
        m,
        "render_opportunity_filter_panel",
        lambda **k: {
            "min_avg_volume_20": 300000.0,
            "universe_limit": 40,
            "subtype_labels": [],
            "run_scan": False,
        },
    )
    monkeypatch.setattr(m.svc.pl, "has_auth_user", lambda *a, **k: True)
    monkeypatch.setattr(m.sm, "is_auth_ok", lambda: True)
    monkeypatch.setattr(m.sm, "get_vn_universe_total", lambda: 100)

    out = m.render_sidebar_runtime_sections(
        watchlist_default=["FPT", "VCB"],
        auth_ready=True,
        user_id="u1",
        profile="growth",
        total_capital_vnd=100_000_000.0,
        plan={"scan_limit": 20},
        plan_label="Free",
        plan_id="free",
        mutations=None,
    )
    assert out.ticker == "FPT"
    assert out.autopilot_mode is True


def test_render_secondary_analysis_tabs_smoke(monkeypatch) -> None:
    import core.app_analysis_tabs_secondary as m

    monkeypatch.setattr(m.st, "expander", lambda *a, **k: _ctx())
    monkeypatch.setattr(m.st, "markdown", lambda *a, **k: None)

    called: list[str] = []
    monkeypatch.setattr(m, "render_ai_chat_style", lambda *a, **k: called.append("ai"))
    monkeypatch.setattr(m, "render_ai_health_panel", lambda *a, **k: called.append("ai_health"))
    monkeypatch.setattr(m, "render_financial_health_tab", lambda *a, **k: called.append("fin"))
    monkeypatch.setattr(m, "render_evidence", lambda *a, **k: called.append("evidence"))
    monkeypatch.setattr(m, "render_portfolio_overview", lambda *a, **k: called.append("overview"))
    monkeypatch.setattr(m, "render_trade_alert_kpi_panel", lambda *a, **k: called.append("kpi"))
    monkeypatch.setattr(m, "render_ops_tail_panel", lambda *a, **k: called.append("ops"))

    m.render_secondary_analysis_tabs(
        show_ai=True,
        show_finance=True,
        ticker="FPT",
        report={"analysis_text": "ok"},
        valuation={},
        ohlcv=pd.DataFrame(),
        user_id="u1",
        plan_id="free",
        notify_cfg={},
        watchlist=["FPT"],
        watchlist_default=["FPT", "VCB"],
        profile="growth",
        total_capital_vnd=100_000_000.0,
        mutations=None,
    )
    assert "ai" in called and "fin" in called and "ops" in called


def test_render_sidebar_account_sections_actions(monkeypatch) -> None:
    import core.app_sidebar_account_panel as m

    st.session_state.clear()
    m.start_authenticated_session("u2")

    button_hits = {
        "Áp dụng watchlist gợi ý": True,
        "✅ Xác nhận nâng cấp (mock checkout)": True,
        "🧪 Tôi quan tâm nâng cấp": True,
        "Xử lý hàng đợi notification": True,
        "Migrate user_state.json -> SQLite": True,
        "Chạy 1 vòng background jobs": True,
    }

    monkeypatch.setattr(m.st, "expander", lambda *a, **k: _ctx())
    monkeypatch.setattr(m.st, "text_input", lambda label, **k: "u2" if "Mã khách hàng" in label else "1234")
    monkeypatch.setattr(m.st, "columns", _columns)
    monkeypatch.setattr(m.st, "button", lambda label, **k: bool(button_hits.get(label, False)))
    monkeypatch.setattr(m.st, "selectbox", lambda label, options, **k: options[-1] if "Gói dịch vụ" in label else options[0])
    monkeypatch.setattr(m.st, "number_input", lambda *a, **k: 50_000_000.0)
    monkeypatch.setattr(m.st, "caption", lambda *a, **k: None)
    monkeypatch.setattr(m.st, "radio", lambda *a, **k: "B3: Watchlist & chạy thử")
    monkeypatch.setattr(m.st, "progress", lambda *a, **k: None)
    monkeypatch.setattr(m.st, "info", lambda *a, **k: None)
    monkeypatch.setattr(m.st, "success", lambda *a, **k: None)
    monkeypatch.setattr(m.st, "warning", lambda *a, **k: None)
    monkeypatch.setattr(m.st, "error", lambda *a, **k: None)

    notify_cfg = SimpleNamespace(
        tg_bot="",
        tg_chat="",
        webhook_url="",
        email_to="",
        smtp_host="",
        smtp_port=587,
        smtp_user="",
        smtp_password="",
        smtp_from="",
        has_any_channel=lambda: False,
    )

    out = m.render_sidebar_account_sections(
        user_id="u2",
        profile_options={"An toàn": "safe_dividend", "Tăng trưởng": "growth"},
        watchlist_default=["FPT", "VCB"],
        has_auth_user=lambda uid: True,
        get_user_plan=lambda *a, **k: "free",
        get_plan_features=lambda plan_id: {"scan_limit": 20, "alerts": 3, "llm_live": False},
        set_user_plan=lambda *a, **k: None,
        render_notification_settings=lambda *a, **k: notify_cfg,
        load_secret=lambda *a, **k: "",
        save_secret=lambda *a, **k: None,
        dispatch_text_notifications=lambda *a, **k: {"sent": 0, "failed": 0},
        log_event=lambda *a, **k: None,
        process_notification_queue=lambda *a, **k: {"processed": 1, "sent": 1, "retried": 0, "failed": 0},
        migrate_legacy_json_to_sqlite=lambda: {"users": 1, "holdings": 1, "alerts": 1, "events": 1},
        run_background_cycle=lambda *a, **k: {"prefetch": {"ok": 1, "total": 1}, "queue": {"processed": 1}},
    )
    assert out.user_id == "u2"
    assert st.session_state.get("cmd_last_queue_stat", {}).get("processed") == 1
