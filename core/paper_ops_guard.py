"""
Wave 4 — paper operations guard (kill-switch).

Halt new paper LONGs when recent closed performance breaches thresholds.
Does not close existing opens; only blocks new entries.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_STATE_PATH = ROOT / "data" / "runtime" / "paper_ops_guard.json"


@dataclass(frozen=True)
class PaperKillSwitchConfig:
    enabled: bool = True
    consecutive_losses: int = 8
    lookback_closed: int = 20
    min_hit_rate_pct: float = 40.0
    min_avg_realized_pct: float = -1.0  # halt if avg below this over lookback
    min_samples_for_avg_rule: int = 12

    def normalize(self) -> PaperKillSwitchConfig:
        env_dis = str(os.getenv("II_PAPER_KILL_SWITCH", "1")).strip().lower() in ("0", "false", "no", "off")
        return PaperKillSwitchConfig(
            enabled=bool(self.enabled) and not env_dis,
            consecutive_losses=max(3, min(50, int(self.consecutive_losses or 8))),
            lookback_closed=max(5, min(100, int(self.lookback_closed or 20))),
            min_hit_rate_pct=max(0.0, min(100.0, float(self.min_hit_rate_pct))),
            min_avg_realized_pct=float(self.min_avg_realized_pct),
            min_samples_for_avg_rule=max(5, int(self.min_samples_for_avg_rule or 12)),
        )


def _closed_trades_newest_first(ledger: dict[str, Any]) -> list[dict[str, Any]]:
    closed: list[tuple[datetime, dict[str, Any]]] = []
    for t in ledger.get("trades") or []:
        if str(t.get("status") or "").upper() != "CLOSED":
            continue
        raw = str(t.get("closed_at") or "")
        try:
            dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
        except Exception:
            dt = datetime(1970, 1, 1, tzinfo=timezone.utc)
        closed.append((dt, t))
    closed.sort(key=lambda x: x[0], reverse=True)
    return [t for _, t in closed]


def evaluate_paper_kill_switch(
    ledger: dict[str, Any],
    *,
    config: PaperKillSwitchConfig | None = None,
) -> dict[str, Any]:
    cfg = (config or PaperKillSwitchConfig()).normalize()
    closed = _closed_trades_newest_first(ledger)
    reasons: list[str] = []
    consec = 0
    for t in closed:
        hit = int(t.get("direction_hit") or 0)
        if hit == 1:
            break
        consec += 1
    if cfg.enabled and consec >= cfg.consecutive_losses:
        reasons.append(f"consecutive_losses={consec}>={cfg.consecutive_losses}")

    window = closed[: cfg.lookback_closed]
    n = len(window)
    hit_rate = None
    avg_ret = None
    if n > 0:
        hits = sum(int(t.get("direction_hit") or 0) for t in window)
        hit_rate = round(100.0 * hits / n, 2)
        avg_ret = round(sum(float(t.get("realized_pct") or 0.0) for t in window) / n, 3)
        if (
            cfg.enabled
            and n >= cfg.min_samples_for_avg_rule
            and hit_rate is not None
            and avg_ret is not None
            and hit_rate < cfg.min_hit_rate_pct
            and avg_ret < cfg.min_avg_realized_pct
        ):
            reasons.append(
                f"lookback_{n}: hit={hit_rate}%<{cfg.min_hit_rate_pct}% "
                f"and avg={avg_ret}%<{cfg.min_avg_realized_pct}%"
            )

    halt = bool(reasons)
    return {
        "enabled": cfg.enabled,
        "halt_new_opens": halt,
        "reasons": reasons,
        "consecutive_losses": consec,
        "lookback_n": n,
        "lookback_hit_rate_pct": hit_rate,
        "lookback_avg_realized_pct": avg_ret,
        "config": {
            "consecutive_losses": cfg.consecutive_losses,
            "lookback_closed": cfg.lookback_closed,
            "min_hit_rate_pct": cfg.min_hit_rate_pct,
            "min_avg_realized_pct": cfg.min_avg_realized_pct,
            "min_samples_for_avg_rule": cfg.min_samples_for_avg_rule,
        },
        "evaluated_at_utc": datetime.now(timezone.utc).isoformat(),
    }


def persist_guard_state(state: dict[str, Any], path: Path | None = None) -> Path:
    p = path or DEFAULT_STATE_PATH
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    return p


def load_guard_state(path: Path | None = None) -> dict[str, Any]:
    p = path or DEFAULT_STATE_PATH
    if not p.is_file():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}
