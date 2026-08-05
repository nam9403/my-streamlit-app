from __future__ import annotations

from contextlib import contextmanager
from typing import Any

import pandas as pd
import streamlit as st

from core.notification_contracts import NotificationChannels


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


def test_action_center_panel_builders_and_renderers_smoke(monkeypatch) -> None:
    import core.action_center_panel as m

    candidates = pd.DataFrame(
        [
            {
                "Mã": "AAA",
                "Trạng thái": "Sẵn sàng",
                "Khuyến nghị": "BUY",
                "Khung thời gian": "Ngắn hạn",
                "Expected Return %": 12.0,
                "Risk % (ước tính)": 10.0,
                "MOS%": 25.0,
                "Giá": 100.0,
                "Tiểu ngành": "Tech",
            },
            {
                "Mã": "BBB",
                "Trạng thái": "Sẵn sàng",
                "Khuyến nghị": "HOLD",
                "Khung thời gian": "Trung hạn",
                "Expected Return %": 8.0,
                "Risk % (ước tính)": 12.0,
                "MOS%": 22.0,
                "Giá": 80.0,
                "Tiểu ngành": "Bank",
            },
        ]
    )
    plans = m.build_portfolio_options(candidates, 100_000_000.0)
    assert "an_toan" in plans and "can_bang" in plans and "mao_hiem" in plans

    final_df = m.build_final_opportunity_table(candidates, discount_threshold_pct=20.0)
    assert not final_df.empty
    assert "Thông điệp cuối cùng" in final_df.columns

    monkeypatch.setattr(m, "load_snapshot_cached", lambda sym: {"symbol": sym, "price": 100.0})
    monkeypatch.setattr(
        m,
        "load_strategic_report_cached",
        lambda sym, snap, profile, capital, quick_mode=True: {
            "valuation": {"margin_of_safety_composite_pct": 15.0, "industry_subtype_label_vi": "Tech"},
            "risk_plan": {"entry_price": 100.0, "stop_loss_price": 95.0, "take_profit_price": 112.0},
            "confidence_score": 75.0,
            "final_action": "BUY",
            "gate_passed": True,
        },
    )
    board = m.build_action_center.__wrapped__(("AAA", "BBB"), "growth", 100_000_000.0, top_n=2)  # type: ignore[attr-defined]
    assert len(board) == 2
    assert "Điểm hành động" in board.columns

    log_calls: list[tuple[str, str]] = []
    monkeypatch.setattr(m.st, "expander", lambda *a, **k: _ctx())
    monkeypatch.setattr(m.st, "dataframe", lambda *a, **k: None)
    monkeypatch.setattr(m.st, "caption", lambda *a, **k: None)
    monkeypatch.setattr(m.st, "info", lambda *a, **k: None)
    monkeypatch.setattr(m.st, "markdown", lambda *a, **k: None)
    monkeypatch.setattr(m.st, "subheader", lambda *a, **k: None)
    monkeypatch.setattr(m.st, "warning", lambda *a, **k: None)
    monkeypatch.setattr(m.st, "columns", _columns)

    m.render_action_center_expander(
        user_id="u1",
        watchlist=["AAA", "BBB"],
        watchlist_default=["AAA", "BBB", "CCC"],
        profile="growth",
        total_capital_vnd=100_000_000.0,
        build_action_center=lambda *a, **k: board,
        log_event=lambda uid, ev, payload=None: log_calls.append((uid, ev)),
    )
    assert ("u1", "action_center_viewed") in log_calls

    session_state = {"scan_candidates": candidates, "scan_relaxed_used": True, "scan_filter_min_vol": 300000}
    m.render_scan_candidates_overview(
        session_state,
        100_000_000.0,
        build_portfolio_options=lambda cand, cap: plans,
    )
    assert "scan_candidates" in session_state

    m.render_scan_results_expander(
        session_state,
        "growth",
        100_000_000.0,
        True,
        False,
        build_final_opportunity_table=lambda *a, **k: final_df,
        load_snapshot_cached=lambda sym: {"symbol": sym, "price": 100.0},
        load_strategic_report_cached=lambda *a, **k: {"valuation": {"margin_of_safety_composite_pct": 20.0, "piotroski_score": 7}, "phase": {"phase": "accumulation"}},
    )


def test_command_center_panel_quick_actions_and_autofix(monkeypatch) -> None:
    import core.command_center_panel as m

    st.session_state.clear()
    st.session_state["report_cache"] = {"latency_seconds": 12.0}
    st.session_state["cmd_last_queue_stat"] = {"processed": 4, "sent": 1, "retried": 1, "failed": 3}
    st.session_state["cmd_last_queue_ts"] = 1.0
    st.session_state["bg_warm_last_ts"] = 1.0

    button_map = {
        "⚡ Phân tích mã chọn": True,
        "♻️ Quét lại cơ hội": False,
        "♨️ Warm nền ngay": False,
        "🛠️ Xử lý queue": False,
        "📨 Gửi Daily Playbook test": False,
        "🩺 Auto-fix nhanh (Queue + Warm + Ping test)": True,
    }
    monkeypatch.setattr(m.st, "expander", lambda *a, **k: _ctx())
    monkeypatch.setattr(m.st, "columns", _columns)
    monkeypatch.setattr(m.st, "button", lambda label, **k: bool(button_map.get(label, False)))
    monkeypatch.setattr(m.st, "caption", lambda *a, **k: None)
    monkeypatch.setattr(m.st, "success", lambda *a, **k: None)
    monkeypatch.setattr(m.st, "warning", lambda *a, **k: None)
    monkeypatch.setattr(m.st, "error", lambda *a, **k: None)
    monkeypatch.setattr(m.st, "metric", lambda *a, **k: None)
    monkeypatch.setattr(m.st, "dataframe", lambda *a, **k: None)

    calls: dict[str, int] = {"queue": 0, "warm": 0, "ping": 0, "upsert": 0}

    def process_queue(**kwargs):
        _ = kwargs
        calls["queue"] += 1
        return {"processed": 1, "sent": 1, "retried": 0, "failed": 0}

    def run_warm(**kwargs):
        _ = kwargs
        calls["warm"] += 1
        return {"prefetch": {"ok": 1}}

    def dispatch_ping(*args, **kwargs):
        _ = (args, kwargs)
        calls["ping"] += 1
        return {"sent": 1, "failed": 0}

    def upsert_cx(*args, **kwargs):
        _ = (args, kwargs)
        calls["upsert"] += 1

    out = m.render_command_center_panel(
        ticker="AAA",
        watchlist=["AAA", "BBB", "CCC"],
        auth_ready=True,
        bg_universe_limit=20,
        tg_bot="b",
        tg_chat="c",
        webhook_url="",
        email_to="",
        smtp_host="",
        smtp_port=587,
        smtp_user="",
        smtp_password="",
        smtp_from="",
        user_id="u1",
        watchlist_default=["AAA", "BBB"],
        process_notification_queue=process_queue,
        run_background_cycle=run_warm,
        dispatch_text_notifications=dispatch_ping,
        upsert_daily_cx_score=upsert_cx,
        get_recent_cx_scores=lambda *a, **k: [{"date": "2026-01-01", "score": 80, "band": "Good"}],
    )
    assert out["quick_run_analysis"] is True
    assert calls["queue"] >= 1 and calls["warm"] >= 1 and calls["ping"] >= 1
    assert calls["upsert"] >= 1


def test_portfolio_kpi_panel_smoke_with_alerts_and_upgrade_prompt(monkeypatch) -> None:
    import core.portfolio_kpi_panel as m

    monkeypatch.setattr(m.st, "subheader", lambda *a, **k: None)
    monkeypatch.setattr(m.st, "dataframe", lambda *a, **k: None)
    monkeypatch.setattr(m.st, "columns", _columns)
    monkeypatch.setattr(m.st, "metric", lambda *a, **k: None)
    monkeypatch.setattr(m.st, "markdown", lambda *a, **k: None)
    monkeypatch.setattr(m.st, "caption", lambda *a, **k: None)
    monkeypatch.setattr(m.st, "info", lambda *a, **k: None)
    monkeypatch.setattr(m.st, "success", lambda *a, **k: None)
    monkeypatch.setattr(m.st, "button", lambda *a, **k: False)

    logs: list[str] = []
    channels = NotificationChannels(
        tg_bot="b",
        tg_chat="c",
        webhook_url="w",
        email_to="e@example.com",
        smtp_host="smtp",
        smtp_user="u",
        smtp_password="p",
        auto_notify=True,
    )
    m.render_trade_alert_kpi_panel(
        user_id="u1",
        plan_id="free",
        channels=channels,
        list_trades=lambda *a, **k: [{"symbol": "AAA", "pnl": 10}],
        realized_performance=lambda *a, **k: {"closed_trades": 1, "realized_pnl_total": 1000.0, "realized_pct_avg": 2.0, "win_rate_pct": 100.0},
        execution_vs_plan_report=lambda *a, **k: [{"symbol": "AAA", "status": "ok"}],
        evaluate_alerts=lambda *a, **k: [{"symbol": "AAA", "kind": "tp"}],
        dispatch_alert_notifications=lambda *a, **k: {"sent": 1, "skipped": 0, "failed": 0},
        dispatch_external_notifications=lambda *a, **k: {"sent": 1, "failed": 0},
        log_event=lambda user_id, event, payload=None: logs.append(event),
        enqueue_notification=lambda *a, **k: None,
        get_kpi_dashboard=lambda *a, **k: {"events_total": 10, "alerts_total": 2, "holdings_total": 3, "by_event": {"a": 1}},
        get_cohort_kpi=lambda *a, **k: {
            "active_days_7": 2,
            "active_days_30": 10,
            "analysis_7": 3,
            "analysis_30": 9,
            "alerts_created_7": 1,
            "alerts_created_30": 2,
            "alerts_dispatched_7": 1,
            "alerts_dispatched_30": 2,
            "upgrade_intent_7": 0,
            "upgrade_intent_30": 1,
            "upgrade_success_7": 0,
            "upgrade_success_30": 0,
        },
        evaluate_decisions=lambda *a, **k: [{"Trạng thái": "TAKE_PROFIT_HIT"}, {"Trạng thái": "STOP_LOSS_HIT"}],
        decision_scorecard=lambda *a, **k: {"discipline_score": 80, "rr_avg": 2.0, "pl_avg_pct": 1.0, "win_rate_closed_pct": 50.0},
        postmortem_report=lambda *a, **k: [{"symbol": "AAA"}],
        monthly_value_report=lambda *a, **k: {
            "value_summary": "ok",
            "plan_id": "free",
            "analysis_30d": 5,
            "alerts_dispatched_30d": 2,
            "decisions_logged": 2,
            "discipline_score": 80,
            "avg_pl_pct": 1.0,
            "win_rate_closed_pct": 50.0,
        },
        smart_upgrade_prompt=lambda *a, **k: {
            "show": True,
            "variant": "v1",
            "variant_source": "auto",
            "cta_plan": "pro",
            "roi_fee_x": 2.0,
            "maturity_score_10": 6,
            "title": "Upgrade",
            "message": "More value",
            "analysis_30d": 5,
        },
    )
    assert "alert_dispatched" in logs
    assert "upgrade_prompt_view" in logs
