from __future__ import annotations

import pandas as pd

from core.engine import _phase_rsi_coherence, detect_market_phase_from_ohlcv


def test_phase_rsi_coherence_flags_divergence() -> None:
    """Trend down under MA20 + RSI still elevated → anomaly clamp (not necessarily RSI=100)."""
    rsi_out, anomaly, note, fail = _phase_rsi_coherence(
        close=90.0,
        ma20=100.0,
        day_change_pct=-2.0,
        rsi14=85.0,
    )
    assert anomaly in (1, 1.0, True)
    assert float(rsi_out) == 50.0
    assert fail is False
    assert "không khớp" in note.lower() or "RSI" in note


def test_phase_marks_extreme_rsi_as_indicator_fail() -> None:
    n = 80
    rows = []
    for i in range(n):
        c = 50.0 + i * 1.5
        rows.append({"open": c - 0.2, "high": c + 0.5, "low": c - 0.5, "close": c, "volume": 1_000_000})
    phase = detect_market_phase_from_ohlcv(pd.DataFrame(rows))
    assert float(phase.metrics.get("rsi14_raw") or 0) >= 99.5
    assert phase.metrics.get("rsi_indicator_fail") is True
    assert float(phase.metrics["rsi14"]) == 50.0
