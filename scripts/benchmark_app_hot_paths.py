#!/usr/bin/env python3
"""
Đo nhanh các hot path: listing VN (cache RAM), product_layer benchmark loops.
Dùng local evidence trước khi đọc artifacts/performance/timing_dashboard.json.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _bench_listing() -> dict[str, object]:
    from scrapers.vn_listing import clear_tradable_vn_symbol_cache, list_tradable_vn_symbols

    clear_tradable_vn_symbol_cache()
    t0 = time.perf_counter()
    _ = list_tradable_vn_symbols()
    cold_ms = (time.perf_counter() - t0) * 1000.0
    t1 = time.perf_counter()
    _ = list_tradable_vn_symbols()
    warm_ms = (time.perf_counter() - t1) * 1000.0
    return {"list_tradable_cold_ms": round(cold_ms, 3), "list_tradable_warm_ms": round(warm_ms, 3)}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--perf-iterations", type=int, default=5, help="Iterations for perf_benchmark_runner.")
    ap.add_argument("--out-json", default=str(ROOT / "artifacts" / "performance" / "hot_paths_snapshot.json"))
    args = ap.parse_args()

    out: dict[str, object] = {"listing": _bench_listing()}

    perf_script = ROOT / "scripts" / "perf_benchmark_runner.py"
    if perf_script.is_file():
        t0 = time.perf_counter()
        rc = subprocess.run(
            [
                sys.executable,
                str(perf_script),
                "--iterations",
                str(max(1, args.perf_iterations)),
                "--warmup",
                "1",
                "--sleep-ms",
                "0",
            ],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
        )
        out["perf_benchmark_runner"] = {
            "returncode": rc.returncode,
            "elapsed_sec": round(time.perf_counter() - t0, 3),
            "stderr_tail": (rc.stderr or "")[-800:],
        }

    outp = Path(args.out_json)
    outp.parent.mkdir(parents=True, exist_ok=True)
    outp.write_text(json.dumps(out, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(out, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
