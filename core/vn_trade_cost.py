"""
Vietnam equity trading cost model (retail-oriented defaults).

Round-trip ≈ buy_fee + sell_fee + sell_tax + 2×slippage.
Override via env:
  II_VN_BUY_FEE_PCT, II_VN_SELL_FEE_PCT, II_VN_SELL_TAX_PCT, II_VN_SLIPPAGE_ONE_WAY_PCT
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None or str(raw).strip() == "":
        return float(default)
    try:
        return float(raw)
    except (TypeError, ValueError):
        return float(default)


@dataclass(frozen=True)
class VnTradeCostConfig:
    buy_fee_pct: float = 0.15
    sell_fee_pct: float = 0.15
    sell_tax_pct: float = 0.10  # thuế TNCN bán CK
    slippage_one_way_pct: float = 0.05

    @classmethod
    def from_env(cls) -> VnTradeCostConfig:
        return cls(
            buy_fee_pct=_env_float("II_VN_BUY_FEE_PCT", 0.15),
            sell_fee_pct=_env_float("II_VN_SELL_FEE_PCT", 0.15),
            sell_tax_pct=_env_float("II_VN_SELL_TAX_PCT", 0.10),
            slippage_one_way_pct=_env_float("II_VN_SLIPPAGE_ONE_WAY_PCT", 0.05),
        ).normalize()

    def normalize(self) -> VnTradeCostConfig:
        return VnTradeCostConfig(
            buy_fee_pct=max(0.0, min(2.0, float(self.buy_fee_pct))),
            sell_fee_pct=max(0.0, min(2.0, float(self.sell_fee_pct))),
            sell_tax_pct=max(0.0, min(2.0, float(self.sell_tax_pct))),
            slippage_one_way_pct=max(0.0, min(2.0, float(self.slippage_one_way_pct))),
        )

    def roundtrip_cost_pct(self) -> float:
        c = self.normalize()
        return round(
            c.buy_fee_pct
            + c.sell_fee_pct
            + c.sell_tax_pct
            + 2.0 * c.slippage_one_way_pct,
            4,
        )

    def as_dict(self) -> dict[str, Any]:
        c = self.normalize()
        return {
            "buy_fee_pct": c.buy_fee_pct,
            "sell_fee_pct": c.sell_fee_pct,
            "sell_tax_pct": c.sell_tax_pct,
            "slippage_one_way_pct": c.slippage_one_way_pct,
            "roundtrip_cost_pct": c.roundtrip_cost_pct(),
        }


def default_roundtrip_cost_pct() -> float:
    return VnTradeCostConfig.from_env().roundtrip_cost_pct()
