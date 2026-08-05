from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _run(cmd: list[str]) -> tuple[int, str, str]:
    proc = subprocess.run(cmd, cwd=str(ROOT), capture_output=True, text=True)
    return int(proc.returncode), str(proc.stdout or ""), str(proc.stderr or "")


def main() -> int:
    ap = argparse.ArgumentParser(description="One-shot runtime benchmark for 6S optimization tracking.")
    ap.add_argument("--symbol", default="FPT", help="Ticker symbol for timeline profiling.")
    ap.add_argument(
        "--out-json",
        default=str(ROOT / "artifacts" / "performance" / "runtime_6s_benchmark_summary.json"),
        help="Output summary JSON path.",
    )
    args = ap.parse_args()

    hot_cmd = [sys.executable, "scripts/benchmark_app_hot_paths.py", "--perf-iterations", "5"]
    timeline_cmd = [
        sys.executable,
        "scripts/profile_app_timeline.py",
        "--symbol",
        str(args.symbol or "FPT").strip().upper(),
        "--out-json",
        "artifacts/performance/profile_timeline_snapshot_latest.json",
    ]

    hot_rc, hot_out, hot_err = _run(hot_cmd)
    timeline_rc, timeline_out, timeline_err = _run(timeline_cmd)

    summary = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "symbol": str(args.symbol or "FPT").strip().upper(),
        "commands": {
            "hot_paths": " ".join(hot_cmd),
            "timeline": " ".join(timeline_cmd),
        },
        "results": {
            "hot_paths": {
                "returncode": hot_rc,
                "stdout_tail": hot_out[-3000:],
                "stderr_tail": hot_err[-1000:],
            },
            "timeline": {
                "returncode": timeline_rc,
                "stdout_tail": timeline_out[-3000:],
                "stderr_tail": timeline_err[-1000:],
            },
        },
        "status": "PASS" if hot_rc == 0 and timeline_rc == 0 else "FAIL",
    }

    out_path = Path(str(args.out_json))
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(f"[runtime_6s_benchmark] status={summary['status']}")
    print(f"[runtime_6s_benchmark] wrote {out_path}")
    return 0 if summary["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
