"""
Forecast metrics helpers: standard MAPE and anti look-ahead settlement price lookup.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Callable

logger = logging.getLogger(__name__)


def mape_point_pct(*, actual_price: float, forecast_price: float) -> float | None:
    """
    Một quan sát MAPE chuẩn (phần trăm):

        |Actual_at_due - Forecast| / |Actual_at_due| * 100

    Trả None nếu actual_price <= 0 (không chia được).
    """
    actual = float(actual_price or 0.0)
    forecast = float(forecast_price or 0.0)
    if actual <= 0:
        return None
    return abs(actual - forecast) / actual * 100.0


def mean_mape_pct(abs_error_pct_values: list[float]) -> float | None:
    """MAPE trung bình = (1/n) * Σ abs_error_pct."""
    vals = [float(x) for x in abs_error_pct_values if x is not None]
    if not vals:
        return None
    return sum(vals) / len(vals)


def settle_realized_price_on_due_date(
    *,
    symbol: str,
    due_at: datetime,
    get_close_on_or_before: Callable[[str, str], tuple[float | None, str | None]],
    fetch_ohlcv_history: Callable[[str, int], Any] | None = None,
    upsert_ohlcv: Callable[..., Any] | None = None,
) -> tuple[float | None, str | None]:
    """
    Lấy giá đóng cửa tại đúng due date (hoặc phiên gần nhất trước đó) từ OHLCV store.
    Không bao giờ dùng giá \"hôm nay\" nếu due date đã qua.

    ``fetch_ohlcv_history`` (nếu có) chỉ dùng để backfill khi store thiếu bar —
    nên truyền hàm settle-safe (vnstock/FireAnt/Yahoo trực tiếp), KHÔNG dùng
    ``portal.fetch_ohlcv_history`` (có nhánh incremental store dễ treo mạng).
    """
    due_day = due_at.astimezone(timezone.utc).date().isoformat() if due_at.tzinfo else due_at.date().isoformat()
    px, as_of = get_close_on_or_before(symbol, due_day)
    if px is not None and px > 0:
        return float(px), as_of

    if fetch_ohlcv_history is None:
        return None, None
    try:
        # Đệm đủ phiên để phủ due date trong quá khứ (horizon dài), nhưng giới hạn
        # để tránh request quá nặng khi backfill.
        age_days = max(30, (datetime.now(timezone.utc).date() - due_at.date()).days + 40)
        sessions = min(1600, max(80, int(age_days * 0.7)))
        df = fetch_ohlcv_history(symbol, sessions)
        if upsert_ohlcv is not None and df is not None and not getattr(df, "empty", True):
            try:
                upsert_ohlcv(symbol, df, source=str(getattr(df, "attrs", {}).get("source") or "forecast_settle"))
            except Exception:
                logger.warning("forecast_settle_upsert_failed symbol=%s", symbol, exc_info=True)
        px2, as_of2 = get_close_on_or_before(symbol, due_day)
        if px2 is not None and px2 > 0:
            return float(px2), as_of2
    except Exception:
        logger.warning("forecast_settle_backfill_failed symbol=%s due=%s", symbol, due_day, exc_info=True)
        return None, None
    return None, None


def mape_safety_should_downgrade(
    *,
    mape_pct: float | None,
    samples: int,
    mape_watch_threshold: float = 14.0,
    mape_hold_threshold: float = 9.0,
    min_samples: int = 5,
) -> str | None:
    """
    Safety Gate dựa trên MAPE chuẩn.

    Trả về action hạ bậc gợi ý: \"WATCH\" / \"HOLD\" / None (không hạ).
    """
    if mape_pct is None or int(samples) < int(min_samples):
        return None
    m = float(mape_pct)
    if m > float(mape_watch_threshold):
        return "WATCH"
    if m > float(mape_hold_threshold):
        return "HOLD"
    return None
