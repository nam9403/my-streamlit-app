from __future__ import annotations

from core.portfolio_caps import PortfolioCapConfig, evaluate_portfolio_caps
from core.vn_trade_cost import VnTradeCostConfig, default_roundtrip_cost_pct


def test_vn_roundtrip_default() -> None:
    cfg = VnTradeCostConfig().normalize()
    # 0.15+0.15+0.10+2*0.05 = 0.50
    assert abs(cfg.roundtrip_cost_pct() - 0.5) < 1e-9
    assert default_roundtrip_cost_pct() >= 0.3


def test_portfolio_max_open() -> None:
    opens = [{"status": "OPEN", "symbol": f"S{i}", "sector": "A"} for i in range(8)]
    gate = evaluate_portfolio_caps(
        open_trades=opens,
        candidate={"symbol": "NEW", "sector": "B"},
        config=PortfolioCapConfig(max_open_positions=8, max_per_sector=5, max_new_per_day=5),
    )
    assert gate["allow"] is False
    assert any("max_open_positions" in r for r in gate["reasons"])


def test_portfolio_sector_cap() -> None:
    opens = [
        {"status": "OPEN", "symbol": "A1", "sector": "Bank", "opened_at": "2026-01-01"},
        {"status": "OPEN", "symbol": "A2", "sector": "Bank", "opened_at": "2026-01-01"},
        {"status": "OPEN", "symbol": "A3", "sector": "Bank", "opened_at": "2026-01-01"},
    ]
    gate = evaluate_portfolio_caps(
        open_trades=opens,
        candidate={"symbol": "A4", "sector": "Bank", "opened_at": "2026-01-02"},
        config=PortfolioCapConfig(max_open_positions=10, max_per_sector=3, max_new_per_day=5),
        as_of="2026-01-02",
    )
    assert gate["allow"] is False
    assert any("max_per_sector" in r for r in gate["reasons"])
