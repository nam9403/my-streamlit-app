"""
Export Wave 6 growth / onboarding conversion + pilot readiness snapshot.

  python scripts/export_growth_conversion_snapshot.py
  python scripts/export_growth_conversion_snapshot.py --days 30
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
    ap = argparse.ArgumentParser(description="Export growth conversion snapshot.")
    ap.add_argument("--days", type=int, default=30)
    ap.add_argument("--out", default="artifacts/operations/growth_conversion_latest.json")
    args = ap.parse_args()

    from core.growth_conversion_service import (
        build_growth_conversion_snapshot,
        write_growth_conversion_snapshot,
    )
    from core.product_layer import _conn, get_admin_kpi

    snap = build_growth_conversion_snapshot(
        conn_factory=_conn,
        days=int(args.days),
        get_admin_kpi=get_admin_kpi,
    )
    out = write_growth_conversion_snapshot(snap, ROOT / str(args.out))
    print(json.dumps(snap, ensure_ascii=False, indent=2))
    print(f"\nWrote {out}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
