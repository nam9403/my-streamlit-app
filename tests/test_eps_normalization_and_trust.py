from __future__ import annotations

from core.data_trust_score import compute_data_trust_score
from core.financial_enrichment import normalize_eps_in_snapshot, normalize_eps_to_vnd_per_share


def test_normalize_eps_divides_when_yield_too_high() -> None:
    # EPS rõ ràng sai scale (nghìn VND) — P/E nguồn không khớp
    eps, notes = normalize_eps_to_vnd_per_share(10677000.0, 35500.0, pe_ratio=3.57)
    assert eps is not None
    assert eps < 20000.0
    assert notes


def test_normalize_eps_keeps_consistent_low_pe() -> None:
    # P/E thấp thật — EPS/price cao nhưng P/E nguồn khớp → không scale
    eps, notes = normalize_eps_to_vnd_per_share(10677.0, 35500.0, pe_ratio=3.57)
    assert eps == 10677.0
    assert not notes


def test_normalize_eps_in_snapshot_mutates() -> None:
    snap = {"symbol": "X", "price": 35500.0, "eps": 10677000.0, "pe_ratio": 50.0}
    out_notes = normalize_eps_in_snapshot(snap)
    assert snap.get("eps_normalized") is True
    assert float(snap["eps"]) < float(snap["eps_raw"])
    assert out_notes


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
