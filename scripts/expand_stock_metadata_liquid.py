"""
Mở rộng stock_metadata.json cho liquid universe (~400 HOSE) — placeholder ngành khi thiếu.

Usage:
  python scripts/expand_stock_metadata_liquid.py
  python scripts/expand_stock_metadata_liquid.py --dry-run
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

META_PATH = ROOT / "data" / "stock_metadata.json"

_DEFAULT_BLOCK = {
    "industry_vi": "Chưa phân loại — HOSE",
    "industry_cluster": "other",
    "industry_subtype": "other",
}


def _load_meta() -> dict:
    if not META_PATH.exists():
        return {}
    try:
        return json.loads(META_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _liquid_pool() -> list[str]:
    try:
        from core.autopilot_nightly_board import resolve_liquid_target_symbols

        return list(resolve_liquid_target_symbols(limit=None))
    except Exception:
        from core.liquid_universe import VN30_SYMBOLS

        return list(VN30_SYMBOLS)


def main() -> int:
    ap = argparse.ArgumentParser(description="Seed stock_metadata for liquid HOSE symbols")
    ap.add_argument("--dry-run", action="store_true", help="Print counts only, do not write")
    args = ap.parse_args()

    meta = _load_meta()
    pool = _liquid_pool()
    added = 0
    for sym in pool:
        key = str(sym).strip().upper()
        if not key or key in meta:
            continue
        meta[key] = dict(_DEFAULT_BLOCK)
        added += 1

    print(f"liquid_pool={len(pool)} existing={len(_load_meta())} added={added} total_after={len(meta)}")
    if args.dry_run:
        return 0

    META_PATH.parent.mkdir(parents=True, exist_ok=True)
    META_PATH.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Wrote {META_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
