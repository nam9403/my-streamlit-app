from __future__ import annotations

from core.financial_enrichment import merge_indicator_fundamentals_into_snapshot, normalize_roe_to_pct
from core.valuation import value_investing_summary


def test_normalize_roe_ratio_to_pct() -> None:
    assert normalize_roe_to_pct(0.277) == 27.7
    assert normalize_roe_to_pct(27.7) == 27.7
    assert normalize_roe_to_pct(None) is None


def test_merge_indicators_fills_de_roe_growth() -> None:
    snap = {
        "symbol": "QTP",
        "price": 11200.0,
        "eps": 2694.0,
        "book_value_per_share": 13132.0,
        "growth_rate_pct": 0.0,
        "piotroski": {},
    }
    fin = {
        "source": "fireant_test",
        "debt_to_equity": 0.28,
        "revenue_growth_yoy": -6.0,
        "profit_growth_yoy": 14.0,
        "roe": None,
    }
    notes = merge_indicator_fundamentals_into_snapshot(snap, fin)
    assert snap["debt_to_equity"] == 0.28
    assert float(snap["growth_rate_pct"]) != 0.0
    assert float(snap["roe"]) > 15.0  # EPS/BVPS estimate
    assert notes


def test_bank_legend_uses_roe_not_industrial_de() -> None:
    snap = {
        "symbol": "ACB",
        "is_bank": True,
        "price": 22400.0,
        "eps": 3258.0,
        "book_value_per_share": 19225.0,
        "growth_rate_pct": 0.0,
        "debt_to_equity": 14.6,
        "roe": 0.277,
        "piotroski": {},
        "source": "test",
    }
    s = value_investing_summary(snap, include_extensions=False)
    assert s["legend_data_ready"]["has_graham_inputs"] is True
    assert s["legend_scorecard"]["buffett_pass"] is True
    assert float(s["roe_5y_avg"]) > 20.0
    assert s["instant_conclusion"] in ("Theo dõi", "Mua mạnh")
