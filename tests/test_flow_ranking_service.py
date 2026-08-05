from __future__ import annotations

import pandas as pd

from core.flow_ranking_service import (
    FlowBoostConfig,
    apply_flow_boost_to_candidates,
    apply_flow_boost_to_dataframe,
    compute_flow_boost,
)
from core.intraday_flow_service import FlowSignal


def _sig(
    symbol: str = "FPT",
    *,
    big: bool = True,
    delta: str = "bullish",
    intensity: float = 7.5,
    z: float = 2.5,
) -> FlowSignal:
    return FlowSignal(
        symbol=symbol,
        timeframe="5m",
        is_big_boy=big,
        aggregated_volume=5_000_000.0,
        delta_status=delta,
        intensity_score=intensity,
        z_volume=z,
        pseudo_delta=0.4,
        cumulative_delta=1.0,
        anomaly_score=-0.1,
        last_close=27_000.0,
        last_volume=5_000_000.0,
        context_note="",
    )


def test_compute_boost_bullish_big_boy_returns_positive() -> None:
    boost, note = compute_flow_boost(_sig(intensity=8.0))
    assert boost > 0
    assert "Big Boy bullish" in note


def test_compute_boost_bearish_big_boy_returns_negative_capped() -> None:
    boost, note = compute_flow_boost(_sig(delta="bearish", intensity=9.0))
    assert boost < 0
    assert boost >= -0.5  # default bearish_cap
    assert "bearish" in note.lower()


def test_compute_boost_below_threshold_returns_zero_for_bullish() -> None:
    boost, _ = compute_flow_boost(_sig(intensity=3.0))
    assert boost == 0.0


def test_compute_boost_mixed_returns_small_positive() -> None:
    boost, note = compute_flow_boost(_sig(delta="mixed", intensity=8.0))
    assert 0 < boost <= 0.5
    assert "mixed" in note.lower()


def test_compute_boost_no_big_boy_high_z_returns_tiny_boost() -> None:
    boost, note = compute_flow_boost(_sig(big=False, delta="neutral", intensity=2.0, z=3.5))
    assert 0 < boost <= 0.2
    assert "Volume" in note


def test_compute_boost_handles_dict_payload() -> None:
    boost, _ = compute_flow_boost(
        {"is_big_boy": True, "delta_status": "bullish", "intensity_score": 8.5, "z_volume": 3.0}
    )
    assert boost > 0


def test_apply_flow_boost_dataframe_reranks_bullish_to_top() -> None:
    df = pd.DataFrame(
        {
            "Mã": ["FPT", "HPG", "VNM"],
            "Hành động hôm nay": ["BUY", "BUY", "BUY"],
            "Confidence %": [70.0, 80.0, 75.0],
        }
    )
    signals = {
        "FPT": _sig("FPT", intensity=9.0, delta="bullish"),
        "HPG": _sig("HPG", intensity=2.0),  # below threshold
        "VNM": _sig("VNM", intensity=8.0, delta="bearish"),
    }
    out = apply_flow_boost_to_dataframe(df, signals)
    assert "Flow boost" in out.columns
    assert "Flow note" in out.columns
    fpt_row = out[out["Mã"] == "FPT"].iloc[0]
    hpg_row = out[out["Mã"] == "HPG"].iloc[0]
    vnm_row = out[out["Mã"] == "VNM"].iloc[0]
    assert fpt_row["Flow boost"] > 0
    assert hpg_row["Flow boost"] == 0
    assert vnm_row["Flow boost"] < 0
    # FPT (boosted) should rank higher than HPG (untouched) despite lower base conf.
    assert out.iloc[0]["Mã"] == "FPT"
    # VNM (penalised) should drop to bottom among same-action group.
    assert out.iloc[-1]["Mã"] == "VNM"


def test_apply_flow_boost_dataframe_is_idempotent() -> None:
    df = pd.DataFrame(
        {"Mã": ["FPT"], "Hành động hôm nay": ["BUY"], "Confidence %": [70.0]}
    )
    signals = {"FPT": _sig(intensity=9.0)}
    once = apply_flow_boost_to_dataframe(df, signals)
    twice = apply_flow_boost_to_dataframe(once, signals)
    assert once["Confidence %"].iloc[0] == twice["Confidence %"].iloc[0]
    assert once["Flow boost"].iloc[0] == twice["Flow boost"].iloc[0]


def test_apply_flow_boost_handles_missing_signal_gracefully() -> None:
    df = pd.DataFrame(
        {"Mã": ["FPT", "HPG"], "Hành động hôm nay": ["BUY", "BUY"], "Confidence %": [70.0, 60.0]}
    )
    out = apply_flow_boost_to_dataframe(df, {"FPT": _sig(intensity=8.0)})
    hpg = out[out["Mã"] == "HPG"].iloc[0]
    assert hpg["Flow boost"] == 0
    assert hpg["Confidence %"] == 60.0


def test_apply_flow_boost_with_empty_signals_returns_original_shape() -> None:
    df = pd.DataFrame(
        {"Mã": ["FPT", "HPG"], "Hành động hôm nay": ["BUY", "BUY"], "Confidence %": [70.0, 80.0]}
    )
    out = apply_flow_boost_to_dataframe(df, None)
    assert list(out["Mã"]) == ["FPT", "HPG"] or list(out["Mã"]) == ["HPG", "FPT"]
    # When signals empty we still re-sort by confidence; ensure no exception.
    assert "Flow boost" in out.columns
    assert (out["Flow boost"] == 0).all()


def test_apply_flow_boost_dataframe_missing_columns_no_op() -> None:
    df = pd.DataFrame({"Symbol": ["FPT"], "Score": [80.0]})
    out = apply_flow_boost_to_dataframe(df, {"FPT": _sig(intensity=8.0)})
    assert "Flow boost" not in out.columns
    pd.testing.assert_frame_equal(df, out)


def test_apply_flow_boost_dataframe_empty_returns_empty() -> None:
    out = apply_flow_boost_to_dataframe(pd.DataFrame(), {"FPT": _sig()})
    assert out.empty


def test_apply_flow_boost_candidates_reranks() -> None:
    rows = [
        {"symbol": "FPT", "confidence": 70.0, "action": "BUY"},
        {"symbol": "HPG", "confidence": 80.0, "action": "BUY"},
    ]
    out = apply_flow_boost_to_candidates(rows, {"FPT": _sig(intensity=9.0)})
    assert out[0]["symbol"] == "FPT"
    assert out[0]["flow_boost"] > 0
    assert "Big Boy" in out[0]["flow_note"]
    assert out[1]["flow_boost"] == 0


def test_apply_flow_boost_candidates_supports_iterable_signals() -> None:
    rows = [
        {"symbol": "FPT", "confidence": 70.0},
        {"symbol": "HPG", "confidence": 60.0},
    ]
    out = apply_flow_boost_to_candidates(
        rows,
        [_sig("FPT", intensity=8.0), _sig("HPG", delta="bearish", intensity=8.0)],
    )
    fpt = next(r for r in out if r["symbol"] == "FPT")
    hpg = next(r for r in out if r["symbol"] == "HPG")
    assert fpt["flow_boost"] > 0
    assert hpg["flow_boost"] < 0


def test_flow_boost_config_normalize_clips_weights() -> None:
    cfg = FlowBoostConfig(
        weight=99.0, bullish_cap=10.0, bearish_cap=-99.0, min_intensity_for_boost=99.0
    ).normalize()
    assert 0.0 <= cfg.weight <= 1.0
    assert cfg.bullish_cap <= 2.0
    assert cfg.bearish_cap >= -1.0
    assert cfg.min_intensity_for_boost <= 10.0


def test_apply_flow_boost_weight_zero_does_not_change_confidence() -> None:
    df = pd.DataFrame(
        {"Mã": ["FPT"], "Hành động hôm nay": ["BUY"], "Confidence %": [70.0]}
    )
    out = apply_flow_boost_to_dataframe(
        df,
        {"FPT": _sig(intensity=9.0)},
        config=FlowBoostConfig(weight=0.0),
    )
    assert out["Confidence %"].iloc[0] == 70.0
    assert out["Flow boost"].iloc[0] > 0
