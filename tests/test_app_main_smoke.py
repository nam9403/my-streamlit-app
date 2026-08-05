from __future__ import annotations

from contextlib import contextmanager
from types import SimpleNamespace

import streamlit as st


@contextmanager
def _ctx():
    yield


def test_app_main_smoke_lite_mode(monkeypatch) -> None:
    import app as app_mod
    import core.ui_shell as shell

    st.session_state.clear()
    auth_order: list[str] = []

    monkeypatch.setattr(st, "sidebar", _ctx())
    monkeypatch.setattr(st, "header", lambda *a, **k: None)
    monkeypatch.setattr(st, "divider", lambda *a, **k: None)
    monkeypatch.setattr(st, "toggle", lambda *a, **k: True)
    monkeypatch.setattr(st, "chat_input", lambda *a, **k: None)
    monkeypatch.setattr(st, "info", lambda *a, **k: None)
    monkeypatch.setattr(st, "markdown", lambda *a, **k: None)
    monkeypatch.setattr(st, "caption", lambda *a, **k: None)
    monkeypatch.setattr(st, "radio", lambda *a, **k: shell.VIEW_TAB_FIN)
    monkeypatch.setattr(st, "container", lambda: SimpleNamespace())
    monkeypatch.setattr(st, "expander", lambda *a, **k: _ctx())

    monkeypatch.setattr(app_mod, "bootstrap_app_ui", lambda: None)
    monkeypatch.setattr(shell, "render_sidebar_auth_section", lambda **kwargs: auth_order.append("auth_ui") or "u1")
    monkeypatch.setattr(shell, "enforce_auth_gate", lambda **kwargs: auth_order.append("auth_gate"))
    monkeypatch.setattr(
        shell.svc,
        "build_guarded_mutations",
        lambda user_id: SimpleNamespace(
            set_user_plan=lambda *a, **k: None,
            load_secret=lambda *a, **k: "",
            save_secret=lambda *a, **k: None,
            dispatch_text_notifications=lambda *a, **k: {},
            log_event=lambda *a, **k: None,
            process_notification_queue=lambda *a, **k: {},
            migrate_legacy_json_to_sqlite=lambda *a, **k: {},
            run_background_cycle=lambda *a, **k: {},
            upsert_daily_cx_score=lambda *a, **k: None,
            add_holding=lambda *a, **k: None,
            add_alert=lambda *a, **k: None,
            add_decision=lambda *a, **k: None,
            open_trade=lambda *a, **k: None,
            close_trade=lambda *a, **k: None,
            record_usage=lambda *a, **k: None,
            record_forecast_snapshot=lambda *a, **k: None,
            export_forecast_health_report=lambda *a, **k: "",
            export_model_accountability_report=lambda *a, **k: "",
            export_monthly_accountability_markdown=lambda *a, **k: "",
            send_monthly_accountability_email=lambda *a, **k: "",
            dispatch_alert_notifications=lambda *a, **k: {},
            dispatch_external_notifications=lambda *a, **k: {},
            enqueue_notification=lambda *a, **k: None,
            retry_failed_notifications=lambda *a, **k: {},
        ),
    )
    monkeypatch.setattr(
        shell,
        "render_sidebar_account_sections",
        lambda **kwargs: (
            auth_order.append("account_panel")
            or SimpleNamespace(
                user_id="u1",
                auth_ready=True,
                plan_label="Pro",
                plan_id="pro",
                plan={"llm_live": False},
                profile="growth",
                total_capital_vnd=100_000_000.0,
                tg_bot="",
                tg_chat="",
                webhook_url="",
                email_to="",
                smtp_host="",
                smtp_port=25,
                smtp_user="",
                smtp_password="",
                smtp_from="",
                notify_cfg={},
            )
        ),
    )
    monkeypatch.setattr(
        shell,
        "render_sidebar_runtime_sections",
        lambda **kwargs: SimpleNamespace(
            runtime_cfg={},
            watchlist=["FPT", "VCB"],
            ticker="FPT",
            autopilot_mode=False,
            profit_focus_mode=False,
            autopilot_limit=10,
            autopilot_refresh=False,
            quick_mode=True,
            run_analysis=False,
            min_avg_volume_20=0.0,
            universe_limit=20,
            subtype_labels=[],
            run_scan=False,
        ),
    )
    monkeypatch.setattr(shell.sm, "refresh_vn_universe_total", lambda fn: 2)
    monkeypatch.setattr(shell, "schedule_focus_prefetch", lambda **kwargs: None)
    monkeypatch.setattr(shell, "handle_warm_flow", lambda **kwargs: None)
    monkeypatch.setattr(shell, "render_app_quickstart_strip", lambda **kwargs: None)
    monkeypatch.setattr(shell, "render_aisle_band", lambda **kwargs: None)
    monkeypatch.setattr(shell, "render_watch_board", lambda **kwargs: None)
    monkeypatch.setattr(shell, "render_autopilot_panel", lambda **kwargs: ("FPT", False))
    monkeypatch.setattr(shell, "run_scan_flow", lambda **kwargs: None)
    monkeypatch.setattr(shell, "resolve_analysis_report", lambda **kwargs: ({"analysis_text": "ok"}, None))
    monkeypatch.setattr(shell, "render_analysis_quick_dashboard", lambda **kwargs: {"price": 100.0})
    monkeypatch.setattr(shell, "render_analysis_main_metrics", lambda *a, **k: None)
    monkeypatch.setattr(shell, "render_analysis_chart_tab", lambda *a, **k: None)
    monkeypatch.setattr(shell, "render_financial_health_tab", lambda *a, **k: None)
    monkeypatch.setattr(shell, "render_evidence", lambda *a, **k: None)
    monkeypatch.setattr(shell, "render_portfolio_overview", lambda *a, **k: None)
    monkeypatch.setattr(shell.sm, "resolve_fast_shell_flags", lambda **k: SimpleNamespace(
        fast_shell=False,
        defer_autopilot=False,
        autopilot_requested=False,
        finder_unlocked=True,
        should_defer_autopilot=False,
    ))

    app_mod.main()
    assert auth_order[:3] == ["auth_ui", "auth_gate", "account_panel"]


def test_compute_top5_for_profile_delegates_to_scanner(monkeypatch) -> None:
    import core.ui_services as svc

    class _FakeDF:
        def __init__(self) -> None:
            self.head_n: int | None = None

        def head(self, n: int):
            self.head_n = n
            return [("n", n)]

    fake = _FakeDF()
    monkeypatch.setattr(svc, "scan_potential_stocks", lambda symbols, profile, volume: fake)
    out = svc.compute_top5_for_profile(("FPT", "VCB"), "growth")

    assert out == [("n", 5)]
    assert fake.head_n == 5
