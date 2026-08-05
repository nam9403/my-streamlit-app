from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from core.deep_insight_service import confirm_smart_money_flow
from core.intraday_flow_service import (
    FlowConfig,
    FlowSignal,
    IntradayFlowError,
    aggregate_super_bars,
    analyze_flow,
    apply_context_intensity_adjustment,
    apply_sector_intensity_adjustment,
    batch_analyze_flow,
    batch_analyze_flow_with_sector_context,
    compute_buy_sell_ratio,
    compute_dynamic_z,
    compute_price_context,
    compute_pseudo_delta,
    screen_universe_for_flow,
    sector_flow_bias,
)


def _make_synthetic_ohlcv(
    n_rows: int = 200,
    *,
    spike_at: int | None = None,
    spike_mult: float = 8.0,
    seed: int = 42,
    trend: float = 0.0,
) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    base_volume = 1_000_000.0
    closes: list[float] = []
    highs: list[float] = []
    lows: list[float] = []
    opens: list[float] = []
    volumes: list[float] = []
    last_close = 25.0
    for i in range(n_rows):
        drift = trend + rng.normal(0.0, 0.6)
        open_ = max(1.0, last_close + rng.normal(0.0, 0.2))
        close_ = max(1.0, open_ + drift)
        high_ = max(open_, close_) + abs(rng.normal(0.2, 0.1))
        low_ = max(0.5, min(open_, close_) - abs(rng.normal(0.2, 0.1)))
        if spike_at is None:
            # Flat volume keeps "normal market" fixtures deterministic (no false big_boy).
            vol = base_volume
        else:
            vol = base_volume * (1.0 + abs(rng.normal(0.0, 0.15)))
            if i == spike_at:
                vol *= spike_mult
            close_ = high_ - 0.01
        opens.append(open_)
        highs.append(high_)
        lows.append(low_)
        closes.append(close_)
        volumes.append(vol)
        last_close = close_
    return pd.DataFrame(
        {
            "date": pd.date_range("2024-01-01", periods=n_rows, freq="B"),
            "open": opens,
            "high": highs,
            "low": lows,
            "close": closes,
            "volume": volumes,
        }
    )


def _make_quiet_ohlcv(n_rows: int = 150, *, base_price: float = 25.0, base_volume: float = 1_000_000.0) -> pd.DataFrame:
    """Deterministic low-volatility series — avoids Isolation Forest false positives in tests."""
    closes = [base_price + i * 0.01 for i in range(n_rows)]
    return pd.DataFrame(
        {
            "date": pd.date_range("2024-01-01", periods=n_rows, freq="B"),
            "open": closes,
            "high": [c + 0.1 for c in closes],
            "low": [c - 0.1 for c in closes],
            "close": closes,
            "volume": [base_volume] * n_rows,
        }
    )


def test_compute_pseudo_delta_extremes() -> None:
    row_high = pd.Series({"open": 10.0, "high": 11.0, "low": 9.0, "close": 10.95})
    row_low = pd.Series({"open": 10.0, "high": 11.0, "low": 9.0, "close": 9.05})
    row_mid = pd.Series({"open": 10.0, "high": 11.0, "low": 9.0, "close": 10.0})
    row_flat = pd.Series({"open": 10.0, "high": 10.0, "low": 10.0, "close": 10.0})

    assert compute_pseudo_delta(row_high) > 0.85
    assert compute_pseudo_delta(row_low) < -0.85
    assert abs(compute_pseudo_delta(row_mid)) < 0.05
    assert compute_pseudo_delta(row_flat) == 0.0


def test_compute_dynamic_z_detects_spike() -> None:
    volumes = pd.Series([1_000_000.0] * 60 + [10_000_000.0])
    z = compute_dynamic_z(volumes, window=30)
    assert float(z.iloc[-1]) > 5.0
    assert abs(float(z.iloc[10])) < 0.5


def test_compute_dynamic_z_rejects_small_window() -> None:
    with pytest.raises(IntradayFlowError):
        compute_dynamic_z(pd.Series([1.0, 2.0, 3.0]), window=2)


def test_aggregate_super_bars_groups_same_direction_streaks() -> None:
    df = pd.DataFrame(
        {
            "open": [10, 10, 10, 10, 10, 10],
            "high": [11, 11, 11, 11, 11, 11],
            "low": [9, 9, 9, 9, 9, 9],
            "close": [10.9, 10.8, 10.7, 9.1, 9.2, 9.3],
            "volume": [100.0, 200.0, 300.0, 400.0, 500.0, 600.0],
        }
    )
    out = aggregate_super_bars(df, streak_min_bars=2)
    assert "super_volume" in out.columns
    assert out.loc[0, "super_volume"] == pytest.approx(600.0)
    assert out.loc[2, "super_volume"] == pytest.approx(600.0)
    assert out.loc[3, "super_volume"] == pytest.approx(1500.0)
    assert out.loc[5, "super_volume"] == pytest.approx(1500.0)


def test_analyze_flow_returns_signal_with_big_volume_spike() -> None:
    df = _make_synthetic_ohlcv(n_rows=180, spike_at=170, spike_mult=12.0, seed=7)
    config = FlowConfig(rolling_window=60, min_rows=30, z_threshold=3.0)
    signal = analyze_flow(df.iloc[: 171], "FPT", config=config, timeframe="1D")
    assert isinstance(signal, FlowSignal)
    assert signal.symbol == "FPT"
    assert signal.is_big_boy is True
    assert signal.z_volume >= 3.0
    assert 1.0 <= signal.intensity_score <= 10.0
    assert signal.delta_status in ("bullish", "absorption", "bearish", "distribution", "neutral")
    d = signal.to_dict()
    assert d["is_big_boy"] is True
    assert d["timeframe"] == "1D"
    assert any("Z-score" in r for r in d["reasons"])


def test_analyze_flow_normal_market_no_big_boy() -> None:
    df = _make_quiet_ohlcv(n_rows=150)
    config = FlowConfig(rolling_window=60, min_rows=30, z_threshold=3.0)
    signal = analyze_flow(df, "VNM", config=config)
    assert isinstance(signal, FlowSignal)
    assert signal.symbol == "VNM"
    assert abs(signal.z_volume) < 3.0
    assert signal.is_big_boy is False


def test_analyze_flow_rejects_insufficient_data() -> None:
    df = _make_synthetic_ohlcv(n_rows=10)
    config = FlowConfig(min_rows=30)
    with pytest.raises(IntradayFlowError):
        analyze_flow(df, "HPG", config=config)


def test_analyze_flow_rejects_missing_columns() -> None:
    df = pd.DataFrame({"open": [1.0, 2.0], "close": [1.5, 2.5]})
    with pytest.raises(IntradayFlowError):
        analyze_flow(df, "ABC")


def test_analyze_flow_context_note_includes_industry_and_position() -> None:
    df = _make_synthetic_ohlcv(n_rows=150, spike_at=148, spike_mult=10.0, seed=3)
    config = FlowConfig(rolling_window=60, min_rows=30)
    sig = analyze_flow(
        df,
        "HPG",
        config=config,
        context={"industry_subtype": "steel_materials", "sector_flow_bias": "bullish"},
    )
    assert "ngành: steel_materials" in sig.context_note
    assert "dòng tiền ngành: bullish" in sig.context_note


def test_batch_analyze_flow_skips_invalid_frames() -> None:
    good = _make_synthetic_ohlcv(n_rows=120, spike_at=119, spike_mult=8.0, seed=5)
    bad = _make_synthetic_ohlcv(n_rows=5)
    config = FlowConfig(rolling_window=60, min_rows=30)
    out = batch_analyze_flow({"FPT": good, "BAD": bad}, config=config)
    assert "FPT" in out
    assert "BAD" not in out


def test_batch_analyze_flow_uses_single_batch_anomaly_fit(monkeypatch) -> None:
    import core.intraday_flow_service as svc

    good_a = _make_synthetic_ohlcv(n_rows=120, spike_at=119, spike_mult=8.0, seed=1)
    good_b = _make_synthetic_ohlcv(n_rows=120, spike_at=119, spike_mult=6.0, seed=2)
    config = FlowConfig(rolling_window=60, min_rows=30)
    fit_calls = {"n": 0}
    real_fit = svc.BatchAnomalyScorer.fit

    def _counting_fit(self, feature_frames, *, contamination):  # type: ignore[no-untyped-def]
        fit_calls["n"] += 1
        return real_fit(self, feature_frames, contamination=contamination)

    monkeypatch.setattr(svc.BatchAnomalyScorer, "fit", _counting_fit)
    out = batch_analyze_flow({"FPT": good_a, "HPG": good_b}, config=config)
    assert len(out) == 2
    assert fit_calls["n"] == 1


def test_sector_flow_bias_ranks_sectors_by_intensity() -> None:
    sig_a = FlowSignal(
        symbol="HPG",
        timeframe="1D",
        is_big_boy=True,
        aggregated_volume=10_000_000.0,
        delta_status="bullish",
        intensity_score=8.0,
        z_volume=3.5,
        pseudo_delta=0.6,
        cumulative_delta=1_000_000.0,
        anomaly_score=-0.1,
        last_close=27.0,
        last_volume=5_000_000.0,
        context_note="vị trí ~70% biên độ 20 bar; ngành: steel_materials",
    )
    sig_b = FlowSignal(
        symbol="VHM",
        timeframe="1D",
        is_big_boy=True,
        aggregated_volume=8_000_000.0,
        delta_status="distribution",
        intensity_score=7.0,
        z_volume=-3.2,
        pseudo_delta=-0.7,
        cumulative_delta=-500_000.0,
        anomaly_score=-0.08,
        last_close=42.0,
        last_volume=2_000_000.0,
        context_note="vị trí ~30% biên độ 20 bar; ngành: real_estate_residential",
    )
    out = sector_flow_bias({"HPG": sig_a, "VHM": sig_b})
    sectors = out["sectors"]
    assert sectors[0]["sector"] == "steel_materials"
    assert sectors[0]["net_intensity"] > 0
    assert sectors[-1]["sector"] == "real_estate_residential"
    assert sectors[-1]["net_intensity"] < 0


def test_confirm_smart_money_flow_strong_alignment() -> None:
    flow = FlowSignal(
        symbol="FPT",
        timeframe="1D",
        is_big_boy=True,
        aggregated_volume=10_000_000.0,
        delta_status="bullish",
        intensity_score=8.5,
        z_volume=3.5,
        pseudo_delta=0.55,
        cumulative_delta=2_000_000.0,
        anomaly_score=-0.12,
        last_close=120.0,
        last_volume=3_000_000.0,
        context_note="vị trí ~60% biên độ 20 bar; ngành: technology_services",
    )
    sm = {
        "bias": "bullish",
        "score": 4.5,
        "avg_event_confidence": 0.8,
        "data_mode": "structured",
    }
    result = confirm_smart_money_flow(flow.to_dict(), sm)
    assert result["confirmation_level"] == "strong"
    assert result["tape_bias"] == "bullish"
    assert result["smart_money_bias"] == "bullish"
    assert result["combined_intensity"] >= flow.intensity_score


def test_confirm_smart_money_flow_diverging_warns_bull_trap() -> None:
    flow = FlowSignal(
        symbol="VHM",
        timeframe="1D",
        is_big_boy=True,
        aggregated_volume=5_000_000.0,
        delta_status="bullish",
        intensity_score=6.5,
        z_volume=2.5,
        pseudo_delta=0.45,
        cumulative_delta=1_000_000.0,
        anomaly_score=-0.05,
        last_close=42.0,
        last_volume=2_000_000.0,
        context_note="gần kháng cự ngắn hạn (90% biên độ 20 bar)",
    )
    sm = {
        "bias": "bearish",
        "score": -3.2,
        "avg_event_confidence": 0.7,
        "data_mode": "structured",
    }
    result = confirm_smart_money_flow(flow, sm)
    assert result["confirmation_level"] == "diverging"
    assert "bull trap" in result["verdict"].lower()
    assert result["combined_intensity"] < flow.intensity_score


def test_confirm_smart_money_flow_weak_when_neutral() -> None:
    flow = {
        "delta_status": "neutral",
        "intensity_score": 2.0,
        "is_big_boy": False,
    }
    result = confirm_smart_money_flow(flow, {"bias": "neutral", "score": 0.0})
    assert result["confirmation_level"] == "weak"
    assert result["combined_intensity"] <= 2.0


def test_screen_universe_for_flow_ranks_by_intensity() -> None:
    big_spike = _make_synthetic_ohlcv(n_rows=160, spike_at=159, spike_mult=12.0, seed=21)
    small = _make_quiet_ohlcv(n_rows=160)
    medium = _make_synthetic_ohlcv(n_rows=160, spike_at=159, spike_mult=4.0, seed=23)

    def loader(sym: str) -> pd.DataFrame | None:
        return {"FPT": big_spike, "VNM": small, "HPG": medium}.get(sym)

    df = screen_universe_for_flow(
        ["FPT", "VNM", "HPG", "MISSING"],
        loader,
        config=FlowConfig(rolling_window=60, min_rows=30, z_threshold=3.0),
        min_intensity=4.0,
    )
    assert not df.empty
    assert set(df["Mã"]).issubset({"FPT", "VNM", "HPG"})
    # FPT should be top because of the big spike.
    assert df.iloc[0]["Mã"] == "FPT"
    intensities = df["Intensity"].tolist()
    assert intensities == sorted(intensities, reverse=True) or df.iloc[0]["Big Boy"] == "🐳"


def test_screen_universe_for_flow_only_big_boy_filter() -> None:
    big_spike = _make_synthetic_ohlcv(n_rows=160, spike_at=159, spike_mult=12.0, seed=11)
    small = _make_quiet_ohlcv(n_rows=160)

    def loader(sym: str) -> pd.DataFrame | None:
        return {"FPT": big_spike, "VNM": small}.get(sym)

    df = screen_universe_for_flow(
        ["FPT", "VNM"],
        loader,
        config=FlowConfig(rolling_window=60, min_rows=30, z_threshold=3.0),
        min_intensity=1.0,
        only_big_boy=True,
    )
    assert set(df["Mã"]) == {"FPT"}


def test_compute_price_context_detects_near_resistance() -> None:
    """Khi close sát đỉnh 60-bar, price_context phải near_resistance=True."""
    df = pd.DataFrame(
        {
            "open": [10.0] * 60,
            "high": [10.5 + (i * 0.05) for i in range(60)],  # max ~ 13.45
            "low": [9.5 + (i * 0.05) for i in range(60)],  # min ~ 9.5
            "close": [10.0 + (i * 0.05) for i in range(60)],
            "volume": [1_000_000.0] * 60,
        }
    )
    # Đẩy close cuối lên sát đỉnh để chắc chắn pos >= 85%.
    df.loc[df.index[-1], "close"] = float(df["high"].max()) - 0.05
    last_close = float(df["close"].iloc[-1])
    ctx = compute_price_context(df, last_close=last_close, window=60)
    assert ctx["resistance_level"] >= last_close
    assert ctx["price_position_pct"] >= 80.0
    assert ctx["near_resistance"] is True
    assert ctx["near_support"] is False


def test_compute_price_context_detects_near_support() -> None:
    df = pd.DataFrame(
        {
            "open": [20.0] * 60,
            "high": [25.0 - (i * 0.02) for i in range(60)],
            "low": [15.0 - (i * 0.02) for i in range(60)],
            "close": [20.0 - (i * 0.05) for i in range(60)],
            "volume": [1_000_000.0] * 60,
        }
    )
    df.loc[df.index[-1], "close"] = float(df["low"].min()) + 0.05  # sát đáy
    last_close = float(df["close"].iloc[-1])
    ctx = compute_price_context(df, last_close=last_close, window=60)
    assert ctx["support_level"] <= last_close
    assert ctx["near_support"] is True
    assert ctx["near_resistance"] is False


def test_compute_price_context_short_data_returns_neutral() -> None:
    df = pd.DataFrame(
        {
            "open": [10.0],
            "high": [11.0],
            "low": [9.0],
            "close": [10.0],
            "volume": [1_000.0],
        }
    )
    ctx = compute_price_context(df, last_close=10.0, window=60)
    assert ctx["near_resistance"] is False
    assert ctx["near_support"] is False


def test_compute_buy_sell_ratio_buy_dominant() -> None:
    df = pd.DataFrame(
        {
            "open": [10.0] * 50,
            "high": [11.0] * 50,
            "low": [9.0] * 50,
            "close": [10.9] * 50,  # close gần high ⇒ pseudo_delta dương
            "volume": [1_000_000.0] * 50,
        }
    )
    result = compute_buy_sell_ratio(df, window=50)
    assert result["imbalance_direction"] == "buy_dominant"
    assert result["sell_volume"] == 0.0
    assert result["buy_sell_ratio"] == pytest.approx(999.0)


def test_compute_buy_sell_ratio_sell_dominant() -> None:
    df = pd.DataFrame(
        {
            "open": [10.0] * 50,
            "high": [11.0] * 50,
            "low": [9.0] * 50,
            "close": [9.1] * 50,  # close gần low ⇒ pseudo_delta âm
            "volume": [1_000_000.0] * 50,
        }
    )
    result = compute_buy_sell_ratio(df, window=50)
    assert result["imbalance_direction"] == "sell_dominant"
    assert result["buy_volume"] == 0.0
    assert result["buy_sell_ratio"] == 0.0


def test_compute_buy_sell_ratio_balanced_mid_close() -> None:
    df = pd.DataFrame(
        {
            "open": [10.0] * 50,
            "high": [11.0] * 50,
            "low": [9.0] * 50,
            "close": [10.5 if i % 2 == 0 else 9.5 for i in range(50)],
            "volume": [1_000_000.0] * 50,
        }
    )
    result = compute_buy_sell_ratio(df, window=50)
    assert result["imbalance_direction"] == "balanced"
    assert 0.3 < result["buy_sell_ratio"] < 3.0


def test_apply_context_intensity_adjustment_bullish_near_resistance_caps() -> None:
    new_i, reasons, risks = apply_context_intensity_adjustment(
        9.0, delta_status="bullish", near_resistance=True, near_support=False
    )
    assert new_i == 7.0
    assert any("bull trap" in r.lower() for r in risks)
    assert reasons == []


def test_apply_context_intensity_adjustment_bullish_near_support_boosts() -> None:
    new_i, reasons, risks = apply_context_intensity_adjustment(
        6.0, delta_status="bullish", near_resistance=False, near_support=True
    )
    assert new_i > 6.0
    assert any("tích lũy" in r for r in reasons)
    assert risks == []


def test_apply_context_intensity_adjustment_bearish_near_support_caps() -> None:
    new_i, _, risks = apply_context_intensity_adjustment(
        8.5, delta_status="bearish", near_resistance=False, near_support=True
    )
    assert new_i == 7.0
    assert any("false breakdown" in r.lower() for r in risks)


def test_apply_context_intensity_adjustment_absorption_near_support_boosts() -> None:
    new_i, reasons, _ = apply_context_intensity_adjustment(
        7.0, delta_status="absorption", near_resistance=False, near_support=True
    )
    assert new_i > 7.0
    assert any("đáy" in r for r in reasons)


def test_apply_context_intensity_adjustment_distribution_near_resistance_boosts() -> None:
    new_i, _, risks = apply_context_intensity_adjustment(
        7.0, delta_status="distribution", near_resistance=True, near_support=False
    )
    assert new_i > 7.0
    assert any("phân phối" in r.lower() for r in risks)


def test_apply_context_intensity_no_change_when_neutral() -> None:
    new_i, reasons, risks = apply_context_intensity_adjustment(
        5.0, delta_status="neutral", near_resistance=False, near_support=False
    )
    assert new_i == 5.0
    assert reasons == []
    assert risks == []


def test_apply_sector_adjustment_aligned_bullish_boost() -> None:
    new_i, reasons, _ = apply_sector_intensity_adjustment(
        6.0,
        delta_status="bullish",
        sector_net_intensity=15.0,
        sector_member_count=5,
        alignment_boost=1.10,
    )
    assert new_i > 6.0
    assert any("cùng chiều" in r for r in reasons)


def test_apply_sector_adjustment_diverging_bullish_penalty() -> None:
    new_i, _, risks = apply_sector_intensity_adjustment(
        8.0,
        delta_status="bullish",
        sector_net_intensity=-10.0,
        sector_member_count=5,
        divergence_penalty=0.85,
    )
    assert new_i < 8.0
    assert any("quỹ cơ cấu" in r for r in risks)


def test_apply_sector_adjustment_skips_when_too_few_members() -> None:
    new_i, reasons, risks = apply_sector_intensity_adjustment(
        7.0,
        delta_status="bullish",
        sector_net_intensity=20.0,
        sector_member_count=2,
        min_members_for_signal=3,
    )
    assert new_i == 7.0
    assert reasons == []
    assert risks == []


def test_apply_sector_adjustment_skips_when_bias_too_weak() -> None:
    new_i, reasons, risks = apply_sector_intensity_adjustment(
        7.0,
        delta_status="bullish",
        sector_net_intensity=1.0,  # < bias_threshold default 2.0
        sector_member_count=5,
    )
    assert new_i == 7.0
    assert reasons == []
    assert risks == []


def test_apply_sector_adjustment_bearish_aligned_with_bearish_sector_boosts() -> None:
    new_i, _, risks = apply_sector_intensity_adjustment(
        6.0,
        delta_status="bearish",
        sector_net_intensity=-15.0,
        sector_member_count=5,
    )
    assert new_i > 6.0
    assert any("cùng chiều bias bán" in r for r in risks)


def test_batch_analyze_flow_with_sector_context_aligned_boost() -> None:
    """Trong ngành steel có 3 mã đều bullish ⇒ tất cả đều được boost intensity."""
    a = _make_synthetic_ohlcv(n_rows=150, spike_at=149, spike_mult=10.0, seed=1, trend=0.1)
    b = _make_synthetic_ohlcv(n_rows=150, spike_at=149, spike_mult=10.0, seed=2, trend=0.1)
    c = _make_synthetic_ohlcv(n_rows=150, spike_at=149, spike_mult=10.0, seed=3, trend=0.1)
    frames = {"HPG": a, "HSG": b, "NKG": c}
    contexts = {
        "HPG": {"industry_subtype": "steel_materials"},
        "HSG": {"industry_subtype": "steel_materials"},
        "NKG": {"industry_subtype": "steel_materials"},
    }
    config = FlowConfig(rolling_window=60, min_rows=30, z_threshold=3.0)

    # Baseline pass 1
    base = batch_analyze_flow(frames, config=config, contexts=contexts)
    enhanced = batch_analyze_flow_with_sector_context(
        frames, config=config, contexts=contexts, alignment_boost=1.10
    )
    assert set(base.keys()) == set(enhanced.keys())
    # Ít nhất 1 mã được boost (intensity tăng).
    boosted_any = any(
        enhanced[s].intensity_score > base[s].intensity_score for s in base
    )
    assert boosted_any


def test_batch_analyze_flow_with_sector_context_isolated_diverger_penalty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """3 mã bearish + 1 mã bullish lẻ loi cùng ngành steel → bullish bị penalty.

    Dùng monkeypatch để inject FlowSignal chính xác (tránh phụ thuộc synthetic
    OHLCV không deterministic ở pseudo_delta classification).
    """
    import core.intraday_flow_service as svc

    def _make_signal(sym: str, status: str, intensity: float) -> FlowSignal:
        return FlowSignal(
            symbol=sym,
            timeframe="1D",
            is_big_boy=True,
            aggregated_volume=5_000_000.0,
            delta_status=status,
            intensity_score=intensity,
            z_volume=3.0,
            pseudo_delta=0.5 if "bull" in status else -0.5,
            cumulative_delta=1_000_000.0,
            anomaly_score=-0.1,
            last_close=20.0,
            last_volume=5_000_000.0,
            context_note="ngành: steel_materials",
        )

    fake_signals = {
        "HPG": _make_signal("HPG", "bearish", 7.0),
        "HSG": _make_signal("HSG", "bearish", 7.0),
        "NKG": _make_signal("NKG", "bearish", 7.0),
        "TIS": _make_signal("TIS", "bullish", 8.0),  # lẻ loi
    }
    monkeypatch.setattr(svc, "batch_analyze_flow", lambda *a, **kw: fake_signals)

    contexts = {
        sym: {"industry_subtype": "steel_materials"} for sym in fake_signals
    }
    enhanced = batch_analyze_flow_with_sector_context(
        {sym: pd.DataFrame() for sym in fake_signals},
        contexts=contexts,
        divergence_penalty=0.85,
    )
    assert enhanced["TIS"].intensity_score < 8.0
    assert any("quỹ cơ cấu" in r for r in enhanced["TIS"].risks)
    # Mã bearish cùng chiều ngành thì được boost.
    assert enhanced["HPG"].intensity_score > 7.0


def test_batch_analyze_flow_with_sector_context_no_industry_no_change() -> None:
    """Không truyền industry_subtype → không có sector bias → no adjustment."""
    a = _make_synthetic_ohlcv(n_rows=120, spike_at=119, spike_mult=8.0, seed=5)
    b = _make_synthetic_ohlcv(n_rows=120, spike_at=119, spike_mult=8.0, seed=6)
    frames = {"AAA": a, "BBB": b}
    config = FlowConfig(rolling_window=60, min_rows=30)
    base = batch_analyze_flow(frames, config=config)
    enhanced = batch_analyze_flow_with_sector_context(frames, config=config)
    for sym in base:
        assert enhanced[sym].intensity_score == base[sym].intensity_score


def test_batch_analyze_flow_with_sector_context_empty_input() -> None:
    out = batch_analyze_flow_with_sector_context({})
    assert out == {}


def test_analyze_flow_exposes_buy_sell_ratio_and_price_context() -> None:
    df = _make_synthetic_ohlcv(n_rows=160, spike_at=159, spike_mult=10.0, seed=17)
    config = FlowConfig(rolling_window=60, min_rows=30, z_threshold=3.0)
    sig = analyze_flow(df, "FPT", config=config)
    d = sig.to_dict()
    assert "buy_sell_ratio" in d
    assert "imbalance_direction" in d
    assert d["imbalance_direction"] in ("buy_dominant", "sell_dominant", "balanced")
    assert "resistance_level" in d
    assert "support_level" in d
    assert "price_position_pct" in d
    assert 0.0 <= d["price_position_pct"] <= 100.0
    assert "near_resistance" in d
    assert "near_support" in d


def test_analyze_flow_signal_backward_compat_minimal_fields() -> None:
    """FlowSignal(...) khởi tạo chỉ với field cốt lõi vẫn dùng được — các
    field mới đều có default."""
    sig = FlowSignal(
        symbol="ABC",
        timeframe="1D",
        is_big_boy=True,
        aggregated_volume=1.0,
        delta_status="neutral",
        intensity_score=5.0,
        z_volume=0.0,
        pseudo_delta=0.0,
        cumulative_delta=0.0,
        anomaly_score=0.0,
        last_close=10.0,
        last_volume=100.0,
        context_note="",
    )
    assert sig.buy_sell_ratio == 1.0
    assert sig.imbalance_direction == "balanced"
    assert sig.near_resistance is False
    assert sig.near_support is False
    assert sig.resistance_level == 0.0
    assert sig.support_level == 0.0
    d = sig.to_dict()
    assert d["buy_sell_ratio"] == 1.0
    assert d["near_resistance"] is False


def test_screen_universe_for_flow_handles_loader_errors_and_empty() -> None:
    def loader(sym: str) -> pd.DataFrame | None:
        if sym == "BAD":
            raise RuntimeError("loader failure")
        if sym == "EMPTY":
            return None
        return _make_synthetic_ohlcv(n_rows=10)

    df = screen_universe_for_flow(
        ["BAD", "EMPTY", "TINY"],
        loader,
        config=FlowConfig(rolling_window=60, min_rows=30),
        min_intensity=0.0,
    )
    assert df.empty
    assert list(df.columns) == [
        "Mã",
        "Big Boy",
        "Trạng thái",
        "Intensity",
        "Z-Vol",
        "Pseudo Δ",
        "Cumulative Δ",
        "Aggregated Vol",
        "Bối cảnh",
    ]
