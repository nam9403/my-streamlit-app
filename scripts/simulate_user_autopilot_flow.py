"""
Gia lap nguoi dung Autopilot: tim co phieu tiem nang tang gia khung 2-6 thang.
Dong thoi giam sat tien trinh + bottleneck.

Chay:
  python scripts/simulate_user_autopilot_flow.py
  python scripts/simulate_user_autopilot_flow.py --universe-limit 40 --finder-limit 25
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

try:
    import env_bootstrap  # noqa: F401
except Exception:
    pass

# Optimizations aligned with snapshot SWR work (fast disk reuse).
os.environ.setdefault("II_SNAPSHOT_PREFER_LIVE", "1")
os.environ.setdefault("II_READ_STALE_DISK", "1")
os.environ.setdefault("II_SNAPSHOT_STALE_WHILE_REVALIDATE", "1")
os.environ.setdefault("II_SNAPSHOT_SWR_PRICE_OVERLAY", "0")
os.environ.setdefault("II_QUOTE_PROVIDER_ORDER", "vndirect,cafef,vietstock")
os.environ.setdefault("II_CAFEF_MAX_BOARDS", "1")
os.environ.setdefault("II_CAFEF_TIMEOUT", "3")
os.environ.setdefault("II_HTTP_TIMEOUT", "5")
os.environ.setdefault("VALUE_INVESTOR_PORTAL_TIMEOUT", "4")
os.environ.setdefault("II_PORTAL_TIMEOUT_LADDER_SEC", "2,4")
os.environ.setdefault("II_PORTAL_FAIL_FAST", "1")
os.environ.setdefault("II_PORTAL_FAIL_FAST_BUDGET_SEC", "3.5")
os.environ.setdefault("II_PORTAL_LIVE_BUDGET_SEC", "6")
os.environ.setdefault("II_OHLCV_DISK_FIRST", "1")
os.environ.setdefault("II_OHLCV_DISK_MAX_AGE_SEC", "7200")
os.environ.setdefault("II_FINANCIAL_DISK_FIRST", "1")
os.environ.setdefault("II_FINANCIAL_DISK_MAX_AGE_SEC", "21600")
os.environ.setdefault("II_SCAN_MAX_WORKERS", "3")
os.environ.setdefault("II_SCAN_PREFILTER_MAX_WORKERS", "3")
os.environ.setdefault("II_SCAN_SYMBOL_BATCH_SIZE", "8")
os.environ.setdefault("II_FINDER_MAX_WORKERS", "3")
os.environ.setdefault("II_FINDER_PARALLEL", "1")
os.environ.setdefault("II_UNIVERSE_AUTO_ROTATE", "1")
os.environ.setdefault("II_AUTOPILOT_UNIVERSE_MODE", "rotate_full")
os.environ.setdefault("II_UNIVERSE_ROTATE_STYLE", "sequential")
os.environ.setdefault("II_SCAN_OHLCV_SESSIONS", "80")
os.environ.setdefault("II_VNSTOCK_TIMEOUT_SEC", "3.5")
os.environ.setdefault("II_VNSTOCK_RETRY_MAX", "1")
os.environ.setdefault("II_OHLCV_ALLOW_STALE_DISK_FALLBACK", "1")
os.environ.setdefault("II_OHLCV_RUNTIME_SESSIONS", "260")

OUT_DIR = ROOT / "artifacts" / "operations"
OUT_DIR.mkdir(parents=True, exist_ok=True)
OUT_PATH = OUT_DIR / "simulate_user_autopilot_flow.json"

MID_HORIZON_TOKEN = "2-6 tháng"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _ensure_streamlit_session() -> None:
    """Autopilot/scanner dung st.session_state — can stub khi chay CLI."""
    try:
        import streamlit as st

        try:
            _ = st.session_state.get("scan_preselect_limit")
        except Exception:
            # ScriptRunContext missing: dung dict gia.
            class _SS(dict):
                def get(self, k, default=None):  # type: ignore[override]
                    return dict.get(self, k, default)

                def __getattr__(self, k):
                    try:
                        return self[k]
                    except KeyError as e:
                        raise AttributeError(k) from e

                def __setattr__(self, k, v):
                    self[k] = v

            st.session_state = _SS()  # type: ignore[misc]
    except Exception:
        pass


class Monitor:
    def __init__(self) -> None:
        self.stages: list[dict[str, Any]] = []
        self.hangs: list[dict[str, Any]] = []
        self.warnings: list[str] = []
        self.symbol_timings: list[dict[str, Any]] = []

    def run(self, name: str, fn, *, soft_limit_s: float = 30.0, hard_limit_s: float = 180.0):
        print(f"\n>>> [{name}] start @ {_now()}", flush=True)
        t0 = time.perf_counter()
        ok = True
        err = ""
        result = None
        try:
            result = fn()
        except Exception as e:
            ok = False
            err = f"{type(e).__name__}: {e}"
            traceback.print_exc()
        dt = time.perf_counter() - t0
        status = "ok" if ok else "error"
        if ok and dt >= hard_limit_s:
            status = "hang_suspect"
            self.hangs.append({"stage": name, "seconds": round(dt, 3), "reason": f">={hard_limit_s}s"})
        elif ok and dt >= soft_limit_s:
            status = "slow"
            self.hangs.append({"stage": name, "seconds": round(dt, 3), "reason": f">={soft_limit_s}s soft"})
        row = {
            "stage": name,
            "seconds": round(dt, 3),
            "ok": ok,
            "status": status,
            "error": err,
            "finished_at": _now(),
        }
        self.stages.append(row)
        print(f"<<< [{name}] {'OK' if ok else 'FAIL'} in {dt:.2f}s status={status}" + (f" err={err}" if err else ""), flush=True)
        return result

    def summary(self) -> dict[str, Any]:
        ranked = sorted(self.stages, key=lambda x: x["seconds"], reverse=True)
        failed = [s for s in self.stages if not s["ok"]]
        total = sum(s["seconds"] for s in self.stages)
        slow_syms = sorted(self.symbol_timings, key=lambda x: x.get("seconds", 0), reverse=True)[:15]
        return {
            "total_monitored_seconds": round(total, 3),
            "stage_count": len(self.stages),
            "ok_count": sum(1 for s in self.stages if s["ok"]),
            "fail_count": len(failed),
            "bottleneck_top": ranked[:10],
            "hangs_or_slow": self.hangs,
            "failed_stages": failed,
            "slowest_symbols": slow_syms,
            "warnings": self.warnings,
            "stages": self.stages,
        }


def _df_records(df, limit: int = 30) -> list[dict[str, Any]]:
    import pandas as pd

    if df is None or not isinstance(df, pd.DataFrame) or df.empty:
        return []
    return json.loads(df.head(limit).to_json(orient="records", force_ascii=False))


def _filter_mid_horizon(df):
    import pandas as pd

    if df is None or not isinstance(df, pd.DataFrame) or df.empty:
        return df
    if "Khung thời gian" not in df.columns:
        return df.iloc[0:0]
    mask = df["Khung thời gian"].astype(str).str.contains(MID_HORIZON_TOKEN, na=False)
    return df.loc[mask].copy()


def _install_symbol_timing_hooks(mon: Monitor) -> None:
    """Do thoi gian snapshot/report theo ma trong scanner path."""
    try:
        import core.analysis_runtime_service as ars

        orig_snap = ars._snapshot_impl
        orig_rep = ars._strategic_report_impl

        def snap_wrap(ticker: str, *a, **k):
            t0 = time.perf_counter()
            out = orig_snap(ticker, *a, **k)
            mon.symbol_timings.append(
                {
                    "ticker": str(ticker).upper(),
                    "op": "snapshot",
                    "seconds": round(time.perf_counter() - t0, 3),
                    "ok": out is not None,
                }
            )
            return out

        def rep_wrap(ticker: str, *a, **k):
            t0 = time.perf_counter()
            out = orig_rep(ticker, *a, **k)
            mon.symbol_timings.append(
                {
                    "ticker": str(ticker).upper(),
                    "op": "strategic_report",
                    "seconds": round(time.perf_counter() - t0, 3),
                    "ok": isinstance(out, dict),
                }
            )
            return out

        ars._snapshot_impl = snap_wrap  # type: ignore[assignment]
        ars._strategic_report_impl = rep_wrap  # type: ignore[assignment]
        # Cached wrappers call impls; also patch public names used by scanner.
        ars.load_snapshot_cached = snap_wrap  # type: ignore[assignment]
        ars.load_strategic_report_cached = rep_wrap  # type: ignore[assignment]
        import core.scanner_service as ss

        ss.load_snapshot_cached = snap_wrap  # type: ignore[assignment]
        ss.load_strategic_report_cached = rep_wrap  # type: ignore[assignment]
    except Exception as e:
        mon.warnings.append(f"symbol timing hooks skipped: {e}")


def main() -> int:
    ap = argparse.ArgumentParser(description="Simulate Autopilot user flow + bottleneck monitor")
    ap.add_argument("--universe-limit", type=int, default=20, help="Autopilot universe window (10-120)")
    ap.add_argument("--min-vol", type=float, default=200_000.0, help="Min avg volume 20")
    ap.add_argument("--finder-limit", type=int, default=15, help="Finder 3M universe size")
    ap.add_argument("--profile", default="growth")
    ap.add_argument("--capital", type=float, default=100_000_000.0)
    ap.add_argument("--skip-finder", action="store_true")
    ap.add_argument("--skip-deepdive", action="store_true")
    ap.add_argument("--top-n", type=int, default=8)
    ap.add_argument(
        "--vn30",
        action="store_true",
        help="Scan VN30 liquid universe instead of daily Autopilot rotation window",
    )
    ap.add_argument(
        "--symbols",
        default="",
        help="Comma-separated symbols override (skips rotation)",
    )
    args = ap.parse_args()

    _ensure_streamlit_session()
    mon = Monitor()
    payload: dict[str, Any] = {
        "ran_at": _now(),
        "user_id": "sim_user_autopilot",
        "goal": "Tim co phieu tiem nang tang gia khung ~6 thang (gan nhat: Trung han 2-6 thang + Finder 3M)",
        "config": {
            "profile": args.profile,
            "universe_limit": args.universe_limit,
            "min_avg_volume_20": args.min_vol,
            "finder_limit": args.finder_limit,
            "capital_vnd": args.capital,
            "scan_max_workers": os.environ.get("II_SCAN_MAX_WORKERS"),
            "quote_order": os.environ.get("II_QUOTE_PROVIDER_ORDER"),
            "swr": os.environ.get("II_SNAPSHOT_STALE_WHILE_REVALIDATE"),
        },
        "results": {},
    }

    _install_symbol_timing_hooks(mon)

    # --- 1) Universe listing ---
    from scrapers.financial_data import list_universe_symbols

    full = mon.run(
        "1_list_universe_symbols",
        lambda: list_universe_symbols(limit=None),
        soft_limit_s=8,
        hard_limit_s=40,
    )
    full_list = list(full or [])
    payload["results"]["universe_total"] = len(full_list)
    payload["results"]["universe_sample"] = full_list[:20]

    # --- 2) Autopilot / Deep Scan board ---
    from core.scanner_service import load_autopilot_board, scan_potential_stocks
    import pandas as pd

    override_syms: list[str] = []
    if str(args.symbols or "").strip():
        override_syms = [s.strip().upper() for s in str(args.symbols).split(",") if s.strip()]
    elif args.vn30:
        override_syms = [
            "ACB", "BCM", "BID", "BVH", "CTG", "FPT", "GAS", "GVR", "HDB", "HPG",
            "MBB", "MSN", "MWG", "PLX", "POW", "SAB", "SHB", "SSB", "SSI", "STB",
            "TCB", "TPB", "VCB", "VHM", "VIB", "VIC", "VJC", "VNM", "VPB", "VRE",
        ]

    def _rank_autopilot_like(df: pd.DataFrame) -> pd.DataFrame:
        if df is None or not isinstance(df, pd.DataFrame) or df.empty:
            return pd.DataFrame()
        ready = df[df["Trạng thái"] == "Sẵn sàng"].copy() if "Trạng thái" in df.columns else df.copy()
        base = ready if not ready.empty else df.copy()
        if "Khuyến nghị" not in base.columns:
            base = base.copy()
            base["Khuyến nghị"] = "AVOID"
        for col, default in (
            ("Expected Return %", 0.0),
            ("MOS%", 0.0),
            ("Risk % (ước tính)", 0.0),
        ):
            if col not in base.columns:
                base[col] = default
        rank_map = {"BUY": 3, "HOLD": 2, "WATCH": 1, "AVOID": 0}
        base["__rank"] = base["Khuyến nghị"].map(rank_map).fillna(0)
        base["__score"] = (
            base["__rank"] * 20
            + base["Expected Return %"].fillna(0) * 0.7
            + base["MOS%"].fillna(0) * 0.3
            - base["Risk % (ước tính)"].fillna(0) * 0.2
        )
        return (
            base.sort_values(["__score", "MOS%", "Expected Return %"], ascending=[False, False, False])
            .drop(columns=["__rank", "__score"], errors="ignore")
            .head(max(10, int(args.top_n)))
            .reset_index(drop=True)
        )

    if override_syms:
        payload["config"]["universe_mode"] = "vn30" if args.vn30 and not args.symbols else "symbols_override"
        payload["config"]["universe_symbols"] = override_syms
        scan_fn = getattr(scan_potential_stocks, "__wrapped__", scan_potential_stocks)
        raw_df = mon.run(
            "2_scan_potential_stocks_override",
            lambda: scan_fn(tuple(override_syms), args.profile, float(args.min_vol)),
            soft_limit_s=60,
            hard_limit_s=360,
        )
        ap_df = _rank_autopilot_like(raw_df if isinstance(raw_df, pd.DataFrame) else pd.DataFrame())
        payload["results"]["autopilot"] = {
            "latency_seconds": next(
                (s["seconds"] for s in mon.stages if s["stage"] == "2_scan_potential_stocks_override"),
                None,
            ),
            "row_count": int(len(ap_df)),
            "rows": _df_records(ap_df, limit=20),
            "raw_row_count": int(len(raw_df)) if isinstance(raw_df, pd.DataFrame) else 0,
        }
    else:
        payload["config"]["universe_mode"] = "autopilot_rotation"
        from core.analysis_job_runner import execute_autopilot_job_payload

        ap_out = mon.run(
            "2_autopilot_board",
            lambda: execute_autopilot_job_payload(
                {
                    "profile": args.profile,
                    "universe_limit": max(10, min(120, int(args.universe_limit))),
                    "min_avg_volume_20": float(args.min_vol),
                }
            ),
            soft_limit_s=45,
            hard_limit_s=240,
        )
        ap_df = None
        if isinstance(ap_out, dict):
            ap_df = ap_out.get("autopilot_df")
            payload["results"]["autopilot"] = {
                "latency_seconds": ap_out.get("latency_seconds"),
                "row_count": ap_out.get("row_count"),
                "rows": _df_records(ap_df, limit=20),
            }

    mid_df = mon.run(
        "3_filter_mid_horizon_2_6m",
        lambda: _filter_mid_horizon(ap_df),
        soft_limit_s=2,
        hard_limit_s=10,
    )
    payload["results"]["mid_horizon_2_6m"] = {
        "row_count": int(len(mid_df)) if mid_df is not None else 0,
        "rows": _df_records(mid_df, limit=20),
    }

    # Prefer mid-horizon; else top autopilot actionable
    picks = []
    import pandas as pd

    if isinstance(mid_df, pd.DataFrame) and not mid_df.empty:
        picks = [str(x).upper() for x in mid_df["Mã"].head(args.top_n).tolist()]
    elif isinstance(ap_df, pd.DataFrame) and not ap_df.empty and "Mã" in ap_df.columns:
        ready = ap_df
        if "Khuyến nghị" in ap_df.columns:
            ready = ap_df[ap_df["Khuyến nghị"].astype(str).str.upper().isin(["BUY", "HOLD", "WATCH"])]
            if ready.empty:
                ready = ap_df
        picks = [str(x).upper() for x in ready["Mã"].head(args.top_n).tolist()]
    payload["results"]["top_picks"] = picks

    # --- 4) Finder 3M (true opportunity model, closest quantitative horizon) ---
    if not args.skip_finder:
        from core.analysis_job_runner import execute_finder_3m_job_payload

        finder_uni = override_syms[:] if override_syms else full_list[: max(10, int(args.finder_limit))]
        # Prefer seeding finder with autopilot picks first
        seed = []
        for s in picks + finder_uni:
            if s and s not in seed:
                seed.append(s)
            if len(seed) >= int(args.finder_limit):
                break
        finder_out = mon.run(
            "4_finder_3m_board",
            lambda: execute_finder_3m_job_payload(
                {
                    "universe": seed,
                    "profile": args.profile,
                    "total_capital_vnd": float(args.capital),
                    "quick_mode": True,
                    "llm_live": False,
                    "min_avg_volume_20": float(args.min_vol),
                    "min_data_quality_pct": 40.0,
                    "only_actionable": False,
                    "top_n": max(10, int(args.top_n)),
                }
            ),
            soft_limit_s=60,
            hard_limit_s=300,
        )
        if isinstance(finder_out, dict):
            fdf = finder_out.get("finder_df")
            payload["results"]["finder_3m"] = {
                "latency_seconds": finder_out.get("latency_seconds"),
                "row_count": finder_out.get("row_count"),
                "universe_used": seed,
                "rows": _df_records(fdf, limit=20),
            }

    # --- 5) Deep-dive top pick (full analysis like user click) ---
    if not args.skip_deepdive and picks:
        from core.analysis_job_runner import execute_full_ticker_job_payload

        top = picks[0]
        deep = mon.run(
            f"5_deepdive_{top}",
            lambda: execute_full_ticker_job_payload(
                {
                    "user_id": "sim_user_autopilot",
                    "ticker": top,
                    "profile": args.profile,
                    "total_capital_vnd": float(args.capital),
                    "effective_quick_mode": True,
                    "llm_live": False,
                }
            ),
            soft_limit_s=20,
            hard_limit_s=90,
        )
        if isinstance(deep, dict):
            rep = deep.get("report") or {}
            payload["results"]["deepdive"] = {
                "ticker": top,
                "latency_seconds": (deep.get("report") or {}).get("latency_seconds"),
                "final_action": rep.get("final_action"),
                "analysis_verdict": rep.get("analysis_verdict"),
                "confidence_score": rep.get("confidence_score"),
                "decision_readiness": rep.get("decision_readiness"),
                "forecast": {
                    "expected_return_pct": (rep.get("probabilistic_forecast") or {}).get("expected_return_pct"),
                    "horizon_days": (rep.get("probabilistic_forecast") or {}).get("horizon_days"),
                    "summary": str((rep.get("probabilistic_forecast") or {}).get("summary") or "")[:300],
                },
            }

    # Aggregate symbol timing
    by_sym: dict[str, dict[str, float]] = {}
    for rec in mon.symbol_timings:
        s = rec["ticker"]
        by_sym.setdefault(s, {"snapshot": 0.0, "strategic_report": 0.0, "total": 0.0})
        by_sym[s][rec["op"]] = by_sym[s].get(rec["op"], 0.0) + float(rec["seconds"])
        by_sym[s]["total"] = by_sym[s]["snapshot"] + by_sym[s]["strategic_report"]
    slow_syms = sorted(
        [{"ticker": k, **v} for k, v in by_sym.items()],
        key=lambda x: x["total"],
        reverse=True,
    )[:15]
    mon.symbol_timings = slow_syms  # replace raw with aggregated for summary

    # Improvement ideas from observed bottlenecks
    ideas: list[str] = []
    for h in mon.hangs:
        if "autopilot" in h["stage"]:
            ideas.append(
                "Autopilot cham: giam universe_limit hoac tang cache warm (prefetch/data tank); "
                "quick_mode da bat — xem slowest_symbols de prefetch uu tien."
            )
        if "finder" in h["stage"]:
            ideas.append(
                "Finder 3M cham: giam finder_limit / II_FINDER_OHLCV_SESSIONS; dam bao OHLCV disk warm."
            )
    if slow_syms and slow_syms[0]["total"] >= 5:
        ideas.append(
            f"Ma cham nhat {slow_syms[0]['ticker']} ~{slow_syms[0]['total']}s "
            "(snapshot/report) — prefetch watchlist truoc Autopilot."
        )
    if not ideas:
        ideas.append("Khong co hang nghiem trong; tiep tuc warm disk + SWR de giu latency on dinh.")
    payload["improvement_ideas"] = ideas

    payload["monitor"] = mon.summary()
    OUT_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")

    # Console summary (ASCII-safe)
    print("\n" + "=" * 64, flush=True)
    print("=== AUTOPILOT SIM RESULT (growth / ~2-6M horizon) ===", flush=True)
    print(f"universe_total = {payload['results'].get('universe_total')}", flush=True)
    ap_info = payload["results"].get("autopilot") or {}
    print(f"autopilot_rows = {ap_info.get('row_count')}  latency={ap_info.get('latency_seconds')}s", flush=True)
    mid = payload["results"].get("mid_horizon_2_6m") or {}
    print(f"mid_horizon_2_6m_rows = {mid.get('row_count')}", flush=True)
    print(f"top_picks = {picks}", flush=True)
    if mid.get("rows"):
        print("\n-- Mid-horizon candidates --", flush=True)
        for r in mid["rows"][:10]:
            print(
                f"  {r.get('Mã')}: rec={r.get('Khuyến nghị')} exp={r.get('Expected Return %')}% "
                f"phase={r.get('Pha')} mos={r.get('MOS%')} horizon={r.get('Khung thời gian')}",
                flush=True,
            )
    elif ap_info.get("rows"):
        print("\n-- Autopilot top (no mid-horizon match) --", flush=True)
        for r in ap_info["rows"][:10]:
            print(
                f"  {r.get('Mã')}: rec={r.get('Khuyến nghị')} exp={r.get('Expected Return %')}% "
                f"phase={r.get('Pha')} horizon={r.get('Khung thời gian')}",
                flush=True,
            )
    f3 = payload["results"].get("finder_3m") or {}
    if f3:
        print(f"\nfinder_3m_rows = {f3.get('row_count')} latency={f3.get('latency_seconds')}s", flush=True)
        for r in (f3.get("rows") or [])[:8]:
            sym = r.get("symbol") or r.get("Mã") or r.get("ticker")
            print(f"  {sym}: { {k:r.get(k) for k in list(r)[:8]} }", flush=True)
    dd = payload["results"].get("deepdive")
    if dd:
        print(f"\ndeepdive {dd.get('ticker')}: action={dd.get('final_action')} verdict={dd.get('analysis_verdict')} conf={dd.get('confidence_score')}", flush=True)

    print("\n=== BOTTLENECKS ===", flush=True)
    for b in payload["monitor"]["bottleneck_top"][:8]:
        print(f"  {b['seconds']:7.2f}s [{b['status']}] {b['stage']}" + (f" :: {b.get('error')}" if b.get("error") else ""), flush=True)
    if payload["monitor"].get("slowest_symbols"):
        print("\nSlowest symbols (agg):", flush=True)
        for s in payload["monitor"]["slowest_symbols"][:8]:
            print(f"  {s['ticker']}: total={s['total']}s snap={s.get('snapshot')} rep={s.get('strategic_report')}", flush=True)
    print("\nImprovement ideas:", flush=True)
    for i in ideas:
        print(f"  - {i}", flush=True)
    print(f"\nWrote: {OUT_PATH}", flush=True)
    return 0 if payload["monitor"]["fail_count"] == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
