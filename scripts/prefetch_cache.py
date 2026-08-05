"""
Prefetch cache for faster user experience.

Usage examples:
  python scripts/prefetch_cache.py --watchlist FPT,HPG,VNM
  python scripts/prefetch_cache.py --universe-limit 30
  # 1000 mã tiếp theo sau 30 mã đầu (không thêm watchlist mặc định):
  python scripts/prefetch_cache.py --universe-without-default-watchlist --universe-offset 30 --universe-limit 1000
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core.ai_logic import generate_strategic_report
from scrapers.financial_data import fetch_financial_snapshot, list_universe_symbols
from scrapers.portal import fetch_financial_indicators, fetch_ohlcv_history


def _parse_symbols(raw: str) -> list[str]:
    if not raw.strip():
        return []
    out: list[str] = []
    for x in raw.replace(";", ",").split(","):
        sym = x.strip().upper()
        if sym:
            out.append(sym)
    return out


def _prefetch_one(sym: str) -> tuple[bool, float, str]:
    t0 = time.time()
    snap = fetch_financial_snapshot(sym)
    if snap is None:
        return False, time.time() - t0, "snapshot_none"
    ohlcv_status = "ohlcv_skip"
    try:
        # Warm long history into OHLCV store/cache for 3Y/5Y chart usage.
        ohlcv = fetch_ohlcv_history(sym, sessions=1300)
        ohlcv_status = f"ohlcv:{len(ohlcv)}"
    except Exception:
        ohlcv_status = "ohlcv_err"
    try:
        fetch_financial_indicators(sym, fast_mode=False)
    except Exception:
        pass
    try:
        generate_strategic_report(
            sym,
            snap,
            profile="growth",
            total_capital_vnd=100_000_000.0,
            sessions=60,
            news_limit=5,
            enable_llm=False,
            fast_mode=True,
        )
    except Exception as e:
        return False, time.time() - t0, f"{ohlcv_status}|report_error:{type(e).__name__}"
    return True, time.time() - t0, f"ok|{ohlcv_status}"


def main() -> int:
    parser = argparse.ArgumentParser(description="Warm up snapshot/report caches.")
    parser.add_argument(
        "--watchlist",
        default="",
        help="Comma-separated symbols. If empty and not --universe-without-default-watchlist, defaults to FPT,HPG,VNM.",
    )
    parser.add_argument(
        "--universe-without-default-watchlist",
        action="store_true",
        help="Do not add default FPT,HPG,VNM when watchlist is empty; use only --watchlist + universe slice.",
    )
    parser.add_argument(
        "--universe-offset",
        type=int,
        default=0,
        help="Skip first N symbols of the tradable universe (after listing order).",
    )
    parser.add_argument("--universe-limit", type=int, default=0, help="If >0, append up to N universe symbols after offset.")
    args = parser.parse_args()

    raw_wl = (args.watchlist or "").strip()
    if args.universe_without_default_watchlist:
        syms = _parse_symbols(raw_wl)
    elif raw_wl:
        syms = _parse_symbols(raw_wl)
    else:
        syms = _parse_symbols("FPT,HPG,VNM")
    if args.universe_limit and args.universe_limit > 0:
        for s in list_universe_symbols(limit=args.universe_limit, offset=max(0, int(args.universe_offset))):
            if s not in syms:
                syms.append(s)

    if not syms:
        print("No symbols to prefetch.")
        return 1

    ok_n = 0
    total_t = 0.0
    try:
        delay = max(
            0.0,
            float(os.environ.get("II_PREFETCH_SLEEP", os.environ.get("II_SNAPSHOT_REFRESH_SLEEP", "0") or "0")),
        )
    except ValueError:
        delay = 0.0
    print(f"Prefetching {len(syms)} symbols... (II_PREFETCH_SLEEP / II_SNAPSHOT_REFRESH_SLEEP delay={delay}s)")
    for i, s in enumerate(syms, start=1):
        ok, elapsed, status = _prefetch_one(s)
        total_t += elapsed
        if ok:
            ok_n += 1
        print(f"[{i:02d}/{len(syms):02d}] {s} -> {status} ({elapsed:.2f}s)")
        if delay and i < len(syms):
            time.sleep(delay)

    avg_t = total_t / max(len(syms), 1)
    print(f"Done. success={ok_n}/{len(syms)} avg_time={avg_t:.2f}s")
    return 0 if ok_n > 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
