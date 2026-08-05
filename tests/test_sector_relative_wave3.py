from __future__ import annotations

from core.decision_playbook import evaluate_thesis
from core.sector_relative import assess_sector_relative, peer_universe


def test_assess_sector_relative_cheap() -> None:
    rows = [
        {"symbol": "A1", "pe": 20.0, "pb": 2.0, "icb_sector": "1000", "industry_subtype": ""},
        {"symbol": "A2", "pe": 22.0, "pb": 2.1, "icb_sector": "1000", "industry_subtype": ""},
        {"symbol": "A3", "pe": 18.0, "pb": 1.9, "icb_sector": "1000", "industry_subtype": ""},
        {"symbol": "A4", "pe": 19.0, "pb": 2.0, "icb_sector": "1000", "industry_subtype": ""},
    ]
    out = assess_sector_relative(symbol="X", pe=12.0, pb=1.2, icb_sector="1000", rows=rows)
    assert out["ok"] is True
    assert out["band"] in ("cheap", "slightly_cheap")
    assert out["thesis_score_nudge"] > 0


def test_peer_universe_falls_back_to_icb() -> None:
    rows = [
        {"symbol": "P1", "pe": 10.0, "pb": 1.0, "icb_sector": "S", "industry_subtype": "banks"},
        {"symbol": "P2", "pe": 11.0, "pb": 1.1, "icb_sector": "S", "industry_subtype": "other"},
        {"symbol": "P3", "pe": 12.0, "pb": 1.2, "icb_sector": "S", "industry_subtype": "other"},
        {"symbol": "P4", "pe": 13.0, "pb": 1.3, "icb_sector": "S", "industry_subtype": "other"},
    ]
    peers = peer_universe(rows, symbol="ME", icb_sector="S", industry_subtype="banks", min_peers=3)
    assert len(peers) >= 3


def test_thesis_eq_high_blocks_attractive() -> None:
    val = {"margin_of_safety_composite_pct": 20.0, "piotroski_score": 7}
    deep = {"earnings_quality": {"warning": True, "severity": "high"}}
    t = evaluate_thesis(val, {"revenue_growth_yoy": 10, "profit_growth_yoy": 10}, deep_insight=deep)
    assert t["attractive"] is False


def test_thesis_sector_relative_nudge() -> None:
    val = {
        "margin_of_safety_composite_pct": 18.0,
        "piotroski_score": 6,
        "sector_relative": {
            "ok": True,
            "band": "cheap",
            "thesis_score_nudge": 8.0,
            "notes_vi": ["Rẻ hơn peer"],
        },
    }
    t = evaluate_thesis(val, {"revenue_growth_yoy": 5, "profit_growth_yoy": 5})
    assert t["score"] >= 48
    assert any("peer" in r.lower() or "Peer" in r or "rẻ" in r.lower() or "Rẻ" in r for r in t["reasons_vi"])
