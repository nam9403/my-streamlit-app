from __future__ import annotations

from core.data_trust_score import compute_data_trust_score
from core.financial_enrichment import normalize_eps_in_snapshot, normalize_eps_to_vnd_per_share
from core.valuation import value_investing_summary


def test_normalize_eps_divides_when_yield_too_high() -> None:
    # EPS rõ ràng sai scale (nghìn VND) — P/E nguồn không khớp
    eps, notes = normalize_eps_to_vnd_per_share(10677000.0, 35500.0, pe_ratio=3.57)
    assert eps is not None
    assert eps < 20000.0
    assert notes


def test_normalize_eps_keeps_true_cheap_with_sane_roe() -> None:
    # P/E thấp vừa phải + EY/ROE hợp lý → giữ nguyên
    eps, notes = normalize_eps_to_vnd_per_share(
        3000.0, 35500.0, pe_ratio=11.83, bvps=20000.0, reported_roe=15.0
    )
    assert eps == 3000.0
    assert not notes


def test_normalize_eps_scales_matched_pe_when_roe_absurd() -> None:
    # P/E nguồn khớp EPS thô nhưng ROE(EPS/BV) > 80% → chuẩn hóa đơn vị
    eps, notes = normalize_eps_to_vnd_per_share(
        10677.0, 35500.0, pe_ratio=3.57, bvps=10000.0, reported_roe=25.0
    )
    assert eps is not None
    assert eps < 2500.0
    assert notes
    assert eps / 35500.0 <= 0.15


def test_normalize_eps_in_snapshot_mutates_and_syncs_pe() -> None:
    snap = {
        "symbol": "X",
        "price": 35500.0,
        "eps": 10677.0,
        "pe_ratio": 3.57,
        "book_value_per_share": 10000.0,
        "roe": 25.0,
    }
    out_notes = normalize_eps_in_snapshot(snap)
    assert out_notes
    assert snap.get("eps_normalized") is True
    assert float(snap["eps"]) < float(snap["eps_raw"])
    assert float(snap["eps"]) / 35500.0 <= 0.15
    # P/E cùng nguồn EPS sai → cập nhật theo EPS chuẩn
    assert float(snap.get("pe_ratio") or 0) >= 5.0


def test_valuation_uses_unit_corrected_eps_for_graham() -> None:
    snap = {
        "symbol": "PNJ",
        "price": 35500.0,
        "eps": 10677.0,
        "pe_ratio": 3.57,
        "book_value_per_share": 10000.0,
        "roe": 25.0,
        "debt_to_equity": 0.2,
        "current_ratio": 1.8,
        "growth_rate_pct": 5.0,
        "industry": "Bán lẻ trang sức — Tiêu dùng",
        "industry_cluster": "consumer_retail_transport",
        "industry_subtype": "consumer_retail",
    }
    out = value_investing_summary(snap, include_extensions=False)
    eps_g = float(out.get("eps_for_graham") or 0)
    assert out.get("eps_unit_corrected") is True
    assert eps_g > 0
    assert eps_g < 2500.0
    assert eps_g / 35500.0 <= 0.15
    # Sau chuẩn hóa: không còn block integrity vì EY/P/E đơn vị
    assert out.get("mos_integrity_blocked") is False
    pe = 35500.0 / eps_g
    assert pe >= 5.0


def test_data_trust_score_penalizes_pe_sanity_and_desync() -> None:
    out = compute_data_trust_score(
        snapshot={
            "price": 35500.0,
            "eps": 10.0,
            "price_crosscheck_note_vi": "lệch",
            "pe_sanity_notes": ["P/E bất thường"],
        },
        financials={"source": "fireant", "data_quality_score": 5, "debt_to_equity": 0.3},
        valuation={"pe_sanity_notes": ["P/E bất thường"]},
        ohlcv_trust={"is_stale": False, "age_sec": 100},
        fin_trust={"is_stale": False, "age_sec": 200},
    )
    assert float(out["score"]) < 80.0
    assert out["band"] in ("LOW", "MEDIUM")
    assert out["notes_vi"]
