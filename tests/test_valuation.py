from __future__ import annotations

from core.valuation import benjamin_graham_value, margin_of_safety_pct, value_investing_summary


def test_graham_and_mos() -> None:
    v = benjamin_graham_value(1000.0, 5.0, bond_yield_pct=4.4)
    assert v > 0
    mos = margin_of_safety_pct(v, 8000.0)
    assert mos is not None and mos > 0


def test_value_investing_summary_includes_data_trust() -> None:
    snap = {
        "symbol": "T",
        "name": "Test",
        "price": 100.0,
        "currency": "VND",
        "eps": 10.0,
        "growth_rate_pct": 5.0,
        "book_value_per_share": 50.0,
        "source": "test",
        "piotroski": {},
        "data_trust": {"fundamentals_source": "test", "price_source": "x", "warnings": []},
    }
    s = value_investing_summary(snap)
    assert "data_trust" in s
    assert s["data_trust"]["fundamentals_source"] == "test"
    assert s.get("growth_rate_pct_source") == "unspecified"
    assert "bond_yield_pct_used" in s
    assert s.get("growth_rate_pct_source_label_vi")
    assert float(s.get("eps_for_graham") or 0) == 10.0
    assert s.get("eps_basis_key") == "reported"


def test_eps_ttm_overrides_reported_for_graham() -> None:
    snap = {
        "symbol": "T",
        "name": "Test",
        "price": 100.0,
        "currency": "VND",
        "eps": 8.0,
        "eps_ttm": 10.0,
        "growth_rate_pct": 5.0,
        "book_value_per_share": 50.0,
        "source": "test",
        "piotroski": {},
        "data_trust": {},
    }
    s = value_investing_summary(snap)
    assert float(s.get("eps_for_graham") or 0) == 10.0
    assert s.get("eps_basis_key") == "ttm"


def test_hybrid_can_infer_de_cr_roe_from_piotroski() -> None:
    snap = {
        "symbol": "T",
        "name": "Test",
        "price": 100.0,
        "currency": "VND",
        "eps": 10.0,
        "growth_rate_pct": 8.0,
        "book_value_per_share": 50.0,
        "source": "test",
        "piotroski": {
            "net_income": 150,
            "total_assets": 1000,
            "long_term_debt": 100,
            "current_assets": 300,
            "current_liabilities": 150,
        },
    }
    s = value_investing_summary(snap)
    assert s["legend_data_ready"]["has_graham_inputs"] is True
    assert float(s.get("debt_to_equity") or 0) > 0
    assert float(s.get("current_ratio") or 0) > 0
    assert float(s.get("roe_5y_avg") or 0) > 0
    assert isinstance(s.get("legend_fallback_notes"), list)


def test_legend_profile_thresholds_exposed() -> None:
    snap = {
        "symbol": "T",
        "name": "Test",
        "price": 80.0,
        "currency": "VND",
        "eps": 10.0,
        "growth_rate_pct": 12.0,
        "book_value_per_share": 50.0,
        "legend_profile": "aggressive",
        "debt_to_equity": 0.3,
        "current_ratio": 2.0,
        "roe": 20.0,
        "source": "test",
        "piotroski": {},
    }
    s = value_investing_summary(snap)
    assert s.get("legend_profile") == "aggressive"
    th = s.get("legend_thresholds") or {}
    assert float(th.get("strong_buy_mos_min") or 0) > 0
    assert float(th.get("max_peg_for_buy") or 0) > 0


def test_legend_threshold_overrides_work() -> None:
    snap = {
        "symbol": "T",
        "name": "Test",
        "price": 80.0,
        "currency": "VND",
        "eps": 10.0,
        "growth_rate_pct": 12.0,
        "book_value_per_share": 50.0,
        "debt_to_equity": 0.3,
        "current_ratio": 2.0,
        "roe": 20.0,
        "legend_profile": "defensive",
        "legend_strong_buy_mos_min": 7.0,
        "legend_max_peg_for_buy": 1.8,
        "source": "test",
    }
    s = value_investing_summary(snap)
    th = s.get("legend_thresholds") or {}
    assert float(th.get("strong_buy_mos_min") or 0) == 7.0
    assert float(th.get("max_peg_for_buy") or 0) == 1.8


def test_graham_filter_manufacturing_keeps_classic_thresholds() -> None:
    from core.valuation import evaluate_graham_filter

    # CR 1.27 fails classic 1.5 for sản xuất; would pass asset-light 1.1
    out = evaluate_graham_filter(
        is_bank=False,
        de=0.4,
        cr=1.27,
        eps=10.0,
        bv=50.0,
        roe=18.0,
        pe=8.0,
        industry_cluster="energy_manufacturing",
        industry_subtype="steel_materials",
        industry_text="Sản xuất thép",
    )
    assert out["pass"] is False
    assert out["group_id"] == "manufacturing_trade"
    assert "CR 1.27 < 1.5" in out["fail_detail_vi"]
    assert "Chuẩn Sản xuất" in out["fail_detail_vi"]


def test_graham_filter_asset_light_relaxes_cr_and_de() -> None:
    from core.valuation import evaluate_graham_filter, value_investing_summary

    ev = evaluate_graham_filter(
        is_bank=False,
        de=0.75,
        cr=1.27,
        eps=10.0,
        bv=50.0,
        roe=18.0,
        pe=12.0,
        industry_cluster="tech_telecom",
        industry_subtype="technology_services",
        industry_text="Công nghệ phần mềm",
    )
    assert ev["pass"] is True
    assert ev["group_id"] == "asset_light"
    assert float(ev["max_debt_to_equity"] or 0) == 0.8
    assert float(ev["min_current_ratio"] or 0) == 1.1

    snap = {
        "symbol": "FPT",
        "price": 70_000.0,
        "eps": 5_000.0,
        "book_value_per_share": 25_000.0,
        "growth_rate_pct": 12.0,
        "debt_to_equity": 0.75,
        "current_ratio": 1.27,
        "roe": 22.0,
        "industry": "Công nghệ — Phần mềm",
        "industry_cluster": "tech_telecom",
        "industry_subtype": "technology_services",
        "source": "test",
    }
    s = value_investing_summary(snap, include_extensions=False)
    assert s["legend_scorecard"]["graham_pass"] is True
    assert s["graham_filter"]["group_id"] == "asset_light"
    assert s["instant_conclusion"] != "Bỏ qua" or "MOS" in str(s.get("instant_conclusion_detail_vi") or "")


def test_graham_filter_fail_exposes_detail_for_tooltip() -> None:
    snap = {
        "symbol": "HPG",
        "price": 25_000.0,
        "eps": 2_000.0,
        "book_value_per_share": 15_000.0,
        "growth_rate_pct": 5.0,
        "debt_to_equity": 0.4,
        "current_ratio": 1.27,
        "roe": 12.0,
        "industry": "Thép — Sản xuất",
        "industry_cluster": "energy_manufacturing",
        "industry_subtype": "steel_materials",
        "source": "test",
    }
    s = value_investing_summary(snap, include_extensions=False)
    assert s["instant_conclusion"] == "Bỏ qua"
    detail = str(s.get("instant_conclusion_detail_vi") or "")
    assert detail.startswith("Bỏ qua:")
    assert "CR 1.27 < 1.5" in detail
    assert "Chuẩn Sản xuất" in detail
    assert s["graham_filter"]["pass"] is False
    assert "CR 1.27 < 1.5" in str(s["value_trap_warning"] or "")


def test_graham_filter_bank_keeps_pe_logic() -> None:
    from core.valuation import evaluate_graham_filter

    fail = evaluate_graham_filter(
        is_bank=True,
        de=8.0,
        cr=1.0,
        eps=4000.0,
        bv=27000.0,
        roe=18.0,
        pe=15.0,
        industry_cluster="financial",
        industry_subtype="bank",
        bank_max_pe=12.0,
    )
    assert fail["pass"] is False
    assert fail["group_id"] == "bank"
    assert "P/E 15.00 > 12" in fail["fail_detail_vi"]
    assert "Chuẩn Ngân hàng" in fail["fail_detail_vi"]

    ok = evaluate_graham_filter(
        is_bank=True,
        de=8.0,
        cr=1.0,
        eps=4000.0,
        bv=27000.0,
        roe=18.0,
        pe=10.0,
        industry_cluster="financial",
        industry_subtype="bank",
        bank_max_pe=12.0,
    )
    assert ok["pass"] is True
    assert ok["has_inputs"] is True