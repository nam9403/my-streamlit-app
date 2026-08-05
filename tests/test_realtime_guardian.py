from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from core.realtime_guardian import RealtimeGuardian, write_guardian_health_artifact


def _signal(symbol: str = "FPT", f_score: int = 8, mos: float = 22.0, rs: float = 4.0):
    return SimpleNamespace(
        symbol=symbol,
        f_score=f_score,
        mos_pct=mos,
        volume_multiple=1.8,
        relative_strength_pct=rs,
        has_flat_base=True,
        has_vcp=True,
        red_flags=[],
    )


def test_guardian_cooldown_blocks_duplicate_signal(tmp_path: Path) -> None:
    state_path = tmp_path / "guardian_state.json"
    g = RealtimeGuardian(state_path, cooldown_minutes=180)
    sig = _signal()
    first = g.decide(sig)
    assert first.allow_notify is True
    g.mark_notified(sig, first.signal_key, status="sent")
    g.save()

    g2 = RealtimeGuardian(state_path, cooldown_minutes=180)
    second = g2.decide(sig)
    assert second.allow_notify is False
    assert second.reason == "cooldown_active"


def test_guardian_allows_when_signal_changed(tmp_path: Path) -> None:
    state_path = tmp_path / "guardian_state.json"
    g = RealtimeGuardian(state_path, cooldown_minutes=180)
    sig1 = _signal(mos=20.0)
    d1 = g.decide(sig1)
    g.mark_notified(sig1, d1.signal_key, status="sent")
    g.save()

    g2 = RealtimeGuardian(state_path, cooldown_minutes=180)
    sig2 = _signal(mos=25.0)
    d2 = g2.decide(sig2)
    assert d2.allow_notify is True
    assert d2.reason == "signal_changed"


def test_write_guardian_health_artifact(tmp_path: Path) -> None:
    out = tmp_path / "artifacts" / "guardian_health.json"
    write_guardian_health_artifact(out, {"status": "ok", "checked": 12})
    assert out.exists()
    text = out.read_text(encoding="utf-8")
    assert '"status": "ok"' in text
