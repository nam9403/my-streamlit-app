from __future__ import annotations

from pathlib import Path

from core.intraday_flow_alert_service import (
    FlowAlertDecision,
    build_alert_payload,
    build_flow_signal_key,
    evaluate_flow_alerts,
    mark_flow_alert_dispatched,
    render_alert_message_vi,
)
from core.intraday_flow_service import FlowSignal
from core.realtime_guardian import RealtimeGuardian


def _signal(
    *,
    symbol: str = "FPT",
    is_big_boy: bool = True,
    intensity: float = 8.0,
    delta_status: str = "bullish",
    z_volume: float = 3.4,
    pseudo_delta: float = 0.55,
    last_close: float = 120.0,
    resistance_level: float = 0.0,
    support_level: float = 0.0,
    near_resistance: bool = False,
    near_support: bool = False,
    buy_sell_ratio: float = 1.0,
    imbalance_direction: str = "balanced",
) -> FlowSignal:
    return FlowSignal(
        symbol=symbol,
        timeframe="1D",
        is_big_boy=is_big_boy,
        aggregated_volume=10_000_000.0,
        delta_status=delta_status,
        intensity_score=intensity,
        z_volume=z_volume,
        pseudo_delta=pseudo_delta,
        cumulative_delta=2_000_000.0,
        anomaly_score=-0.1,
        last_close=last_close,
        last_volume=3_000_000.0,
        context_note="ngành: technology_services",
        reasons=["Volume Z-score 3.4σ"],
        risks=[],
        resistance_level=resistance_level,
        support_level=support_level,
        near_resistance=near_resistance,
        near_support=near_support,
        buy_sell_ratio=buy_sell_ratio,
        imbalance_direction=imbalance_direction,
    )


def test_build_flow_signal_key_changes_with_status() -> None:
    sig1 = _signal(delta_status="bullish")
    sig2 = _signal(delta_status="bearish")
    sig3 = _signal(delta_status="bullish", intensity=8.2)
    sig4 = _signal(delta_status="bullish", intensity=5.0)
    k1 = build_flow_signal_key(sig1)
    k2 = build_flow_signal_key(sig2)
    k3 = build_flow_signal_key(sig3)
    k4 = build_flow_signal_key(sig4)
    assert k1 != k2
    assert k1 == k3
    assert k1 != k4


def test_build_alert_payload_carries_vi_headline() -> None:
    payload = build_alert_payload(_signal(delta_status="absorption"))
    assert payload.symbol == "FPT"
    assert payload.is_big_boy is True
    assert "Hấp thụ" in payload.headline
    d = payload.to_dict()
    assert d["intensity_score"] == 8.0
    assert d["delta_status"] == "absorption"


def test_evaluate_flow_alerts_filters_and_calls_guardian(tmp_path: Path) -> None:
    state = tmp_path / "guardian.json"
    guardian = RealtimeGuardian(state, cooldown_minutes=120)
    sig_buy = _signal(symbol="FPT", intensity=8.0, delta_status="bullish")
    sig_low = _signal(symbol="HPG", intensity=4.5, delta_status="bullish")
    sig_neutral = _signal(symbol="VNM", intensity=7.0, delta_status="neutral")
    sig_not_big = _signal(symbol="VIC", is_big_boy=False, intensity=7.0)

    decisions = evaluate_flow_alerts(
        {"FPT": sig_buy, "HPG": sig_low, "VNM": sig_neutral, "VIC": sig_not_big},
        guardian,
        min_intensity=6.0,
        require_big_boy=True,
    )
    assert len(decisions) == 1
    only = decisions[0]
    assert only.payload.symbol == "FPT"
    assert only.allow_notify is True
    assert only.reason == "first_signal"


def test_cooldown_blocks_resend_same_signal(tmp_path: Path) -> None:
    state = tmp_path / "guardian.json"
    guardian = RealtimeGuardian(state, cooldown_minutes=120)
    sig = _signal()
    first = evaluate_flow_alerts({"FPT": sig}, guardian, min_intensity=6.0)
    assert len(first) == 1
    assert first[0].allow_notify is True
    mark_flow_alert_dispatched(guardian, first[0])
    guardian.save()

    guardian2 = RealtimeGuardian(state, cooldown_minutes=120)
    second = evaluate_flow_alerts({"FPT": sig}, guardian2, min_intensity=6.0)
    assert len(second) == 1
    assert second[0].allow_notify is False
    assert second[0].reason == "cooldown_active"


def test_signal_changed_allows_resend(tmp_path: Path) -> None:
    state = tmp_path / "guardian.json"
    guardian = RealtimeGuardian(state, cooldown_minutes=120)
    sig1 = _signal(delta_status="bullish")
    sig2 = _signal(delta_status="distribution")

    d1 = evaluate_flow_alerts({"FPT": sig1}, guardian, min_intensity=6.0, skip_delta_statuses=())
    assert d1[0].allow_notify is True
    mark_flow_alert_dispatched(guardian, d1[0])
    guardian.save()

    guardian2 = RealtimeGuardian(state, cooldown_minutes=120)
    d2 = evaluate_flow_alerts({"FPT": sig2}, guardian2, min_intensity=6.0, skip_delta_statuses=())
    assert d2[0].allow_notify is True
    assert d2[0].reason == "signal_changed"


def test_render_alert_message_includes_big_boy_tag() -> None:
    payload = build_alert_payload(_signal(delta_status="bullish"))
    text = render_alert_message_vi(payload)
    assert "[BIG BOY]" in text
    assert "FPT" in text
    assert "Intensity" in text


def test_evaluate_handles_list_input(tmp_path: Path) -> None:
    state = tmp_path / "guardian.json"
    guardian = RealtimeGuardian(state, cooldown_minutes=60)
    sigs = [_signal(symbol="FPT"), _signal(symbol="HPG", intensity=7.0)]
    decisions = evaluate_flow_alerts(sigs, guardian, min_intensity=6.0)
    symbols = {d.payload.symbol for d in decisions}
    assert symbols == {"FPT", "HPG"}
    assert all(isinstance(d, FlowAlertDecision) for d in decisions)


def test_build_alert_payload_suggests_buy_now_near_support() -> None:
    """Bullish + sát hỗ trợ ⇒ action = BUY_NOW, entry quanh giá hiện tại."""
    sig = _signal(
        delta_status="bullish",
        last_close=27_000.0,
        support_level=26_500.0,
        resistance_level=30_000.0,
        near_support=True,
    )
    payload = build_alert_payload(sig)
    assert payload.entry_action == "BUY_NOW"
    assert payload.suggested_entry_low <= 27_000.0
    assert payload.suggested_entry_high >= 27_000.0
    assert payload.suggested_stop_loss > 0
    assert payload.suggested_stop_loss < payload.suggested_entry_low


def test_build_alert_payload_suggests_wait_breakout_near_resistance() -> None:
    """Bullish sát kháng cự ⇒ action = WAIT_BREAKOUT, entry > resistance."""
    sig = _signal(
        delta_status="bullish",
        last_close=29_800.0,
        support_level=26_500.0,
        resistance_level=30_000.0,
        near_resistance=True,
    )
    payload = build_alert_payload(sig)
    assert payload.entry_action == "WAIT_BREAKOUT"
    assert payload.suggested_entry_low > 30_000.0


def test_build_alert_payload_avoids_bearish() -> None:
    """Bearish ⇒ action = AVOID, không gợi entry."""
    sig = _signal(
        delta_status="bearish",
        last_close=29_800.0,
    )
    payload = build_alert_payload(sig)
    assert payload.entry_action == "AVOID"
    assert payload.suggested_entry_low == 0.0
    assert payload.suggested_entry_high == 0.0


def test_render_alert_message_includes_price_level_and_entry() -> None:
    sig = _signal(
        delta_status="bullish",
        last_close=27_000.0,
        support_level=26_500.0,
        resistance_level=30_000.0,
        near_support=True,
        buy_sell_ratio=3.5,
        imbalance_direction="buy_dominant",
    )
    payload = build_alert_payload(sig)
    text = render_alert_message_vi(payload)
    assert "Giá:" in text
    assert "Hỗ trợ" in text
    assert "Kháng cự" in text
    assert "MUA NGAY" in text
    assert "Vùng entry" in text
    assert "SL" in text
    assert "buy/sell" in text


def test_render_alert_message_avoid_skips_entry_zone() -> None:
    sig = _signal(
        delta_status="bearish",
        last_close=27_000.0,
        support_level=25_000.0,
        resistance_level=30_000.0,
    )
    payload = build_alert_payload(sig)
    text = render_alert_message_vi(payload)
    assert "TRÁNH" in text
    assert "Vùng entry" not in text


def test_render_alert_message_omits_sell_ratio_when_balanced() -> None:
    payload = build_alert_payload(_signal(delta_status="bullish"))
    text = render_alert_message_vi(payload)
    assert "buy/sell" not in text  # balanced ⇒ không show


def test_payload_to_dict_includes_new_fields() -> None:
    payload = build_alert_payload(
        _signal(
            delta_status="bullish",
            last_close=27_000.0,
            support_level=26_500.0,
            near_support=True,
        )
    )
    d = payload.to_dict()
    assert d["last_close"] == 27_000.0
    assert d["support_level"] == 26_500.0
    assert d["entry_action"] == "BUY_NOW"
    assert d["suggested_entry_low"] > 0
    assert d["suggested_stop_loss"] > 0
    assert "buy_sell_ratio" in d
    assert "imbalance_direction" in d


def test_render_alert_handles_zero_price() -> None:
    """FlowSignal lỗi không có last_close (=0) ⇒ render vẫn không crash."""
    sig = _signal(last_close=0.0)
    payload = build_alert_payload(sig)
    text = render_alert_message_vi(payload)
    assert "FPT" in text
    assert "Giá:" not in text  # không có price line khi last_close=0
    assert payload.entry_action == "WATCH"
    assert payload.suggested_entry_low == 0.0
