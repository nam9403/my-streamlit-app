from __future__ import annotations

import pandas as pd

from core.decision_playbook_backtest import PlaybookBacktestConfig
from core.walk_forward_playbook import (
    WalkForwardConfig,
    build_walk_forward_folds,
    evaluate_fold_window,
    run_walk_forward_on_pools,
)


def test_build_walk_forward_folds_expanding() -> None:
    folds = build_walk_forward_folds(
        pd.Timestamp("2019-01-01"),
        pd.Timestamp("2024-01-01"),
        fold_months=6,
        min_train_months=18,
        embargo_days=10,
        rolling=False,
    )
    assert len(folds) >= 3
    assert folds[0]["train_start"] == "2019-01-01"
    # embargo then test
    assert folds[0]["test_start"] > folds[0]["train_end"]


def test_evaluate_fold_window_pass_on_excess() -> None:
    entries = [
        {
            "date": "2023-01-01",
            "fwd_60d_pct": 5.0,
            "excess_60d_pct": 2.0,
            "hit_60d": True,
            "action": "BUY",
        }
        for _ in range(10)
    ]
    watch = [
        {
            "date": "2023-01-01",
            "fwd_60d_pct": 1.0,
            "excess_60d_pct": 0.0,
            "hit_60d": True,
            "action": "WATCH",
        }
        for _ in range(10)
    ]
    ev = evaluate_fold_window(
        entry_rows=entries,
        watch_rows=watch,
        horizons=(60,),
        primary_horizon=60,
        min_test_samples=8,
    )
    assert ev["enough_samples"] is True
    assert ev["fold_pass"] is True


def test_run_walk_forward_locked_smoke() -> None:
    # Synthetic dated armed pool spanning years
    armed = []
    watch = []
    start = pd.Timestamp("2019-06-01")
    for i in range(200):
        d = (start + pd.Timedelta(days=i * 5)).strftime("%Y-%m-%d")
        base = {
            "date": d,
            "action": "BUY",
            "setup": "ARMED",
            "trigger": "READY",
            "phase": "accumulation",
            "rsi": 50.0,
            "mos_proxy": 15.0,
            "regime": "risk_on",
            "pit_ok": True,
            "rev_yoy": 5.0,
            "profit_yoy": 5.0,
            "fwd_20d_pct": 1.0,
            "fwd_60d_pct": 2.0 if i % 3 else -0.5,
            "fwd_90d_pct": 2.5,
            "excess_20d_pct": 0.5,
            "excess_60d_pct": 1.0 if i % 3 else -0.2,
            "excess_90d_pct": 0.3,
            "hit_20d": True,
            "hit_60d": bool(i % 3),
            "hit_90d": True,
        }
        armed.append(base)
        watch.append(
            {
                **base,
                "action": "WATCH",
                "fwd_60d_pct": 0.5,
                "excess_60d_pct": 0.0,
            }
        )
    report = run_walk_forward_on_pools(
        armed_pool=armed,
        watch_control=watch,
        config=WalkForwardConfig(
            mode="locked",
            fold_months=6,
            min_train_months=12,
            embargo_days=5,
            primary_horizon=60,
            min_test_samples=5,
            horizons=(20, 60, 90),
        ).normalize(),
        locked_cfg=PlaybookBacktestConfig(entry_style="pit_quality").normalize(),
    )
    assert report["ok"] is True
    assert report["n_folds"] >= 1
    assert "gate_pass" in report
