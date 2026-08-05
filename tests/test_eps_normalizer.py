from __future__ import annotations

from core.eps_normalizer import EPSNormalizer, EPS_ANOMALY_WARNING_VI
from core.valuation import value_investing_summary


def test_normalize_eps_strips_other_income_above_20pct() -> None:
    n = EPSNormalizer()
    # Other income = 30% of pretax → strip after-tax portion from NI
    fin = {
        "net_income": 800.0,
        "profit_before_tax": 1000.0,
        "other_income": 300.0,
        "shares_outstanding": 100.0,
        "industry_cluster": "consumer_retail",
    }
    detail = n.normalize_eps_detail("PNJ", fin)
    assert detail["one_off_adjusted"] is True
    assert detail["eps_anomaly_flag"] is True
    # after_tax_one_off = 300 * (800/1000) = 240 → NI_norm = 560 → EPS = 5.6
    assert detail["normalized_eps"] == 5.6
    assert n.normalize_eps("PNJ", fin) == 5.6


def test_normalize_eps_skips_banks() -> None:
    n = EPSNormalizer()
    fin = {
        "net_income": 800.0,
        "profit_before_tax": 1000.0,
        "other_income": 400.0,
        "shares_outstanding": 100.0,
        "is_bank_sector": True,
    }
    detail = n.normalize_eps_detail("ACB", fin)
    assert detail["one_off_adjusted"] is False
    assert detail["normalized_eps"] == 8.0


def test_pe_sanity_flags_drop_vs_3y() -> None:
    n = EPSNormalizer()
    out = n.pe_sanity_check(
        "QTP",
        current_pe=4.0,
        industry_pe=12.0,
        eps_growth=80.0,
        pe_avg_3y=12.0,
        base_trust_score=90.0,
    )
    assert out["pe_anomaly_flag"] is True
    assert out["data_trust_score"] < 90.0
    assert out["mos_requirement_bump_pct"] >= 10.0
    assert EPS_ANOMALY_WARNING_VI in out["warning_vi"]


def test_valuation_uses_normalized_eps_and_bumps_mos() -> None:
    snap = {
        "symbol": "XYZ",
        "price": 10000.0,
        "eps": 2000.0,  # raw inflated
        "net_income": 800_000_000_000.0,
        "profit_before_tax": 1_000_000_000_000.0,
        "other_income": 300_000_000_000.0,
        "shares_outstanding": 400_000_000.0,  # raw EPS from NI = 2000
        "book_value_per_share": 12000.0,
        "roe": 20.0,
        "debt_to_equity": 0.3,
        "current_ratio": 1.8,
        "growth_rate_pct": 80.0,
        "pe_avg_3y": 18.0,
        "sector_pe_5y_avg": 15.0,
        "industry": "Bán lẻ",
        "industry_cluster": "consumer_retail_transport",
        "industry_subtype": "consumer_retail",
    }
    out = value_investing_summary(snap, include_extensions=False)
    assert out.get("eps_basis_key") == "normalized"
    assert out.get("normalized_eps") is not None
    assert float(out["normalized_eps"]) < float(out["eps"])
    assert out.get("pe_anomaly_flag") is True
    assert float(out.get("mos_requirement_bump_pct") or 0) >= 10.0
    thr = out.get("legend_thresholds") or {}
    # balanced default strong_buy ~18 + bump 12 → ~30
    assert float(thr.get("strong_buy_mos_min") or 0) >= 28.0
    assert "méo mó" in (out.get("eps_pe_anomaly_warning_vi") or out.get("value_trap_warning") or "")
