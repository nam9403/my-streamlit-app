"""
Build ``data/sector_multiples_5y.json`` from local statements_cache + OHLCV.

Chạy đêm / cuối tuần (không hot path phiên):
  python scripts/build_sector_multiples_5y.py
  python scripts/build_sector_multiples_5y.py --symbols BID,ACB,VCB --years 5
  python scripts/build_sector_multiples_5y.py --refresh-statements   # gọi FireAnt lại (+BVPS)
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

try:
    import env_bootstrap  # noqa: F401
except Exception:
    pass


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Build sector P/E–P/B multi-year warehouse")
    p.add_argument("--symbols", default="", help="CSV symbols (default: all statements_cache)")
    p.add_argument(
        "--liquid",
        action="store_true",
        help="Use liquid universe (VN30 + HOSE pool) instead of only existing cache",
    )
    p.add_argument(
        "--liquid-limit",
        type=int,
        default=0,
        help="Cap --liquid symbols (0 = full liquid pool)",
    )
    p.add_argument("--years", type=int, default=5, help="Lookback years (default 5)")
    p.add_argument(
        "--refresh-statements",
        action="store_true",
        help="Force-refresh FireAnt quarterly rows (includes BVPS) before build",
    )
    p.add_argument("--sleep", type=float, default=0.35, help="Sleep between FireAnt refreshes")
    p.add_argument(
        "--out",
        default="",
        help="Output JSON path (default data/sector_multiples_5y.json)",
    )
    return p.parse_args()


def _resolve_symbols(args: argparse.Namespace) -> list[str]:
    symbols = [s.strip().upper() for s in str(args.symbols or "").split(",") if s.strip()]
    if symbols:
        return symbols
    if args.liquid:
        try:
            from core.autopilot_nightly_board import resolve_liquid_target_symbols

            pool = list(resolve_liquid_target_symbols(limit=None))
        except Exception:
            from core.liquid_universe import VN30_SYMBOLS

            pool = list(VN30_SYMBOLS)
        lim = int(args.liquid_limit or 0)
        if lim > 0:
            pool = pool[:lim]
        return [str(s).strip().upper() for s in pool if str(s).strip()]
    from core.sector_multiples_5y import list_statement_symbols

    return list_statement_symbols()


def main() -> int:
    args = _parse_args()
    from core.sector_multiples_5y import DEFAULT_OUT, build_sector_multiples_5y

    symbols = _resolve_symbols(args)
    if not symbols:
        print("No symbols to build", file=sys.stderr)
        return 1

    if args.refresh_statements:
        from core.fundamentals_pit import load_statement_rows_cached

        ok = 0
        for i, sym in enumerate(symbols):
            rows, src = load_statement_rows_cached(sym, force_refresh=True)
            if rows:
                ok += 1
            print(f"[{i+1}/{len(symbols)}] {sym}: {src} rows={len(rows)}")
            time.sleep(max(0.0, float(args.sleep)))
        print(f"Refreshed statements: {ok}/{len(symbols)}")

    out = Path(args.out) if args.out else DEFAULT_OUT
    # Always merge with existing cache symbols so a partial --symbols run doesn't wipe coverage.
    from core.sector_multiples_5y import list_statement_symbols

    merged = sorted(set(symbols) | set(list_statement_symbols()))
    payload = build_sector_multiples_5y(symbols=merged, years=int(args.years), out_path=out)
    print(
        f"Wrote {out} | symbols={payload.get('symbols_with_points')}/"
        f"{payload.get('symbols_input')} | subtypes={len(payload.get('by_industry_subtype') or {})} "
        f"| icb={len(payload.get('by_icb_sector') or {})}"
    )
    banks = (payload.get("by_industry_subtype") or {}).get("bank")
    if banks:
        print(
            f"  bank: PE={banks.get('pe_avg')} PB={banks.get('pb_avg')} "
            f"n={banks.get('n_names')} coverage={banks.get('coverage')}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
