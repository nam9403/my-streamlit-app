"""
Light concurrent load smoke (no Streamlit). Exercises disk snapshot path in parallel.

  python scripts/load_smoke_concurrent.py
  python scripts/load_smoke_concurrent.py --threads 12 --rounds 30
"""
from __future__ import annotations

import argparse
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

SYMS = ("VNM", "FPT", "HPG", "VCB", "MSN")


def _one_task() -> float:
    from core.snapshot_disk_cache import get_disk_snapshot_any_age

    t0 = time.perf_counter()
    for s in SYMS:
        get_disk_snapshot_any_age(s)
    return time.perf_counter() - t0


def main() -> int:
    p = argparse.ArgumentParser(description="Concurrent load smoke (disk snapshot reads).")
    p.add_argument("--threads", type=int, default=8, help="Parallel workers (default 8).")
    p.add_argument("--rounds", type=int, default=20, help="Total tasks = rounds (default 20).")
    args = p.parse_args()
    threads = max(1, min(64, args.threads))
    rounds = max(1, args.rounds)

    print("=== load_smoke_concurrent (get_disk_snapshot_any_age x5 per task) ===")
    print(f"threads={threads} rounds={rounds} cwd={_ROOT}\n")

    times: list[float] = []
    t_wall0 = time.perf_counter()
    with ThreadPoolExecutor(max_workers=threads) as ex:
        futs = [ex.submit(_one_task) for _ in range(rounds)]
        for f in as_completed(futs):
            try:
                times.append(f.result())
            except Exception as e:
                print(f"task error: {e}", file=sys.stderr)
    wall = time.perf_counter() - t_wall0

    if not times:
        print("no successful tasks")
        return 1
    times.sort()
    p50 = times[len(times) // 2]
    p95 = times[int(0.95 * (len(times) - 1))]
    print(f"task wall times: n={len(times)}  p50={p50*1000:.1f}ms  p95={p95*1000:.1f}ms  max={times[-1]*1000:.1f}ms")
    print(f"total wall {wall:.2f}s  throughput {len(times)/wall:.2f} tasks/s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
