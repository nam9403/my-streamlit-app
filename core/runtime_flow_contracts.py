from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class RuntimeFlowConfig:
    watchlist: list[str] = field(default_factory=list)
    ticker: str = ""
    autopilot_mode: bool = True
    profit_focus_mode: bool = True
    autopilot_limit: int = 30
    autopilot_refresh: bool = False
    quick_mode: bool = False
    auto_bg_warm: bool = True
    bg_interval_min: int = 8
    bg_universe_limit: int = 30
    prewarm_now: bool = False
    prewarm_now_async: bool = False
    run_analysis: bool = False

    def symbols(self, watchlist_default: list[str]) -> list[str]:
        return self.watchlist or watchlist_default
