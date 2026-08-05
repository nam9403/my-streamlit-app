"""
PostgreSQL-backed durable job queue for heavy UI workloads.

Streamlit chỉ INSERT job ``PENDING`` (status DB: ``queued``) + ``payload_json``.
Worker độc lập claim bằng ``FOR UPDATE SKIP LOCKED``, heartbeat lease, ghi kết quả.

Canonical UI/API names ↔ DB status:
  PENDING     → queued
  PROCESSING  → running
  COMPLETED   → succeeded
  FAILED      → failed
"""

from __future__ import annotations

import json
import os
import pickle
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parent.parent

# Canonical names (docs / UI); DB stores legacy lowercase for backward compatibility.
STATUS_PENDING = "queued"
STATUS_PROCESSING = "running"
STATUS_COMPLETED = "succeeded"
STATUS_FAILED = "failed"

JOB_TYPE_FULL_TICKER = "full_ticker_analysis"
JOB_TYPE_FINDER_3M = "finder_3m_board"
JOB_TYPE_DEEP_SCAN = "deep_scan"
JOB_TYPE_AUTOPILOT = "autopilot_board"

DEFAULT_VISIBILITY_TIMEOUT_SEC = 900  # 15 minutes
DEFAULT_LEASE_SEC = 900


def pg_analysis_jobs_enabled() -> bool:
    if str(os.environ.get("II_USE_PG_ANALYSIS_JOBS", "1") or "").strip().lower() in ("0", "false", "no", "off"):
        return False
    if not _postgres_driver_available():
        return False
    from core.db_runtime import resolve_db_runtime

    cfg = resolve_db_runtime(root=_ROOT, default_sqlite_path=_ROOT / "data" / "app_state.db")
    return cfg.backend == "postgresql" and bool(cfg.dsn)


def local_daemon_jobs_allowed() -> bool:
    """Daemon threads trong Streamlit chỉ được phép khi PG tắt và env cho phép (dev/offline)."""
    if pg_analysis_jobs_enabled():
        return False
    return str(os.environ.get("II_ALLOW_LOCAL_DAEMON_JOBS", "1") or "").strip().lower() not in (
        "0",
        "false",
        "no",
        "off",
    )


def _postgres_driver_available() -> bool:
    try:
        import importlib.util

        return importlib.util.find_spec("psycopg") is not None
    except Exception:
        return False


def _dsn() -> str:
    from core.db_runtime import resolve_db_runtime

    cfg = resolve_db_runtime(root=_ROOT, default_sqlite_path=_ROOT / "data" / "app_state.db")
    if cfg.backend != "postgresql" or not cfg.dsn:
        raise RuntimeError("PostgreSQL DSN required for pg_analysis_jobs")
    return cfg.dsn


def visibility_timeout_seconds() -> int:
    try:
        return max(60, int(os.environ.get("II_ASYNC_JOB_VISIBILITY_TIMEOUT_SEC", str(DEFAULT_VISIBILITY_TIMEOUT_SEC))))
    except ValueError:
        return DEFAULT_VISIBILITY_TIMEOUT_SEC


def ensure_pg_job_schema(conn: Any) -> None:
    ddl_parts = [
        """
        CREATE TABLE IF NOT EXISTS ii_async_jobs (
            idempotency_key TEXT PRIMARY KEY,
            job_type TEXT NOT NULL,
            payload_json JSONB NOT NULL,
            status TEXT NOT NULL,
            locked_until TIMESTAMPTZ,
            worker_id TEXT,
            result_pickle BYTEA,
            result_json JSONB,
            error_text TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """,
        """
        CREATE INDEX IF NOT EXISTS ii_async_jobs_status_created_idx
            ON ii_async_jobs (status, created_at)
        """,
        # Idempotent migration for older DBs created before result_json existed.
        "ALTER TABLE ii_async_jobs ADD COLUMN IF NOT EXISTS result_json JSONB",
    ]
    with conn.cursor() as cur:
        for stmt in ddl_parts:
            cur.execute(stmt)
    conn.commit()


def _ui_state_from_db_status(st: str, *, err: str | None = None, has_result: bool = False) -> dict[str, Any]:
    if st in (STATUS_PENDING, "PENDING", "pending"):
        return {"state": "pending", "status": "PENDING"}
    if st in (STATUS_PROCESSING, "PROCESSING", "processing", "running"):
        return {"state": "running", "status": "PROCESSING"}
    if st in (STATUS_COMPLETED, "COMPLETED", "completed", "succeeded"):
        if has_result:
            return {"state": "done", "status": "COMPLETED"}
        return {"state": "pending", "status": "PENDING"}
    if st in (STATUS_FAILED, "FAILED", "failed"):
        return {"state": "error", "status": "FAILED", "error": str(err or "")}
    return {"state": "pending", "status": "PENDING"}


def read_job_status(idempotency_key: str) -> dict[str, Any] | None:
    """Map DB row to UI shape: state pending|running|done|error (+ canonical status)."""
    import psycopg

    with psycopg.connect(_dsn(), autocommit=True) as conn:
        ensure_pg_job_schema(conn)
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT status, error_text, result_pickle, result_json
                FROM ii_async_jobs WHERE idempotency_key = %s
                """,
                (idempotency_key,),
            )
            row = cur.fetchone()
    if not row:
        return None
    st, err, blob, rjson = row[0], row[1], row[2], row[3]
    has_result = bool(blob) or rjson is not None
    return _ui_state_from_db_status(str(st or ""), err=str(err) if err else None, has_result=has_result)


def try_consume_completed_result(idempotency_key: str) -> dict[str, Any] | None:
    """If job completed, return bundle and remove row."""
    import psycopg

    with psycopg.connect(_dsn()) as conn:
        ensure_pg_job_schema(conn)
        with conn.cursor() as cur:
            cur.execute(
                """
                DELETE FROM ii_async_jobs
                WHERE idempotency_key = %s
                  AND status = %s
                  AND (result_pickle IS NOT NULL OR result_json IS NOT NULL)
                RETURNING result_pickle, result_json
                """,
                (idempotency_key, STATUS_COMPLETED),
            )
            row = cur.fetchone()
        conn.commit()
    if not row:
        return None
    blob, rjson = row[0], row[1]
    if blob is not None:
        try:
            return pickle.loads(bytes(blob))
        except Exception:
            pass
    if rjson is not None:
        if isinstance(rjson, str):
            try:
                return json.loads(rjson)
            except json.JSONDecodeError:
                return {"result": rjson}
        if isinstance(rjson, dict):
            return dict(rjson)
        return {"result": rjson}
    return None


def finder_pg_jobs_enabled() -> bool:
    if not pg_analysis_jobs_enabled():
        return False
    v = str(os.environ.get("II_USE_PG_FINDER_JOBS", "1") or "").strip().lower()
    return v not in ("0", "false", "no", "off")


def scan_pg_jobs_enabled() -> bool:
    if not pg_analysis_jobs_enabled():
        return False
    v = str(os.environ.get("II_USE_PG_SCAN_JOBS", "1") or "").strip().lower()
    return v not in ("0", "false", "no", "off")


def autopilot_pg_jobs_enabled() -> bool:
    if not pg_analysis_jobs_enabled():
        return False
    v = str(os.environ.get("II_USE_PG_AUTOPILOT_JOBS", "1") or "").strip().lower()
    return v not in ("0", "false", "no", "off")


def enqueue_durable_job(idempotency_key: str, job_type: str, payload: dict[str, Any]) -> None:
    """Insert PENDING job. Payload must be JSON-serializable."""
    import psycopg
    from psycopg.types.json import Json

    jt = str(job_type or "").strip() or JOB_TYPE_FULL_TICKER
    payload_json = Json(payload)
    with psycopg.connect(_dsn()) as conn:
        ensure_pg_job_schema(conn)
        with conn.cursor() as cur:
            cur.execute(
                "SELECT status, result_pickle, result_json FROM ii_async_jobs WHERE idempotency_key = %s",
                (idempotency_key,),
            )
            row = cur.fetchone()
            if row:
                st, blob, rjson = row[0], row[1], row[2]
                if st == STATUS_COMPLETED and (blob is not None or rjson is not None):
                    conn.commit()
                    return
                if st in (STATUS_PENDING, STATUS_PROCESSING):
                    conn.commit()
                    return
                if st == STATUS_FAILED:
                    cur.execute(
                        """
                        UPDATE ii_async_jobs
                        SET status = %s, job_type = %s, payload_json = %s, error_text = NULL,
                            locked_until = NULL, worker_id = NULL, result_pickle = NULL,
                            result_json = NULL, updated_at = NOW()
                        WHERE idempotency_key = %s
                        """,
                        (STATUS_PENDING, jt, payload_json, idempotency_key),
                    )
                    conn.commit()
                    return
            cur.execute(
                """
                INSERT INTO ii_async_jobs (idempotency_key, job_type, payload_json, status)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (idempotency_key) DO NOTHING
                """,
                (idempotency_key, jt, payload_json, STATUS_PENDING),
            )
        conn.commit()


def enqueue_full_ticker_analysis(idempotency_key: str, payload: dict[str, Any]) -> None:
    enqueue_durable_job(idempotency_key, JOB_TYPE_FULL_TICKER, payload)


def enqueue_finder_3m_board(idempotency_key: str, payload: dict[str, Any]) -> None:
    enqueue_durable_job(idempotency_key, JOB_TYPE_FINDER_3M, payload)


def enqueue_deep_scan(idempotency_key: str, payload: dict[str, Any]) -> None:
    enqueue_durable_job(idempotency_key, JOB_TYPE_DEEP_SCAN, payload)


def enqueue_autopilot_board(idempotency_key: str, payload: dict[str, Any]) -> None:
    enqueue_durable_job(idempotency_key, JOB_TYPE_AUTOPILOT, payload)


def delete_job_if_failed(idempotency_key: str) -> None:
    import psycopg

    with psycopg.connect(_dsn(), autocommit=True) as conn:
        ensure_pg_job_schema(conn)
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM ii_async_jobs WHERE idempotency_key = %s AND status = %s",
                (idempotency_key, STATUS_FAILED),
            )


def reclaim_stale_processing_jobs(*, visibility_timeout_sec: int | None = None) -> int:
    """
    Jobs stuck in PROCESSING past visibility / lease → PENDING for retry.
    Default visibility timeout: 15 minutes (II_ASYNC_JOB_VISIBILITY_TIMEOUT_SEC).
    """
    import psycopg

    timeout = int(visibility_timeout_sec if visibility_timeout_sec is not None else visibility_timeout_seconds())
    timeout = max(60, timeout)
    with psycopg.connect(_dsn()) as conn:
        ensure_pg_job_schema(conn)
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE ii_async_jobs
                SET status = %s,
                    locked_until = NULL,
                    worker_id = NULL,
                    updated_at = NOW()
                WHERE status = %s
                  AND (
                    (locked_until IS NOT NULL AND locked_until < NOW())
                    OR (
                        locked_until IS NULL
                        AND updated_at < NOW() - (%s * INTERVAL '1 second')
                    )
                    OR (
                        locked_until IS NOT NULL
                        AND updated_at < NOW() - (%s * INTERVAL '1 second')
                        AND locked_until < NOW() + INTERVAL '1 second'
                    )
                  )
                """,
                (STATUS_PENDING, STATUS_PROCESSING, timeout, timeout),
            )
            n = int(cur.rowcount or 0)
        conn.commit()
    return n


def claim_next_job(*, worker_id: str, lease_seconds: int | None = None) -> dict[str, Any] | None:
    """
    Atomically claim one PENDING (or stale PROCESSING) job → PROCESSING.
    Uses SELECT ... FOR UPDATE SKIP LOCKED.
    """
    import psycopg

    lease = max(60, int(lease_seconds if lease_seconds is not None else DEFAULT_LEASE_SEC))
    # Reclaim clearly expired leases before claim (visibility timeout path).
    try:
        reclaim_stale_processing_jobs()
    except Exception:
        pass

    with psycopg.connect(_dsn()) as conn:
        conn.autocommit = False
        ensure_pg_job_schema(conn)
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE ii_async_jobs AS j
                SET status = %s,
                    locked_until = NOW() + (%s * INTERVAL '1 second'),
                    worker_id = %s,
                    updated_at = NOW()
                FROM (
                    SELECT idempotency_key FROM ii_async_jobs
                    WHERE (status = %s)
                       OR (status = %s AND (
                            locked_until IS NULL
                            OR locked_until < NOW()
                       ))
                    ORDER BY created_at ASC
                    FOR UPDATE SKIP LOCKED
                    LIMIT 1
                ) AS sub
                WHERE j.idempotency_key = sub.idempotency_key
                RETURNING j.idempotency_key, j.job_type, j.payload_json
                """,
                (STATUS_PROCESSING, lease, worker_id, STATUS_PENDING, STATUS_PROCESSING),
            )
            row = cur.fetchone()
        conn.commit()
    if not row:
        return None
    key, jt, pj = row[0], row[1], row[2]
    if isinstance(pj, str):
        payload = json.loads(pj)
    elif isinstance(pj, dict):
        payload = pj
    else:
        payload = dict(pj) if pj is not None else {}
    return {"idempotency_key": key, "job_type": str(jt or JOB_TYPE_FULL_TICKER), "payload": payload}


def heartbeat_job(idempotency_key: str, *, worker_id: str, lease_seconds: int | None = None) -> bool:
    """Extend lease while PROCESSING so other workers do not reclaim mid-job."""
    import psycopg

    lease = max(60, int(lease_seconds if lease_seconds is not None else DEFAULT_LEASE_SEC))
    with psycopg.connect(_dsn()) as conn:
        ensure_pg_job_schema(conn)
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE ii_async_jobs
                SET locked_until = NOW() + (%s * INTERVAL '1 second'),
                    updated_at = NOW()
                WHERE idempotency_key = %s
                  AND status = %s
                  AND worker_id = %s
                """,
                (lease, idempotency_key, STATUS_PROCESSING, worker_id),
            )
            ok = (cur.rowcount or 0) > 0
        conn.commit()
    return bool(ok)


def _json_safe_result(bundle: dict[str, Any]) -> dict[str, Any]:
    """Thin JSON summary for polling UIs (DataFrames stay in pickle)."""
    out: dict[str, Any] = {}
    if not isinstance(bundle, dict):
        return {"ok": True}
    for k in ("latency_seconds", "ticker", "user_id", "job_type", "symbol_count", "row_count"):
        if k in bundle:
            out[k] = bundle[k]
    report = bundle.get("report")
    if isinstance(report, dict):
        out["final_action"] = report.get("final_action")
        out["ticker"] = report.get("ticker") or out.get("ticker")
    finder_df = bundle.get("finder_df")
    if finder_df is not None and hasattr(finder_df, "__len__"):
        try:
            out["row_count"] = int(len(finder_df))
        except Exception:
            pass
    candidates = bundle.get("candidates")
    if candidates is not None and hasattr(candidates, "__len__"):
        try:
            out["row_count"] = int(len(candidates))
        except Exception:
            pass
    out["ok"] = True
    return out


def mark_succeeded(idempotency_key: str, bundle: dict[str, Any]) -> None:
    import psycopg
    from psycopg.types.json import Json

    blob = pickle.dumps(bundle, protocol=pickle.HIGHEST_PROTOCOL)
    summary = _json_safe_result(bundle if isinstance(bundle, dict) else {})
    with psycopg.connect(_dsn()) as conn:
        ensure_pg_job_schema(conn)
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE ii_async_jobs
                SET status = %s, result_pickle = %s, result_json = %s, locked_until = NULL,
                    error_text = NULL, updated_at = NOW()
                WHERE idempotency_key = %s AND status = %s
                """,
                (STATUS_COMPLETED, blob, Json(summary), idempotency_key, STATUS_PROCESSING),
            )
        conn.commit()


def mark_failed(idempotency_key: str, error: str) -> None:
    import psycopg

    with psycopg.connect(_dsn()) as conn:
        ensure_pg_job_schema(conn)
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE ii_async_jobs
                SET status = %s, error_text = %s, locked_until = NULL,
                    result_pickle = NULL, result_json = NULL, updated_at = NOW()
                WHERE idempotency_key = %s AND status = %s
                """,
                (STATUS_FAILED, error[:8000], idempotency_key, STATUS_PROCESSING),
            )
        conn.commit()
