"""Guard against Plotly Candlestick hover compatibility regressions."""
from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
from plotly.io import to_json

from core.analysis_chart_panel import render_candlestick_with_intrinsic


def test_candlestick_hoverinfo_with_text_is_valid() -> None:
    df = pd.DataFrame(
        {
            "date": pd.date_range("2026-01-01", periods=3, freq="D"),
            "open": [10.0, 11.0, 12.0],
            "high": [11.0, 12.0, 13.0],
            "low": [9.0, 10.0, 11.0],
            "close": [10.5, 11.5, 12.5],
        }
    )
    hover_text = [
        "O:10.00<br>H:11.00<br>L:9.00<br>C:10.50<br>Biên an toàn hiện tại: 5.0%",
        "O:11.00<br>H:12.00<br>L:10.00<br>C:11.50<br>Biên an toàn hiện tại: 6.0%",
        "O:12.00<br>H:13.00<br>L:11.00<br>C:12.50<br>Biên an toàn hiện tại: 7.0%",
    ]

    trace = go.Candlestick(
        x=df["date"],
        open=df["open"],
        high=df["high"],
        low=df["low"],
        close=df["close"],
        text=hover_text,
        hoverinfo="x+text+name",
        name="Giá thị trường",
    )

    fig = go.Figure(data=[trace])
    assert len(fig.data) == 1
    assert fig.data[0].hoverinfo == "x+text+name"
    assert fig.data[0].text[0].startswith("O:10.00")


def test_candlestick_rsi_path_does_not_emit_pd_na(monkeypatch) -> None:
    """Regression test for Streamlit/Plotly NAType serialization crash."""
    captured = {}

    def fake_plotly_chart(fig, width=None):  # noqa: ANN001, ANN202
        captured["json"] = to_json(fig)

    monkeypatch.setattr("core.analysis_chart_panel.st.plotly_chart", fake_plotly_chart)
    monkeypatch.setattr("core.analysis_chart_panel.st.caption", lambda *args, **kwargs: None)
    monkeypatch.setattr("core.analysis_chart_panel.st.warning", lambda *args, **kwargs: None)

    # Constant close can produce zero down-move windows in RSI path.
    ohlcv = pd.DataFrame(
        {
            "date": pd.date_range("2026-01-01", periods=90, freq="D"),
            "open": [10.0] * 90,
            "high": [10.0] * 90,
            "low": [10.0] * 90,
            "close": [10.0] * 90,
            "volume": [1_000_000] * 90,
        }
    )
    valuation = {"composite_target_price": 12.0}

    render_candlestick_with_intrinsic(ohlcv, valuation, show_rsi=True)
    assert captured.get("json")

