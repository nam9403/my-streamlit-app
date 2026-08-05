"""Helper áp ``FlowSignal`` thành lớp boost cho danh sách cơ hội của scanner.

Mục đích:
- Biến detector "Big Boy" từ *passive alert* → *active discovery*: mỗi lần
  scan, các mã có dòng tiền lớn xác nhận hướng tăng được nâng confidence,
  mã có dòng tiền lớn ngược hướng bị giảm. Không sửa ``scanner_service``
  (file critical-tier) — module này là **post-processor opt-in**.

Thiết kế:
- Pure function (không Streamlit, không DB) ⇒ test offline 100%.
- Idempotent: gọi 2 lần cho cùng DataFrame không cộng dồn boost.
- Tôn trọng ngưỡng: penalty bị clip để 1 mã ngược dòng không tụt > 50% conf.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Mapping

import pandas as pd

_DEFAULT_WEIGHT = 0.25
_BOOST_COLUMN = "Flow boost"
_NOTE_COLUMN = "Flow note"
_CONFIDENCE_COLUMN = "Confidence %"
_ACTION_COLUMN = "Hành động hôm nay"
_SYMBOL_COLUMN = "Mã"
_ACTION_RANK = {"BUY": 3, "HOLD": 2, "WATCH": 1, "SELL": 0}


@dataclass(frozen=True)
class FlowBoostConfig:
    """Tham số áp dụng boost — readonly, dễ propagate ra UI."""

    weight: float = _DEFAULT_WEIGHT
    bullish_cap: float = 1.0
    bearish_cap: float = -0.5
    min_intensity_for_boost: float = 4.0
    min_intensity_for_penalty: float = 5.5
    confidence_column: str = _CONFIDENCE_COLUMN
    symbol_column: str = _SYMBOL_COLUMN
    action_column: str = _ACTION_COLUMN

    def normalize(self) -> FlowBoostConfig:
        # Note: dùng explicit None-check để cho phép weight=0.0 (tắt boost mà
        # vẫn ghi cột ``Flow boost`` / ``Flow note`` cho UI hiển thị).
        w = float(_DEFAULT_WEIGHT if self.weight is None else self.weight)
        w = max(0.0, min(1.0, w))
        bull = float(1.0 if self.bullish_cap is None else self.bullish_cap)
        bull = max(0.0, min(2.0, bull))
        bear = float(-0.5 if self.bearish_cap is None else self.bearish_cap)
        bear = max(-1.0, min(0.0, bear))
        boost_th = float(4.0 if self.min_intensity_for_boost is None else self.min_intensity_for_boost)
        pen_th = float(5.5 if self.min_intensity_for_penalty is None else self.min_intensity_for_penalty)
        return FlowBoostConfig(
            weight=w,
            bullish_cap=bull,
            bearish_cap=bear,
            min_intensity_for_boost=max(1.0, min(10.0, boost_th)),
            min_intensity_for_penalty=max(1.0, min(10.0, pen_th)),
            confidence_column=str(self.confidence_column or _CONFIDENCE_COLUMN),
            symbol_column=str(self.symbol_column or _SYMBOL_COLUMN),
            action_column=str(self.action_column or _ACTION_COLUMN),
        )


def _signal_as_dict(signal: Any) -> dict[str, Any]:
    if hasattr(signal, "to_dict") and callable(signal.to_dict):
        try:
            payload = signal.to_dict()
            if isinstance(payload, dict):
                return payload
        except Exception:  # noqa: BLE001
            pass
    if isinstance(signal, dict):
        return signal
    return {
        "is_big_boy": bool(getattr(signal, "is_big_boy", False)),
        "delta_status": str(getattr(signal, "delta_status", "")),
        "intensity_score": float(getattr(signal, "intensity_score", 0.0) or 0.0),
        "z_volume": float(getattr(signal, "z_volume", 0.0) or 0.0),
    }


def compute_flow_boost(signal: Any, *, config: FlowBoostConfig | None = None) -> tuple[float, str]:
    """Tính hệ số boost ∈ [bearish_cap, bullish_cap] cho 1 signal.

    Logic:
    - big_boy + bullish + intensity ≥ ``min_intensity_for_boost``: boost dương
      bằng ``intensity/10`` (capped ``bullish_cap``).
    - big_boy + bearish + intensity ≥ ``min_intensity_for_penalty``: penalty
      bằng ``-intensity/15`` (capped ``bearish_cap``).
    - big_boy + mixed: boost dương nhỏ ``intensity/25``.
    - không big_boy nhưng ``z_volume ≥ 2``: boost rất nhỏ ``z_volume/40``.
    - khác: 0.

    Returns:
        Tuple ``(boost, note)`` — ``note`` là chuỗi mô tả tiếng Việt cho UI.
    """
    cfg = (config or FlowBoostConfig()).normalize()
    payload = _signal_as_dict(signal)
    big = bool(payload.get("is_big_boy"))
    delta = str(payload.get("delta_status") or "").lower()
    try:
        intensity = float(payload.get("intensity_score") or 0.0)
    except (TypeError, ValueError):
        intensity = 0.0
    try:
        z_volume = float(payload.get("z_volume") or 0.0)
    except (TypeError, ValueError):
        z_volume = 0.0

    if big and delta == "bullish" and intensity >= cfg.min_intensity_for_boost:
        boost = min(intensity / 10.0, cfg.bullish_cap)
        return boost, f"Big Boy bullish · intensity {intensity:.1f}"
    if big and delta == "bearish" and intensity >= cfg.min_intensity_for_penalty:
        boost = max(-intensity / 15.0, cfg.bearish_cap)
        return boost, f"Big Boy bearish · intensity {intensity:.1f} (cảnh báo)"
    if big and delta in ("mixed", "neutral"):
        boost = min(intensity / 25.0, cfg.bullish_cap / 2.0)
        return boost, f"Big Boy {delta or 'neutral'} · intensity {intensity:.1f}"
    if (not big) and z_volume >= 2.0:
        boost = min(z_volume / 40.0, 0.2)
        return boost, f"Volume bất thường z={z_volume:.2f}"
    return 0.0, ""


def _coerce_signals_map(signals: Mapping[str, Any] | Iterable[Any] | None) -> dict[str, dict[str, Any]]:
    if not signals:
        return {}
    out: dict[str, dict[str, Any]] = {}
    if isinstance(signals, Mapping):
        for k, v in signals.items():
            sym = str(k or "").strip().upper()
            if not sym:
                continue
            out[sym] = _signal_as_dict(v)
        return out
    for item in signals:
        payload = _signal_as_dict(item)
        sym = str(payload.get("symbol") or "").strip().upper()
        if not sym:
            continue
        out[sym] = payload
    return out


def apply_flow_boost_to_dataframe(
    df: pd.DataFrame,
    signals: Mapping[str, Any] | Iterable[Any] | None,
    *,
    config: FlowBoostConfig | None = None,
) -> pd.DataFrame:
    """Trả về DataFrame mới có cột ``Flow boost`` + ``Flow note`` và đã re-sort.

    - Không sửa DataFrame gốc (return copy).
    - Nếu ``signals`` rỗng hoặc DataFrame thiếu cột symbol/confidence: trả
      về copy nguyên trạng (không raise).
    - Idempotent: nếu đã có cột ``Flow boost``, hàm reset rồi tính lại từ
      confidence gốc (đã backup ở ``__conf_base``).
    """
    if df is None or df.empty:
        return df.copy() if isinstance(df, pd.DataFrame) else pd.DataFrame()
    cfg = (config or FlowBoostConfig()).normalize()
    if cfg.symbol_column not in df.columns or cfg.confidence_column not in df.columns:
        return df.copy()
    signals_map = _coerce_signals_map(signals)

    out = df.copy()
    if "__conf_base" not in out.columns:
        out["__conf_base"] = pd.to_numeric(out[cfg.confidence_column], errors="coerce").fillna(0.0)
    boosts: list[float] = []
    notes: list[str] = []
    new_conf: list[float] = []
    for _, row in out.iterrows():
        sym = str(row.get(cfg.symbol_column) or "").strip().upper()
        sig = signals_map.get(sym)
        if sig is None:
            boosts.append(0.0)
            notes.append("")
            new_conf.append(float(row.get("__conf_base") or 0.0))
            continue
        boost, note = compute_flow_boost(sig, config=cfg)
        base = float(row.get("__conf_base") or 0.0)
        adjusted = base * (1.0 + cfg.weight * boost)
        adjusted = max(0.0, min(100.0, adjusted))
        boosts.append(round(boost, 3))
        notes.append(note)
        new_conf.append(round(adjusted, 2))
    out[_BOOST_COLUMN] = boosts
    out[_NOTE_COLUMN] = notes
    out[cfg.confidence_column] = new_conf

    if cfg.action_column in out.columns:
        out["__r"] = out[cfg.action_column].map(_ACTION_RANK).fillna(0)
        sort_cols = ["__r", cfg.confidence_column, _BOOST_COLUMN]
        out = (
            out.sort_values(sort_cols, ascending=[False, False, False])
            .drop(columns=["__r"])
            .reset_index(drop=True)
        )
    else:
        out = (
            out.sort_values([cfg.confidence_column, _BOOST_COLUMN], ascending=[False, False])
            .reset_index(drop=True)
        )
    return out


def apply_flow_boost_to_candidates(
    candidates: list[dict[str, Any]],
    signals: Mapping[str, Any] | Iterable[Any] | None,
    *,
    config: FlowBoostConfig | None = None,
    symbol_key: str = "symbol",
    confidence_key: str = "confidence",
) -> list[dict[str, Any]]:
    """Phiên bản dict-list của ``apply_flow_boost_to_dataframe`` — dùng cho
    code không xử lý DataFrame trực tiếp (vd alert preview, JSON API).
    """
    if not candidates:
        return list(candidates or [])
    cfg = (config or FlowBoostConfig()).normalize()
    signals_map = _coerce_signals_map(signals)
    out: list[dict[str, Any]] = []
    for row in candidates:
        if not isinstance(row, dict):
            continue
        enriched = dict(row)
        sym = str(enriched.get(symbol_key) or "").strip().upper()
        sig = signals_map.get(sym)
        base_conf = float(enriched.get(confidence_key) or 0.0)
        if sig is None:
            enriched["flow_boost"] = 0.0
            enriched["flow_note"] = ""
            enriched[confidence_key] = round(base_conf, 2)
        else:
            boost, note = compute_flow_boost(sig, config=cfg)
            adjusted = base_conf * (1.0 + cfg.weight * boost)
            adjusted = max(0.0, min(100.0, adjusted))
            enriched["flow_boost"] = round(boost, 3)
            enriched["flow_note"] = note
            enriched[confidence_key] = round(adjusted, 2)
        out.append(enriched)
    out.sort(key=lambda r: (float(r.get(confidence_key) or 0.0), float(r.get("flow_boost") or 0.0)), reverse=True)
    return out


__all__ = [
    "FlowBoostConfig",
    "apply_flow_boost_to_candidates",
    "apply_flow_boost_to_dataframe",
    "compute_flow_boost",
]
