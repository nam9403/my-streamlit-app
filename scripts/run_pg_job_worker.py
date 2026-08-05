#!/usr/bin/env python3
"""
Durable worker for PostgreSQL-backed jobs in `ii_async_jobs`.

Thin wrapper around repo-root ``worker.py`` (same loop: claim / heartbeat / COMPLETED|FAILED).

Usage:
  python scripts/run_pg_job_worker.py
  python scripts/run_pg_job_worker.py --lease-sec 900 --heartbeat-sec 30 --poll-sec 1.0
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from worker import main

if __name__ == "__main__":
    raise SystemExit(main())
