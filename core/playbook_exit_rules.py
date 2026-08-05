"""
Wave 2 — trade lifecycle exits for playbook entries (research-grade).

Path-aware exits (no look-ahead beyond bar j):
- time_stop: exit at fixed horizon H
- stop_atr: exit if close <= entry * (1 - k*ATR%)
- invalidation: exit if close < invalidation_price (when provided on row)
- giveback: after +M% peak, exit if give back G% from peak

All returns net of round-trip cost at exit.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pandas as pd


@dataclass(frozen=True)
class ExitRuleConfig:
    time_stop_days: int = 40
    atr_stop_mult: float | None = 2.0  # None = disable
    giveback_arm_pct: float | None = None  # default off; enable in bake-off variants
    giveback_pct: float | None = None
    roundtrip_cost_pct: float = 0.50  # VN retail default (fee+tax+slip)
    max_hold_days: int = 90

    def normalize(self) -> ExitRuleConfig:
        return ExitRuleConfig(
            time_stop_days=max(5, min(180, int(self.time_stop_days or 60))),
            atr_stop_mult=(
                None
                if self.atr_stop_mult is None
                else max(0.5, min(5.0, float(self.atr_stop_mult)))
            ),
            giveback_arm_pct=(
                None
                if self.giveback_arm_pct is None
                else max(1.0, float(self.giveback_arm_pct))
            ),
            giveback_pct=(
                None if self.giveback_pct is None else max(0.5, float(self.giveback_pct))
            ),
            roundtrip_cost_pct=max(0.0, min(5.0, float(self.roundtrip_cost_pct or 0.0))),
            max_hold_days=max(5, min(250, int(self.max_hold_days or 90))),
        )


def _atr_pct_at(ohlcv: pd.DataFrame, idx: int, window: int = 14) -> float | None:
    if idx < window or ohlcv is None or getattr(ohlcv, "empty", True):
        return None
    w = ohlcv.iloc[idx - window + 1 : idx + 1]
    high = pd.to_numeric(w["high"], errors="coerce")
    low = pd.to_numeric(w["low"], errors="coerce")
    close = pd.to_numeric(w["close"], errors="coerce")
    prev = close.shift(1)
    tr = pd.concat([(high - low), (high - prev).abs(), (low - prev).abs()], axis=1).max(axis=1)
    atr = float(tr.mean()) if len(tr) else 0.0
    c = float(close.iloc[-1] or 0.0)
    if c <= 0 or atr <= 0:
        return None
    return (atr / c) * 100.0


def simulate_exit_path(
    ohlcv: pd.DataFrame,
    *,
    signal_index: int,
    config: ExitRuleConfig | None = None,
    invalidation_price: float | None = None,
    atr_pct_entry: float | None = None,
) -> dict[str, Any]:
    """
    Walk forward from signal_index+1 … until exit rule fires or max_hold.
    """
    cfg = (config or ExitRuleConfig()).normalize()
    i = int(signal_index)
    if i < 0 or i >= len(ohlcv) - 1:
        return {"ok": False, "reason": "bad_index"}
    entry = float(ohlcv.iloc[i]["close"])
    if entry <= 0:
        return {"ok": False, "reason": "bad_entry"}

    atr_pct = atr_pct_entry
    if atr_pct is None:
        atr_pct = _atr_pct_at(ohlcv, i)
    stop_px = None
    if cfg.atr_stop_mult is not None and atr_pct is not None and atr_pct > 0:
        stop_px = entry * (1.0 - (float(cfg.atr_stop_mult) * float(atr_pct) / 100.0))
    inv = float(invalidation_price) if invalidation_price and float(invalidation_price) > 0 else None

    peak = entry
    armed_giveback = False
    reason = "time_stop"
    exit_idx = min(i + cfg.time_stop_days, i + cfg.max_hold_days, len(ohlcv) - 1)
    end = min(i + cfg.max_hold_days, len(ohlcv) - 1)

    for j in range(i + 1, end + 1):
        px = float(ohlcv.iloc[j]["close"])
        if px > peak:
            peak = px
        if cfg.giveback_arm_pct is not None and ((peak / entry) - 1.0) * 100.0 >= cfg.giveback_arm_pct:
            armed_giveback = True
        # hard stops
        if stop_px is not None and px <= stop_px:
            exit_idx, reason = j, "atr_stop"
            break
        if inv is not None and px < inv:
            exit_idx, reason = j, "invalidation"
            break
        if (
            armed_giveback
            and cfg.giveback_pct is not None
            and peak > 0
            and ((peak - px) / peak) * 100.0 >= cfg.giveback_pct
        ):
            exit_idx, reason = j, "giveback"
            break
        if (j - i) >= cfg.time_stop_days:
            exit_idx, reason = j, "time_stop"
            break
    else:
        exit_idx = end
        reason = "max_hold"

    exit_px = float(ohlcv.iloc[exit_idx]["close"])
    raw = ((exit_px / entry) - 1.0) * 100.0
    net = raw - float(cfg.roundtrip_cost_pct)
    hold = int(exit_idx - i)
    return {
        "ok": True,
        "entry_price": round(entry, 4),
        "exit_price": round(exit_px, 4),
        "hold_days": hold,
        "exit_reason": reason,
        "raw_return_pct": round(raw, 4),
        "net_return_pct": round(net, 4),
        "hit": bool(net > 0),
        "stop_price": round(stop_px, 4) if stop_px else None,
        "peak_price": round(peak, 4),
    }


def summarize_exit_sims(sims: list[dict[str, Any]]) -> dict[str, Any]:
    ok = [s for s in sims if s.get("ok")]
    if not ok:
        return {"samples": 0}
    rets = [float(s["net_return_pct"]) for s in ok]
    hits = [bool(s.get("hit")) for s in ok]
    holds = [int(s.get("hold_days") or 0) for s in ok]
    reasons: dict[str, int] = {}
    for s in ok:
        r = str(s.get("exit_reason") or "?")
        reasons[r] = reasons.get(r, 0) + 1
    return {
        "samples": len(ok),
        "hit_rate_pct": round(100.0 * sum(hits) / len(hits), 2),
        "avg_return_pct": round(sum(rets) / len(rets), 3),
        "median_return_pct": round(float(pd.Series(rets).median()), 3),
        "avg_hold_days": round(sum(holds) / len(holds), 2),
        "exit_reasons": reasons,
    }


def compare_exit_configs(
    ohlcv_by_symbol: dict[str, pd.DataFrame],
    trades: list[dict[str, Any]],
    configs: list[tuple[str, ExitRuleConfig]],
) -> dict[str, Any]:
    """Run each exit config on the same trade list; rank by avg net return."""
    ranked: list[dict[str, Any]] = []
    for label, cfg in configs:
        sims: list[dict[str, Any]] = []
        for t in trades:
            sym = str(t.get("symbol") or "").upper()
            df = ohlcv_by_symbol.get(sym)
            if df is None or getattr(df, "empty", True):
                continue
            idx = t.get("signal_index")
            if idx is None:
                continue
            sims.append(
                simulate_exit_path(
                    df,
                    signal_index=int(idx),
                    config=cfg,
                    invalidation_price=t.get("invalidation_price"),
                    atr_pct_entry=t.get("atr_pct"),
                )
            )
        summary = summarize_exit_sims(sims)
        ranked.append({"label": label, "config": cfg.normalize().__dict__, "summary": summary})
    ranked.sort(key=lambda r: float((r.get("summary") or {}).get("avg_return_pct") or -999), reverse=True)
    return {
        "n_trades_input": len(trades),
        "variants": len(ranked),
        "best": ranked[0] if ranked else {},
        "ranked": ranked,
    }
