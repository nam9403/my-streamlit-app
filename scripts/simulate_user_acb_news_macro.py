"""
Giả lập người dùng phân tích ACB sau khi tích hợp News/Macro P0.
Chạy: python scripts/simulate_user_acb_news_macro.py
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

TICKER = "ACB"
PROFILE = "growth"
CAPITAL = 100_000_000.0
OUT_PATH = ROOT / "artifacts" / "operations" / "simulate_user_acb_news_macro.json"


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
        "module": "news_macro_service P0",
    }

    # --- 1) Snapshot + valuation (luồng phân tích mã) ---
    def _snap():
        from scrapers.financial_data import fetch_financial_snapshot

        return fetch_financial_snapshot(TICKER)

    snap = _run("1_fetch_financial_snapshot", _snap, stages) or {}
    payload["snapshot"] = {
        "price": snap.get("price"),
        "pe_ratio": snap.get("pe_ratio"),
        "pb_ratio": snap.get("pb_ratio"),
        "roe": snap.get("roe"),
        "debt_to_equity": snap.get("debt_to_equity"),
        "growth_rate_pct": snap.get("growth_rate_pct"),
        "source": snap.get("source"),
        "fundamentals_merge_notes": snap.get("fundamentals_merge_notes"),
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
        "is_bank_sector": val.get("is_bank_sector"),
    }

    # --- 2) News/Macro P0 (lazy theo mã, disk-first) ---
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

    def _micro_disk():
        from core.news_macro_service import get_micro_bundle

        return get_micro_bundle(TICKER, allow_network=False)

    micro_disk = _run("4_get_micro_bundle_disk_only", _micro_disk, stages) or {}
    payload["micro_disk"] = {
        "source": micro_disk.get("source"),
        "news_count": len(micro_disk.get("news") or []),
        "events_hint": micro_disk.get("events_hint") or [],
        "news_sample": [
            {"title": x.get("title"), "source": x.get("source")}
            for x in (micro_disk.get("news") or [])[:3]
        ],
    }

    def _micro_lazy():
        # Giống user mở chi tiết mã — có thể mạng nhưng fail-soft
        from core.news_macro_service import get_micro_bundle

        return get_micro_bundle(TICKER, allow_network=True, news_limit=8)

    micro = _run("5_get_micro_bundle_lazy_network", _micro_lazy, stages) or {}
    payload["micro_lazy"] = {
        "source": micro.get("source"),
        "news_count": len(micro.get("news") or []),
        "events_hint": (micro.get("events_hint") or [])[:5],
        "news_sample": [
            {"title": x.get("title"), "source": x.get("source")}
            for x in (micro.get("news") or [])[:5]
        ],
    }

    def _catalyst():
        from core.news_macro_service import format_news_macro_bias_caption, score_catalyst

        score = score_catalyst(TICKER, allow_network=False)
        caption = format_news_macro_bias_caption(TICKER, allow_network=False)
        return {"score": score, "caption": caption}

    cat = _run("6_score_catalyst_and_caption", _catalyst, stages) or {}
    payload["catalyst"] = cat

    # --- 3) Post-scan boost OFF vs ON (không chạy full autopilot universe) ---
    import pandas as pd

    fake_board = pd.DataFrame(
        {
            "Mã": [TICKER, "FPT", "HPG"],
            "Khuyến nghị": ["WATCH", "BUY", "HOLD"],
            "Expected Return %": [8.0, 12.0, 6.0],
            "MOS%": [float(val.get("margin_of_safety_composite_pct") or 40.0), 15.0, 8.0],
            "Risk % (ước tính)": [12.0, 10.0, 14.0],
            "Trạng thái": ["Sẵn sàng", "Sẵn sàng", "Sẵn sàng"],
        }
    )
    fake_board["__rank"] = fake_board["Khuyến nghị"].map({"BUY": 3, "HOLD": 2, "WATCH": 1, "AVOID": 0}).fillna(0)
    fake_board["__score"] = (
        fake_board["__rank"] * 20
        + fake_board["Expected Return %"] * 0.7
        + fake_board["MOS%"] * 0.3
        - fake_board["Risk % (ước tính)"] * 0.2
    )

    def _boost_off():
        os.environ["II_SCANNER_NEWS_MACRO_BOOST"] = "0"
        from core.news_macro_service import apply_news_macro_boost

        out = apply_news_macro_boost(fake_board.copy())
        return {
            "enabled": False,
            "unchanged": out.equals(fake_board) or "News/Macro Bias" not in out.columns,
            "columns": list(out.columns),
            "acb_score": float(out.loc[out["Mã"] == TICKER, "__score"].iloc[0]),
        }

    boost_off = _run("7_apply_boost_OFF", _boost_off, stages) or {}
    payload["boost_off"] = boost_off

    def _boost_on():
        os.environ["II_SCANNER_NEWS_MACRO_BOOST"] = "1"
        os.environ["II_NEWS_MACRO_SCORE_WEIGHT"] = "1.0"
        from importlib import reload
        import core.news_macro_service as nms

        reload(nms)
        out = nms.apply_news_macro_boost(fake_board.copy())
        row = out.loc[out["Mã"] == TICKER].iloc[0]
        ranked = out.sort_values("__score", ascending=False)[["Mã", "__score", "News/Macro Bias"]]
        return {
            "enabled": True,
            "acb_bias": float(row.get("News/Macro Bias") or 0),
            "acb_score_after": float(row["__score"]),
            "ranking": ranked.to_dict(orient="records"),
        }

    boost_on = _run("8_apply_boost_ON", _boost_on, stages) or {}
    payload["boost_on"] = boost_on

    # --- 4) Strategic report nhẹ (kế thừa tin trong report; không đụng scan loop) ---
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

    report = _run("9_strategic_report_fast", _report, stages) or {}
    rec = report.get("recommendation") if isinstance(report, dict) else {}
    payload["recommendation"] = {
        "final_action": (rec or {}).get("final_action") or report.get("final_action"),
        "confidence_score": (rec or {}).get("confidence_score") or report.get("confidence_score"),
        "analysis_verdict": (rec or {}).get("analysis_verdict"),
        "whys_steps": ((rec or {}).get("whys_steps") or report.get("whys_steps") or [])[:5],
    }

    # Restore default boost off for process hygiene
    os.environ["II_SCANNER_NEWS_MACRO_BOOST"] = "0"

    payload["stages"] = stages
    payload["total_seconds"] = round(sum(s["seconds"] for s in stages), 3)
    payload["all_ok"] = all(s["ok"] for s in stages)
    payload["user_experience_summary_vi"] = {
        "ma": TICKER,
        "ket_luan_dinh_gia": payload["valuation"].get("instant_conclusion"),
        "legend": payload["valuation"].get("legend_scorecard"),
        "news_macro_bias": (cat or {}).get("score"),
        "caption": (cat or {}).get("caption"),
        "khuyen_nghi_report": payload["recommendation"].get("final_action"),
        "boost_mac_dinh": "OFF — ranking cũ không đổi trừ khi bật II_SCANNER_NEWS_MACRO_BOOST=1",
        "ghi_chu": "Micro/Macro P0 không chạy trong vòng quét _one_symbol; lazy theo mã + post-rank opt-in.",
    }

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print("\n=== USER EXPERIENCE ACB + NEWS/MACRO P0 ===", flush=True)
    print(json.dumps(payload["user_experience_summary_vi"], ensure_ascii=False, indent=2), flush=True)
    print(f"\nSaved: {OUT_PATH}", flush=True)
    print(f"Total: {payload['total_seconds']}s all_ok={payload['all_ok']}", flush=True)
    return 0 if payload["all_ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
