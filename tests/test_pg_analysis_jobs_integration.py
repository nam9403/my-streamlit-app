"""Integration tests for PostgreSQL job queue (optional; needs II_DB_URL=postgresql://...)."""

from __future__ import annotations

import os
import uuid

import pytest

pytest.importorskip("psycopg")

from core import pg_analysis_jobs as pgj


def _pg_dsn() -> str:
    dsn = str(os.environ.get("II_DB_URL") or "").strip()
    if not (dsn.startswith("postgres://") or dsn.startswith("postgresql://")):
        pytest.skip("Set II_DB_URL to a PostgreSQL DSN to run pg job queue integration tests.")
    return dsn


@pytest.fixture(autouse=True)
def _set_pg_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("II_DB_URL", _pg_dsn())
    monkeypatch.setenv("II_USE_PG_ANALYSIS_JOBS", "1")


def test_pg_enqueue_claim_complete_roundtrip() -> None:
    key = f"test_{uuid.uuid4().hex[:20]}"
    payload = {
        "user_id": "test_user",
        "ticker": "FPT",
        "profile": "growth",
        "total_capital_vnd": 100_000_000.0,
        "plan_id": "free",
        "effective_quick_mode": True,
        "llm_live": False,
    }
    pgj.enqueue_full_ticker_analysis(key, payload)
    st = pgj.read_job_status(key)
    assert st is not None
    assert st.get("state") in ("pending", "running")

    job = pgj.claim_next_job(worker_id="pytest-worker", lease_seconds=60)
    assert job is not None
    assert job["idempotency_key"] == key
    assert job.get("job_type") == "full_ticker_analysis"

    bundle = {
        "report": {"final_action": "HOLD", "ticker": "FPT"},
        "ohlcv": None,
    }
    pgj.mark_succeeded(key, bundle)

    out = pgj.try_consume_completed_result(key)
    assert isinstance(out, dict)
    assert out.get("report", {}).get("final_action") == "HOLD"

    st2 = pgj.read_job_status(key)
    assert st2 is None


def test_pg_finder_enqueue_claim_job_type() -> None:
    key = f"test_finder_{uuid.uuid4().hex[:16]}"
    payload = {
        "universe": ["AAA", "BBB"],
        "profile": "balanced",
        "total_capital_vnd": 50_000_000.0,
        "quick_mode": True,
        "llm_live": False,
        "allowed_subtypes": [],
        "min_avg_volume_20": 0.0,
        "benchmark_return_3m_pct": None,
        "min_data_quality_pct": 55.0,
        "only_actionable": False,
        "min_catalyst_score": 0.0,
        "dynamic_sector_calibration": True,
        "top_n": 5,
    }
    pgj.enqueue_finder_3m_board(key, payload)
    job = pgj.claim_next_job(worker_id="pytest-worker-finder", lease_seconds=60)
    assert job is not None
    assert job["idempotency_key"] == key
    assert job.get("job_type") == "finder_3m_board"
    assert job.get("payload", {}).get("universe") == ["AAA", "BBB"]
    pgj.mark_failed(key, "pytest_abort")
    pgj.delete_job_if_failed(key)
    assert pgj.read_job_status(key) is None
