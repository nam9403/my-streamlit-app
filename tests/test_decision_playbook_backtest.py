from __future__ import annotations

import pandas as pd

from core.decision_playbook_backtest import (
    PlaybookBacktestConfig,
    compute_forward_returns,
    replay_playbook_on_ohlcv,
    summarize_playbook_trades,
    valuation_proxy_from_bar,
)


def _synthetic_ohlcv(n: int = 320) -> pd.DataFrame:
    """Mild trend with a mid stretch of tight range (accumulation-like)."""
    rows = []
    price = 100.0
    for i in range(n):
        if 140 <= i < 200:
            # tight range, low vol
            price = 110.0 + ((i % 3) - 1) * 0.15
            vol = 80_000.0
        elif 200 <= i < 210:
            # breakout-ish
            price = 110.0 + (i - 200) * 1.2
            vol = 250_000.0
        else:
            price = 100.0 + i * 0.05
            vol = 120_000.0
        rows.append(
            {
                "date": pd.Timestamp("2020-01-01") + pd.Timedelta(days=i),
                "open": price * 0.99,
                "high": price * 1.01,
                "low": price * 0.98,
                "close": price,
                "volume": vol,
            }
        )
    return pd.DataFrame(rows)


def test_valuation_proxy_cheaper_below_ma200() -> None:
    cheap = valuation_proxy_from_bar(close=80.0, ma200=100.0, ma50=90.0, rsi14=40.0)
    rich = valuation_proxy_from_bar(close=120.0, ma200=100.0, ma50=110.0, rsi14=70.0)
    assert cheap["margin_of_safety_composite_pct"] > rich["margin_of_safety_composite_pct"]
    assert cheap["valuation_proxy"] is True


def test_valuation_proxy_percentile_blend() -> None:
    closes = pd.Series([100 + i for i in range(60)] + [70.0])  # last bar near lows
    prox = valuation_proxy_from_bar(
        close=70.0, ma200=120.0, ma50=100.0, rsi14=35.0, closes_window=closes
    )
    assert prox["margin_of_safety_composite_pct"] > 5



def test_forward_returns_no_lookahead_math() -> None:
    df = pd.DataFrame(
        {
            "close": [100.0, 101.0, 105.0, 110.0],
            "high": [101, 102, 106, 111],
            "low": [99, 100, 104, 109],
            "open": [100, 101, 105, 110],
            "volume": [1, 1, 1, 1],
        }
    )
    fwd = compute_forward_returns(df, signal_index=0, horizons=(2,), cost_pct=0.0)
    assert fwd["fwd_2d_pct"] == 5.0
    assert fwd["hit_2d"] is True


def test_replay_playbook_smoke() -> None:
    df = _synthetic_ohlcv(300)
    cfg = PlaybookBacktestConfig(min_history=120, stride=10, horizons=(5, 10), roundtrip_cost_pct=0.0)
    res = replay_playbook_on_ohlcv(df, symbol="TEST", benchmark_ohlcv=df, config=cfg)
    assert res["ok"] is True
    assert res["n_replays"] > 0
    assert "summary" in res
    # action counts should include at least WATCH or others
    assert isinstance(res.get("action_counts"), dict)


def test_summarize_empty() -> None:
    s = summarize_playbook_trades([], horizons=(20, 60))
    assert s["samples"] == 0


def test_passes_entry_filters_pit_strict() -> None:
    from core.decision_playbook_backtest import passes_entry_filters

    row = {
        "action": "BUY",
        "setup": "ARMED",
        "trigger": "READY",
        "phase": "accumulation",
        "rsi": 48.0,
        "mos_proxy": 16.0,
        "regime": "risk_on",
        "pit_ok": True,
        "rev_yoy": 8.0,
        "profit_yoy": 5.0,
    }
    cfg = PlaybookBacktestConfig(entry_style="pit_strict").normalize()
    assert passes_entry_filters(row, cfg) is True
    bad = dict(row, action="CONDITIONAL_BUY")
    assert passes_entry_filters(bad, cfg) is False
    weak = dict(row, rev_yoy=-1.0, profit_yoy=10.0)
    assert passes_entry_filters(weak, cfg) is False
