"""Re-rank scanner candidates bằng ``FlowSignal`` đã ghi vào journal.

Đây là **mảnh ghép cuối** của loop "Big Boy detector → ranking":
- Background cycle chạy ``analyze_flow`` cho universe → ghi mọi signal
  vào ``data/runtime/flow_journal/flow_signals_*.jsonl``.
- Khi user mở app, scanner trả về danh sách ứng viên (DataFrame).
- Module này đọc journal trong ``lookback_hours`` gần nhất, gộp signal
  mới nhất per-symbol, rồi gọi ``apply_flow_boost_to_dataframe`` để
  tăng/giảm confidence trước khi user nhìn thấy.

Thiết kế quan trọng:
- **Opt-in qua env** (``II_SCANNER_FLOW_RERANK_ENABLED=0`` default OFF)
  ⇒ không thay đổi behavior hiện tại khi deploy lần đầu.
- **Không network call**: chỉ đọc file JSONL local đã được background
  cycle ghi ⇒ không thêm latency cho UI thread.
- **Graceful degrade**: journal rỗng / lỗi I/O ⇒ trả candidates nguyên
  trạng + meta giải thích lý do (không raise).
- **Idempotent**: gọi 2 lần cho cùng DataFrame không cộng dồn boost
  (delegate cho ``apply_flow_boost_to_dataframe`` đã handle).
"""

from __future__ import annotations

import logging
import os
from typing import Any, Callable

import pandas as pd

from core.flow_ranking_service import (
    FlowBoostConfig,
    apply_flow_boost_to_dataframe,
)
from core.intraday_flow_journal import read_recent_flow_signals

logger = logging.getLogger(__name__)

_DEFAULT_LOOKBACK_HOURS = 24
_DEFAULT_WEIGHT = 0.25
_DEFAULT_JOURNAL_LIMIT = 5000


def _env_bool(name: str, *, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return str(raw).strip().lower() in ("1", "true", "yes", "on")


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        return float(raw)
    except (TypeError, ValueError):
        return default


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except (TypeError, ValueError):
        return default


def is_scanner_rerank_enabled() -> bool:
    """Kiểm tra env flag opt-in. Default OFF cho backward-compat."""
    return _env_bool("II_SCANNER_FLOW_RERANK_ENABLED", default=False)


def _latest_signal_per_symbol(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Gộp các signal trong journal → 1 signal mới nhất cho mỗi symbol.

    Dùng ``journaled_at_utc`` (ISO string) để so sánh — ISO format sắp
    xếp đúng theo thời gian khi so sánh string.
    """
    latest: dict[str, dict[str, Any]] = {}
    latest_ts: dict[str, str] = {}
    for r in rows:
        if not isinstance(r, dict):
            continue
        sym = str(r.get("symbol") or "").strip().upper()
        if not sym:
            continue
        ts = str(r.get("journaled_at_utc") or r.get("ts") or r.get("timestamp") or "")
        if sym not in latest or ts > latest_ts.get(sym, ""):
            latest[sym] = r
            latest_ts[sym] = ts
    return latest


def rerank_candidates_with_flow_journal(
    candidates: pd.DataFrame,
    *,
    enabled: bool | None = None,
    lookback_hours: int | None = None,
    weight: float | None = None,
    journal_reader: Callable[..., list[dict[str, Any]]] | None = None,
    config: FlowBoostConfig | None = None,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Re-rank scanner candidates bằng flow signals đọc từ journal.

    Args:
        candidates: DataFrame trả về từ ``scan_potential_stocks``.
        enabled: Override env flag (None → đọc env).
        lookback_hours: Cửa sổ đọc journal (None → đọc env, default 24h).
        weight: Override trọng số boost (None → đọc env, default 0.25).
        journal_reader: Callable thay thế ``read_recent_flow_signals``
            (dùng cho test).
        config: ``FlowBoostConfig`` override toàn phần (None → tự build
            từ ``weight``).

    Returns:
        Tuple ``(df_out, meta)`` — luôn an toàn để gọi:
        - Disabled / non-DataFrame / empty journal / I/O error: trả copy
          DataFrame gốc + meta giải thích.
        - Áp dụng thành công: trả DataFrame có cột ``Flow boost`` /
          ``Flow note`` + meta báo số mã đã áp + lookback + weight.
    """
    if not isinstance(candidates, pd.DataFrame):
        return candidates, {"enabled": False, "reason": "not_dataframe", "applied_count": 0}

    on = is_scanner_rerank_enabled() if enabled is None else bool(enabled)
    if not on:
        return candidates.copy(), {"enabled": False, "reason": "disabled", "applied_count": 0}

    if candidates.empty:
        return candidates.copy(), {
            "enabled": True,
            "reason": "empty_candidates",
            "applied_count": 0,
        }

    hours = (
        _env_int("II_SCANNER_FLOW_RERANK_LOOKBACK_HOURS", _DEFAULT_LOOKBACK_HOURS)
        if lookback_hours is None
        else int(lookback_hours)
    )
    hours = max(1, hours)

    reader = journal_reader or read_recent_flow_signals
    try:
        rows = reader(hours=hours, limit=_DEFAULT_JOURNAL_LIMIT)
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "scanner_flow_rerank_journal_read_failed error=%s",
            exc.__class__.__name__,
        )
        return candidates.copy(), {
            "enabled": True,
            "reason": "journal_error",
            "applied_count": 0,
            "lookback_hours": hours,
        }

    if not rows:
        return candidates.copy(), {
            "enabled": True,
            "reason": "journal_empty",
            "applied_count": 0,
            "lookback_hours": hours,
        }

    signals_map = _latest_signal_per_symbol(rows)
    if not signals_map:
        return candidates.copy(), {
            "enabled": True,
            "reason": "no_valid_signals",
            "applied_count": 0,
            "lookback_hours": hours,
        }

    eff_weight = (
        _env_float("II_SCANNER_FLOW_RERANK_WEIGHT", _DEFAULT_WEIGHT)
        if weight is None
        else float(weight)
    )
    cfg = (config or FlowBoostConfig(weight=eff_weight)).normalize()

    try:
        boosted = apply_flow_boost_to_dataframe(candidates, signals_map, config=cfg)
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "scanner_flow_rerank_apply_failed error=%s",
            exc.__class__.__name__,
        )
        return candidates.copy(), {
            "enabled": True,
            "reason": "apply_error",
            "applied_count": 0,
            "lookback_hours": hours,
        }

    sym_col = cfg.symbol_column
    applied = 0
    if sym_col in boosted.columns:
        candidate_syms = {
            str(s).strip().upper()
            for s in boosted[sym_col].tolist()
            if isinstance(s, str) and str(s).strip()
        }
        applied = len(candidate_syms & set(signals_map.keys()))

    return boosted, {
        "enabled": True,
        "reason": "applied",
        "applied_count": applied,
        "journal_signal_count": len(signals_map),
        "lookback_hours": hours,
        "weight": cfg.weight,
    }


__all__ = [
    "is_scanner_rerank_enabled",
    "rerank_candidates_with_flow_journal",
]
