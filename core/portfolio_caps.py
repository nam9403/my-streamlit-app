"""
Simple portfolio constraints for paper / backtest (Wave 2.4).

Caps concurrent LONGs, optional sector concentration, and new opens per day.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Any


@dataclass(frozen=True)
class PortfolioCapConfig:
    max_open_positions: int = 8
    max_per_sector: int = 3
    max_new_per_day: int = 3

    def normalize(self) -> PortfolioCapConfig:
        return PortfolioCapConfig(
            max_open_positions=max(1, min(50, int(self.max_open_positions or 8))),
            max_per_sector=max(1, min(20, int(self.max_per_sector or 3))),
            max_new_per_day=max(1, min(20, int(self.max_new_per_day or 3))),
        )


def _as_day(v: Any) -> date | None:
    if v is None:
        return None
    if isinstance(v, date) and not isinstance(v, datetime):
        return v
    try:
        return datetime.fromisoformat(str(v).replace("Z", "+00:00")).date()
    except Exception:
        try:
            return datetime.strptime(str(v)[:10], "%Y-%m-%d").date()
        except Exception:
            return None


def evaluate_portfolio_caps(
    *,
    open_trades: list[dict[str, Any]],
    candidate: dict[str, Any],
    config: PortfolioCapConfig | None = None,
    as_of: date | str | datetime | None = None,
) -> dict[str, Any]:
    """
    Return allow/deny for opening ``candidate`` given current open book.
    """
    cfg = (config or PortfolioCapConfig()).normalize()
    opens = [t for t in open_trades if str(t.get("status") or "").upper() == "OPEN"]
    reasons: list[str] = []

    if len(opens) >= cfg.max_open_positions:
        reasons.append(f"max_open_positions={cfg.max_open_positions}")

    sector = str(candidate.get("sector") or candidate.get("Tiểu ngành") or "").strip()
    if sector:
        same = [
            t
            for t in opens
            if str(t.get("sector") or t.get("Tiểu ngành") or "").strip() == sector
        ]
        if len(same) >= cfg.max_per_sector:
            reasons.append(f"max_per_sector={cfg.max_per_sector} sector={sector}")

    day = _as_day(as_of) or _as_day(candidate.get("opened_at")) or _as_day(candidate.get("date"))
    if day is not None:
        opened_today = 0
        for t in opens:
            od = _as_day(t.get("opened_at")) or _as_day(t.get("date"))
            if od == day:
                opened_today += 1
        # candidate itself not in opens yet
        if opened_today >= cfg.max_new_per_day:
            reasons.append(f"max_new_per_day={cfg.max_new_per_day}")

    return {
        "allow": len(reasons) == 0,
        "reasons": reasons,
        "open_count": len(opens),
        "config": {
            "max_open_positions": cfg.max_open_positions,
            "max_per_sector": cfg.max_per_sector,
            "max_new_per_day": cfg.max_new_per_day,
        },
    }
