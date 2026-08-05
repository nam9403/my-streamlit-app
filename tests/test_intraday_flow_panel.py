from __future__ import annotations

from contextlib import contextmanager
from typing import Any

import numpy as np
import pandas as pd

from core.intraday_flow_panel import build_flow_view_model, render_intraday_flow_panel
from core.intraday_flow_service import FlowConfig, FlowSignal


@contextmanager
def _ctx():
    yield


def _columns(spec) -> list[Any]:
    if isinstance(spec, int):
        n = spec
    elif isinstance(spec, list):
        n = len(spec)
    else:
        n = 2
    return [_ctx() for _ in range(max(1, n))]


def _flow_signal(
    *,
    symbol: str = "FPT",
    is_big_boy: bool = True,
    delta_status: str = "bullish",
    intensity: float = 8.0,
) -> FlowSignal:
    return FlowSignal(
        symbol=symbol,
        timeframe="1D",
        is_big_boy=is_big_boy,
        aggregated_volume=10_000_000.0,
        delta_status=delta_status,
        intensity_score=intensity,
        z_volume=3.4,
        pseudo_delta=0.55,
        cumulative_delta=2_000_000.0,
        anomaly_score=-0.1,
        last_close=120.0,
        last_volume=3_000_000.0,
        context_note="vị trí ~60% biên độ 20 bar; ngành: technology_services",
        reasons=["Z-score 3.4σ"],
        risks=[],
    )


def _make_synthetic_ohlcv(n: int = 150, spike_at: int | None = 145) -> pd.DataFrame:
    rng = np.random.default_rng(7)
    base_volume = 1_000_000.0
    closes: list[float] = []
    highs: list[float] = []
    lows: list[float] = []
    opens: list[float] = []
    volumes: list[float] = []
    last = 25.0
    for i in range(n):
        drift = rng.normal(0.0, 0.6)
        open_ = max(1.0, last + rng.normal(0.0, 0.2))
        close_ = max(1.0, open_ + drift)
        high_ = max(open_, close_) + abs(rng.normal(0.2, 0.1))
        low_ = max(0.5, min(open_, close_) - abs(rng.normal(0.2, 0.1)))
        vol = base_volume * (1.0 + abs(rng.normal(0.0, 0.15)))
        if spike_at is not None and i == spike_at:
            vol *= 12.0
            close_ = high_ - 0.01
        opens.append(open_)
        highs.append(high_)
        lows.append(low_)
        closes.append(close_)
        volumes.append(vol)
        last = close_
    return pd.DataFrame(
        {
            "date": pd.date_range("2024-01-01", periods=n, freq="B"),
            "open": opens,
            "high": highs,
            "low": lows,
            "close": closes,
            "volume": volumes,
        }
    )


def test_build_view_model_big_boy_bullish() -> None:
    vm = build_flow_view_model(_flow_signal())
    assert vm["status"] == "ok"
    assert "BIG BOY" in vm["headline_metric"]
    label, kind = vm["delta_badge"]
    assert kind == "success"
    assert "Dòng tiền vào" in label
    assert len(vm["metrics"]) == 3
    assert vm["confirmation_badge"] is None
    assert vm["tier2"] is None


def test_build_view_model_with_smart_money_diverging() -> None:
    sig = _flow_signal(delta_status="bullish")
    sm = {"bias": "bearish", "score": -3.5, "avg_event_confidence": 0.75, "data_mode": "structured"}
    vm = build_flow_view_model(sig, sm)
    assert vm["confirmation_badge"] is not None
    label, kind = vm["confirmation_badge"]
    assert kind == "error"
    assert "NGHỊCH PHA" in label
    assert vm["tier2"]["confirmation_level"] == "diverging"
    assert vm["combined_intensity"] is not None
    assert vm["combined_intensity"] < sig.intensity_score


def test_build_view_model_handles_error() -> None:
    vm = build_flow_view_model(None, None, error="Không đủ dữ liệu")
    assert vm["status"] == "error"
    assert "Không đủ dữ liệu" in vm["error_message"]
    assert vm["metrics"] == []


def test_render_intraday_flow_panel_smoke(monkeypatch) -> None:
    import core.intraday_flow_panel as panel

    captured: dict[str, list[Any]] = {"info": [], "success": [], "error": [], "metric": [], "markdown": [], "caption": []}

    monkeypatch.setattr(panel.st, "markdown", lambda *a, **k: captured["markdown"].append(a))
    monkeypatch.setattr(panel.st, "caption", lambda *a, **k: captured["caption"].append(a))
    monkeypatch.setattr(panel.st, "info", lambda *a, **k: captured["info"].append(a))
    monkeypatch.setattr(panel.st, "success", lambda *a, **k: captured["success"].append(a))
    monkeypatch.setattr(panel.st, "warning", lambda *a, **k: captured["info"].append(a))
    monkeypatch.setattr(panel.st, "error", lambda *a, **k: captured["error"].append(a))
    monkeypatch.setattr(panel.st, "metric", lambda **k: captured["metric"].append(k))
    monkeypatch.setattr(panel.st, "columns", _columns)
    monkeypatch.setattr(panel.st, "expander", lambda *a, **k: _ctx())

    df = _make_synthetic_ohlcv(n=150, spike_at=148)
    vm = render_intraday_flow_panel(
        container=_ctx(),
        symbol="FPT",
        ohlcv=df,
        smart_money_summary={"bias": "bullish", "score": 2.5, "avg_event_confidence": 0.7, "data_mode": "structured"},
        config=FlowConfig(rolling_window=60, min_rows=30),
        context={"industry_subtype": "technology_services"},
        timeframe="1D",
    )
    assert vm["status"] == "ok"
    assert len(captured["metric"]) == 3
    assert any("Dòng tiền lớn" in a[0] for a in captured["markdown"])


def test_render_panel_handles_empty_ohlcv(monkeypatch) -> None:
    import core.intraday_flow_panel as panel

    captured: dict[str, list[Any]] = {"info": [], "markdown": []}

    monkeypatch.setattr(panel.st, "markdown", lambda *a, **k: captured["markdown"].append(a))
    monkeypatch.setattr(panel.st, "info", lambda *a, **k: captured["info"].append(a))
    monkeypatch.setattr(panel.st, "success", lambda *a, **k: None)
    monkeypatch.setattr(panel.st, "error", lambda *a, **k: None)
    monkeypatch.setattr(panel.st, "warning", lambda *a, **k: None)
    monkeypatch.setattr(panel.st, "metric", lambda **k: None)
    monkeypatch.setattr(panel.st, "caption", lambda *a, **k: None)
    monkeypatch.setattr(panel.st, "columns", _columns)
    monkeypatch.setattr(panel.st, "expander", lambda *a, **k: _ctx())

    vm = render_intraday_flow_panel(
        container=_ctx(),
        symbol="ABC",
        ohlcv=None,
        timeframe="1D",
    )
    assert vm["status"] == "error"
    assert captured["info"], "should call st.info with explanatory message"
