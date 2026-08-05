from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


def _parse_iso(ts: str) -> datetime | None:
    raw = str(ts or "").strip()
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True)
class GuardianDecision:
    allow_notify: bool
    reason: str
    signal_key: str


class RealtimeGuardian:
    """
    Guardian chống spam cảnh báo real-time:
    - Cooldown theo từng mã
    - Chỉ gửi lại sớm nếu tín hiệu thay đổi đáng kể (signal_key đổi)
    """

    def __init__(self, state_path: Path, cooldown_minutes: int = 180) -> None:
        self.state_path = state_path
        self.cooldown_minutes = max(10, int(cooldown_minutes))
        self._state = self._load_state()

    def _load_state(self) -> dict[str, Any]:
        if not self.state_path.exists():
            return {"signals": {}}
        try:
            payload = json.loads(self.state_path.read_text(encoding="utf-8"))
            if isinstance(payload, dict):
                return payload
        except (OSError, ValueError):
            pass
        return {"signals": {}}

    def save(self) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        self.state_path.write_text(json.dumps(self._state, ensure_ascii=False, indent=2), encoding="utf-8")

    def _build_signal_key(self, signal: Any) -> str:
        parts = [
            str(getattr(signal, "symbol", "")),
            str(int(getattr(signal, "f_score", 0))),
            str(round(float(getattr(signal, "mos_pct", 0.0)), 1)),
            str(round(float(getattr(signal, "volume_multiple", 0.0)), 2)),
            str(round(float(getattr(signal, "relative_strength_pct", 0.0)), 2)),
            "1" if bool(getattr(signal, "has_flat_base", False)) else "0",
            "1" if bool(getattr(signal, "has_vcp", False)) else "0",
            str(len(getattr(signal, "red_flags", []) or [])),
        ]
        return "|".join(parts)

    def decide(self, signal: Any) -> GuardianDecision:
        sym = str(getattr(signal, "symbol", "") or "").strip().upper()
        if not sym:
            return GuardianDecision(False, "invalid_symbol", "")
        signals = self._state.setdefault("signals", {})
        current_key = self._build_signal_key(signal)
        now = _utcnow()
        prev = signals.get(sym) if isinstance(signals, dict) else None
        if not isinstance(prev, dict):
            return GuardianDecision(True, "first_signal", current_key)

        prev_key = str(prev.get("signal_key") or "")
        prev_notified = _parse_iso(str(prev.get("notified_at") or ""))
        if prev_key != current_key:
            return GuardianDecision(True, "signal_changed", current_key)

        if prev_notified is None:
            return GuardianDecision(True, "missing_timestamp", current_key)

        due_at = prev_notified + timedelta(minutes=self.cooldown_minutes)
        if now >= due_at:
            return GuardianDecision(True, "cooldown_elapsed", current_key)
        return GuardianDecision(False, "cooldown_active", current_key)

    def mark_notified(self, signal: Any, signal_key: str, status: str = "sent") -> None:
        sym = str(getattr(signal, "symbol", "") or "").strip().upper()
        if not sym:
            return
        signals = self._state.setdefault("signals", {})
        if not isinstance(signals, dict):
            self._state["signals"] = {}
            signals = self._state["signals"]
        signals[sym] = {
            "signal_key": signal_key,
            "notified_at": _utcnow().isoformat(),
            "status": str(status or "sent"),
        }

    def build_health_summary(self) -> dict[str, Any]:
        signals = self._state.get("signals") if isinstance(self._state, dict) else {}
        n = len(signals) if isinstance(signals, dict) else 0
        return {
            "tracked_symbols": int(n),
            "cooldown_minutes": int(self.cooldown_minutes),
            "generated_at_utc": _utcnow().isoformat(),
        }


def write_guardian_health_artifact(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
