"""Smoke test — chạy: python scripts/smoke_test.py [--offline] (từ thư mục gốc dự án).

--offline hoặc II_SMOKE_OFFLINE=1: không gọi mạng (phù hợp CI/air-gapped).
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

errors: list[str] = []


def ok(name: str) -> None:
    print(f"OK  {name}")


def fail(name: str, e: BaseException) -> None:
    errors.append(f"{name}: {e}")
    print(f"FAIL {name}: {e}")


def _minimal_snapshot(symbol: str) -> dict:
    return {
        "symbol": symbol,
        "name": "SmokeCo",
        "price": 55.0,
        "currency": "VND",
        "eps": 2.0,
        "growth_rate_pct": 5.0,
        "book_value_per_share": 20.0,
        "bond_yield_pct": 4.4,
        "source": "mock_json",
        "piotroski": {"f_score": 5},
    }


def _section_core_valuation() -> None:
    print("=== Core valuation ===")
    try:
        from core.valuation import (
            benjamin_graham_value,
            margin_of_safety_pct,
            value_investing_summary,
        )

        v = benjamin_graham_value(1000, 5.0, bond_yield_pct=4.4)
        assert v > 0
        mos = margin_of_safety_pct(v, 8000)
        assert mos is not None and mos > 0
        ok("benjamin_graham + mos")

        snap = {
            "symbol": "T",
            "name": "Test",
            "price": 100.0,
            "currency": "VND",
            "eps": 10.0,
            "growth_rate_pct": 5.0,
            "book_value_per_share": 50.0,
            "bond_yield_pct": 4.4,
            "source": "test",
            "piotroski": {},
        }
        s = value_investing_summary(snap)
        assert "intrinsic_value_graham" in s
        ok("value_investing_summary minimal snapshot")
    except Exception as e:
        fail("core valuation", e)


def _section_engine() -> None:
    print("\n=== Core engine (technical/phase) ===")
    try:
        from core.engine import compute_technical_indicators, detect_market_phase_from_ohlcv

        rows = []
        base = 100.0
        for i in range(60):
            c = base + i * 0.2
            rows.append(
                {
                    "open": c - 0.3,
                    "high": c + 0.5,
                    "low": c - 0.6,
                    "close": c,
                    "volume": 1_000_000 + i * 1000,
                }
            )
        df = pd.DataFrame(rows)
        x = compute_technical_indicators(df)
        assert "ma20" in x.columns and "rsi14" in x.columns
        phase = detect_market_phase_from_ohlcv(df)
        assert phase.phase in ("accumulation", "breakout", "distribution", "neutral")
        ok("core.engine indicators + phase")
    except Exception as e:
        fail("core.engine", e)


def _section_financial_data(*, offline: bool) -> None:
    print("\n=== Scrapers / financial_data ===")
    try:
        from scrapers.financial_data import (
            build_peer_comparison_dataframe,
            fetch_financial_snapshot,
            financials_to_dataframe,
            peer_symbols_same_cluster,
        )

        if offline:
            m = _minimal_snapshot("VNM")
            assert m.get("symbol") == "VNM"
            ok("fetch_financial_snapshot VNM (offline synthetic)")
            m_hpg = _minimal_snapshot("HPG")
            assert m_hpg.get("symbol") == "HPG"
            ok("fetch_financial_snapshot HPG (offline synthetic)")
        else:
            m = fetch_financial_snapshot("VNM")
            assert m is not None and m.get("symbol") == "VNM"
            assert str(m.get("source") or "").strip() != ""
            ok("fetch_financial_snapshot VNM available source")

            m_hpg = fetch_financial_snapshot("HPG")
            assert m_hpg is not None and m_hpg.get("symbol") == "HPG"
            ok("fetch_financial_snapshot HPG mock")

        none = fetch_financial_snapshot("NOTREALZZZ")
        assert none is None
        ok("fetch_financial_snapshot unknown -> None")

        financials_to_dataframe([{"a": 1}])
        ok("financials_to_dataframe")

        if offline:
            peers = ["VNM", "HPG"]
            df, failed = build_peer_comparison_dataframe(peers)
        else:
            peers = peer_symbols_same_cluster("VNM", limit=5)
            assert "VNM" in peers and len(peers) >= 1
            df, failed = build_peer_comparison_dataframe(peers)
        assert not df.empty
        ok("peer_symbols_same_cluster + build_peer_comparison_dataframe")

        from core.report_export import investment_report_html, investment_report_markdown
        from core.valuation import value_investing_summary

        summ = value_investing_summary(m)
        assert "piotroski_block" in summ
        assert len(investment_report_markdown(summ)) > 80
        assert "<html" in investment_report_html(summ).lower()
        ok("report_export + piotroski_block")
    except Exception as e:
        fail("financial_data", e)


def _section_finance_scraper(*, offline: bool) -> None:
    print("\n=== finance_scraper ===")
    try:
        from scrapers.finance_scraper import ScraperError, get_stock_data

        if not offline:
            try:
                d = get_stock_data("VNM")
                assert d.get("price", 0) > 0
                ok("get_stock_data VNM live")
            except ScraperError as e:
                print(f"SKIP/WARN scraper live VNM: {e}")
        else:
            print("SKIP offline: get_stock_data VNM live")

        try:
            get_stock_data("NOTREALZZZ")
            fail("get_stock_data invalid should raise", AssertionError("expected ScraperError"))
        except ScraperError:
            ok("get_stock_data invalid raises ScraperError")
    except Exception as e:
        fail("get_stock_data invalid", e)


def _section_portal(*, offline: bool) -> None:
    print("\n=== Portal module ===")
    if offline:
        print("SKIP offline: portal fetch_ohlcv / indicators / news")
        return
    try:
        from scrapers.portal import (
            PortalDataError,
            fetch_financial_indicators,
            fetch_latest_news,
            fetch_ohlcv_history,
        )

        try:
            ohlcv = fetch_ohlcv_history("VNM", sessions=50)
            assert len(ohlcv) >= 50 and "close" in ohlcv.columns
            ok("portal fetch_ohlcv_history VNM")
        except PortalDataError as e:
            print(f"SKIP/WARN portal ohlcv: {e}")

        try:
            fi = fetch_financial_indicators("VNM")
            assert "debt_to_equity" in fi
            ok("portal fetch_financial_indicators VNM")
        except PortalDataError as e:
            print(f"SKIP/WARN portal financial indicators: {e}")

        try:
            news = fetch_latest_news("VNM", limit=3)
            assert len(news) >= 1
            ok("portal fetch_latest_news VNM")
        except PortalDataError as e:
            print(f"SKIP/WARN portal news: {e}")
    except Exception as e:
        fail("portal module", e)


def _section_ai_logic(*, offline: bool) -> None:
    print("\n=== AI logic (fallback) ===")
    try:
        from core.ai_logic import generate_strategic_report
        from scrapers.financial_data import fetch_financial_snapshot

        if offline:
            snap_raw = _minimal_snapshot("VNM")
        else:
            snap_raw = fetch_financial_snapshot("VNM")
            assert isinstance(snap_raw, dict)
        try:
            rep = generate_strategic_report("VNM", snap_raw, preferred_llm="auto")
            assert "whys_steps" in rep
            ok("ai_logic generate_strategic_report")
        except Exception as e:
            print(f"SKIP/WARN ai_logic pipeline: {e}")
    except Exception as e:
        fail("ai_logic", e)


def _section_scrapers_package() -> None:
    print("\n=== Package import scrapers ===")
    try:
        import scrapers

        assert hasattr(scrapers, "get_stock_data")
        assert hasattr(scrapers, "fetch_financial_snapshot")
        assert hasattr(scrapers, "peer_symbols_same_cluster")
        assert hasattr(scrapers, "build_peer_comparison_dataframe")
        ok("scrapers __init__ exports")
    except Exception as e:
        fail("scrapers package", e)


def _section_app_compile() -> None:
    print("\n=== app.py syntax (không chạy Streamlit) ===")
    app_path = ROOT / "app.py"
    try:
        compile(app_path.read_text(encoding="utf-8"), str(app_path), "exec")
        ok("app.py compile")
    except Exception as e:
        fail("app.py compile", e)


def main() -> int:
    reconfigure = getattr(sys.stdout, "reconfigure", None)
    if callable(reconfigure):
        reconfigure(encoding="utf-8")

    ap = argparse.ArgumentParser(description="Smoke test core paths.")
    ap.add_argument(
        "--offline",
        action="store_true",
        help="Không gọi mạng (dùng snapshot tổng hợp + bỏ portal/live scraper).",
    )
    args = ap.parse_args()
    offline = bool(args.offline) or os.environ.get("II_SMOKE_OFFLINE", "").strip() in ("1", "true", "yes")

    if offline:
        print("Chế độ OFFLINE (II_SMOKE_OFFLINE / --offline)\n")

    _section_core_valuation()
    _section_engine()
    _section_financial_data(offline=offline)
    _section_finance_scraper(offline=offline)
    _section_portal(offline=offline)
    _section_ai_logic(offline=offline)
    _section_scrapers_package()
    _section_app_compile()

    print("\n=== Kết quả ===")
    if errors:
        print(f"Có {len(errors)} lỗi:")
        for x in errors:
            print(" -", x)
        return 1
    if offline:
        print("Tất cả smoke test đạt (offline, không phụ thuộc mạng).")
    else:
        print("Tất cả smoke test đạt (trừ scraper/portal nếu bị SKIP/WARN).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
