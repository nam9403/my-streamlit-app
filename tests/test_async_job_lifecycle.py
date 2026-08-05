"""
Unit tests for async job lifecycle helpers (no live Postgres required).
"""

from __future__ import annotations

import pandas as pd

from core import pg_analysis_jobs as pgj
from core.analysis_job_runner import dispatch_job_payload


def test_ui_state_mapping_canonical_statuses() -> None:
    assert pgj._ui_state_from_db_status("queued")["status"] == "PENDING"
    assert pgj._ui_state_from_db_status("running")["status"] == "PROCESSING"
    assert pgj._ui_state_from_db_status("succeeded", has_result=True)["state"] == "done"
    assert pgj._ui_state_from_db_status("failed", err="boom")["state"] == "error"
    assert pgj._ui_state_from_db_status("FAILED", err="x")["status"] == "FAILED"


def test_local_daemon_blocked_when_pg_enabled(monkeypatch) -> None:
    monkeypatch.setattr(pgj, "pg_analysis_jobs_enabled", lambda: True)
    assert pgj.local_daemon_jobs_allowed() is False


def test_local_daemon_respects_env(monkeypatch) -> None:
    monkeypatch.setattr(pgj, "pg_analysis_jobs_enabled", lambda: False)
    monkeypatch.setenv("II_ALLOW_LOCAL_DAEMON_JOBS", "0")
    assert pgj.local_daemon_jobs_allowed() is False
    monkeypatch.setenv("II_ALLOW_LOCAL_DAEMON_JOBS", "1")
    assert pgj.local_daemon_jobs_allowed() is True


def test_json_safe_result_summary() -> None:
    out = pgj._json_safe_result(
        {
            "latency_seconds": 1.2,
            "report": {"final_action": "BUY", "ticker": "FPT"},
            "finder_df": pd.DataFrame([{"a": 1}, {"a": 2}]),
        }
    )
    assert out["ok"] is True
    assert out["final_action"] == "BUY"
    assert out["row_count"] == 2


def test_dispatch_job_routes_deep_scan(monkeypatch) -> None:
    monkeypatch.setattr(
        "core.analysis_job_runner.execute_deep_scan_job_payload",
        lambda payload: {"candidates": pd.DataFrame(), "job_type": "deep_scan", "row_count": 0},
    )
    out = dispatch_job_payload("deep_scan", {"universe": ["FPT"]})
    assert out["job_type"] == "deep_scan"


def test_dispatch_job_routes_autopilot(monkeypatch) -> None:
    monkeypatch.setattr(
        "core.analysis_job_runner.execute_autopilot_job_payload",
        lambda payload: {"autopilot_df": pd.DataFrame(), "job_type": "autopilot_board"},
    )
    out = dispatch_job_payload("autopilot_board", {"profile": "growth"})
    assert out["job_type"] == "autopilot_board"


def test_start_analysis_background_job_raises_when_pg_on(monkeypatch) -> None:
    from core import ui_bg_analysis as bg

    monkeypatch.setattr(pgj, "pg_analysis_jobs_enabled", lambda: True)
    try:
        bg.start_analysis_background_job("jid", lambda: {})
        raised = False
    except RuntimeError as e:
        raised = True
        assert "PostgreSQL" in str(e)
    assert raised is True


def test_claim_sql_uses_skip_locked() -> None:
    """Regression: claim must use FOR UPDATE SKIP LOCKED for multi-worker safety."""
    import inspect

    src = inspect.getsource(pgj.claim_next_job)
    assert "FOR UPDATE SKIP LOCKED" in src
    assert "STATUS_PROCESSING" in src or "running" in src


def test_heartbeat_and_reclaim_signatures() -> None:
    assert callable(pgj.heartbeat_job)
    assert callable(pgj.reclaim_stale_processing_jobs)
    assert pgj.DEFAULT_VISIBILITY_TIMEOUT_SEC == 900


def test_status_constants_match_db_contract() -> None:
    assert pgj.STATUS_PENDING == "queued"
    assert pgj.STATUS_PROCESSING == "running"
    assert pgj.STATUS_COMPLETED == "succeeded"
    assert pgj.STATUS_FAILED == "failed"
    assert pgj.JOB_TYPE_DEEP_SCAN == "deep_scan"
    assert pgj.JOB_TYPE_AUTOPILOT == "autopilot_board"
