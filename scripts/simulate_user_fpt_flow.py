"""
Giả lập người dùng phân tích FPT end-to-end + giám sát nghẽn.
Chạy: python scripts/simulate_user_fpt_flow.py
"""
from __future__ import annotations

import json
import sys
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

try:
    import env_bootstrap  # noqa: F401
except Exception:
    pass

TICKER = "FPT"
USER_ID = "sim_user_fpt"
PROFILE = "growth"
CAPITAL = 100_000_000.0
OUT_DIR = ROOT / "artifacts" / "operations"
OUT_DIR.mkdir(parents=True, exist_ok=True)
OUT_PATH = OUT_DIR / "simulate_user_fpt_flow.json"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class Monitor:
    def __init__(self) -> None:
        self.stages: list[dict] = []
        self.hangs: list[dict] = []
        self.warnings: list[str] = []

    def run(self, name: str, fn, *, soft_limit_s: float = 15.0, hard_limit_s: float = 120.0):
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
            self.hangs.append({"stage": name, "seconds": round(dt, 3), "reason": f">={hard_limit_s}s hard limit"})
        elif ok and dt >= soft_limit_s:
            status = "slow"
            self.hangs.append({"stage": name, "seconds": round(dt, 3), "reason": f">={soft_limit_s}s soft limit"})
        row = {
            "stage": name,
            "seconds": round(dt, 3),
            "ok": ok,
            "status": status,
            "error": err,
            "finished_at": _now(),
        }
        self.stages.append(row)
        flag = "OK" if ok else "FAIL"
        print(f"<<< [{name}] {flag} in {dt:.2f}s status={status}" + (f" err={err}" if err else ""), flush=True)
        return result

    def summary(self) -> dict:
        ok_stages = [s for s in self.stages if s["ok"]]
        failed = [s for s in self.stages if not s["ok"]]
        ranked = sorted(self.stages, key=lambda x: x["seconds"], reverse=True)
        total = sum(s["seconds"] for s in self.stages)
        return {
            "ticker": TICKER,
            "started_finish": {"finished_at": _now()},
            "total_monitored_seconds": round(total, 3),
            "stage_count": len(self.stages),
            "ok_count": len(ok_stages),
            "fail_count": len(failed),
            "bottleneck_top": ranked[:8],
            "hangs_or_slow": self.hangs,
            "failed_stages": failed,
            "warnings": self.warnings,
            "stages": self.stages,
        }


def main() -> int:
    mon = Monitor()
    payload: dict = {
        "ticker": TICKER,
        "user_id": USER_ID,
        "profile": PROFILE,
        "capital_vnd": CAPITAL,
        "ran_at": _now(),
        "results": {},
    }

    # --- 1) Snapshot tài chính ---
    snap = mon.run(
        "1_fetch_financial_snapshot",
        lambda: __import__("scrapers.financial_data", fromlist=["fetch_financial_snapshot"]).fetch_financial_snapshot(TICKER),
        soft_limit_s=10,
        hard_limit_s=45,
    )
    if isinstance(snap, dict):
        payload["results"]["snapshot"] = {
            "keys": sorted(list(snap.keys()))[:40],
            "source": snap.get("source"),
            "price_source": snap.get("price_source"),
            "price": snap.get("price") or snap.get("close") or snap.get("last_price"),
            "pe": snap.get("pe") or snap.get("PE"),
            "pb": snap.get("pb") or snap.get("PB"),
            "roe": snap.get("roe") or snap.get("ROE"),
        }
    else:
        mon.warnings.append("Snapshot không phải dict — dừng sớm các bước phụ thuộc.")
        payload["monitor"] = mon.summary()
        OUT_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(payload["monitor"], ensure_ascii=False, indent=2))
        return 1

    # --- 2) Valuation ---
    from core.valuation import value_investing_summary

    val = mon.run(
        "2_value_investing_summary",
        lambda: value_investing_summary(snap, include_extensions=True),
        soft_limit_s=5,
        hard_limit_s=30,
    )
    if isinstance(val, dict):
        payload["results"]["valuation"] = {
            k: val.get(k)
            for k in (
                "fair_value",
                "margin_of_safety",
                "valuation_label",
                "score",
                "verdict",
                "status",
            )
            if k in val or True
        }

    # --- 3) OHLCV ---
    from scrapers.portal import fetch_ohlcv_history, fetch_latest_news, fetch_financial_indicators

    ohlcv = mon.run(
        "3_fetch_ohlcv_history_80",
        lambda: fetch_ohlcv_history(TICKER, sessions=80),
        soft_limit_s=12,
        hard_limit_s=60,
    )
    if ohlcv is not None:
        try:
            import pandas as pd

            if isinstance(ohlcv, pd.DataFrame):
                payload["results"]["ohlcv"] = {
                    "rows": int(len(ohlcv)),
                    "source": ohlcv.attrs.get("source"),
                    "cols": list(ohlcv.columns)[:12],
                }
        except Exception as e:
            mon.warnings.append(f"OHLCV summarize failed: {e}")

    # --- 4) Indicators ---
    ind = mon.run(
        "4_fetch_financial_indicators",
        lambda: fetch_financial_indicators(TICKER, fast_mode=False),
        soft_limit_s=12,
        hard_limit_s=60,
    )
    if ind is not None:
        payload["results"]["indicators_type"] = type(ind).__name__
        if isinstance(ind, dict):
            payload["results"]["indicators_keys"] = sorted(list(ind.keys()))[:30]

    # --- 5) News ---
    news = mon.run(
        "5_fetch_latest_news",
        lambda: fetch_latest_news(TICKER, limit=8),
        soft_limit_s=10,
        hard_limit_s=45,
    )
    if isinstance(news, list):
        payload["results"]["news_count"] = len(news)
        payload["results"]["news_sample"] = [
            {k: n.get(k) for k in ("title", "source", "published", "date") if isinstance(n, dict) and k in n}
            for n in news[:3]
        ]

    # --- 6) Deep insight (nếu có đủ data) ---
    eq = None
    sm = None
    try:
        from core.deep_insight_service import analyze_earnings_quality, analyze_smart_money_flow

        eq = mon.run(
            "6a_deep_insight_earnings_quality",
            lambda: analyze_earnings_quality(snap, val if isinstance(val, dict) else None),
            soft_limit_s=8,
            hard_limit_s=40,
        )
        sm = mon.run(
            "6b_deep_insight_smart_money",
            lambda: analyze_smart_money_flow(
                list(news) if isinstance(news, list) else [],
                symbol=TICKER,
            ),
            soft_limit_s=8,
            hard_limit_s=40,
        )
        payload["results"]["deep_insight_direct"] = {
            "earnings_quality": {k: (eq or {}).get(k) for k in ("warning", "severity", "score", "label", "notes") if isinstance(eq, dict)},
            "smart_money": {k: (sm or {}).get(k) for k in ("bias", "score", "label", "signals") if isinstance(sm, dict)},
        }
    except Exception as e:
        mon.warnings.append(f"Deep insight import/call skip: {e}")

    # --- 7) Strategic report (không LLM — ổn định local) ---
    from core.ai_logic import generate_strategic_report

    report = mon.run(
        "7_generate_strategic_report_no_llm",
        lambda: generate_strategic_report(
            TICKER,
            snap,
            profile=PROFILE,
            total_capital_vnd=CAPITAL,
            sessions=80,
            news_limit=8,
            enable_llm=False,
            fast_mode=False,
        ),
        soft_limit_s=20,
        hard_limit_s=90,
    )

    # --- 8) Full job bundle (đường UI background) ---
    try:
        from core.analysis_job_runner import execute_full_ticker_job_payload

        bundle = mon.run(
            "8_execute_full_ticker_job_payload",
            lambda: execute_full_ticker_job_payload(
                {
                    "user_id": USER_ID,
                    "ticker": TICKER,
                    "profile": PROFILE,
                    "total_capital_vnd": CAPITAL,
                    "effective_quick_mode": False,
                    "llm_live": False,
                }
            ),
            soft_limit_s=25,
            hard_limit_s=120,
        )
        if isinstance(bundle, dict) and isinstance(bundle.get("report"), dict):
            report = bundle["report"]
            payload["results"]["bundle_keys"] = sorted(list(bundle.keys()))
            payload["results"]["bundle_latency_seconds"] = bundle.get("latency_seconds") or report.get("latency_seconds")
    except Exception as e:
        mon.warnings.append(f"Full job bundle skip: {e}")

    # --- 9) Trích xuất khuyến nghị ---
    risk_plan = {}
    if isinstance(report, dict):
        pf = report.get("probabilistic_forecast") or {}
        di = report.get("deep_insight") or {}
        risk_plan = report.get("risk_plan") if isinstance(report.get("risk_plan"), dict) else {}
        payload["results"]["recommendation"] = {
            "final_action": report.get("final_action"),
            "analysis_verdict": report.get("analysis_verdict"),
            "decision_readiness": report.get("decision_readiness"),
            "confidence_score": report.get("confidence_score"),
            "risk_plan": {
                k: risk_plan.get(k)
                for k in (
                    "entry_price",
                    "buy_zone_low",
                    "buy_zone_high",
                    "stop_loss_price",
                    "take_profit_price",
                    "allocated_capital_vnd",
                    "estimated_quantity",
                    "max_position_pct",
                    "worst_case_loss_vnd",
                    "worst_case_loss_pct_total_capital",
                )
            },
            "forecast": {
                "expected_price": pf.get("expected_price") if isinstance(pf, dict) else None,
                "expected_return_pct": pf.get("expected_return_pct") if isinstance(pf, dict) else None,
                "horizon_days": pf.get("horizon_days") if isinstance(pf, dict) else None,
                "summary": (str(pf.get("summary"))[:400] if isinstance(pf, dict) and pf.get("summary") else None),
                "scenarios": pf.get("scenarios") if isinstance(pf, dict) else None,
            },
            "deep_insight_keys": sorted(list(di.keys()))[:20] if isinstance(di, dict) else [],
            "latency_seconds": report.get("latency_seconds"),
            "reasons_sample": report.get("reasons") or report.get("why") or report.get("summary") or report.get("executive_summary"),
        }
        rs = payload["results"]["recommendation"].get("reasons_sample")
        if isinstance(rs, str) and len(rs) > 500:
            payload["results"]["recommendation"]["reasons_sample"] = rs[:500] + "..."
        elif isinstance(rs, list):
            payload["results"]["recommendation"]["reasons_sample"] = rs[:8]
        elif isinstance(rs, dict):
            payload["results"]["recommendation"]["reasons_sample"] = str(rs)[:500]

    # --- 10) Opportunity 3M (đánh giá mã trong universe logic) ---
    try:
        from core.opportunity_finder import evaluate_stock_opportunity_3m
        import pandas as pd

        ohlcv_df = ohlcv if hasattr(ohlcv, "empty") else None
        if ohlcv_df is None:
            ohlcv_df = pd.DataFrame()
        financials = ind if isinstance(ind, dict) else {}
        valuation_in = val if isinstance(val, dict) else {}

        opp = mon.run(
            "10_evaluate_stock_opportunity_3m",
            lambda: evaluate_stock_opportunity_3m(
                TICKER,
                ohlcv_df,
                valuation_in,
                financials,
                news_items=list(news) if isinstance(news, list) else None,
            ),
            soft_limit_s=15,
            hard_limit_s=60,
        )
        if opp is not None:
            if hasattr(opp, "_asdict"):
                payload["results"]["opportunity_3m"] = dict(opp._asdict())
            elif isinstance(opp, dict):
                payload["results"]["opportunity_3m"] = {
                    k: opp.get(k)
                    for k in ("score", "rank_score", "label", "action", "verdict", "status", "reason", "total_score")
                    if k in opp
                } or {"keys": sorted(list(opp.keys()))[:25], "preview": str(opp)[:500]}
            else:
                # dataclass / object
                payload["results"]["opportunity_3m"] = {
                    k: getattr(opp, k, None)
                    for k in (
                        "symbol",
                        "total_score",
                        "score",
                        "label",
                        "action",
                        "verdict",
                        "technical_score",
                        "fundamental_score",
                        "expected_return_3m_pct",
                        "reasons",
                        "risks",
                    )
                    if hasattr(opp, k)
                } or {"type": type(opp).__name__, "preview": str(opp)[:500]}
    except Exception as e:
        mon.warnings.append(f"Opportunity 3M skip: {e}")

    # --- 11) DSS readiness ---
    try:
        from core.product_layer import get_dss_readiness_report

        dss = mon.run(
            "11_dss_readiness",
            lambda: get_dss_readiness_report(report if isinstance(report, dict) else {}, USER_ID),
            soft_limit_s=10,
            hard_limit_s=45,
        )
        if isinstance(dss, dict):
            payload["results"]["dss"] = {
                "decision": dss.get("decision"),
                "commercial_score": dss.get("commercial_score"),
                "missing_items": dss.get("missing_items"),
                "summary_vi": str(dss.get("summary_vi") or "")[:500],
                "checks": dss.get("checks"),
                "generated_at_utc": dss.get("generated_at_utc"),
            }
    except Exception as e:
        mon.warnings.append(f"DSS readiness skip: {e}")

    # --- 12) Ghi quyết định giả lập vào journal ---
    try:
        from core.product_layer import add_decision as pl_add

        action = "WATCH"
        if isinstance(report, dict):
            action = str(report.get("final_action") or "WATCH").upper()
            if action not in ("BUY", "WATCH"):
                action = "WATCH"
        entry = float((risk_plan or {}).get("entry_price") or snap.get("price") or 0) or float(snap.get("price") or 0)
        sl = float((risk_plan or {}).get("stop_loss_price") or 0)
        tp = float((risk_plan or {}).get("take_profit_price") or 0)
        if entry <= 0:
            entry = float(snap.get("price") or 1)
        if sl <= 0:
            sl = round(entry * 0.92, 2)
        if tp <= 0:
            tp = round(entry * 1.12, 2)
        # BUY journal requires SL < Entry < TP
        if not (sl < entry < tp):
            sl = round(entry * 0.92, 2)
            tp = round(entry * 1.12, 2)

        dec = mon.run(
            "12_add_decision_journal",
            lambda: pl_add(
                USER_ID,
                TICKER,
                action,
                entry,
                sl,
                tp,
                thesis=f"Simulated user flow FPT -> {action}",
                horizon_days=30,
            ),
            soft_limit_s=5,
            hard_limit_s=20,
        )
        ok_flag = False
        msg = ""
        if isinstance(dec, tuple) and len(dec) >= 2:
            ok_flag, msg = bool(dec[0]), str(dec[1])
        payload["results"]["decision_journal"] = {
            "ok": ok_flag,
            "message": msg,
            "action": action,
            "entry": entry,
            "stop_loss": sl,
            "take_profit": tp,
        }
    except Exception as e:
        mon.warnings.append(f"Decision journal skip: {e}")

    # --- Monitor tổng hợp ---
    payload["monitor"] = mon.summary()
    OUT_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")

    print("\n" + "=" * 60, flush=True)
    print("=== KET QUA KHUYEN NGHI FPT ===", flush=True)
    rec = payload["results"].get("recommendation") or {}
    print(f"final_action      = {rec.get('final_action')}", flush=True)
    print(f"analysis_verdict  = {rec.get('analysis_verdict')}", flush=True)
    print(f"decision_readiness= {rec.get('decision_readiness')}", flush=True)
    print(f"confidence_score  = {rec.get('confidence_score')}", flush=True)
    print(f"risk_plan         = {rec.get('risk_plan')}", flush=True)
    print(f"forecast          = {rec.get('forecast')}", flush=True)
    print(f"opportunity_3m    = {payload['results'].get('opportunity_3m')}", flush=True)
    print(f"dss               = {payload['results'].get('dss')}", flush=True)
    print(f"decision_journal  = {payload['results'].get('decision_journal')}", flush=True)
    print("\n=== BOTTLENECK / NGHEN ===", flush=True)
    for b in payload["monitor"]["bottleneck_top"][:6]:
        print(f"  {b['seconds']:7.2f}s  [{b['status']}] {b['stage']}" + (f" :: {b.get('error')}" if b.get("error") else ""), flush=True)
    if payload["monitor"]["hangs_or_slow"]:
        print("\nCanh bao cham/nghen:", flush=True)
        for h in payload["monitor"]["hangs_or_slow"]:
            print(f"  - {h['stage']}: {h['seconds']}s -- {h['reason']}", flush=True)
    if payload["monitor"]["failed_stages"]:
        print("\nFailed stages:", flush=True)
        for f in payload["monitor"]["failed_stages"]:
            print(f"  - {f['stage']}: {f.get('error')}", flush=True)
    if payload["monitor"]["warnings"]:
        print("\nWarnings:", flush=True)
        for w in payload["monitor"]["warnings"]:
            print(f"  - {w}", flush=True)
    print(f"\nWrote: {OUT_PATH}", flush=True)
    print(f"Total monitored seconds: {payload['monitor']['total_monitored_seconds']}s", flush=True)
    return 0 if payload["monitor"]["fail_count"] == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
