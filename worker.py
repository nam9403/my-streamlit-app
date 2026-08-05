#!/usr/bin/env python3
"""
Standalone async job worker for `ii_async_jobs` (Postgres).

Entrypoint tách biệt Streamlit: claim FOR UPDATE SKIP LOCKED, heartbeat lease,
COMPLETED/FAILED. Chạy:
  python worker.py
  python worker.py --lease-sec 900 --heartbeat-sec 30 --poll-sec 1.0

Hoặc: python scripts/run_pg_job_worker.py (cùng logic).
"""
from __future__ import annotations

import argparse
import os
import socket
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import env_bootstrap

env_bootstrap.init_app_environment()

from core.observability import capture_exception, configure_observability

configure_observability("async_worker")

from core.product_layer import initialize_database_connection

initialize_database_connection()


def _run_with_heartbeat(
    *,
    key: str,
    worker_id: str,
    lease_sec: int,
    heartbeat_sec: float,
    work,
):
    stop = threading.Event()

    def _beat() -> None:
        from core import pg_analysis_jobs as pgj

        while not stop.wait(max(5.0, float(heartbeat_sec))):
            try:
                pgj.heartbeat_job(key, worker_id=worker_id, lease_seconds=lease_sec)
            except Exception as e:
                print(f"[worker] heartbeat error key={key[:16]}... err={e!r}")

    th = threading.Thread(target=_beat, name=f"job_heartbeat_{key[:12]}", daemon=True)
    th.start()
    try:
        return work()
    finally:
        stop.set()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="PostgreSQL ii_async_jobs worker")
    ap.add_argument(
        "--lease-sec",
        type=int,
        default=900,
        help="Lease/heartbeat window while PROCESSING (default 15m).",
    )
    ap.add_argument("--heartbeat-sec", type=float, default=30.0, help="Heartbeat interval while running a job.")
    ap.add_argument("--poll-sec", type=float, default=1.0, help="Sleep when queue empty.")
    ap.add_argument("--worker-id", default="", help="Override worker id (default hostname-pid).")
    args = ap.parse_args(argv)

    from core import pg_analysis_jobs as pgj
    from core.analysis_job_runner import dispatch_job_payload

    if not pgj.pg_analysis_jobs_enabled():
        print("[BLOCKED] Enable PostgreSQL: set II_DB_URL=postgresql://... and II_USE_PG_ANALYSIS_JOBS=1")
        return 2

    wid = str(args.worker_id or "").strip() or f"{socket.gethostname()}-{os.getpid()}"
    lease = max(60, int(args.lease_sec))
    print(f"[worker] started worker_id={wid} lease_sec={lease} heartbeat_sec={args.heartbeat_sec}")

    while True:
        try:
            job = pgj.claim_next_job(worker_id=wid, lease_seconds=lease)
            if not job:
                time.sleep(max(0.2, float(args.poll_sec)))
                continue
            key = str(job["idempotency_key"])
            payload = job.get("payload") or {}
            job_type = str(job.get("job_type") or "full_ticker_analysis")
            print(f"[worker] claimed job_type={job_type} key={key[:16]}...")
            try:
                bundle = _run_with_heartbeat(
                    key=key,
                    worker_id=wid,
                    lease_sec=lease,
                    heartbeat_sec=float(args.heartbeat_sec),
                    work=lambda: dispatch_job_payload(job_type, payload),
                )
                pgj.mark_succeeded(key, bundle)
                print(f"[worker] COMPLETED key={key[:16]}...")
            except Exception as e:
                pgj.mark_failed(key, repr(e))
                capture_exception(e, job_key=key, job_type=job_type)
                print(f"[worker] FAILED key={key[:16]}... err={e!r}")
        except KeyboardInterrupt:
            print("[worker] stopped")
            return 0
        except Exception as e:
            capture_exception(e)
            print(f"[worker] loop error: {e!r}")
            time.sleep(2.0)


if __name__ == "__main__":
    raise SystemExit(main())
