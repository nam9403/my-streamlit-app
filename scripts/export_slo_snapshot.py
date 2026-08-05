"""
Export SLO / ops snapshot to artifacts (P2 dashboard feed).

  python scripts/export_slo_snapshot.py
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

try:
    import env_bootstrap  # noqa: F401
except Exception:
    pass


def main() -> int:
    ap = argparse.ArgumentParser(description="Export SLO snapshot JSON.")
    ap.add_argument("--out", default="artifacts/operations/slo_snapshot.json")
    args = ap.parse_args()

    from core.slo_ops_panel import collect_slo_snapshot

    snap = collect_slo_snapshot()
    out = ROOT / str(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(snap, ensure_ascii=False, indent=2), encoding="utf-8")
    health = snap.get("nightly_health") or {}
    print(
        json.dumps(
            {
                "out": str(out),
                "nightly_ok": health.get("ok"),
                "coverage_pct": health.get("coverage_pct"),
                "fail_rate_pct": snap.get("fail_rate_pct"),
                "p95": (snap.get("autopilot_timing") or {}).get("p95_ms"),
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
