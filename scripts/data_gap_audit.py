#!/usr/bin/env python3
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


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load_symbols(limit: int = 0) -> list[str]:
    p = ROOT / "data" / "stock_metadata.json"
    if not p.exists():
        return []
    raw = json.loads(p.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        return []
    symbols = sorted(str(k).strip().upper() for k in raw.keys() if str(k).strip())
    if limit > 0:
        return symbols[:limit]
    return symbols


def _financial_ready(fin: dict[str, Any] | None) -> bool:
    if not isinstance(fin, dict):
        return False
    keys = ("debt_to_equity", "gross_margin", "revenue_growth_yoy", "profit_growth_yoy")
    return any(fin.get(k) is not None for k in keys)


def _ohlcv_3y_ready(df: Any) -> bool:
    if df is None:
        return False
    try:
        import pandas as pd

        if len(df) <= 0:
            return False
        d = df.copy()
        d["date"] = pd.to_datetime(d["date"], errors="coerce")
        d = d.dropna(subset=["date"]).sort_values("date")
        if d.empty:
            return False
        end = d["date"].max()
        rows_3y = int((d["date"] >= (end - pd.Timedelta(days=1096))).sum())
        return rows_3y >= 700
    except Exception:
        return False


def run_audit(symbols: list[str], include_ohlcv: bool) -> dict[str, Any]:
    os.environ["II_STRICT_REAL_FINANCIAL_DATA"] = "1"
    os.environ["II_PORTAL_FAIL_FAST"] = "1"
    os.environ["II_PORTAL_FAIL_FAST_BUDGET_SEC"] = "4"
    os.environ["II_PORTAL_LIVE_BUDGET_SEC"] = "8"
    os.environ["II_PORTAL_TIMEOUT_LADDER_SEC"] = "1.2,2.2,3.8"
    os.environ["II_FINANCIAL_MAX_PROBES"] = "2"

    rows: list[dict[str, Any]] = []
    ok_snapshot = 0
    ok_financial = 0
    ok_ohlcv = 0
    started = time.perf_counter()
    total = len(symbols)

    for idx, sym in enumerate(symbols, start=1):
        t0 = time.perf_counter()
        snap_ok = False
        fin_ok = False
        ohlcv_ok = False
        snap_src = ""
        fin_src = ""
        ohlcv_src = ""
        err = ""
        try:
            snap = fetch_financial_snapshot(sym, bypass_cache=False)
            snap_ok = isinstance(snap, dict) and bool(snap)
            snap_src = str((snap or {}).get("source") or "")
            if snap_ok:
                ok_snapshot += 1
        except Exception as e:
            err = f"snapshot:{type(e).__name__}"

        try:
            fin = fetch_financial_indicators(sym, fast_mode=False)
            fin_ok = _financial_ready(fin)
            fin_src = str((fin or {}).get("source") or "")
            if fin_ok:
                ok_financial += 1
        except Exception as e:
            err = f"{err}|financial:{type(e).__name__}" if err else f"financial:{type(e).__name__}"

        if include_ohlcv:
            try:
                px = fetch_ohlcv_history(sym, sessions=1300)
                ohlcv_ok = _ohlcv_3y_ready(px)
                ohlcv_src = str(getattr(px, "attrs", {}).get("source") or "")
                if ohlcv_ok:
                    ok_ohlcv += 1
            except Exception as e:
                err = f"{err}|ohlcv:{type(e).__name__}" if err else f"ohlcv:{type(e).__name__}"

        elapsed = round((time.perf_counter() - t0) * 1000.0, 1)
        rows.append(
            {
                "symbol": sym,
                "snapshot_ok": snap_ok,
                "snapshot_source": snap_src,
                "financial_ok": fin_ok,
                "financial_source": fin_src,
                "ohlcv_3y_ok": ohlcv_ok,
                "ohlcv_source": ohlcv_src,
                "elapsed_ms": elapsed,
                "error": err,
            }
        )
        print(
            f"[{idx:03d}/{total:03d}] {sym} snap={'OK' if snap_ok else 'MISS'} "
            f"fin={'OK' if fin_ok else 'MISS'} "
            f"{('ohlcv3y=' + ('OK' if ohlcv_ok else 'MISS')) if include_ohlcv else ''}".strip()
        )

    elapsed_s = round(time.perf_counter() - started, 2)
    missing_financial = [r["symbol"] for r in rows if not r["financial_ok"]]
    missing_snapshot = [r["symbol"] for r in rows if not r["snapshot_ok"]]
    missing_ohlcv = [r["symbol"] for r in rows if include_ohlcv and not r["ohlcv_3y_ok"]]
    return {
        "generated_at_utc": _now_iso(),
        "symbol_count": total,
        "include_ohlcv": include_ohlcv,
        "elapsed_sec": elapsed_s,
        "summary": {
            "snapshot_ok": ok_snapshot,
            "financial_ok": ok_financial,
            "ohlcv_3y_ok": ok_ohlcv if include_ohlcv else None,
            "snapshot_missing": total - ok_snapshot,
            "financial_missing": total - ok_financial,
            "ohlcv_3y_missing": (total - ok_ohlcv) if include_ohlcv else None,
        },
        "missing": {
            "snapshot": missing_snapshot,
            "financial": missing_financial,
            "ohlcv_3y": missing_ohlcv,
        },
        "rows": rows,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0, help="Limit symbol count for quick audits.")
    ap.add_argument("--skip-ohlcv", action="store_true", help="Skip 3Y OHLCV coverage check.")
    args = ap.parse_args()

    symbols = _load_symbols(limit=max(0, int(args.limit)))
    if not symbols:
        print("No symbols found in data/stock_metadata.json")
        return 2

    payload = run_audit(symbols=symbols, include_ohlcv=not bool(args.skip_ohlcv))
    out_dir = ROOT / "data" / "reports"
    out_dir.mkdir(parents=True, exist_ok=True)
    suffix = "no_ohlcv" if args.skip_ohlcv else "full"
    out = out_dir / f"data_gap_audit_{suffix}.json"
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    s = payload["summary"]
    print(
        f"SUMMARY snapshot_ok={s['snapshot_ok']}/{payload['symbol_count']} "
        f"financial_ok={s['financial_ok']}/{payload['symbol_count']} "
        f"ohlcv_3y_ok={s['ohlcv_3y_ok']}/{payload['symbol_count'] if s['ohlcv_3y_ok'] is not None else 0}"
    )
    print(f"REPORT={out.as_posix()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

