from __future__ import annotations

import pandas as pd

from core.playbook_exit_rules import ExitRuleConfig, simulate_exit_path, summarize_exit_sims


def _df(n: int = 100) -> pd.DataFrame:
    rows = []
    px = 100.0
    for i in range(n):
        # mild up then drop
        if i < 40:
            px *= 1.002
        else:
            px *= 0.997
        rows.append(
            {
                "date": pd.Timestamp("2020-01-01") + pd.Timedelta(days=i),
                "open": px,
                "high": px * 1.01,
                "low": px * 0.99,
                "close": px,
                "volume": 1e5,
            }
        )
    return pd.DataFrame(rows)


def test_time_stop_exit() -> None:
    df = _df(120)
    sim = simulate_exit_path(df, signal_index=10, config=ExitRuleConfig(time_stop_days=20, atr_stop_mult=None, giveback_arm_pct=None))
    assert sim["ok"] is True
    assert sim["hold_days"] == 20
    assert sim["exit_reason"] == "time_stop"


def test_atr_stop_can_fire() -> None:
    df = _df(80)
    # force collapse after entry
    df.loc[15:, "close"] = 50.0
    df.loc[15:, "low"] = 49.0
    sim = simulate_exit_path(
        df,
        signal_index=10,
        config=ExitRuleConfig(time_stop_days=60, atr_stop_mult=1.0, giveback_arm_pct=None),
        atr_pct_entry=5.0,
    )
    assert sim["ok"] is True
    assert sim["exit_reason"] == "atr_stop"


def test_summarize_exit_sims() -> None:
    s = summarize_exit_sims(
        [
            {"ok": True, "net_return_pct": 2.0, "hit": True, "hold_days": 10, "exit_reason": "time_stop"},
            {"ok": True, "net_return_pct": -1.0, "hit": False, "hold_days": 5, "exit_reason": "atr_stop"},
        ]
    )
    assert s["samples"] == 2
    assert s["hit_rate_pct"] == 50.0
