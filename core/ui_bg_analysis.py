"""
Background full-ticker analysis: worker thread writes only to disk; Streamlit main thread consumes.

Avoids mutating st.session_state from non-main threads.
"""

from __future__ import annotations

import json
import pickle
import threading
import time
from pathlib import Path
from typing import Any, Callable

_ROOT = Path(__file__).resolve().parent.parent
_JOBS = _ROOT / "data" / "runtime" / "ui_bg_jobs"


def analysis_job_id(parts: tuple[Any, ...]) -> str:
    from core.ui_day_cache import cache_key_hash

    return cache_key_hash("analysis_bg", parts)


def _status_path(job_id: str) -> Path:
    return _JOBS / f"{job_id}.status.json"


def _payload_path(job_id: str) -> Path:
    return _JOBS / f"{job_id}.payload.pkl"


def read_analysis_job_status(job_id: str) -> dict[str, Any] | None:
    try:
        from core import pg_analysis_jobs as pgj

        if pgj.pg_analysis_jobs_enabled():
            return pgj.read_job_status(job_id)
    except Exception:
        pass
    p = _status_path(job_id)
    if not p.is_file():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def start_analysis_background_job(job_id: str, work: Callable[[], dict[str, Any]]) -> None:
    """
    Spawn daemon thread ONLY when PostgreSQL jobs are disabled and local daemons are allowed.
    Prefer ``pg_analysis_jobs.enqueue_*`` from the composition/UI layer when PG is on.
    """
    try:
        from core import pg_analysis_jobs as pgj

        if pgj.pg_analysis_jobs_enabled():
            raise RuntimeError(
                "PostgreSQL async jobs are enabled — do not start Streamlit daemon threads. "
                "Enqueue via ii_async_jobs and run worker.py."
            )
        if not pgj.local_daemon_jobs_allowed():
            raise RuntimeError(
                "Local daemon jobs disabled (II_ALLOW_LOCAL_DAEMON_JOBS=0). "
                "Enable PostgreSQL worker or set II_ALLOW_LOCAL_DAEMON_JOBS=1 for offline/dev."
            )
    except ImportError:
        pass
    _JOBS.mkdir(parents=True, exist_ok=True)
    st_path = _status_path(job_id)
    pay_path = _payload_path(job_id)
    try:
        cur = json.loads(st_path.read_text(encoding="utf-8")) if st_path.is_file() else {}
        if cur.get("state") in ("pending", "running"):
            return
    except (OSError, json.JSONDecodeError):
        pass

    def _runner() -> None:
        t0 = time.time()
        try:
            st_path.write_text(
                json.dumps({"state": "running", "started_mono": time.monotonic()}, ensure_ascii=False),
                encoding="utf-8",
            )
            bundle = work()
            pay_path.write_bytes(pickle.dumps(bundle, protocol=pickle.HIGHEST_PROTOCOL))
            st_path.write_text(
                json.dumps(
                    {
                        "state": "done",
                        "elapsed_sec": round(time.time() - t0, 3),
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
        except Exception as e:
            st_path.write_text(
                json.dumps({"state": "error", "error": repr(e), "elapsed_sec": round(time.time() - t0, 3)}, ensure_ascii=False),
                encoding="utf-8",
            )

    st_path.write_text(json.dumps({"state": "pending"}, ensure_ascii=False), encoding="utf-8")
    if pay_path.exists():
        try:
            pay_path.unlink()
        except OSError:
            pass
    th = threading.Thread(target=_runner, name=f"analysis_bg_{job_id}", daemon=True)
    th.start()


def try_consume_analysis_job(job_id: str) -> dict[str, Any] | None:
    """
    If job finished, read payload and delete job files.
    Returns dict with keys report, ohlcv or None if not ready.
    """
    try:
        from core import pg_analysis_jobs as pgj

        if pgj.pg_analysis_jobs_enabled():
            return pgj.try_consume_completed_result(job_id)
    except Exception:
        pass
    st = read_analysis_job_status(job_id)
    if not st or st.get("state") != "done":
        return None
    pay = _payload_path(job_id)
    if not pay.is_file():
        return None
    try:
        raw = pay.read_bytes()
    except OSError:
        return None
    try:
        bundle = pickle.loads(raw)
    except Exception:
        return None
    try:
        _status_path(job_id).unlink(missing_ok=True)
        pay.unlink(missing_ok=True)
    except OSError:
        pass
    return bundle if isinstance(bundle, dict) else None
