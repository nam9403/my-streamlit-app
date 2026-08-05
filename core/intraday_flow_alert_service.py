"""Adapter giữa ``FlowSignal`` (Tier 1) và ``RealtimeGuardian`` (cooldown chống spam).

Mục tiêu:
- Tận dụng cooldown + signal-changed-detection sẵn có ở ``RealtimeGuardian`` mà không
  phải sửa giao diện của guardian (đã có test ổn định).
- Tạo ``signal_key`` đặc thù cho dòng tiền, đảm bảo cùng một trạng thái dòng tiền
  trên một mã sẽ ra cùng một key (qua cửa sổ cooldown), khác trạng thái sẽ ra key
  khác để cho phép gửi cảnh báo mới.
- Cho phép caller xác định ngưỡng phát alert (``min_intensity``, ``require_big_boy``)
  để giữ cảnh báo đủ chất lượng, tránh thông báo cho mọi tín hiệu nhỏ.

Module này thuần — không import streamlit, dễ test và dễ reuse trong job nền.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from core.intraday_flow_service import FlowSignal


@dataclass(frozen=True)
class FlowAlertPayload:
    """Payload chuẩn để đẩy qua các kênh thông báo (Telegram/email/in-app).

    Các field mở rộng (C3 enrichment) đều có default cho backward-compat:
    - Price levels: ``last_close``, ``resistance_level``, ``support_level``.
    - Imbalance: ``buy_sell_ratio``, ``imbalance_direction``.
    - Entry: ``suggested_entry_low`` / ``suggested_entry_high`` (zone) +
      ``entry_action`` (BUY_NOW / WAIT_BREAKOUT / WATCH / AVOID).
    """

    symbol: str
    timeframe: str
    is_big_boy: bool
    intensity_score: float
    delta_status: str
    z_volume: float
    pseudo_delta: float
    headline: str
    context_note: str
    reasons: list[str] = field(default_factory=list)
    risks: list[str] = field(default_factory=list)
    last_close: float = 0.0
    resistance_level: float = 0.0
    support_level: float = 0.0
    buy_sell_ratio: float = 1.0
    imbalance_direction: str = "balanced"
    suggested_entry_low: float = 0.0
    suggested_entry_high: float = 0.0
    suggested_stop_loss: float = 0.0
    entry_action: str = "WATCH"

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "timeframe": self.timeframe,
            "is_big_boy": bool(self.is_big_boy),
            "intensity_score": round(float(self.intensity_score), 2),
            "delta_status": self.delta_status,
            "z_volume": round(float(self.z_volume), 3),
            "pseudo_delta": round(float(self.pseudo_delta), 4),
            "headline": self.headline,
            "context_note": self.context_note,
            "reasons": list(self.reasons),
            "risks": list(self.risks),
            "last_close": round(float(self.last_close), 4),
            "resistance_level": round(float(self.resistance_level), 4),
            "support_level": round(float(self.support_level), 4),
            "buy_sell_ratio": round(float(self.buy_sell_ratio), 3),
            "imbalance_direction": self.imbalance_direction,
            "suggested_entry_low": round(float(self.suggested_entry_low), 4),
            "suggested_entry_high": round(float(self.suggested_entry_high), 4),
            "suggested_stop_loss": round(float(self.suggested_stop_loss), 4),
            "entry_action": self.entry_action,
        }


@dataclass(frozen=True)
class FlowAlertDecision:
    payload: FlowAlertPayload
    allow_notify: bool
    reason: str
    signal_key: str
    intensity_bucket: int


_DELTA_HEADLINE_VI = {
    "bullish": "Dòng tiền vào — Big Boy mua",
    "bearish": "Dòng tiền ra — Big Boy bán",
    "absorption": "Hấp thụ lực bán — pha tích lũy cạn kiệt",
    "distribution": "Phân phối — rủi ro xả hàng",
    "neutral": "Tín hiệu chưa đủ rõ",
}


def _intensity_bucket(intensity: float, *, bucket_size: int = 2) -> int:
    """Chia ``intensity_score`` (1-10) thành các nhóm để tránh đổi key vặt vãnh.

    Ví dụ ``bucket_size=2`` ⇒ các mức (1-2, 3-4, 5-6, 7-8, 9-10) chia thành nhóm 0-4.
    """
    size = max(1, int(bucket_size))
    val = max(1.0, min(10.0, float(intensity)))
    return int((val - 1.0) // size)


def build_flow_signal_key(
    signal: FlowSignal,
    *,
    intensity_bucket_size: int = 2,
) -> str:
    """Fingerprint ổn định cho cooldown — gộp các trục mà người dùng quan tâm.

    Bao gồm:
    - symbol
    - is_big_boy (cờ chính)
    - delta_status (chuyển trạng thái = tín hiệu mới)
    - intensity_bucket (mức khẩn trương sau khi bucketize)
    - z_volume làm tròn 1 chữ số (tránh đổi key chỉ vì 0.05σ)
    - pseudo_delta làm tròn 1 chữ số
    """
    bucket = _intensity_bucket(signal.intensity_score, bucket_size=intensity_bucket_size)
    return "|".join(
        [
            str(signal.symbol),
            "1" if signal.is_big_boy else "0",
            str(signal.delta_status),
            str(bucket),
            str(round(float(signal.z_volume), 1)),
            str(round(float(signal.pseudo_delta), 1)),
        ]
    )


def _suggest_entry_zone(signal: FlowSignal) -> dict[str, Any]:
    """Đề xuất vùng entry + stop-loss + action dựa trên context giá.

    Triết lý:
    - Bullish gần kháng cự ⇒ ``WAIT_BREAKOUT`` (chờ giá đóng > resistance +0.5%).
    - Bullish gần hỗ trợ / absorption gần hỗ trợ ⇒ ``BUY_NOW`` (entry ±1% giá hiện tại).
    - Bullish ở vùng giữa ⇒ ``WATCH`` (entry ở pullback về 25-50% biên độ).
    - Bearish / distribution ⇒ ``AVOID`` (không gợi ý entry, chỉ cảnh báo).
    - SL gắn vào support gần nhất hoặc -3% từ entry low (chọn cao hơn).
    """
    last = float(signal.last_close or 0.0)
    if last <= 0:
        return {
            "low": 0.0,
            "high": 0.0,
            "stop_loss": 0.0,
            "action": "WATCH",
        }
    status = str(signal.delta_status or "").lower()
    near_res = bool(signal.near_resistance)
    near_sup = bool(signal.near_support)
    resistance = float(signal.resistance_level or 0.0)
    support = float(signal.support_level or 0.0)

    action = "WATCH"
    low = last * 0.99
    high = last * 1.01

    if status in ("bearish", "distribution"):
        return {
            "low": 0.0,
            "high": 0.0,
            "stop_loss": 0.0,
            "action": "AVOID",
        }

    if status in ("bullish", "absorption") and near_res and resistance > last:
        action = "WAIT_BREAKOUT"
        low = resistance * 1.001
        high = resistance * 1.010
    elif status in ("bullish", "absorption") and near_sup:
        action = "BUY_NOW"
        low = last * 0.995
        high = last * 1.010
    elif status == "bullish":
        action = "WATCH"
        if support > 0 and last > support:
            mid = (support + last) / 2.0
            low = mid * 0.995
            high = last * 1.005
        else:
            low = last * 0.990
            high = last * 1.005

    sl_candidates = [low * 0.97]
    if support > 0 and support < low:
        sl_candidates.append(support * 0.99)
    stop_loss = max(sl_candidates)
    return {
        "low": float(low),
        "high": float(high),
        "stop_loss": float(stop_loss),
        "action": action,
    }


def build_alert_payload(signal: FlowSignal) -> FlowAlertPayload:
    """Map ``FlowSignal`` thành payload sẵn sàng cho kênh notification."""
    head = _DELTA_HEADLINE_VI.get(str(signal.delta_status), "Tín hiệu dòng tiền")
    entry = _suggest_entry_zone(signal)
    return FlowAlertPayload(
        symbol=signal.symbol,
        timeframe=signal.timeframe,
        is_big_boy=bool(signal.is_big_boy),
        intensity_score=float(signal.intensity_score),
        delta_status=str(signal.delta_status),
        z_volume=float(signal.z_volume),
        pseudo_delta=float(signal.pseudo_delta),
        headline=head,
        context_note=str(signal.context_note),
        reasons=list(signal.reasons),
        risks=list(signal.risks),
        last_close=float(signal.last_close or 0.0),
        resistance_level=float(signal.resistance_level or 0.0),
        support_level=float(signal.support_level or 0.0),
        buy_sell_ratio=float(signal.buy_sell_ratio or 1.0),
        imbalance_direction=str(signal.imbalance_direction or "balanced"),
        suggested_entry_low=float(entry["low"]),
        suggested_entry_high=float(entry["high"]),
        suggested_stop_loss=float(entry["stop_loss"]),
        entry_action=str(entry["action"]),
    )


class _GuardianAdapter:
    """Bridge object để guardian (``getattr``-based) đọc đúng signal_key của ta.

    ``RealtimeGuardian._build_signal_key`` dùng ``getattr(signal, "symbol", ...)`` +
    nhiều trường stock-screener. Chúng ta truyền ``signal_key`` đã tính trước thông qua
    thuộc tính có cùng tên trong build_signal_key → guardian sẽ join lại — *không sai
    về cooldown* vì symbol+key tuple vẫn ổn định, chỉ là các trường giả trị mặc định.

    Lưu ý: chỉ dùng nội bộ để pipe alert flow qua guardian — không expose ra ngoài.
    """

    def __init__(self, symbol: str, fingerprint: str) -> None:
        self.symbol = symbol
        self._fingerprint = fingerprint

    def __getattr__(self, name: str) -> Any:
        if name == "symbol":
            return self.__dict__["symbol"]
        if name == "f_score":
            return hash(self._fingerprint) & 0xFFFF
        if name == "mos_pct":
            return 0.0
        if name == "volume_multiple":
            return 0.0
        if name == "relative_strength_pct":
            return 0.0
        if name == "has_flat_base":
            return False
        if name == "has_vcp":
            return False
        if name == "red_flags":
            return [self._fingerprint]
        raise AttributeError(name)


def evaluate_flow_alerts(
    signals: dict[str, FlowSignal] | list[FlowSignal],
    guardian: Any,
    *,
    min_intensity: float = 6.0,
    require_big_boy: bool = True,
    intensity_bucket_size: int = 2,
    skip_delta_statuses: tuple[str, ...] = ("neutral",),
) -> list[FlowAlertDecision]:
    """Đánh giá hàng loạt tín hiệu, trả về danh sách alert candidate đã qua guardian.

    Lọc trước theo intensity / big_boy / delta_status để tránh "gửi mọi thứ".
    Sau đó hỏi ``guardian.decide(...)`` cho từng tín hiệu để áp cooldown.
    """
    if isinstance(signals, dict):
        iterable = list(signals.values())
    else:
        iterable = list(signals or [])
    decisions: list[FlowAlertDecision] = []
    for sig in iterable:
        if not isinstance(sig, FlowSignal):
            continue
        if require_big_boy and not sig.is_big_boy:
            continue
        if sig.intensity_score < float(min_intensity):
            continue
        if sig.delta_status in (skip_delta_statuses or ()):
            continue
        fingerprint = build_flow_signal_key(sig, intensity_bucket_size=intensity_bucket_size)
        adapter = _GuardianAdapter(symbol=sig.symbol, fingerprint=fingerprint)
        try:
            decision = guardian.decide(adapter)
            allow = bool(getattr(decision, "allow_notify", False))
            reason = str(getattr(decision, "reason", ""))
            key = str(getattr(decision, "signal_key", "") or fingerprint)
        except Exception:
            allow, reason, key = True, "guardian_error", fingerprint
        decisions.append(
            FlowAlertDecision(
                payload=build_alert_payload(sig),
                allow_notify=allow,
                reason=reason,
                signal_key=key,
                intensity_bucket=_intensity_bucket(sig.intensity_score, bucket_size=intensity_bucket_size),
            )
        )
    return decisions


def mark_flow_alert_dispatched(
    guardian: Any,
    decision: FlowAlertDecision,
    *,
    status: str = "sent",
) -> None:
    """Ghi nhận đã gửi để guardian áp cooldown — gọi sau khi kênh thông báo trả về OK."""
    adapter = _GuardianAdapter(symbol=decision.payload.symbol, fingerprint=decision.signal_key)
    try:
        guardian.mark_notified(adapter, decision.signal_key, status=status)
    except Exception:
        return


_ACTION_LABEL_VI = {
    "BUY_NOW": "MUA NGAY (sát vùng hỗ trợ)",
    "WAIT_BREAKOUT": "CHỜ BREAKOUT (vượt kháng cự)",
    "WATCH": "QUAN SÁT (chờ pullback)",
    "AVOID": "TRÁNH (rủi ro phân phối)",
}


def _format_price(value: float) -> str:
    """Format giá theo quy ước VN: <1000 giữ 2 chữ số, >=1000 dùng dấu chấm phần nghìn."""
    v = float(value or 0.0)
    if v <= 0:
        return "—"
    if v >= 1000:
        return f"{v:,.0f}".replace(",", ".")
    return f"{v:.2f}"


def render_alert_message_vi(payload: FlowAlertPayload) -> str:
    """Sinh nội dung text gọn cho Telegram/email/in-app.

    Format đã được enrich (C3) — bao gồm price levels, buy/sell ratio,
    entry zone, và stop-loss đề xuất. Vẫn giữ plain text để chạy được trên
    các kênh không hỗ trợ markdown.
    """
    lines: list[str] = []
    big_tag = "[BIG BOY] " if payload.is_big_boy else ""
    lines.append(
        f"{big_tag}{payload.symbol} ({payload.timeframe}) — {payload.headline}"
    )

    metrics_parts = [
        f"Intensity {payload.intensity_score:.1f}/10",
        f"Z-vol {payload.z_volume:+.2f}σ",
        f"Δ {payload.pseudo_delta:+.2f}",
    ]
    if payload.buy_sell_ratio and payload.imbalance_direction != "balanced":
        if payload.imbalance_direction == "buy_dominant":
            metrics_parts.append(f"buy/sell {payload.buy_sell_ratio:.2f}x")
        elif payload.imbalance_direction == "sell_dominant":
            metrics_parts.append(f"sell/buy {1.0 / max(payload.buy_sell_ratio, 0.001):.2f}x")
    lines.append(" · ".join(metrics_parts))

    if payload.last_close > 0:
        price_line = f"Giá: {_format_price(payload.last_close)}"
        if payload.support_level > 0:
            price_line += f" · Hỗ trợ {_format_price(payload.support_level)}"
        if payload.resistance_level > 0:
            price_line += f" · Kháng cự {_format_price(payload.resistance_level)}"
        lines.append(price_line)

    if payload.entry_action and payload.entry_action != "WATCH":
        action_label = _ACTION_LABEL_VI.get(payload.entry_action, payload.entry_action)
        if payload.entry_action == "AVOID":
            lines.append(f"Khuyến nghị: {action_label}")
        elif payload.suggested_entry_low > 0 and payload.suggested_entry_high > 0:
            entry_str = (
                f"Khuyến nghị: {action_label} · Vùng entry "
                f"{_format_price(payload.suggested_entry_low)}–"
                f"{_format_price(payload.suggested_entry_high)}"
            )
            if payload.suggested_stop_loss > 0:
                entry_str += f" · SL {_format_price(payload.suggested_stop_loss)}"
            lines.append(entry_str)

    if payload.context_note:
        lines.append(f"Bối cảnh: {payload.context_note}")
    if payload.reasons:
        lines.append("Lý do: " + " | ".join(payload.reasons[:3]))
    if payload.risks:
        lines.append("Rủi ro: " + " | ".join(payload.risks[:2]))
    return "\n".join(lines)


__all__ = [
    "FlowAlertDecision",
    "FlowAlertPayload",
    "build_alert_payload",
    "build_flow_signal_key",
    "evaluate_flow_alerts",
    "mark_flow_alert_dispatched",
    "render_alert_message_vi",
]
