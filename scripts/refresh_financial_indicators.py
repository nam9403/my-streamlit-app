"""
Refresh financial indicators (BCTC) vào disk cache — chạy đêm / cuối tuần.

Không gọi trong phiên giao dịch realtime. Trong app, fetch_financial_indicators
mặc định chỉ đọc cache (II_FINANCIAL_LIVE_REFRESH=0).

Ví dụ:
  python scripts/refresh_financial_indicators.py --symbols FPT,HPG,VNM --force
  python scripts/refresh_financial_indicators.py --vn30 --watchlist --force
  python scripts/refresh_financial_indicators.py --vn30 --watchlist --live
"""

from __future__ import annotations

import argparse
import os
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


def _env_truthy(name: str) -> bool:
    return str(os.environ.get(name, "")).strip().lower() in {"1", "true", "yes", "on"}


def _resolve_force_live(args: argparse.Namespace) -> bool:
    """CLI --force/--live hoặc II_FINANCIAL_LIVE_REFRESH=1 → bỏ qua disk/mem cache."""
    if args.force or args.live:
        return True
    return _env_truthy("II_FINANCIAL_LIVE_REFRESH")


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Nightly/weekend financial indicators refresh")
    p.add_argument("--symbols", default="", help="CSV symbols, e.g. FPT,HPG,VNM")
    p.add_argument("--vn30", action="store_true", help="Include VN30 universe")
    p.add_argument(
        "--watchlist",
        action="store_true",
        help="Include default watchlist (II_WATCHLIST or FPT,HPG,VNM,ACB,QTP)",
    )
    p.add_argument(
        "--liquid",
        action="store_true",
        help="Include liquid universe (VN30 + HOSE pool, same as nightly scan)",
    )
    p.add_argument(
        "--liquid-limit",
        type=int,
        default=0,
        help="Cap --liquid symbols (0 = full pool)",
    )
    p.add_argument(
        "--top10",
        action="store_true",
        help="Include symbols from latest nightly autopilot board Top 10",
    )
    p.add_argument(
        "--force",
        action="store_true",
        help="Bypass disk/mem cache; fetch live from vnstock and overwrite cache",
    )
    p.add_argument(
        "--live",
        action="store_true",
        help="Alias for --force (live vnstock refresh)",
    )
    p.add_argument("--sleep", type=float, default=0.4, help="Sleep seconds between symbols")
    return p.parse_args()


def _vn30_symbols() -> list[str]:
    try:
        from scrapers.vn_listing import list_tradable_vn_symbols

        static = [
            "ACB", "BCM", "BID", "BVH", "CTG", "FPT", "GAS", "GVR", "HDB", "HPG",
            "MBB", "MSN", "MWG", "PLX", "LPB", "SAB", "SHB", "SSB", "SSI", "STB",
            "TCB", "TPB", "VCB", "VHM", "VIB", "VIC", "VJC", "VNM", "VPB", "VRE",
        ]
        try:
            bag = list_tradable_vn_symbols(use_api=False) or []
            if bag:
                return [s for s in static if s in set(str(x).upper() for x in bag)] or static
        except Exception:
            pass
        return static
    except Exception:
        return ["FPT", "HPG", "VNM"]


def _watchlist_symbols() -> list[str]:
    raw = str(os.environ.get("II_WATCHLIST") or "FPT,HPG,VNM,ACB,QTP").strip()
    return [s.strip().upper() for s in raw.split(",") if s.strip()]


def _liquid_symbols(limit: int = 0) -> list[str]:
    try:
        from core.autopilot_nightly_board import resolve_liquid_target_symbols

        lim = int(limit) if limit and limit > 0 else None
        return list(resolve_liquid_target_symbols(limit=lim))
    except Exception:
        return _vn30_symbols()


def _nightly_top10_symbols() -> list[str]:
    try:
        from core.autopilot_nightly_board import load_board

        board = load_board()
        rows = (board or {}).get("rows")
        if isinstance(rows, dict):
            return [str(k).strip().upper() for k in list(rows.keys())[:10] if str(k).strip()]
        if isinstance(rows, list):
            out: list[str] = []
            for item in rows[:10]:
                if isinstance(item, dict):
                    sym = str(item.get("Mã") or item.get("symbol") or "").strip().upper()
                    if sym:
                        out.append(sym)
            return out
        return []
    except Exception:
        return []


def _dedupe(symbols: list[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for s in symbols:
        sym = str(s or "").strip().upper()
        if not sym or sym in seen:
            continue
        seen.add(sym)
        out.append(sym)
    return out


def _completeness(payload: dict) -> dict[str, bool]:
    cr = payload.get("current_ratio")
    return {
        "current_ratio": cr is not None,
        "operating_cash_flow": payload.get("operating_cash_flow") is not None,
        "net_income": payload.get("net_income") is not None,
        "roe": payload.get("roe") is not None,
        "debt_to_equity": payload.get("debt_to_equity") is not None,
    }


def main() -> int:
    args = _parse_args()
    # Job refresh định kỳ luôn ép live; --force/--live hoặc II_FINANCIAL_LIVE_REFRESH cũng bật.
    force_live = _resolve_force_live(args) or True
    os.environ["II_FINANCIAL_LIVE_REFRESH"] = "1"
    os.environ["II_FINANCIAL_DISK_FIRST"] = "0"
    os.environ.setdefault("II_VNSTOCK_FETCH_STATEMENTS", "1")

    from scrapers.portal import PortalDataError, fetch_financial_indicators

    symbols: list[str] = []
    if args.symbols.strip():
        symbols.extend(s.strip().upper() for s in args.symbols.split(",") if s.strip())
    if args.vn30:
        symbols.extend(_vn30_symbols())
    if args.watchlist:
        symbols.extend(_watchlist_symbols())
    if args.liquid:
        symbols.extend(_liquid_symbols(limit=int(args.liquid_limit or 0)))
    if args.top10:
        symbols.extend(_nightly_top10_symbols())
    symbols = _dedupe(symbols)
    if not symbols:
        print(
            "Cần --symbols và/hoặc --vn30 / --watchlist / --liquid / --top10",
            file=sys.stderr,
        )
        return 2

    ok = 0
    fail = 0
    thin = 0
    for i, sym in enumerate(symbols):
        try:
            out = fetch_financial_indicators(sym, fast_mode=False, force_refresh=force_live) or {}
            src = str(out.get("source") or "")
            comp = _completeness(out)
            core_ok = any(comp[k] for k in ("current_ratio", "operating_cash_flow", "net_income"))
            flag = "OK" if core_ok else "THIN"
            if not core_ok:
                thin += 1
            print(
                f"[{i + 1}/{len(symbols)}] {flag} {sym} source={src} "
                f"CR={comp['current_ratio']} CFO={comp['operating_cash_flow']} NI={comp['net_income']}"
            )
            ok += 1
        except PortalDataError as e:
            print(f"[{i + 1}/{len(symbols)}] FAIL {sym}: {e}", file=sys.stderr)
            fail += 1
        except Exception as e:
            print(f"[{i + 1}/{len(symbols)}] ERROR {sym}: {e}", file=sys.stderr)
            fail += 1
        if args.sleep > 0 and i + 1 < len(symbols):
            time.sleep(args.sleep)

    print(
        f"Done. ok={ok} fail={fail} thin={thin} total={len(symbols)} force_live={force_live}"
    )
    return 0 if fail == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
