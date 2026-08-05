"""
Giả lập phân tích mã PNJ end-to-end (snapshot → valuation → news/story → strategic report).
Chạy: python scripts/simulate_user_pnj_flow.py
"""
from __future__ import annotations

import json
import os
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

# Live-ish sample: không ép offline quá mức (giống trải nghiệm người dùng).
os.environ.setdefault("II_PORTAL_FAIL_FAST", "1")
os.environ.setdefault("II_PORTAL_FAIL_FAST_BUDGET_SEC", "6")
os.environ.setdefault("II_SNAPSHOT_QUOTE_BUDGET_SEC", "10")
os.environ.setdefault("II_OHLCV_DISK_FIRST", "1")
os.environ.setdefault("II_OHLCV_ALLOW_STALE_DISK_FALLBACK", "1")
os.environ.setdefault("II_FINANCIAL_DISK_FIRST", "1")
# Sample UX: dùng disk fin đã prefetch; không ép live refresh (tránh bỏ qua cache).
os.environ["II_FINANCIAL_LIVE_REFRESH"] = "0"
os.environ.setdefault("II_SNAPSHOT_PREFER_LIVE", "1")
os.environ.setdefault("II_UNIFIED_LIVE_PRICE", "1")
os.environ.setdefault("II_SNAPSHOT_FORCE_OHLCV_CROSSCHECK", "0")

TICKER = "PNJ"
PROFILE = "growth"
CAPITAL = 100_000_000.0
OUT_PATH = ROOT / "artifacts" / "operations" / "simulate_user_pnj_flow.json"

try:
    from scrapers.financial_data import clear_stock_metadata_cache

    clear_stock_metadata_cache()
except Exception:
    pass


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _run(name: str, fn, stages: list[dict]):
    print(f"\n>>> [{name}] start", flush=True)
    t0 = time.perf_counter()
    ok, err, result = True, "", None
    try:
        result = fn()
    except Exception as e:
        ok = False
        err = f"{type(e).__name__}: {e}"
        traceback.print_exc()
    dt = time.perf_counter() - t0
    stages.append({"stage": name, "seconds": round(dt, 3), "ok": ok, "error": err})
    print(f"<<< [{name}] {'OK' if ok else 'FAIL'} in {dt:.2f}s" + (f" err={err}" if err else ""), flush=True)
    return result


def main() -> int:
    stages: list[dict] = []
    payload: dict = {
        "ran_at": _now(),
        "ticker": TICKER,
        "profile": PROFILE,
        "capital_vnd": CAPITAL,
    }

    def _snap():
        from scrapers.financial_data import fetch_financial_snapshot

        return fetch_financial_snapshot(TICKER)

    snap = _run("1_fetch_financial_snapshot", _snap, stages) or {}
    payload["snapshot"] = {
        "price": snap.get("price"),
        "ohlcv_close": snap.get("ohlcv_close"),
        "pe_ratio": snap.get("pe_ratio"),
        "pb_ratio": snap.get("pb_ratio"),
        "roe": snap.get("roe"),
        "eps": snap.get("eps"),
        "debt_to_equity": snap.get("debt_to_equity"),
        "growth_rate_pct": snap.get("growth_rate_pct"),
        "source": snap.get("source"),
        "price_source": snap.get("price_source"),
        "price_crosscheck_note_vi": snap.get("price_crosscheck_note_vi"),
        "industry": snap.get("industry") or snap.get("industry_name") or snap.get("industry_vi"),
        "industry_cluster": snap.get("industry_cluster"),
        "fundamentals_merge_notes": (snap.get("fundamentals_merge_notes") or [])[:8],
    }

    def _val():
        from core.valuation import value_investing_summary

        return value_investing_summary(snap, include_extensions=False)

    val = _run("2_value_investing_summary", _val, stages) or {}
    payload["valuation"] = {
        "instant_conclusion": val.get("instant_conclusion"),
        "piotroski_score": val.get("piotroski_score"),
        "roe_5y_avg": val.get("roe_5y_avg"),
        "margin_of_safety_composite_pct": val.get("margin_of_safety_composite_pct"),
        "legend_scorecard": val.get("legend_scorecard"),
        "value_trap_warning": val.get("value_trap_warning"),
        "pe_sanity_notes": val.get("pe_sanity_notes") or [],
        "is_bank_sector": val.get("is_bank_sector"),
        "industry_subtype_label_vi": val.get("industry_subtype_label_vi"),
    }

    def _macro():
        from core.news_macro_service import get_macro_snapshot

        return get_macro_snapshot()

    macro = _run("3_get_macro_snapshot", _macro, stages) or {}
    payload["macro_snapshot"] = {
        "market_bias": macro.get("market_bias"),
        "source": macro.get("source"),
        "usd_vnd": macro.get("usd_vnd"),
        "notes_vi": macro.get("notes_vi"),
        "saved_at": macro.get("saved_at"),
    }

    def _micro():
        from core.news_macro_service import get_micro_bundle

        return get_micro_bundle(TICKER, allow_network=True, news_limit=8)

    micro = _run("4_get_micro_bundle", _micro, stages) or {}
    payload["micro"] = {
        "source": micro.get("source"),
        "news_count": len(micro.get("news") or []),
        "events_hint": (micro.get("events_hint") or [])[:5],
        "news_sample": [
            {"title": x.get("title"), "source": x.get("source")}
            for x in (micro.get("news") or [])[:5]
        ],
    }

    def _story():
        from core.news_macro_service import (
            detect_story_catalysts,
            format_news_macro_bias_caption,
            get_combined_story_score,
            score_catalyst,
        )

        catalysts = detect_story_catalysts(TICKER)
        return {
            "catalyst_score": score_catalyst(TICKER, allow_network=False),
            "story_score": get_combined_story_score(TICKER),
            "catalysts": catalysts,
            "caption": format_news_macro_bias_caption(TICKER, allow_network=False),
        }

    story = _run("5_story_catalyst", _story, stages) or {}
    payload["story"] = story

    def _report():
        from core.ai_logic import generate_strategic_report

        return generate_strategic_report(
            TICKER,
            snap,
            profile=PROFILE,
            total_capital_vnd=CAPITAL,
            enable_llm=False,
            fast_mode=True,
            news_limit=5,
        )

    report = _run("6_strategic_report_fast", _report, stages) or {}
    # Report/context có thể gắn ohlcv_close + industry lên snapshot in-place.
    payload["snapshot"]["ohlcv_close"] = snap.get("ohlcv_close") or payload["snapshot"].get("ohlcv_close")
    payload["snapshot"]["price_crosscheck_note_vi"] = snap.get("price_crosscheck_note_vi") or payload[
        "snapshot"
    ].get("price_crosscheck_note_vi")
    payload["snapshot"]["industry"] = (
        snap.get("industry")
        or snap.get("industry_name")
        or snap.get("industry_vi")
        or payload["snapshot"].get("industry")
    )
    payload["snapshot"]["debt_to_equity"] = snap.get("debt_to_equity") or payload["snapshot"].get("debt_to_equity")
    rec = report.get("recommendation") if isinstance(report, dict) else {}
    phase = report.get("phase") if isinstance(report, dict) else {}
    financials = report.get("financials") if isinstance(report, dict) else {}
    # Prefer nested phase metrics if report stores market_phase differently.
    if (not phase or not isinstance(phase, dict)) and isinstance(report, dict):
        tech = report.get("technical") if isinstance(report.get("technical"), dict) else {}
        mp = tech.get("market_phase") if isinstance(tech.get("market_phase"), dict) else {}
        if mp:
            phase = mp
    if isinstance(phase, dict) and "metrics" not in phase and phase.get("phase"):
        # Some paths nest as {phase, reason, metrics} already.
        pass
    val_from_report = report.get("valuation") if isinstance(report.get("valuation"), dict) else {}
    if val_from_report.get("margin_of_safety_composite_pct") is not None:
        payload["valuation"]["margin_of_safety_composite_pct"] = val_from_report.get(
            "margin_of_safety_composite_pct"
        )
        payload["valuation"]["legend_scorecard"] = val_from_report.get("legend_scorecard") or payload[
            "valuation"
        ].get("legend_scorecard")
        payload["valuation"]["value_trap_warning"] = val_from_report.get("value_trap_warning") or payload[
            "valuation"
        ].get("value_trap_warning")
        payload["valuation"]["pe_sanity_notes"] = val_from_report.get("pe_sanity_notes") or payload["valuation"].get(
            "pe_sanity_notes"
        )
        payload["valuation"]["industry_subtype_label_vi"] = val_from_report.get(
            "industry_subtype_label_vi"
        ) or payload["valuation"].get("industry_subtype_label_vi")
    payload["recommendation"] = {
        "final_action": (rec or {}).get("final_action") or report.get("final_action"),
        "confidence_score": (rec or {}).get("confidence_score") or report.get("confidence_score"),
        "analysis_verdict": (rec or {}).get("analysis_verdict") or report.get("analysis_verdict"),
        "decision_readiness": report.get("decision_readiness"),
        "readiness_score": report.get("readiness_score") or report.get("decision_readiness"),
        "whys_steps": ((rec or {}).get("whys_steps") or report.get("whys_steps") or [])[:6],
        "risks": ((rec or {}).get("risks") or report.get("risks") or [])[:5],
    }
    payload["phase"] = {
        "phase": (phase or {}).get("phase"),
        "metrics": (phase or {}).get("metrics") if isinstance(phase, dict) else None,
    }
    payload["financials_summary"] = {
        "revenue_growth_yoy": (financials or {}).get("revenue_growth_yoy"),
        "ni_growth_yoy": (financials or {}).get("ni_growth_yoy")
        or (financials or {}).get("profit_growth_yoy"),
        "cfo": (financials or {}).get("cfo") or (financials or {}).get("operating_cash_flow"),
        "debt_to_equity": (financials or {}).get("debt_to_equity") or snap.get("debt_to_equity"),
        "source": (financials or {}).get("source"),
    }

    def _completeness():
        from core.decision_completeness import (
            apply_completeness_to_report,
            assess_decision_completeness,
        )

        gate = assess_decision_completeness(
            snap,
            val if isinstance(val, dict) else {},
            financials if isinstance(financials, dict) else {},
        )
        patched = apply_completeness_to_report(
            report if isinstance(report, dict) else {},
            snap,
        )
        return {
            "gate": gate,
            "final_action_after": patched.get("final_action")
            or ((patched.get("recommendation") or {}) if isinstance(patched.get("recommendation"), dict) else {}).get(
                "final_action"
            ),
            "decision_readiness_after": patched.get("decision_readiness"),
            "softened": bool(gate.get("soften_legend")),
            "notes": gate.get("notes") or [],
        }

    soft = _run("7_decision_completeness", _completeness, stages) or {}
    payload["decision_completeness"] = soft

    payload["stages"] = stages
    payload["total_seconds"] = round(sum(s["seconds"] for s in stages), 3)
    payload["all_ok"] = all(s["ok"] for s in stages)
    payload["user_experience_summary_vi"] = {
        "ma": TICKER,
        "gia": payload["snapshot"].get("price"),
        "ohlcv_close": payload["snapshot"].get("ohlcv_close"),
        "price_crosscheck": payload["snapshot"].get("price_crosscheck_note_vi"),
        "ket_luan_dinh_gia": payload["valuation"].get("instant_conclusion"),
        "mos_pct": payload["valuation"].get("margin_of_safety_composite_pct"),
        "f_score": payload["valuation"].get("piotroski_score"),
        "legend": payload["valuation"].get("legend_scorecard"),
        "industry": payload["snapshot"].get("industry"),
        "pha": (payload.get("phase") or {}).get("phase"),
        "rsi14": ((payload.get("phase") or {}).get("metrics") or {}).get("rsi14"),
        "rsi_anomaly": ((payload.get("phase") or {}).get("metrics") or {}).get("rsi_anomaly"),
        "story_score": (story or {}).get("story_score"),
        "catalyst_score": (story or {}).get("catalyst_score"),
        "khuyen_nghi": payload["recommendation"].get("final_action"),
        "verdict": payload["recommendation"].get("analysis_verdict"),
        "readiness": payload["recommendation"].get("readiness_score"),
        "do_tin_cay": payload["recommendation"].get("confidence_score"),
    }

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print("\n=== PNJ SAMPLE RESULT ===", flush=True)
    print(json.dumps(payload["user_experience_summary_vi"], ensure_ascii=False, indent=2), flush=True)
    print(f"\nSaved: {OUT_PATH}", flush=True)
    print(f"Total: {payload['total_seconds']}s all_ok={payload['all_ok']}", flush=True)
    return 0 if payload["all_ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
