from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from core.flow_backtest_service import (
    BacktestConfig,
    aggregate_universe_backtest,
    backtest_flow_signals,
    compute_forward_returns,
    load_recommendation_artifact,
    recommend_min_intensity,
    replay_flow_signals_on_ohlcv,
    save_recommendation_artifact,
    summarize_backtest_by_intensity,
)
from core.intraday_flow_service import FlowConfig


def _ohlcv_with_intermittent_spikes(
    n: int = 300, *, spike_every: int = 25, mult: float = 12.0, seed: int = 11
) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    base = 25_000.0
    rows = []
    last = base
    for i in range(n):
        drift = rng.normal(0.0, 250.0)
        open_ = max(1.0, last + rng.normal(0.0, 100.0))
        close_ = max(1.0, open_ + drift)
        high_ = max(open_, close_) + abs(rng.normal(150.0, 50.0))
        low_ = max(0.5, min(open_, close_) - abs(rng.normal(150.0, 50.0)))
        vol = 1_000_000.0 * (1.0 + abs(rng.normal(0.0, 0.15)))
        if (i + 1) % spike_every == 0:
            vol *= mult
            close_ = high_ - 1.0  # close near high ⇒ bullish bar
        rows.append(
            {
                "date": pd.Timestamp("2024-01-01") + pd.Timedelta(days=i),
                "open": open_,
                "high": high_,
                "low": low_,
                "close": close_,
                "volume": vol,
            }
        )
        last = close_
    return pd.DataFrame(rows)


def _flat_ohlcv(n: int = 200, seed: int = 7) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    base = 25_000.0
    rows = []
    last = base
    for i in range(n):
        drift = rng.normal(0.0, 80.0)
        open_ = max(1.0, last + rng.normal(0.0, 50.0))
        close_ = max(1.0, open_ + drift)
        high_ = max(open_, close_) + abs(rng.normal(50.0, 20.0))
        low_ = max(0.5, min(open_, close_) - abs(rng.normal(50.0, 20.0)))
        vol = 1_000_000.0 * (1.0 + abs(rng.normal(0.0, 0.1)))
        rows.append(
            {
                "date": pd.Timestamp("2024-01-01") + pd.Timedelta(days=i),
                "open": open_,
                "high": high_,
                "low": low_,
                "close": close_,
                "volume": vol,
            }
        )
        last = close_
    return pd.DataFrame(rows)


def test_compute_forward_returns_basic() -> None:
    df = pd.DataFrame({"close": [100.0, 101.0, 105.0, 108.0, 110.0]})
    out = compute_forward_returns(df, signal_index=0, horizons=[1, 3])
    assert abs(out["return_1d"] - 1.0) < 1e-6
    assert abs(out["return_3d"] - 8.0) < 1e-6


def test_compute_forward_returns_returns_none_beyond_data() -> None:
    df = pd.DataFrame({"close": [100.0, 101.0, 105.0]})
    out = compute_forward_returns(df, signal_index=2, horizons=[1, 5])
    assert out["return_1d"] is None
    assert out["return_5d"] is None


def test_compute_forward_returns_handles_missing_close_column() -> None:
    df = pd.DataFrame({"price": [100.0, 101.0]})
    out = compute_forward_returns(df, signal_index=0, horizons=[1])
    assert out["return_1d"] is None


def test_replay_flow_signals_produces_signals_with_dates() -> None:
    df = _ohlcv_with_intermittent_spikes(n=250)
    cfg = BacktestConfig(min_history=120, stride=10, flow_config=FlowConfig(min_rows=30))
    out = replay_flow_signals_on_ohlcv(df, symbol="FPT", config=cfg)
    assert len(out) >= 8
    for row in out:
        assert "signal_index" in row
        assert "signal_date" in row
        assert row["symbol"] == "FPT"
        assert 1.0 <= float(row["intensity_score"]) <= 10.0


def test_replay_flow_skips_when_insufficient_history() -> None:
    df = _ohlcv_with_intermittent_spikes(n=80)
    cfg = BacktestConfig(min_history=120, stride=10)
    out = replay_flow_signals_on_ohlcv(df, symbol="FPT", config=cfg)
    assert out == []


def test_backtest_flow_signals_returns_summary_and_per_signal() -> None:
    df = _ohlcv_with_intermittent_spikes(n=260, spike_every=20, mult=14.0)
    cfg = BacktestConfig(
        min_history=120,
        stride=5,
        horizons=(1, 5),
        intensity_buckets=(4.0, 6.0, 8.0),
        require_big_boy=False,  # giữ tất cả signal để bucket nào cũng có data
    )
    out = backtest_flow_signals(df, symbol="HPG", config=cfg)
    assert out["symbol"] == "HPG"
    assert out["n_signals"] > 0
    assert out["n_replays"] >= out["n_signals"]
    summary = out["summary"]
    assert isinstance(summary, list)
    assert len(summary) == 3  # 3 buckets
    assert all("count" in b for b in summary)
    assert all("hit_rate_1d" in b or b["count"] == 0 for b in summary)
    for sig in out["per_signal"]:
        assert "return_1d" in sig
        assert "return_5d" in sig


def test_backtest_big_boy_filter_keeps_only_flagged_signals() -> None:
    df = _ohlcv_with_intermittent_spikes(n=260, spike_every=20, mult=14.0)
    cfg = BacktestConfig(min_history=120, stride=5, require_big_boy=True)
    out = backtest_flow_signals(df, symbol="VNM", config=cfg)
    assert all(sig.get("is_big_boy") is True for sig in out["per_signal"])


def test_summarize_handles_empty_signals() -> None:
    assert summarize_backtest_by_intensity([], buckets=(4.0, 6.0)) == []


def test_summarize_buckets_split_correctly() -> None:
    rows = [
        {"intensity_score": 3.0, "return_1d": 1.0, "return_5d": 2.0},
        {"intensity_score": 5.5, "return_1d": 2.5, "return_5d": 3.0},
        {"intensity_score": 7.0, "return_1d": 4.0, "return_5d": 5.0},
        {"intensity_score": 8.5, "return_1d": -1.0, "return_5d": 6.0},
        {"intensity_score": 9.5, "return_1d": 3.0, "return_5d": 8.0},
    ]
    summary = summarize_backtest_by_intensity(
        rows, buckets=(4.0, 6.0, 8.0), horizons=(1, 5)
    )
    by_bucket = {b["bucket"]: b for b in summary}
    assert by_bucket["4.0-6.0"]["count"] == 1  # only 5.5
    assert by_bucket["6.0-8.0"]["count"] == 1  # only 7.0
    assert by_bucket[">=8.0"]["count"] == 2  # 8.5 + 9.5
    assert by_bucket[">=8.0"]["avg_return_5d"] == 7.0


def test_summarize_skips_none_returns() -> None:
    rows = [
        {"intensity_score": 7.0, "return_1d": None, "return_5d": 3.0},
        {"intensity_score": 7.5, "return_1d": 1.5, "return_5d": None},
    ]
    summary = summarize_backtest_by_intensity(rows, buckets=(6.0,), horizons=(1, 5))
    bucket = summary[0]
    assert bucket["count"] == 2
    assert bucket["avg_return_1d"] == 1.5
    assert bucket["avg_return_5d"] == 3.0


def test_recommend_min_intensity_prefers_lowest_qualifying_bucket() -> None:
    summary = [
        {"bucket": "4.0-6.0", "intensity_lower": 4.0, "count": 12, "avg_return_5d": 0.5, "hit_rate_5d": 45.0},
        {"bucket": "6.0-8.0", "intensity_lower": 6.0, "count": 8, "avg_return_5d": 2.1, "hit_rate_5d": 62.5},
        {"bucket": ">=8.0", "intensity_lower": 8.0, "count": 4, "avg_return_5d": 3.5, "hit_rate_5d": 75.0},
    ]
    rec = recommend_min_intensity(
        summary, horizon_days=5, min_count=5, min_avg_return_pct=0.0, min_hit_rate_pct=50.0
    )
    assert rec["recommended"] == 6.0
    assert "6.0-8.0" in rec["reason"]


def test_recommend_min_intensity_returns_none_when_no_bucket_qualifies() -> None:
    summary = [
        {"bucket": "4.0-6.0", "intensity_lower": 4.0, "count": 12, "avg_return_5d": -1.0, "hit_rate_5d": 30.0},
    ]
    rec = recommend_min_intensity(summary, horizon_days=5, min_count=5)
    assert rec["recommended"] is None
    assert "không có" in rec["reason"].lower() or "Không có" in rec["reason"]


def test_recommend_min_intensity_filters_low_sample_size() -> None:
    summary = [
        {"bucket": "4.0-6.0", "intensity_lower": 4.0, "count": 1, "avg_return_5d": 10.0, "hit_rate_5d": 100.0},
        {"bucket": "6.0-8.0", "intensity_lower": 6.0, "count": 20, "avg_return_5d": 1.5, "hit_rate_5d": 55.0},
    ]
    rec = recommend_min_intensity(summary, horizon_days=5, min_count=5)
    assert rec["recommended"] == 6.0


def test_aggregate_universe_backtest_pools_signals() -> None:
    per_symbol = {
        "FPT": {
            "per_signal": [
                {"intensity_score": 7.0, "return_5d": 2.0},
                {"intensity_score": 8.0, "return_5d": 4.0},
            ],
        },
        "HPG": {
            "per_signal": [
                {"intensity_score": 6.5, "return_5d": 1.0},
                {"intensity_score": 9.0, "return_5d": 5.0},
            ],
        },
    }
    agg = aggregate_universe_backtest(per_symbol, buckets=(6.0, 8.0), horizons=(5,))
    assert agg["n_symbols"] == 2
    assert agg["n_signals_pooled"] == 4
    summary = agg["summary"]
    assert len(summary) == 2  # 2 buckets


def test_replay_flow_signals_no_lookahead_bias() -> None:
    """At index i, analyze_flow should only see data[:i+1]; the signal value
    at index i must NOT change when we append more bars after i."""
    df = _ohlcv_with_intermittent_spikes(n=300, spike_every=15, mult=10.0)
    cfg = BacktestConfig(min_history=150, stride=1, flow_config=FlowConfig(min_rows=30))
    short = replay_flow_signals_on_ohlcv(df.iloc[:200], symbol="FPT", config=cfg)
    long = replay_flow_signals_on_ohlcv(df.iloc[:280], symbol="FPT", config=cfg)
    short_by_idx = {s["signal_index"]: s for s in short}
    long_by_idx = {s["signal_index"]: s for s in long}
    # Compare signals at indices present in both replays.
    common = set(short_by_idx) & set(long_by_idx)
    assert len(common) >= 10
    for idx in common:
        assert short_by_idx[idx]["intensity_score"] == long_by_idx[idx]["intensity_score"]
        assert short_by_idx[idx]["is_big_boy"] == long_by_idx[idx]["is_big_boy"]


def _ok_recs() -> dict[str, dict[str, object]]:
    return {
        "horizon_1d": {
            "recommended": 7.5,
            "reason": "bucket >=8 hit_rate 60",
            "chosen_bucket": {"bucket": ">=8.0", "count": 8},
        },
        "horizon_5d": {
            "recommended": 6.0,
            "reason": "bucket 6.0-8.0 hit_rate 58",
            "chosen_bucket": {"bucket": "6.0-8.0", "count": 12},
        },
        "horizon_20d": {
            "recommended": None,
            "reason": "không đủ data",
        },
    }


def test_save_recommendation_writes_json_for_chosen_horizon(tmp_path: Path) -> None:
    target = tmp_path / "rec.json"
    out = save_recommendation_artifact(
        _ok_recs(),
        horizon_days=5,
        path=target,
        metadata={"n_symbols": 10},
    )
    assert out == target
    assert target.exists()
    payload = json.loads(target.read_text(encoding="utf-8"))
    assert payload["recommended_min_intensity"] == 6.0
    assert payload["horizon_days"] == 5
    assert payload["n_symbols"] == 10
    assert "all_horizons" in payload


def test_save_recommendation_returns_none_when_horizon_missing(tmp_path: Path) -> None:
    target = tmp_path / "rec.json"
    out = save_recommendation_artifact(_ok_recs(), horizon_days=20, path=target)
    assert out is None
    assert not target.exists()


def test_save_recommendation_returns_none_for_invalid_input(tmp_path: Path) -> None:
    target = tmp_path / "rec.json"
    assert save_recommendation_artifact({}, horizon_days=5, path=target) is None
    assert save_recommendation_artifact({"horizon_5d": "bad"}, horizon_days=5, path=target) is None  # type: ignore[arg-type]


def test_load_recommendation_returns_payload_for_fresh_artifact(tmp_path: Path) -> None:
    target = tmp_path / "rec.json"
    save_recommendation_artifact(_ok_recs(), horizon_days=5, path=target)
    loaded = load_recommendation_artifact(path=target, max_age_days=14)
    assert loaded is not None
    assert loaded["recommended_min_intensity"] == 6.0


def test_load_recommendation_rejects_stale_artifact(tmp_path: Path) -> None:
    target = tmp_path / "rec.json"
    stale_ts = datetime.now(timezone.utc) - timedelta(days=60)
    save_recommendation_artifact(_ok_recs(), horizon_days=5, path=target, now=stale_ts)
    loaded = load_recommendation_artifact(path=target, max_age_days=14)
    assert loaded is None


def test_load_recommendation_returns_none_when_file_missing(tmp_path: Path) -> None:
    assert load_recommendation_artifact(path=tmp_path / "missing.json") is None


def test_load_recommendation_returns_none_for_corrupt_json(tmp_path: Path) -> None:
    bad = tmp_path / "rec.json"
    bad.write_text("{not valid json", encoding="utf-8")
    assert load_recommendation_artifact(path=bad) is None


def test_load_recommendation_returns_none_when_recommended_null(tmp_path: Path) -> None:
    target = tmp_path / "rec.json"
    target.write_text(
        json.dumps({
            "schema_version": 1,
            "generated_at_utc": datetime.now(timezone.utc).isoformat(),
            "recommended_min_intensity": None,
            "horizon_days": 5,
        }),
        encoding="utf-8",
    )
    assert load_recommendation_artifact(path=target) is None


def test_backtest_config_normalize_clamps_values() -> None:
    cfg = BacktestConfig(
        min_history=10_000,
        stride=999,
        horizons=(1, 5, -3, 100),
        intensity_buckets=(0.5, 4.0, 6.0, 11.0),
    ).normalize()
    assert 60 <= cfg.min_history <= 2000
    assert 1 <= cfg.stride <= 50
    assert 100 in cfg.horizons
    assert all(1.0 <= b <= 10.0 for b in cfg.intensity_buckets)
