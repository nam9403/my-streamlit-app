"""

Nightly Autopilot liquid scan — batch over ranked liquid universe, persist ranked board.



Usage:

  python scripts/run_autopilot_nightly_scan.py

  python scripts/run_autopilot_nightly_scan.py --batch-size 40 --limit 120

  python scripts/run_autopilot_nightly_scan.py --reset --limit 80

  python scripts/run_autopilot_nightly_scan.py --offset 80 --batch-size 40 --limit 40

  python scripts/run_autopilot_nightly_scan.py --universe-mode dynamic_liquid --limit 40



Cron / Task Scheduler (VPS 4GB example, ~22:30):

  python scripts/run_autopilot_nightly_scan.py --batch-size 40 --min-avg-volume 200000

  python scripts/run_autopilot_nightly_scan.py --universe-mode dynamic_liquid --limit 120

"""



from __future__ import annotations



import argparse

import json

import sys

import time

from datetime import datetime, timezone

from pathlib import Path



ROOT = Path(__file__).resolve().parent.parent

sys.path.insert(0, str(ROOT))



try:

    import env_bootstrap  # noqa: F401

except Exception:

    pass





def main() -> int:

    ap = argparse.ArgumentParser(description="Batch-scan liquid universe into Autopilot nightly board.")

    ap.add_argument("--profile", default="growth")

    ap.add_argument("--batch-size", type=int, default=40, help="Symbols per batch (20-80 recommended on VPS)")

    ap.add_argument("--limit", type=int, default=0, help="Cap scan window after prefilter (0 = rest of pool)")

    ap.add_argument("--offset", type=int, default=0, help="Start offset into prefiltered liquid pool (resume)")

    ap.add_argument("--max-batches", type=int, default=0, help="Stop after N batches (0 = until end)")

    ap.add_argument("--min-avg-volume", type=float, default=200_000.0)

    ap.add_argument("--workers", type=int, default=0, help="Override II_SCAN_MAX_WORKERS for this run")

    ap.add_argument("--reset", action="store_true", help="Reset board before scanning")

    ap.add_argument("--sleep-between-batches", type=float, default=1.0)

    ap.add_argument(

        "--universe-mode",

        default="",

        choices=["", "dynamic_liquid", "liquid", "vn30"],

        help="Universe pool (default: II_AUTOPILOT_NIGHTLY_UNIVERSE_MODE or dynamic_liquid)",

    )

    ap.add_argument(

        "--no-prefilter-volume",

        action="store_true",

        help="Scan full pool without OHLCV volume prefilter (legacy behaviour)",

    )

    ap.add_argument(

        "--out-summary",

        default="artifacts/operations/autopilot_nightly_scan_latest.json",

        help="Write run summary JSON",

    )

    args = ap.parse_args()



    from core.autopilot_nightly_board import (
        board_path,
        compute_meta,
        init_board_for_universe,
        load_board,
        merge_batch_into_board,
        nightly_universe_mode_default,
        resolve_nightly_target_symbols,
        save_board,
        scan_batch,
        top_n_from_board,
    )



    if args.workers and args.workers > 0:

        import os



        os.environ["II_SCAN_MAX_WORKERS"] = str(int(args.workers))



    universe_mode = str(args.universe_mode or nightly_universe_mode_default()).strip().lower()

    lim = int(args.limit) if int(args.limit) > 0 else None

    off = max(0, int(args.offset))

    batch_size = max(5, min(120, int(args.batch_size)))

    prefilter = not bool(args.no_prefilter_volume)



    target, uni_meta = resolve_nightly_target_symbols(

        limit=lim,

        offset=off,

        universe_mode=universe_mode,

        min_avg_volume_20=float(args.min_avg_volume),

        prefilter_volume=prefilter,

    )

    slice_syms = list(target)

    print(

        f"[nightly] mode={universe_mode} pool={uni_meta.get('pool_size')} "

        f"scan_pool={uni_meta.get('scan_pool_size')} prefilter_skip={uni_meta.get('prefilter_skipped_count')} "

        f"offset={off} scan_n={len(slice_syms)} batch_size={batch_size} board={board_path()}",

        flush=True,

    )

    board = init_board_for_universe(
        symbols=slice_syms,
        profile=str(args.profile),
        universe_mode=universe_mode,
        reset=bool(args.reset),
        universe_meta=uni_meta,
    )

    batches_run = 0

    t_all = time.perf_counter()

    max_batches = int(args.max_batches) if int(args.max_batches) > 0 else 10_000

    last_batch_stats: dict = {}

    for i in range(0, len(slice_syms), batch_size):

        if batches_run >= max_batches:

            break

        chunk = slice_syms[i : i + batch_size]

        batch_id = f"b{off + i:04d}_{datetime.now(timezone.utc).strftime('%H%M%S')}"

        print(f"[nightly] batch {batch_id} n={len(chunk)} first={chunk[:5]}", flush=True)

        rows, stt = scan_batch(

            chunk,

            profile=str(args.profile),

            min_avg_volume_20=float(args.min_avg_volume),

        )

        last_batch_stats = dict(stt)

        board = merge_batch_into_board(

            board,

            rows=rows,

            batch_id=batch_id,

            symbols=chunk,

            seconds=float(stt.get("seconds") or 0.0),

            ok=int(stt.get("ok") or 0),

            fail=int(stt.get("fail") or 0),

        )

        save_board(board)

        batches_run += 1

        meta = board.get("meta") or {}

        print(

            f"[nightly] batch done ready={stt.get('ok')}/{stt.get('total')} "

            f"ready_rate={stt.get('ready_rate_pct')}% "

            f"liquidity={stt.get('liquidity_filtered')} data_err={stt.get('data_error')} "

            f"batch_s={stt.get('seconds')}",

            flush=True,

        )

        print(

            f"[nightly] board coverage={meta.get('coverage_pct')}% "

            f"scanned={meta.get('scanned_count')}/{meta.get('target_count')} "

            f"ready={meta.get('ready_count')} liq_filter={meta.get('liquidity_filtered_count')} "

            f"data_err={meta.get('data_error_count')}",

            flush=True,

        )

        if args.sleep_between_batches > 0 and i + batch_size < len(slice_syms):

            time.sleep(float(args.sleep_between_batches))



    top = top_n_from_board(board, top_n=10, ready_only=True)

    top_records = json.loads(top.to_json(orient="records", force_ascii=False)) if not top.empty else []

    seed_stat = {"seeded": 0, "skipped": 0}

    paper_stat = {"opened": 0, "skipped": 0}

    try:

        from core.autopilot_nightly_board import seed_top_forecast_records



        seed_stat = seed_top_forecast_records(top, user_id="autopilot_nightly", horizon_days=90)

        print(f"[nightly] forecast_seed={seed_stat}", flush=True)

    except Exception as exc:

        seed_stat = {"seeded": 0, "skipped": 0, "error": exc.__class__.__name__}

    resolve_stat: dict = {}
    paper_stat: dict = {}
    try:

        from core.paper_trade_ledger import open_paper_trades_from_top, resolve_due_trades



        def _fetch_price(sym: str):

            try:

                from scrapers.financial_data import fetch_financial_snapshot

                snap = fetch_financial_snapshot(sym) or {}

                px = float(snap.get("price") or 0.0)

                return px if px > 0 else None

            except Exception:

                return None



        resolve_stat = resolve_due_trades(fetch_price=_fetch_price)

        print(f"[nightly] paper_resolve={resolve_stat}", flush=True)



        paper_stat = open_paper_trades_from_top(

            top_records,

            source="autopilot_nightly",

            horizon_days=40,

            quantity=100.0,

        )

        print(f"[nightly] paper_trades={paper_stat}", flush=True)

        try:

            import subprocess

            wr = subprocess.run(

                [sys.executable, str(ROOT / "scripts" / "export_paper_weekly_report.py")],

                cwd=str(ROOT),

                capture_output=True,

                text=True,

                timeout=180,

            )

            paper_stat = dict(paper_stat or {})

            paper_stat["weekly_report"] = "artifacts/operations/paper_weekly_latest.json"

            paper_stat["weekly_report_rc"] = int(wr.returncode)

        except Exception as exc:

            paper_stat = dict(paper_stat or {})

            paper_stat["weekly_report_error"] = exc.__class__.__name__

    except Exception as exc:

        paper_stat = {"opened": 0, "skipped": 0, "error": exc.__class__.__name__}

        resolve_stat = {"resolved": 0, "failed": 0, "still_open": 0, "error": exc.__class__.__name__}

    summary = {

        "ran_at": datetime.now(timezone.utc).isoformat(),

        "board_path": str(board_path()),

        "profile": args.profile,

        "universe_mode": universe_mode,

        "prefilter_volume": prefilter,

        "universe_meta": uni_meta,

        "batches_run": batches_run,

        "last_batch_stats": last_batch_stats,

        "total_seconds": round(time.perf_counter() - t_all, 3),

        "meta": board.get("meta"),

        "top10": top_records,

        "forecast_seed": seed_stat,

        "paper_resolve": resolve_stat,

        "paper_trades": paper_stat,

    }

    out_path = ROOT / str(args.out_summary)

    out_path.parent.mkdir(parents=True, exist_ok=True)

    out_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    try:

        dated = board_path().with_name(

            f"autopilot_nightly_board_{datetime.now(timezone.utc).strftime('%Y%m%d')}.json"

        )

        dated.write_text(json.dumps(load_board() or board, ensure_ascii=False, indent=2), encoding="utf-8")

    except Exception:

        pass

    print(

        json.dumps(

            {

                "ok": True,

                "summary": summary["meta"],

                "universe_mode": universe_mode,

                "top": [r.get("Mã") for r in top_records],

            },

            ensure_ascii=False,

        ),

        flush=True,

    )

    return 0





if __name__ == "__main__":

    raise SystemExit(main())

