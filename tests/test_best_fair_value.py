"""Multi-method best fair value selection."""

from __future__ import annotations

from core.valuation import capped_graham_fair, select_best_fair_value, value_investing_summary


def test_capped_graham_respects_price_ceiling() -> None:
    assert capped_graham_fair(200_000.0, 10_000.0) == 16_000.0  # 60% MOS cap
    assert capped_graham_fair(12_000.0, 10_000.0) == 12_000.0
    assert capped_graham_fair(0.0, 10_000.0) == 0.0


def test_select_best_skips_raw_graham_when_suspect() -> None:
    out = select_best_fair_value(
        graham_raw=180_000.0,
        graham_capped=16_000.0,
        pe_fair=50_000.0,
        pb_fair=12_500.0,
        price=10_000.0,
        eps_trusted=False,
        mos_integrity_blocked=True,
        pe_anomaly_flag=True,
        is_bank=False,
    )
    assert out["best_fair_method"] != "graham_raw"
    assert float(out["best_fair_value"] or 0) <= 16_000.0
    assert out["suspect_inputs"] is True
    assert out["methods"]["graham_raw"] == 180_000.0


def test_hii_like_snap_publishes_capped_not_raw_graham() -> None:
    """EPS lệch đơn vị → chuẩn hóa trước Graham; fair công bố hợp lý."""
    snap = {
        "symbol": "HII",
        "price": 12000.0,
        "eps": 8500.0,  # absurd vs price → EY ~70% trước chuẩn hóa
        "pe_ratio": 1.4,
        "book_value_per_share": 15000.0,
        "roe": 18.0,
        "debt_to_equity": 0.4,
        "current_ratio": 1.5,
        "growth_rate_pct": 8.0,
        "industry": "Thép — Công nghiệp",
        "industry_cluster": "industrial_materials",
        "industry_subtype": "materials",
    }
    out = value_investing_summary(snap, include_extensions=False)
    assert out.get("eps_unit_corrected") is True
    eps_g = float(out.get("eps_for_graham") or 0)
    assert 0 < eps_g < 2000.0
    published = float(out.get("composite_target_price") or out.get("best_fair_value") or 0)
    graham = float(out.get("intrinsic_value_graham") or 0)
    assert published > 0
    assert graham > 0
    # Không còn Graham blow-up từ EPS 8500
    assert graham < 50_000.0
    assert abs(float(out.get("margin_of_safety_composite_pct") or 0)) <= 95.0
    assert out.get("mos_integrity_blocked") is False
    assert str(out.get("best_fair_label_vi") or "")
