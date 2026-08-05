#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core.analysis_runtime_service import load_snapshot_cached, load_strategic_report_cached  # noqa: E402
from core.product_layer import get_dss_readiness_report  # noqa: E402


def _build_report(symbol: str, profile: str, capital: float) -> dict[str, Any]:
    snap = load_snapshot_cached(symbol)
    if snap is None:
        raise RuntimeError(f"Không có snapshot cho {symbol}.")
    return load_strategic_report_cached(
        symbol,
        snap,
        profile,
        float(capital),
        quick_mode=True,
        llm_live=False,
    )


def main() -> int:
    reconfigure = getattr(sys.stdout, "reconfigure", None)
    if callable(reconfigure):
        reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbol", default="FPT")
    ap.add_argument("--user-id", default="default_user")
    ap.add_argument("--profile", default="growth")
    ap.add_argument("--capital", type=float, default=100_000_000.0)
    ap.add_argument("--strict", action="store_true")
    ap.add_argument("--out", default="artifacts/operations/dss_release_gate.json")
    args = ap.parse_args()

    report = _build_report(str(args.symbol).strip().upper(), str(args.profile), float(args.capital))
    gate = get_dss_readiness_report(report, str(args.user_id), lookback_days=365)
    out_path = Path(str(args.out))
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(gate, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(gate, ensure_ascii=False, indent=2))
    if args.strict and str(gate.get("decision")) != "COMMERCIAL_READY":
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
