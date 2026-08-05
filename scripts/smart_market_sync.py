"""
Smart market data sync for VN symbols.

Goals:
- Automatically include newly listed symbols.
- Refresh existing symbols in round-robin batches.
- Avoid overlapping runs via a lock file.
- Avoid duplicate work in one run and keep checkpoint state.

Usage examples:
  python scripts/smart_market_sync.py --new-batch-size 200 --existing-batch-size 200
  python scripts/smart_market_sync.py --force-full-existing --existing-batch-size 1000
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from scrapers.financial_data import fetch_financial_snapshot
from scrapers.portal import fetch_financial_indicators, fetch_ohlcv_history
from scrapers.vn_listing import load_or_refresh_listing_cache

STATE_PATH = ROOT / "data" / "smart_market_sync_state.json"
LOCK_PATH = ROOT / "data" / ".smart_market_sync.lock"


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_int(v: object, default: int = 0) -> int:
    if isinstance(v, bool):
        return int(v)
    if isinstance(v, int):
        return v
    if isinstance(v, float):
        return int(v)
    if isinstance(v, str):
        vv = v.strip()
        if not vv:
            return int(default)
        try:
            return int(vv)
        except ValueError:
            return int(default)
    return int(default)


def _normalize_symbols(symbols: list[str] | tuple[str, ...]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for s in symbols:
        sym = str(s or "").strip().upper()
        if not sym or sym in seen:
            continue
        seen.add(sym)
        out.append(sym)
    return out


def _read_json(path: Path, default: dict) -> dict:
    if not path.exists():
        return dict(default)
    try:
        with open(path, encoding="utf-8") as f:
            raw = json.load(f)
        if isinstance(raw, dict):
            return raw
        return dict(default)
    except (OSError, ValueError):
        return dict(default)


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    tmp.replace(path)


def _acquire_lock(lock_path: Path) -> bool:
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(json.dumps({"pid": os.getpid(), "started_at": _utc_now_iso()}, ensure_ascii=False))
        return True
    except FileExistsError:
        return False


def _release_lock(lock_path: Path) -> None:
    try:
        lock_path.unlink(missing_ok=True)
    except OSError:
        return


def select_round_robin(existing: list[str], cursor: int, take_n: int) -> tuple[list[str], int]:
    symbols = _normalize_symbols(existing)
    if not symbols or take_n <= 0:
        return [], max(0, int(cursor or 0))
    cur = max(0, int(cursor or 0)) % len(symbols)
    out: list[str] = []
    for i in range(min(take_n, len(symbols))):
        out.append(symbols[(cur + i) % len(symbols)])
    next_cursor = (cur + len(out)) % len(symbols)
    return out, next_cursor


@dataclass
class SyncPlan:
    new_symbols: list[str]
    existing_symbols: list[str]
    batch_new: list[str]
    batch_existing: list[str]
    next_cursor: int


def build_sync_plan(
    universe_symbols: list[str],
    known_symbols: list[str],
    cursor: int,
    *,
    new_batch_size: int,
    existing_batch_size: int,
    force_full_existing: bool,
) -> SyncPlan:
    universe = _normalize_symbols(universe_symbols)
    known = set(_normalize_symbols(known_symbols))
    new_symbols = [s for s in universe if s not in known]
    existing = [s for s in universe if s in known]

    batch_new = new_symbols[: max(0, int(new_batch_size))]
    if force_full_existing:
        batch_existing = existing[: max(0, int(existing_batch_size))]
        next_cursor = (max(0, int(existing_batch_size)) % len(existing)) if existing else 0
    else:
        batch_existing, next_cursor = select_round_robin(existing, cursor, max(0, int(existing_batch_size)))
    return SyncPlan(
        new_symbols=new_symbols,
        existing_symbols=existing,
        batch_new=batch_new,
        batch_existing=batch_existing,
        next_cursor=next_cursor,
    )


def _sync_one_symbol(sym: str, ohlcv_sessions: int, refresh_financial_live: bool) -> tuple[bool, str]:
    snap = fetch_financial_snapshot(sym, bypass_cache=True)
    if snap is None:
        return False, "snapshot_none"
    try:
        fetch_ohlcv_history(sym, sessions=ohlcv_sessions)
    except Exception as e:
        return False, f"ohlcv_error:{e.__class__.__name__}"
    try:
        fetch_financial_indicators(
            sym,
            fast_mode=not refresh_financial_live,
            force_refresh=bool(refresh_financial_live),
        )
    except Exception:
        # Indicators failure should not fail full sync for that symbol.
        return True, "ok_with_financial_warn"
    return True, "ok"


def main() -> int:
    parser = argparse.ArgumentParser(description="Smart VN market sync with dedupe + checkpoint.")
    parser.add_argument("--new-batch-size", type=int, default=200)
    parser.add_argument("--existing-batch-size", type=int, default=200)
    parser.add_argument("--ohlcv-sessions", type=int, default=1300)
    parser.add_argument("--sleep-sec", type=float, default=0.2)
    parser.add_argument("--refresh-financial-live", action="store_true")
    parser.add_argument("--force-full-existing", action="store_true")
    parser.add_argument("--listing-max-age-hours", type=float, default=4.0)
    args = parser.parse_args()

    if not _acquire_lock(LOCK_PATH):
        print("Another smart sync is running (lock exists).")
        return 3

    try:
        state = _read_json(
            STATE_PATH,
            default={
                "known_symbols": [],
                "cursor": 0,
                "last_run_at": None,
                "last_listing_note": "",
                "stats": {},
            },
        )
        codes, note = load_or_refresh_listing_cache(max_age_hours=max(0.0, float(args.listing_max_age_hours)))
        plan = build_sync_plan(
            universe_symbols=codes,
            known_symbols=list(state.get("known_symbols") or []),
            cursor=_safe_int(state.get("cursor"), 0),
            new_batch_size=max(0, int(args.new_batch_size)),
            existing_batch_size=max(0, int(args.existing_batch_size)),
            force_full_existing=bool(args.force_full_existing),
        )

        # Prioritize newly listed symbols first, then rotate existing symbols.
        run_symbols = _normalize_symbols(plan.batch_new + plan.batch_existing)
        print(
            f"universe={len(_normalize_symbols(codes))} new={len(plan.new_symbols)} "
            f"run_new={len(plan.batch_new)} run_existing={len(plan.batch_existing)} total_run={len(run_symbols)}"
        )
        ok = 0
        fail = 0
        t0 = time.time()
        for i, sym in enumerate(run_symbols, start=1):
            success, status = _sync_one_symbol(
                sym,
                ohlcv_sessions=max(80, int(args.ohlcv_sessions)),
                refresh_financial_live=bool(args.refresh_financial_live),
            )
            if success:
                ok += 1
            else:
                fail += 1
            if i <= 5 or i % 25 == 0 or i == len(run_symbols):
                print(f"[{i}/{len(run_symbols)}] {sym} -> {status} (ok={ok} fail={fail})", flush=True)
            if args.sleep_sec > 0 and i < len(run_symbols):
                time.sleep(max(0.0, float(args.sleep_sec)))

        merged_known = _normalize_symbols(plan.existing_symbols + plan.new_symbols)
        state["known_symbols"] = merged_known
        state["cursor"] = int(plan.next_cursor)
        state["last_run_at"] = _utc_now_iso()
        state["last_listing_note"] = str(note or "")
        state["stats"] = {
            "universe_count": len(_normalize_symbols(codes)),
            "new_count": len(plan.new_symbols),
            "run_count": len(run_symbols),
            "ok": ok,
            "fail": fail,
            "elapsed_sec": round(time.time() - t0, 2),
        }
        _write_json(STATE_PATH, state)
        print(json.dumps(state["stats"], ensure_ascii=False))
        return 0 if ok > 0 else 2
    finally:
        _release_lock(LOCK_PATH)


if __name__ == "__main__":
    raise SystemExit(main())
