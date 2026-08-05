from __future__ import annotations

from datetime import datetime, timedelta, timezone


def test_can_auto_execute_symbol_rules(monkeypatch) -> None:
    import core.product_layer as pl

    ok, msg = pl.can_auto_execute_symbol("u1", "", cooldown_hours=24)
    assert ok is False
    assert "Mã rỗng" in msg

    now = datetime.now(timezone.utc)
    monkeypatch.setattr(
        pl,
        "list_decisions",
        lambda *a, **k: [{"symbol": "FPT", "created_at": (now - timedelta(hours=1)).isoformat()}],
    )
    ok2, msg2 = pl.can_auto_execute_symbol("u1", "FPT", cooldown_hours=24)
    assert ok2 is False
    assert "24h" in msg2

    monkeypatch.setattr(
        pl,
        "list_decisions",
        lambda *a, **k: [{"symbol": "FPT", "created_at": (now - timedelta(hours=30)).isoformat()}],
    )
    ok3, msg3 = pl.can_auto_execute_symbol("u1", "FPT", cooldown_hours=24)
    assert ok3 is True
    assert msg3 == "ok"


def test_smart_upgrade_prompt_variants(monkeypatch) -> None:
    import core.product_layer as pl

    monkeypatch.setattr(pl, "proof_of_value_report", lambda *a, **k: {"realized_pnl_30d": 700_000.0})
    monkeypatch.setattr(pl, "value_maturity_score", lambda *a, **k: {"score_10": 5.0})
    monkeypatch.setattr(pl, "get_kpi_dashboard", lambda *a, **k: {"by_event": {"analysis_completed": 5}})
    monkeypatch.setattr(pl, "list_alerts", lambda *a, **k: [])
    monkeypatch.setattr(pl, "select_upgrade_variant_auto", lambda *a, **k: {"variant": "none", "reason": "rule"})
    p1 = pl.smart_upgrade_prompt("u1", "free")
    assert p1["show"] is True
    assert p1["variant"] == "roi_positive"

    monkeypatch.setattr(pl, "proof_of_value_report", lambda *a, **k: {"realized_pnl_30d": 0.0})
    monkeypatch.setattr(pl, "value_maturity_score", lambda *a, **k: {"score_10": 7.0})
    monkeypatch.setattr(pl, "get_kpi_dashboard", lambda *a, **k: {"by_event": {"analysis_completed": 25}})
    p2 = pl.smart_upgrade_prompt("u1", "free")
    assert p2["show"] is True
    assert p2["variant"] == "high_engagement"

    monkeypatch.setattr(pl, "value_maturity_score", lambda *a, **k: {"score_10": 5.0})
    monkeypatch.setattr(pl, "get_kpi_dashboard", lambda *a, **k: {"by_event": {"analysis_completed": 1}})
    monkeypatch.setattr(pl, "list_alerts", lambda *a, **k: [{"id": "1"}, {"id": "2"}, {"id": "3"}])
    p3 = pl.smart_upgrade_prompt("u1", "free")
    assert p3["variant"] == "alerts_limit_pressure"

    monkeypatch.setattr(pl, "proof_of_value_report", lambda *a, **k: {"realized_pnl_30d": 1_100_000.0})
    monkeypatch.setattr(pl, "value_maturity_score", lambda *a, **k: {"score_10": 8.2})
    monkeypatch.setattr(pl, "get_kpi_dashboard", lambda *a, **k: {"by_event": {"analysis_completed": 12}})
    monkeypatch.setattr(pl, "list_alerts", lambda *a, **k: [])
    p4 = pl.smart_upgrade_prompt("u1", "pro")
    assert p4["show"] is True
    assert p4["cta_plan"] == "expert"
    assert p4["variant"] == "expert_ready"


def test_next_best_action_priority(monkeypatch) -> None:
    import core.product_layer as pl

    monkeypatch.setattr(pl, "user_aha_progress", lambda *a, **k: {"progress_pct": 0})
    monkeypatch.setattr(pl, "realized_performance", lambda *a, **k: {"closed_trades": 0})
    monkeypatch.setattr(pl, "decision_scorecard", lambda *a, **k: {"discipline_score": 50})
    monkeypatch.setattr(pl, "get_kpi_dashboard", lambda *a, **k: {"by_event": {"analysis_completed": 0}})
    monkeypatch.setattr(pl, "list_alerts", lambda *a, **k: [])
    monkeypatch.setattr(pl, "list_decisions", lambda *a, **k: [])
    monkeypatch.setattr(pl, "list_trades", lambda *a, **k: [])
    a1 = pl.next_best_action("u1")
    assert a1["id"] == "do_first_analysis"

    monkeypatch.setattr(pl, "get_kpi_dashboard", lambda *a, **k: {"by_event": {"analysis_completed": 3}})
    monkeypatch.setattr(pl, "list_decisions", lambda *a, **k: [{"id": 1}])
    monkeypatch.setattr(pl, "list_alerts", lambda *a, **k: [{"id": "a"}])
    monkeypatch.setattr(pl, "list_trades", lambda *a, **k: [{"Trạng thái": "OPEN"}])
    monkeypatch.setattr(pl, "decision_scorecard", lambda *a, **k: {"discipline_score": 50})
    a2 = pl.next_best_action("u1")
    assert a2["id"] == "tighten_execution"


def test_today_action_board_and_overdue_reminders(monkeypatch) -> None:
    import core.product_layer as pl

    monkeypatch.setattr(
        pl,
        "get_kpi_dashboard",
        lambda uid, days=7: {"by_event": {"analysis_completed": 0 if days == 1 else 1}},
    )
    monkeypatch.setattr(pl, "list_decisions", lambda *a, **k: [])
    monkeypatch.setattr(pl, "list_alerts", lambda *a, **k: [])
    monkeypatch.setattr(pl, "list_trades", lambda *a, **k: [{"Trạng thái": "OPEN"}])
    monkeypatch.setattr(pl, "decision_scorecard", lambda *a, **k: {"discipline_score": 50})
    monkeypatch.setattr(pl, "user_aha_progress", lambda *a, **k: {"progress_pct": 100})

    reminders = pl.overdue_action_reminders("u1")
    ids = {x["id"] for x in reminders}
    assert "no_analysis_24h" in ids
    assert "discipline_low_with_open_trades" in ids

    board = pl.today_action_board("u1")
    assert len(board) == 3
    assert board[0]["status"] == "todo"


def test_value_maturity_score_and_proof_of_value(monkeypatch) -> None:
    import core.product_layer as pl

    monkeypatch.setattr(pl, "user_aha_progress", lambda *a, **k: {"progress_pct": 100.0})
    monkeypatch.setattr(pl, "decision_scorecard", lambda *a, **k: {"discipline_score": 88.0, "rr_avg": 2.1})
    monkeypatch.setattr(pl, "realized_performance", lambda *a, **k: {"closed_trades": 12, "realized_pnl_total": 2_000_000.0, "win_rate_pct": 61.0})
    monkeypatch.setattr(pl, "get_kpi_dashboard", lambda *a, **k: {"by_event": {"analysis_completed": 40}})
    monkeypatch.setattr(pl, "list_alerts", lambda *a, **k: [{"id": "1"}, {"id": "2"}, {"id": "3"}])
    monkeypatch.setattr(pl, "list_decisions", lambda *a, **k: [{"id": i} for i in range(15)])
    monkeypatch.setattr(pl, "monthly_value_report", lambda *a, **k: {"analysis_30d": 40, "alerts_dispatched_30d": 12})

    ms = pl.value_maturity_score("u1")
    assert float(ms["score_10"]) >= 8.5
    assert ms["level"] == "Tinh gọn hiệu suất cao"

    pov = pl.proof_of_value_report("u1")
    assert float(pov["risk_shield_score"]) > 0
    assert "30 ngày" in str(pov["value_message"])


def test_coach_and_adaptive_coach_and_position_sizing(monkeypatch) -> None:
    import core.product_layer as pl

    c1 = pl.coach_decision_quality(
        side="BUY",
        entry_price=100.0,
        stop_loss=95.0,
        take_profit=110.0,
        gate_passed=False,
        confidence_score=55.0,
    )
    assert c1["verdict"] in ("CAUTION", "NO-GO")
    assert any("Gate chưa PASS" in w for w in c1["warnings"])

    monkeypatch.setattr(pl, "decision_scorecard", lambda *a, **k: {"discipline_score": 85.0})
    monkeypatch.setattr(pl, "realized_performance", lambda *a, **k: {"win_rate_pct": 60.0, "closed_trades": 20})
    th = pl.adaptive_coach_thresholds("u1")
    assert th["profile"] == "adaptive_agile"

    monkeypatch.setattr(pl, "adaptive_coach_thresholds", lambda *a, **k: {"rr_min": 2.0, "go_min_score": 75.0, "caution_min_score": 60.0, "profile": "adaptive_defensive"})
    c2 = pl.coach_decision_quality_adaptive(
        "u1",
        side="BUY",
        entry_price=100.0,
        stop_loss=95.0,
        take_profit=107.0,  # RR under rr_min
        gate_passed=True,
        confidence_score=80.0,
    )
    assert c2["adaptive_profile"] == "adaptive_defensive"
    assert any("RR (" in w for w in c2["warnings"])

    monkeypatch.setattr(pl, "decision_scorecard", lambda *a, **k: {"discipline_score": 50.0})
    ps = pl.adaptive_position_sizing(
        "u1",
        base_max_position_pct=20.0,
        confidence_score=50.0,
        gate_passed=False,
        vol_multiple=1.8,
        coach_verdict="NO-GO",
    )
    assert float(ps["suggested_position_pct"]) <= 8.0
    assert isinstance(ps["reason"], str) and ps["reason"]
