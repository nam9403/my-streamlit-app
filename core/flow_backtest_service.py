"""Backtest harness cho ``FlowSignal`` — chứng minh detector hoạt động hay không.

Tại sao module này tồn tại:
- Trước khi đẩy alert tới user thật, ta phải biết: với ngưỡng ``min_intensity``
  hiện tại (default 6.0) thì sau N phiên trung bình mã được flag có lời hay
  không? Hit-rate bao nhiêu? Chênh lệch giữa intensity 6 vs 8 vs 9 là gì?
- Không có backtest = đoán mò = mọi alert là gambling.
- Module này replay ``analyze_flow`` trên OHLCV lịch sử (cả daily lẫn intraday)
  với chiến lược "rolling window" để tránh look-ahead bias hoàn toàn.

Pipeline:
1. ``replay_flow_signals_on_ohlcv(df)``: với mỗi index ``i`` từ ``min_history``
   trở đi, gọi ``analyze_flow(df[:i+1])`` ⇒ 1 signal tại bar ``i``.
2. ``compute_forward_returns(df, i, horizons)``: pct return giữa ``close[i]``
   và ``close[i+H]`` cho mỗi H trong ``horizons``.
3. ``backtest_flow_signals``: ghép 2 step + ép thành list ``{date, symbol,
   intensity, ...returns}``.
4. ``summarize_backtest_by_intensity``: nhóm theo bucket cường độ → hit-rate,
   avg_return, ưu tiên giúp tune ``min_intensity``.
5. ``recommend_min_intensity``: trả về số float (hoặc None nếu data không đủ)
   — đầu vào cho default scheduler.

Không có dependency mới: dùng đúng những gì ``analyze_flow`` đã require.
"""

from __future__ import annotations

import json
import logging
import math
import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import pandas as pd

from core.intraday_flow_service import FlowConfig, IntradayFlowError, analyze_flow

logger = logging.getLogger(__name__)

DEFAULT_HORIZONS: tuple[int, ...] = (1, 5, 20)
DEFAULT_INTENSITY_BUCKETS: tuple[float, ...] = (4.0, 6.0, 7.5, 9.0, 10.0)
DEFAULT_RECOMMENDATION_PATH: Path = Path("artifacts/flow_backtest/recommendation_latest.json")
DEFAULT_RECOMMENDATION_TTL_DAYS: int = 14


@dataclass(frozen=True)
class BacktestConfig:
    """Tham số replay — tách khỏi ``FlowConfig`` để giữ ``analyze_flow`` thuần."""

    min_history: int = 120
    stride: int = 5
    horizons: tuple[int, ...] = DEFAULT_HORIZONS
    intensity_buckets: tuple[float, ...] = DEFAULT_INTENSITY_BUCKETS
    require_big_boy: bool = True
    flow_config: FlowConfig | None = None

    def normalize(self) -> BacktestConfig:
        history = max(60, min(2000, int(self.min_history or 120)))
        stride = max(1, min(50, int(self.stride or 5)))
        horizons = tuple(sorted({max(1, int(h)) for h in (self.horizons or DEFAULT_HORIZONS)}))
        buckets = tuple(sorted({float(b) for b in (self.intensity_buckets or DEFAULT_INTENSITY_BUCKETS) if 1.0 <= float(b) <= 10.0}))
        if not buckets:
            buckets = DEFAULT_INTENSITY_BUCKETS
        return BacktestConfig(
            min_history=history,
            stride=stride,
            horizons=horizons,
            intensity_buckets=buckets,
            require_big_boy=bool(self.require_big_boy),
            flow_config=self.flow_config,
        )


def _resolve_signal_date(ohlcv: pd.DataFrame, idx: int) -> str:
    if "date" in ohlcv.columns:
        try:
            return str(pd.to_datetime(ohlcv["date"].iloc[idx]).date())
        except (ValueError, TypeError):
            return ""
    try:
        return str(ohlcv.index[idx])
    except (IndexError, TypeError):
        return ""


def compute_forward_returns(
    ohlcv: pd.DataFrame,
    *,
    signal_index: int,
    horizons: Iterable[int] = DEFAULT_HORIZONS,
) -> dict[str, float | None]:
    """Tính pct return từ close[idx] tới close[idx+H] cho mỗi H trong ``horizons``.

    Trả về ``None`` cho horizon vượt quá dữ liệu (không có future data).
    """
    out: dict[str, float | None] = {}
    if not isinstance(ohlcv, pd.DataFrame) or "close" not in ohlcv.columns:
        return {f"return_{int(h)}d": None for h in horizons}
    closes = pd.to_numeric(ohlcv["close"], errors="coerce")
    n = len(closes)
    if signal_index < 0 or signal_index >= n:
        return {f"return_{int(h)}d": None for h in horizons}
    base = closes.iloc[signal_index]
    try:
        base_f = float(base)
    except (TypeError, ValueError):
        base_f = float("nan")
    for h in horizons:
        h_int = max(1, int(h))
        target_idx = signal_index + h_int
        key = f"return_{h_int}d"
        if target_idx >= n or not math.isfinite(base_f) or base_f <= 0:
            out[key] = None
            continue
        try:
            future = float(closes.iloc[target_idx])
        except (TypeError, ValueError):
            out[key] = None
            continue
        if not math.isfinite(future):
            out[key] = None
            continue
        out[key] = round((future / base_f - 1.0) * 100.0, 4)
    return out


def replay_flow_signals_on_ohlcv(
    ohlcv: pd.DataFrame,
    *,
    symbol: str,
    config: BacktestConfig | None = None,
    timeframe: str = "1D",
) -> list[dict[str, Any]]:
    """Replay ``analyze_flow`` trên rolling window.

    Lưu ý quan trọng (anti look-ahead bias): tại bar ``i``, chỉ truyền
    ``ohlcv.iloc[: i + 1]`` ⇒ analyzer **không** nhìn thấy giá tương lai.
    """
    cfg = (config or BacktestConfig()).normalize()
    if ohlcv is None or len(ohlcv) <= cfg.min_history:
        return []
    flow_cfg = cfg.flow_config or FlowConfig()
    out: list[dict[str, Any]] = []
    for i in range(cfg.min_history, len(ohlcv), cfg.stride):
        window = ohlcv.iloc[: i + 1]
        try:
            sig = analyze_flow(window, symbol=symbol, config=flow_cfg, timeframe=timeframe)
        except IntradayFlowError:
            continue
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "replay_flow_failed symbol=%s index=%s error=%s",
                symbol,
                i,
                exc.__class__.__name__,
            )
            continue
        payload = sig.to_dict() if hasattr(sig, "to_dict") else dict(sig)
        payload["signal_index"] = int(i)
        payload["signal_date"] = _resolve_signal_date(ohlcv, i)
        out.append(payload)
    return out


def backtest_flow_signals(
    ohlcv: pd.DataFrame,
    *,
    symbol: str,
    config: BacktestConfig | None = None,
    timeframe: str = "1D",
) -> dict[str, Any]:
    """End-to-end backtest cho 1 mã: trả về ``{per_signal, summary}``."""
    cfg = (config or BacktestConfig()).normalize()
    signals = replay_flow_signals_on_ohlcv(ohlcv, symbol=symbol, config=cfg, timeframe=timeframe)
    enriched: list[dict[str, Any]] = []
    for s in signals:
        idx = int(s.get("signal_index") or -1)
        if idx < 0:
            continue
        if cfg.require_big_boy and not bool(s.get("is_big_boy")):
            continue
        fwd = compute_forward_returns(ohlcv, signal_index=idx, horizons=cfg.horizons)
        enriched.append({**s, **fwd})
    summary = summarize_backtest_by_intensity(
        enriched,
        buckets=cfg.intensity_buckets,
        horizons=cfg.horizons,
    )
    return {
        "symbol": symbol,
        "timeframe": timeframe,
        "n_signals": len(enriched),
        "n_replays": len(signals),
        "per_signal": enriched,
        "summary": summary,
        "config": {
            "min_history": cfg.min_history,
            "stride": cfg.stride,
            "horizons": list(cfg.horizons),
            "intensity_buckets": list(cfg.intensity_buckets),
            "require_big_boy": cfg.require_big_boy,
        },
    }


def _bucket_label(low: float, high: float | None) -> str:
    if high is None:
        return f">={low:.1f}"
    return f"{low:.1f}-{high:.1f}"


def summarize_backtest_by_intensity(
    per_signal: list[dict[str, Any]],
    *,
    buckets: Iterable[float] = DEFAULT_INTENSITY_BUCKETS,
    horizons: Iterable[int] = DEFAULT_HORIZONS,
) -> list[dict[str, Any]]:
    """Group ``per_signal`` theo intensity bucket, tính count / hit-rate / avg return.

    Buckets được hiểu là các *cận dưới* — bucket cuối là half-open
    ``[max_bucket, +∞)``.
    """
    if not per_signal:
        return []
    sorted_buckets = sorted({float(b) for b in buckets if 1.0 <= float(b) <= 10.0})
    if not sorted_buckets:
        sorted_buckets = list(DEFAULT_INTENSITY_BUCKETS)
    h_list = sorted({int(h) for h in horizons})

    edges: list[tuple[float, float | None]] = []
    for i, lo in enumerate(sorted_buckets):
        hi = sorted_buckets[i + 1] if (i + 1) < len(sorted_buckets) else None
        edges.append((lo, hi))

    out: list[dict[str, Any]] = []
    for lo, hi in edges:
        rows = [
            s for s in per_signal
            if float(s.get("intensity_score") or 0.0) >= lo
            and (hi is None or float(s.get("intensity_score") or 0.0) < hi)
        ]
        bucket_payload: dict[str, Any] = {
            "bucket": _bucket_label(lo, hi),
            "intensity_lower": lo,
            "intensity_upper": hi,
            "count": len(rows),
        }
        if not rows:
            for h in h_list:
                bucket_payload[f"hit_rate_{h}d"] = None
                bucket_payload[f"avg_return_{h}d"] = None
                bucket_payload[f"median_return_{h}d"] = None
                bucket_payload[f"std_return_{h}d"] = None
            out.append(bucket_payload)
            continue
        for h in h_list:
            key = f"return_{h}d"
            vals = [float(r[key]) for r in rows if r.get(key) is not None]
            if not vals:
                bucket_payload[f"hit_rate_{h}d"] = None
                bucket_payload[f"avg_return_{h}d"] = None
                bucket_payload[f"median_return_{h}d"] = None
                bucket_payload[f"std_return_{h}d"] = None
                continue
            arr = np.array(vals, dtype=float)
            hits = int((arr > 0).sum())
            bucket_payload[f"hit_rate_{h}d"] = round(hits / len(arr) * 100.0, 2)
            bucket_payload[f"avg_return_{h}d"] = round(float(arr.mean()), 4)
            bucket_payload[f"median_return_{h}d"] = round(float(np.median(arr)), 4)
            bucket_payload[f"std_return_{h}d"] = round(float(arr.std(ddof=0)), 4)
        out.append(bucket_payload)
    return out


def recommend_min_intensity(
    summary: list[dict[str, Any]],
    *,
    horizon_days: int = 5,
    min_count: int = 5,
    min_avg_return_pct: float = 0.0,
    min_hit_rate_pct: float = 50.0,
) -> dict[str, Any]:
    """Đề xuất ``min_intensity`` empirical từ summary.

    Chiến lược: lấy bucket *thấp nhất* mà thoả mãn:
    - ``count >= min_count`` (đủ mẫu thống kê)
    - ``avg_return_<horizon>d >= min_avg_return_pct``
    - ``hit_rate_<horizon>d >= min_hit_rate_pct``

    Output có ``recommended`` (float hoặc None) + ``reason`` để dễ audit.
    """
    avg_key = f"avg_return_{int(horizon_days)}d"
    hit_key = f"hit_rate_{int(horizon_days)}d"
    candidates: list[dict[str, Any]] = []
    for bucket in summary or []:
        cnt = int(bucket.get("count") or 0)
        if cnt < int(min_count):
            continue
        avg = bucket.get(avg_key)
        hit = bucket.get(hit_key)
        if avg is None or hit is None:
            continue
        if float(avg) < float(min_avg_return_pct):
            continue
        if float(hit) < float(min_hit_rate_pct):
            continue
        candidates.append(bucket)
    if not candidates:
        return {
            "recommended": None,
            "horizon_days": int(horizon_days),
            "reason": "Không có bucket nào thoả ngưỡng — dữ liệu quá ít hoặc detector không tạo được edge dương.",
            "all_buckets": list(summary or []),
        }
    candidates.sort(key=lambda b: float(b.get("intensity_lower") or 0.0))
    chosen = candidates[0]
    return {
        "recommended": float(chosen.get("intensity_lower") or 0.0),
        "horizon_days": int(horizon_days),
        "reason": (
            f"Bucket {chosen.get('bucket')} đạt count={chosen.get('count')}, "
            f"avg_return_{horizon_days}d={chosen.get(avg_key)}%, "
            f"hit_rate_{horizon_days}d={chosen.get(hit_key)}%."
        ),
        "chosen_bucket": chosen,
        "all_buckets": list(summary or []),
    }


def aggregate_universe_backtest(
    per_symbol_results: dict[str, dict[str, Any]],
    *,
    buckets: Iterable[float] = DEFAULT_INTENSITY_BUCKETS,
    horizons: Iterable[int] = DEFAULT_HORIZONS,
) -> dict[str, Any]:
    """Gộp kết quả backtest nhiều mã thành 1 summary toàn vũ trụ.

    Hữu ích cho VN-Universe scan: thay vì tune ``min_intensity`` riêng cho
    từng mã (overfit), ta tune trên pool toàn thị trường.
    """
    pooled: list[dict[str, Any]] = []
    for _sym, res in per_symbol_results.items():
        per_signal = res.get("per_signal") if isinstance(res, dict) else None
        if isinstance(per_signal, list):
            pooled.extend(per_signal)
    summary = summarize_backtest_by_intensity(pooled, buckets=buckets, horizons=horizons)
    return {
        "n_symbols": len(per_symbol_results or {}),
        "n_signals_pooled": len(pooled),
        "summary": summary,
    }


def _recommendation_path_default() -> Path:
    raw = os.environ.get("II_FLOW_RECOMMENDATION_PATH")
    return Path(str(raw)) if raw else DEFAULT_RECOMMENDATION_PATH


def save_recommendation_artifact(
    recommendations: dict[str, dict[str, Any]],
    *,
    horizon_days: int = 5,
    path: Path | None = None,
    metadata: dict[str, Any] | None = None,
    now: datetime | None = None,
) -> Path | None:
    """Ghi đề xuất ``min_intensity`` ra JSON artifact để runtime tự đọc lại.

    Args:
        recommendations: dict ``{"horizon_5d": {...}, ...}`` từ
            ``recommend_min_intensity`` đã chạy với nhiều horizon.
        horizon_days: Horizon ưu tiên để runtime sử dụng (default 5 — cân
            bằng nhiễu ngắn hạn và mục tiêu trade swing).
        path: Override file path (default ``artifacts/flow_backtest/
            recommendation_latest.json`` hoặc env ``II_FLOW_RECOMMENDATION_PATH``).
        metadata: Trộn thêm context (vd ``{"n_symbols": 10}``) để dễ audit.
        now: Override timestamp cho test.

    Returns:
        Path đã ghi hoặc None nếu không có recommendation hợp lệ để ghi
        (vd horizon chưa đủ data ⇒ runtime giữ default thay vì áp số xấu).
    """
    if not isinstance(recommendations, dict):
        return None
    key = f"horizon_{int(horizon_days)}d"
    chosen = recommendations.get(key)
    if not isinstance(chosen, dict) or chosen.get("recommended") is None:
        return None
    target = path or _recommendation_path_default()
    payload: dict[str, Any] = {
        "schema_version": 1,
        "generated_at_utc": (now or datetime.now(timezone.utc)).astimezone(timezone.utc).isoformat(),
        "horizon_days": int(horizon_days),
        "recommended_min_intensity": float(chosen.get("recommended") or 0.0),
        "reason": str(chosen.get("reason") or ""),
        "chosen_bucket": chosen.get("chosen_bucket"),
        "all_horizons": recommendations,
    }
    if isinstance(metadata, dict):
        for k, v in metadata.items():
            payload.setdefault(k, v)
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
        return target
    except OSError as exc:
        logger.warning("save_recommendation_failed path=%s error=%s", target, exc.__class__.__name__)
        return None


def load_recommendation_artifact(
    *,
    path: Path | None = None,
    max_age_days: int | None = None,
    now: datetime | None = None,
) -> dict[str, Any] | None:
    """Đọc lại recommendation, tự reject nếu quá cũ.

    TTL mặc định ``DEFAULT_RECOMMENDATION_TTL_DAYS`` ngày — quá hạn nghĩa là
    market regime có thể đã đổi, dùng số cũ không an toàn ⇒ runtime fallback
    về default cho tới khi user chạy backtest mới.

    Returns:
        dict đầy đủ payload nếu hợp lệ; None nếu thiếu file / hỏng / quá hạn.
    """
    target = path or _recommendation_path_default()
    if not target.exists():
        return None
    try:
        raw = target.read_text(encoding="utf-8")
        payload = json.loads(raw)
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    if payload.get("recommended_min_intensity") is None:
        return None
    ttl = int(max_age_days) if max_age_days is not None else DEFAULT_RECOMMENDATION_TTL_DAYS
    ttl = max(1, ttl)
    ts_raw = str(payload.get("generated_at_utc") or "")
    try:
        ts_gen = datetime.fromisoformat(ts_raw)
        if ts_gen.tzinfo is None:
            ts_gen = ts_gen.replace(tzinfo=timezone.utc)
    except ValueError:
        return None
    ref_now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    if ref_now - ts_gen > timedelta(days=ttl):
        return None
    return payload


__all__ = [
    "BacktestConfig",
    "DEFAULT_HORIZONS",
    "DEFAULT_INTENSITY_BUCKETS",
    "DEFAULT_RECOMMENDATION_PATH",
    "DEFAULT_RECOMMENDATION_TTL_DAYS",
    "aggregate_universe_backtest",
    "backtest_flow_signals",
    "compute_forward_returns",
    "load_recommendation_artifact",
    "recommend_min_intensity",
    "replay_flow_signals_on_ohlcv",
    "save_recommendation_artifact",
    "summarize_backtest_by_intensity",
]
