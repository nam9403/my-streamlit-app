from __future__ import annotations

from contextlib import contextmanager
from typing import Any

import pandas as pd


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


def test_render_primary_analysis_tab_smoke(monkeypatch) -> None:
    import core.app_analysis_tab_primary as m

    called: list[str] = []

    monkeypatch.setattr(m.st, "markdown", lambda *a, **k: None)
    monkeypatch.setattr(m.st, "info", lambda *a, **k: None)
    monkeypatch.setattr(m.st, "caption", lambda *a, **k: None)
    monkeypatch.setattr(m.st, "warning", lambda *a, **k: None)
    monkeypatch.setattr(m.st, "error", lambda *a, **k: None)
    monkeypatch.setattr(m.st, "success", lambda *a, **k: None)
    monkeypatch.setattr(m.st, "dataframe", lambda *a, **k: None)
    monkeypatch.setattr(m.st, "download_button", lambda *a, **k: None)
    monkeypatch.setattr(m.st, "columns", _columns)
    monkeypatch.setattr(m.st, "expander", lambda *a, **k: _ctx())
    monkeypatch.setattr(m.st, "selectbox", lambda *a, **k: "Auto (hiện tại)")
    monkeypatch.setattr(m.st, "slider", lambda *a, **k: 10)
    monkeypatch.setattr(m.st, "button", lambda *a, **k: False)
    monkeypatch.setattr(m.st, "container", lambda: _ctx())

    monkeypatch.setattr(m, "render_next_best_action_cta", lambda *a, **k: called.append("cta"))
    monkeypatch.setattr(m, "render_risk_box", lambda *a, **k: called.append("risk_box"))
    monkeypatch.setattr(m, "render_analysis_action_explanation", lambda *a, **k: called.append("explain"))
    monkeypatch.setattr(m, "render_macro_micro_outlook", lambda *a, **k: called.append("outlook"))
    monkeypatch.setattr(m, "render_probabilistic_forecast", lambda *a, **k: called.append("forecast"))
    monkeypatch.setattr(m, "render_intraday_flow_panel", lambda *a, **k: called.append("intraday_flow"))
    monkeypatch.setattr(m, "render_forecast_accuracy", lambda *a, **k: called.append("accuracy"))
    monkeypatch.setattr(m, "render_forecast_benchmark", lambda *a, **k: called.append("bench"))
    monkeypatch.setattr(m, "render_model_drift_panel", lambda *a, **k: called.append("drift"))
    monkeypatch.setattr(m, "render_forecast_portfolio_dashboard", lambda *a, **k: called.append("portfolio"))
    monkeypatch.setattr(m, "render_forecast_regime_dashboard", lambda *a, **k: called.append("regime"))
    monkeypatch.setattr(m, "render_forecast_backtesting_report", lambda *a, **k: called.append("backtesting_report"))
    monkeypatch.setattr(m, "render_dss_readiness_panel", lambda *a, **k: called.append("dss_readiness"))
    monkeypatch.setattr(m, "render_forecast_leaderboard", lambda *a, **k: called.append("leaderboard"))
    monkeypatch.setattr(m, "render_sector_mode_suggestions", lambda *a, **k: called.append("sector"))
    monkeypatch.setattr(m, "render_forecast_accountability_actions", lambda *a, **k: called.append("accountability"))
    monkeypatch.setattr(m, "profile_match_note", lambda *a, **k: "ok")
    monkeypatch.setattr(m, "render_aha_and_value", lambda *a, **k: called.append("aha"))
    monkeypatch.setattr(m, "render_health_cards", lambda *a, **k: called.append("health"))
    monkeypatch.setattr(m, "render_readiness_checklist", lambda *a, **k: called.append("readiness"))
    monkeypatch.setattr(m, "render_risk_plan", lambda *a, **k: called.append("risk_plan"))
    monkeypatch.setattr(m, "render_action_center_expander", lambda *a, **k: called.append("action_center"))
    monkeypatch.setattr(m, "render_scan_results_expander", lambda *a, **k: called.append("scan_results"))
    monkeypatch.setattr(m, "render_report_downloads", lambda *a, **k: called.append("downloads"))
    monkeypatch.setattr(
        m.svc.pl,
        "adaptive_position_sizing",
        lambda *a, **k: {
            "suggested_position_pct": 10,
            "risk_bucket": "B",
            "discipline_score": 80,
            "reason": "ok",
        },
    )

    m.render_primary_analysis_tab(
        container=_ctx(),
        user_id="u1",
        ticker="FPT",
        report={"risk_plan": {"stop_loss_price": 90, "take_profit_price": 120}, "phase": {"metrics": {}}},
        plan_id="pro",
        profile="growth",
        watchlist=["FPT"],
        watchlist_default=["FPT", "VCB"],
        total_capital_vnd=100_000_000.0,
        effective_quick_mode=True,
        plan={"llm_live": False},
        notify_cfg={},
        ohlcv=pd.DataFrame([{"close": 1.0}]),
        mutations=None,
    )

    assert "cta" in called and "downloads" in called and "accountability" in called


def test_render_admin_growth_panel_smoke(monkeypatch) -> None:
    import core.admin_growth_panel as m

    monkeypatch.setattr(m.st, "markdown", lambda *a, **k: None)
    monkeypatch.setattr(m.st, "subheader", lambda *a, **k: None)
    monkeypatch.setattr(m.st, "metric", lambda *a, **k: None)
    monkeypatch.setattr(m.st, "caption", lambda *a, **k: None)
    monkeypatch.setattr(m.st, "dataframe", lambda *a, **k: None)
    monkeypatch.setattr(m.st, "warning", lambda *a, **k: None)
    monkeypatch.setattr(m.st, "info", lambda *a, **k: None)
    monkeypatch.setattr(m.st, "columns", _columns)
    monkeypatch.setattr(m.st, "button", lambda *a, **k: False)

    m.render_admin_growth_panel(
        email_to="a@b.com",
        smtp_host="smtp",
        smtp_port=25,
        smtp_user="u",
        smtp_password="p",
        smtp_from="from@x.com",
        tg_bot="bot",
        tg_chat="chat",
        webhook_url="https://x.example",
        get_admin_kpi=lambda **k: {
            "users_total": 10,
            "active_users_period": 7,
            "events_period": 100,
            "alerts_total": 5,
            "plans": [{"plan_id": "free", "count": 5}],
            "events_by_type": [{"event": "analysis", "count": 10}],
            "notification_queue": [{"status": "pending", "count": 2}],
            "notification_observability": {
                "fail_reasons": [{"reason": "smtp_text", "count": 3}],
                "retry_tiers": [{"retry_tier": "t3_4", "count": 1}],
            },
        },
        get_notification_queue_diagnostics=lambda **k: [{"status": "failed", "attempts": 3}],
        get_notification_fail_reason_summary=lambda **k: [{"reason": "smtp_text", "count": 3}],
        retry_failed_notifications=lambda **k: 0,
        get_admin_cx_kpi=lambda **k: {"avg_score": 77.5, "samples": 12, "bands": [{"band": "good", "count": 8}], "trend": []},
        get_upgrade_funnel=lambda **k: [{"variant": "A", "shown": 10, "upgraded": 2}],
        select_upgrade_variant_auto=lambda **k: {"variant": "A", "reason": "best", "score": 1.2},
        dispatch_text_notifications=lambda *a, **k: {"sent": 0, "failed": 0},
    )
