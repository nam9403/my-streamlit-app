from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scrapers.financial_data import fetch_financial_snapshot
from scrapers.portal import fetch_financial_indicators, fetch_ohlcv_history

VN30 = [
    "ACB",
    "BCM",
    "BID",
    "BVH",
    "CTG",
    "FPT",
    "GAS",
    "GVR",
    "HDB",
    "HPG",
    "MBB",
    "MSN",
    "MWG",
    "PLX",
    "POW",
    "SAB",
    "SHB",
    "SSB",
    "SSI",
    "STB",
    "TCB",
    "TPB",
    "VCB",
    "VHM",
    "VIB",
    "VIC",
    "VJC",
    "VNM",
    "VPB",
    "VRE",
]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _financial_ready(fin: dict[str, Any] | None) -> bool:
    if not isinstance(fin, dict) or not fin:
        return False
    core = ("debt_to_equity", "gross_margin", "revenue_growth_yoy", "profit_growth_yoy")
    return any(fin.get(k) is not None for k in core)


def _run_pass(name: str, strict_live: bool, fail_fast: bool) -> dict[str, Any]:
    if strict_live:
        os.environ["II_STRICT_REAL_FINANCIAL_DATA"] = "1"
    else:
        os.environ["II_STRICT_REAL_FINANCIAL_DATA"] = "0"
    os.environ["II_PORTAL_FAIL_FAST"] = "1" if fail_fast else "0"
    os.environ["II_PORTAL_FAIL_FAST_BUDGET_SEC"] = "4"
    os.environ["II_PORTAL_LIVE_BUDGET_SEC"] = "20" if not fail_fast else "8"
    os.environ["II_PORTAL_TIMEOUT_LADDER_SEC"] = "3,6,10,16" if not fail_fast else "1.5,3,5"
    os.environ["II_FINANCIAL_MAX_PROBES"] = "4" if not fail_fast else "2"
    os.environ["II_OHLCV_STORE_ENABLED"] = "1"
    os.environ["II_OHLCV_DISK_FIRST"] = "0"

    rows: list[dict[str, Any]] = []
    ok_fin = 0
    ok_ohlcv_3y = 0
    for i, sym in enumerate(VN30, start=1):
        t0 = time.perf_counter()
        snap = None
        fin = None
        ohlcv = None
        snap_ok = False
        fin_ok = False
        ohlcv_3y_ok = False
        fin_src = ""
        ohlcv_src = ""
        err = ""
        try:
            snap = fetch_financial_snapshot(sym, bypass_cache=True)
            snap_ok = isinstance(snap, dict) and bool(snap)
            fin = fetch_financial_indicators(sym, fast_mode=False)
            fin_ok = _financial_ready(fin)
            fin_src = str((fin or {}).get("source") or "")
            ohlcv = fetch_ohlcv_history(sym, sessions=1300)
            ohlcv_src = str(getattr(ohlcv, "attrs", {}).get("source") or "")
            rows_3y = 0
            if ohlcv is not None and len(ohlcv) > 0:
                import pandas as pd

                d = ohlcv.copy()
                d["date"] = pd.to_datetime(d["date"], errors="coerce")
                d = d.dropna(subset=["date"]).sort_values("date")
                if not d.empty:
                    end = d["date"].max()
                    rows_3y = int((d["date"] >= (end - pd.Timedelta(days=1096))).sum())
            ohlcv_3y_ok = rows_3y >= 700
            if fin_ok:
                ok_fin += 1
            if ohlcv_3y_ok:
                ok_ohlcv_3y += 1
        except Exception as e:  # pragma: no cover - diagnostic utility
            err = f"{type(e).__name__}: {e}"
        elapsed = (time.perf_counter() - t0) * 1000.0
        rows.append(
            {
                "symbol": sym,
                "snapshot_ok": snap_ok,
                "financial_ok": fin_ok,
                "financial_source": fin_src,
                "ohlcv_3y_ok": ohlcv_3y_ok,
                "ohlcv_source": ohlcv_src,
                "elapsed_ms": round(elapsed, 1),
                "error": err,
            }
        )
        print(
            f"[{i:02d}/30] {sym} fin={'OK' if fin_ok else 'MISS'} "
            f"ohlcv3y={'OK' if ohlcv_3y_ok else 'MISS'} src_fin={fin_src or '-'} src_px={ohlcv_src or '-'}"
        )
    return {
        "pass_name": name,
        "strict_live": strict_live,
        "fail_fast": fail_fast,
        "financial_ok": ok_fin,
        "ohlcv_3y_ok": ok_ohlcv_3y,
        "rows": rows,
    }


def _run_financial_only_pass(name: str, strict_live: bool, fail_fast: bool) -> dict[str, Any]:
    if strict_live:
        os.environ["II_STRICT_REAL_FINANCIAL_DATA"] = "1"
    else:
        os.environ["II_STRICT_REAL_FINANCIAL_DATA"] = "0"
    os.environ["II_PORTAL_FAIL_FAST"] = "1" if fail_fast else "0"
    os.environ["II_PORTAL_FAIL_FAST_BUDGET_SEC"] = "3.5"
    os.environ["II_PORTAL_LIVE_BUDGET_SEC"] = "8" if not fail_fast else "4.5"
    os.environ["II_PORTAL_TIMEOUT_LADDER_SEC"] = "1.5,2.5,4" if not fail_fast else "1.0,1.8,2.5"
    os.environ["II_FINANCIAL_MAX_PROBES"] = "2" if not fail_fast else "1"
    os.environ["II_OHLCV_STORE_ENABLED"] = "1"
    os.environ["II_OHLCV_DISK_FIRST"] = "0"
    rows: list[dict[str, Any]] = []
    ok_fin = 0
    for i, sym in enumerate(VN30, start=1):
        t0 = time.perf_counter()
        fin_ok = False
        fin_src = ""
        err = ""
        try:
            fin = fetch_financial_indicators(sym, fast_mode=False)
            fin_ok = _financial_ready(fin)
            fin_src = str((fin or {}).get("source") or "")
            if fin_ok:
                ok_fin += 1
        except Exception as e:  # pragma: no cover - diagnostic utility
            err = f"{type(e).__name__}: {e}"
        elapsed = (time.perf_counter() - t0) * 1000.0
        rows.append(
            {
                "symbol": sym,
                "snapshot_ok": False,
                "financial_ok": fin_ok,
                "financial_source": fin_src,
                "ohlcv_3y_ok": False,
                "ohlcv_source": "",
                "elapsed_ms": round(elapsed, 1),
                "error": err,
            }
        )
        print(f"[{i:02d}/30] {sym} fin={'OK' if fin_ok else 'MISS'} src_fin={fin_src or '-'}")
    return {
        "pass_name": name,
        "strict_live": strict_live,
        "fail_fast": fail_fast,
        "financial_ok": ok_fin,
        "ohlcv_3y_ok": 0,
        "rows": rows,
    }


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Refresh VN30 free-data quality report.")
    p.add_argument(
        "--mode",
        choices=("full", "financial-only"),
        default="full",
        help="full: financial + ohlcv checks; financial-only: fast strict financial readiness check.",
    )
    p.add_argument(
        "--single-pass",
        action="store_true",
        help="Run only one pass (fail-fast strict) for quicker diagnostics.",
    )
    return p.parse_args()


def main() -> int:
    args = _parse_args()
    print("=== Free-data maximization for VN30 ===")
    started = _now_iso()
    if args.single_pass:
        if args.mode == "financial-only":
            pass1 = _run_financial_only_pass("pass_fin_only_failfast", strict_live=True, fail_fast=True)
        else:
            pass1 = _run_pass("pass_live_failfast", strict_live=True, fail_fast=True)
        pass2 = {
            "pass_name": "skipped_single_pass",
            "strict_live": True,
            "fail_fast": True,
            "financial_ok": 0,
            "ohlcv_3y_ok": 0,
            "rows": [],
        }
    else:
        if args.mode == "financial-only":
            pass1 = _run_financial_only_pass("pass_fin_only_relaxed", strict_live=True, fail_fast=False)
            pass2 = _run_financial_only_pass("pass_fin_only_failfast", strict_live=True, fail_fast=True)
        else:
            pass1 = _run_pass("pass_live_relaxed", strict_live=True, fail_fast=False)
            pass2 = _run_pass("pass_live_failfast", strict_live=True, fail_fast=True)
    best_by_symbol: dict[str, dict[str, Any]] = {}
    pass1_rows = pass1.get("rows")
    pass2_rows = pass2.get("rows")
    rows_all = (list(pass1_rows) if isinstance(pass1_rows, list) else []) + (
        list(pass2_rows) if isinstance(pass2_rows, list) else []
    )
    for row in rows_all:
        sym = str(row["symbol"])
        cur = best_by_symbol.get(sym)
        if cur is None:
            best_by_symbol[sym] = row
            continue
        cur_score = int(bool(cur["financial_ok"])) * 2 + int(bool(cur["ohlcv_3y_ok"]))
        new_score = int(bool(row["financial_ok"])) * 2 + int(bool(row["ohlcv_3y_ok"]))
        if new_score > cur_score:
            best_by_symbol[sym] = row
    best_rows = [best_by_symbol.get(s, {"symbol": s, "financial_ok": False, "ohlcv_3y_ok": False}) for s in VN30]
    fin_ok = sum(1 for r in best_rows if r["financial_ok"])
    ohlcv_ok = sum(1 for r in best_rows if r["ohlcv_3y_ok"])
    payload = {
        "started_at": started,
        "ended_at": _now_iso(),
        "passes": [pass1, pass2],
        "best_summary": {
            "financial_ok": fin_ok,
            "financial_missing": len(VN30) - fin_ok,
            "ohlcv_3y_ok": ohlcv_ok,
            "ohlcv_3y_missing": len(VN30) - ohlcv_ok,
            "total": len(VN30),
        },
        "best_rows": best_rows,
    }
    out_dir = ROOT / "data" / "reports"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "vn30_free_data_quality.json"
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(
        f"BEST summary: financial_ok={fin_ok}/30, ohlcv_3y_ok={ohlcv_ok}/30 "
        f"-> report={out_path.as_posix()}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

