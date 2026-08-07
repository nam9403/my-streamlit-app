"""
Overnight Autopilot scan tick for VPS 24/7.

Default window: 17:00 → 07:00 (Asia/Ho_Chi_Minh). Outside window → exit quickly.

Usage (one tick — Task Scheduler every N minutes):
  python scripts/run_overnight_scan_tick.py
  python scripts/run_overnight_scan_tick.py --force
  python scripts/run_overnight_scan_tick.py --batch-size 40 --workers 3

Usage (long-running loop on VPS):
  python scripts/run_overnight_scan_tick.py --loop --interval-min 30

Env:
  II_OVERNIGHT_SCAN_START=17:00
  II_OVERNIGHT_SCAN_END=07:00
  II_OVERNIGHT_SCAN_TZ=Asia/Ho_Chi_Minh
  II_OVERNIGHT_SCAN_STATE=data/runtime/overnight_scan_state.json
"""

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
sys.path.insert(0, str(ROOT))

try:
    import env_bootstrap

    env_bootstrap.init_app_environment()
except Exception:
    pass


def _now_local():
    from core.overnight_scan_window import overnight_tz

    return datetime.now(overnight_tz())


def run_tick(
    *,
    batch_size: int = 40,
    workers: int = 0,
    profile: str = "growth",
    universe_mode: str = "",
    min_avg_volume: float = 200_000.0,
    prefilter_volume: bool = True,
    force: bool = False,
    reset_session: bool = False,
) -> dict[str, Any]:
    from core.autopilot_nightly_board import (
        board_path,
        init_board_for_universe,
        merge_batch_into_board,
        nightly_universe_mode_default,
        resolve_nightly_target_symbols,
        save_board,
        scan_batch,
        top_n_from_board,
    )
    from core.overnight_scan_window import (
        configured_window,
        is_in_overnight_window,
        load_overnight_state,
        overnight_session_date,
        save_overnight_state,
        seconds_until_window_opens,
    )

    now = _now_local()
    start_t, end_t = configured_window()
    in_window = is_in_overnight_window(now, start=start_t, end=end_t)
    session = overnight_session_date(now, start=start_t, end=end_t).isoformat()

    out: dict[str, Any] = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "local_ts": now.isoformat(),
        "window": f"{start_t.strftime('%H:%M')}-{end_t.strftime('%H:%M')}",
        "in_window": in_window,
        "session_date": session,
        "status": "ok",
    }

    if not in_window and not force:
        out["status"] = "skipped_outside_window"
        out["seconds_until_open"] = round(seconds_until_window_opens(now, start=start_t, end=end_t), 1)
        return out

    if workers and workers > 0:
        os.environ["II_SCAN_MAX_WORKERS"] = str(int(workers))

    mode = str(universe_mode or nightly_universe_mode_default()).strip().lower()
    batch_n = max(5, min(120, int(batch_size)))
    state = load_overnight_state()
    new_session = str(state.get("session_date") or "") != session
    do_reset = bool(reset_session) or new_session
    offset = 0 if do_reset else max(0, int(state.get("next_offset") or 0))

    _probe, uni_meta = resolve_nightly_target_symbols(
        limit=None,
        offset=0,
        universe_mode=mode,
        min_avg_volume_20=float(min_avg_volume),
        prefilter_volume=bool(prefilter_volume),
    )
    pool_n = int(uni_meta.get("scan_pool_size") or len(_probe) or 0)
    if pool_n <= 0:
        out["status"] = "empty_universe"
        out["universe"] = uni_meta
        return out

    if offset >= pool_n:
        offset = 0

    target, slice_meta = resolve_nightly_target_symbols(
        limit=batch_n,
        offset=offset,
        universe_mode=mode,
        min_avg_volume_20=float(min_avg_volume),
        prefilter_volume=bool(prefilter_volume),
    )
    if not target:
        offset = 0
        target, slice_meta = resolve_nightly_target_symbols(
            limit=batch_n,
            offset=0,
            universe_mode=mode,
            min_avg_volume_20=float(min_avg_volume),
            prefilter_volume=bool(prefilter_volume),
        )

    print(
        f"[overnight] session={session} reset={do_reset} offset={offset} "
        f"n={len(target)} pool={pool_n} board={board_path()}",
        flush=True,
    )

    # On new overnight session, rebuild board from this batch onward (reset=True).
    # Within session, merge into existing board and grow target_symbols.
    board = init_board_for_universe(
        symbols=target,
        profile=str(profile),
        universe_mode=mode,
        reset=bool(do_reset),
        universe_meta=slice_meta,
    )

    batch_id = f"ov_{offset:04d}_{now.strftime('%H%M%S')}"
    t0 = time.perf_counter()
    rows, stt = scan_batch(
        target,
        profile=str(profile),
        min_avg_volume_20=float(min_avg_volume),
    )
    board = merge_batch_into_board(
        board,
        rows=rows,
        batch_id=batch_id,
        symbols=target,
        seconds=float(stt.get("seconds") or (time.perf_counter() - t0)),
        ok=int(stt.get("ok") or 0),
        fail=int(stt.get("fail") or 0),
    )
    save_board(board)

    next_offset = offset + len(target)
    wrapped = False
    if next_offset >= pool_n:
        next_offset = 0
        wrapped = True

    batches_run = 1 if do_reset else int(state.get("batches_run") or 0) + 1

    save_overnight_state(
        {
            "next_offset": next_offset,
            "session_date": session,
            "batches_run": batches_run,
            "last_status": "ok",
            "last_batch_id": batch_id,
            "last_symbols": target[:20],
            "pool_size": pool_n,
            "wrapped": wrapped,
            "board": str(board_path()),
        }
    )

    top = top_n_from_board(board, top_n=10, ready_only=True)
    out.update(
        {
            "status": "ok",
            "reset": do_reset,
            "offset": offset,
            "next_offset": next_offset,
            "wrapped": wrapped,
            "batch_id": batch_id,
            "scanned": len(target),
            "symbols_sample": target[:10],
            "batch_stats": stt,
            "universe": slice_meta,
            "top_ready": int(len(top)),
            "batches_run_session": batches_run,
        }
    )
    print(
        f"[overnight] done ready={stt.get('ok')}/{stt.get('total')} "
        f"next_offset={next_offset} wrapped={wrapped}",
        flush=True,
    )
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="Overnight Autopilot scan tick (17:00–07:00).")
    ap.add_argument("--batch-size", type=int, default=int(os.environ.get("II_OVERNIGHT_SCAN_BATCH", "40") or 40))
    ap.add_argument("--workers", type=int, default=int(os.environ.get("II_OVERNIGHT_SCAN_WORKERS", "3") or 3))
    ap.add_argument("--profile", default="growth")
    ap.add_argument("--universe-mode", default="", choices=["", "dynamic_liquid", "liquid", "vn30"])
    ap.add_argument("--min-avg-volume", type=float, default=200_000.0)
    ap.add_argument("--no-prefilter-volume", action="store_true")
    ap.add_argument("--force", action="store_true", help="Run even outside overnight window")
    ap.add_argument("--reset-session", action="store_true", help="Force new overnight session reset")
    ap.add_argument("--loop", action="store_true", help="Keep process alive; sleep between ticks")
    ap.add_argument(
        "--interval-min",
        type=float,
        default=float(os.environ.get("II_OVERNIGHT_SCAN_INTERVAL_MIN", "30") or 30),
        help="Minutes between ticks in --loop mode",
    )
    ap.add_argument(
        "--out-summary",
        default="artifacts/operations/overnight_scan_tick_latest.json",
        help="Write last tick summary JSON",
    )
    args = ap.parse_args()

    def _one() -> dict[str, Any]:
        return run_tick(
            batch_size=int(args.batch_size),
            workers=int(args.workers),
            profile=str(args.profile),
            universe_mode=str(args.universe_mode or ""),
            min_avg_volume=float(args.min_avg_volume),
            prefilter_volume=not bool(args.no_prefilter_volume),
            force=bool(args.force),
            reset_session=bool(args.reset_session),
        )

    if not args.loop:
        result = _one()
        out_path = ROOT / str(args.out_summary)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if str(result.get("status")) in {"ok", "skipped_outside_window"} else 1

    from core.overnight_scan_window import is_in_overnight_window, seconds_until_window_opens

    interval_s = max(60.0, float(args.interval_min) * 60.0)
    print(
        f"[overnight] loop start interval={args.interval_min}m batch={args.batch_size} workers={args.workers}",
        flush=True,
    )
    while True:
        now = _now_local()
        if not is_in_overnight_window(now) and not args.force:
            wait_s = min(interval_s, max(30.0, seconds_until_window_opens(now)))
            print(f"[overnight] outside window; sleep {wait_s:.0f}s", flush=True)
            time.sleep(wait_s)
            continue
        result = _one()
        out_path = ROOT / str(args.out_summary)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        print(
            json.dumps(
                {"status": result.get("status"), "next_offset": result.get("next_offset")},
                ensure_ascii=False,
            )
        )
        time.sleep(interval_s)


if __name__ == "__main__":
    raise SystemExit(main())
