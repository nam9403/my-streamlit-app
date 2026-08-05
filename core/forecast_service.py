from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from core import forecast_repository
from core.forecast_metrics import mape_point_pct, mean_mape_pct


def record_forecast_snapshot(
    *,
    conn_factory: Callable[[], Any],
    utcnow_iso: Callable[[], str],
    user_id: str,
    symbol: str,
    report: dict[str, Any],
) -> None:
    fc = (report or {}).get("probabilistic_forecast") or {}
    val = (report or {}).get("valuation") or {}
    base_price = float(val.get("price") or 0.0)
    expected_price = float(fc.get("expected_price") or 0.0)
    expected_return = float(fc.get("expected_return_pct") or 0.0)
    horizon_days = int(fc.get("horizon_days") or 0)
    sym = str(symbol or "").strip().upper()
    if not sym or base_price <= 0 or expected_price <= 0 or horizon_days <= 0:
        return
    forecast_repository.insert_forecast_record(
        conn_factory=conn_factory,
        user_id=str(user_id or "default_user"),
        symbol=sym,
        created_at=utcnow_iso(),
        horizon_days=horizon_days,
        base_price=base_price,
        expected_price=expected_price,
        expected_return_pct=expected_return,
    )


def refresh_matured_forecasts(
    *,
    conn_factory: Callable[[], Any],
    parse_ts: Callable[[str], datetime | None],
    fetch_financial_snapshot_func: Callable[[str], dict[str, Any]],
    user_id: str,
    symbol: str,
    settle_realized_price_func: Callable[..., tuple[float | None, str | None]] | None = None,
) -> None:
    """
    Nghiệm thu forecast đã đáo hạn.

    Anti look-ahead: giá thực tế PHẢI là đóng cửa tại đúng due date (hoặc phiên
    giao dịch gần nhất trước đó) từ OHLCV lịch sử — không dùng giá hiện tại hôm nay.
    """
    uid = str(user_id or "default_user")
    sym = str(symbol or "").strip().upper()
    if not sym:
        return
    now = datetime.now(timezone.utc)
    rows = forecast_repository.fetch_pending_forecasts(conn_factory=conn_factory, user_id=uid, symbol=sym, limit=80)
    if not rows:
        return

    # Fallback chỉ khi không inject settle func (tests cũ); vẫn ưu tiên due-date lookup.
    snap_price_today: float | None = None

    for r in rows:
        created_at = parse_ts(str(r["created_at"]))
        if created_at is None:
            continue
        horizon_days = int(r["horizon_days"] or 0)
        if horizon_days <= 0:
            continue
        due_at = created_at + timedelta(days=horizon_days)
        if now < due_at:
            continue
        base_price = float(r["base_price"] or 0.0)
        expected_price = float(r["expected_price"] or 0.0)
        if base_price <= 0 or expected_price <= 0:
            continue

        realized_price: float | None = None
        if settle_realized_price_func is not None:
            try:
                realized_price, _as_of = settle_realized_price_func(symbol=sym, due_at=due_at)
            except TypeError:
                realized_price, _as_of = settle_realized_price_func(sym, due_at)
            except Exception:
                realized_price = None

        if realized_price is None or realized_price <= 0:
            # Không có giá lịch sử tại due date → bỏ qua (không settle bằng giá hôm nay).
            # Chỉ dùng snapshot hôm nay khi due_at là \"hôm nay\" (đáo hạn trong ngày).
            due_day = due_at.astimezone(timezone.utc).date() if due_at.tzinfo else due_at.date()
            if due_day == now.date():
                if snap_price_today is None:
                    snap = fetch_financial_snapshot_func(sym) or {}
                    snap_price_today = float(snap.get("price") or 0.0)
                if snap_price_today and snap_price_today > 0:
                    realized_price = snap_price_today
            if realized_price is None or realized_price <= 0:
                continue

        realized_ret = (float(realized_price) / base_price - 1.0) * 100.0
        expected_ret = (expected_price / base_price - 1.0) * 100.0
        # MAPE chuẩn trên giá: |Actual - Forecast| / |Actual| * 100
        abs_error = mape_point_pct(actual_price=float(realized_price), forecast_price=expected_price)
        if abs_error is None:
            continue
        direction_hit = 1 if (realized_ret >= 0 and expected_ret >= 0) or (realized_ret < 0 and expected_ret < 0) else 0
        forecast_repository.mark_forecast_resolved(
            conn_factory=conn_factory,
            row_id=int(r["id"]),
            realized_price=float(realized_price),
            realized_return_pct=realized_ret,
            abs_error_pct=float(abs_error),
            direction_hit=direction_hit,
        )


def get_forecast_accuracy_dashboard(
    *,
    conn_factory: Callable[[], Any],
    refresh_matured_forecasts_func: Callable[[str, str], None],
    user_id: str,
    symbol: str,
    lookback_days: int = 540,
) -> dict[str, Any]:
    uid = str(user_id or "default_user")
    sym = str(symbol or "").strip().upper()
    if not sym:
        return {"records": 0, "resolved": 0, "hit_rate_pct": None, "mape_pct": None, "bias_pct": None, "rows": []}
    refresh_matured_forecasts_func(uid, sym)
    since = (datetime.now(timezone.utc) - timedelta(days=max(30, int(lookback_days)))).isoformat()
    rows = forecast_repository.fetch_forecast_rows_by_symbol(
        conn_factory=conn_factory,
        user_id=uid,
        symbol=sym,
        since_iso=since,
        limit=300,
    )
    items = [dict(r) for r in rows]
    resolved = [x for x in items if str(x.get("status")) == "resolved"]
    hit_rate = None
    mape = None
    bias = None
    if resolved:
        hit_vals = [int(x.get("direction_hit") or 0) for x in resolved]
        err_vals = [float(x.get("abs_error_pct") or 0.0) for x in resolved]
        bias_vals = [float(x.get("realized_return_pct") or 0.0) - float(x.get("expected_return_pct") or 0.0) for x in resolved]
        hit_rate = round(sum(hit_vals) / len(hit_vals) * 100.0, 2)
        mape_raw = mean_mape_pct(err_vals)
        mape = None if mape_raw is None else round(mape_raw, 2)
        bias = round(sum(bias_vals) / len(bias_vals), 2)
    return {"records": len(items), "resolved": len(resolved), "hit_rate_pct": hit_rate, "mape_pct": mape, "bias_pct": bias, "rows": items[:80]}


def get_forecast_benchmark_by_horizon(
    *,
    conn_factory: Callable[[], Any],
    refresh_matured_forecasts_func: Callable[[str, str], None],
    user_id: str,
    symbol: str,
    horizons: tuple[int, ...] = (30, 60, 90),
    lookback_days: int = 720,
) -> list[dict[str, Any]]:
    uid = str(user_id or "default_user")
    sym = str(symbol or "").strip().upper()
    if not sym:
        return []
    refresh_matured_forecasts_func(uid, sym)
    since = (datetime.now(timezone.utc) - timedelta(days=max(60, int(lookback_days)))).isoformat()
    rows = forecast_repository.fetch_resolved_rows_for_benchmark(
        conn_factory=conn_factory,
        user_id=uid,
        symbol=sym,
        since_iso=since,
        limit=1000,
    )
    items = [dict(r) for r in rows if str(r["status"]) == "resolved"]
    out: list[dict[str, Any]] = []
    for h in horizons:
        grp = [x for x in items if int(x.get("horizon_days") or 0) == int(h)]
        if not grp:
            out.append({"horizon_days": int(h), "samples": 0, "hit_rate_pct": None, "mape_pct": None, "expected_return_pct_avg": None, "realized_return_pct_avg": None, "alpha_pct": None, "beat_expected_pct": None})
            continue
        n = len(grp)
        hit = sum(int(x.get("direction_hit") or 0) for x in grp) / n * 100.0
        mape = sum(float(x.get("abs_error_pct") or 0.0) for x in grp) / n
        exp_avg = sum(float(x.get("expected_return_pct") or 0.0) for x in grp) / n
        real_avg = sum(float(x.get("realized_return_pct") or 0.0) for x in grp) / n
        alpha = real_avg - exp_avg
        beat = sum(1 for x in grp if float(x.get("realized_return_pct") or 0.0) > float(x.get("expected_return_pct") or 0.0)) / n * 100.0
        out.append({"horizon_days": int(h), "samples": int(n), "hit_rate_pct": round(hit, 2), "mape_pct": round(mape, 2), "expected_return_pct_avg": round(exp_avg, 2), "realized_return_pct_avg": round(real_avg, 2), "alpha_pct": round(alpha, 2), "beat_expected_pct": round(beat, 2)})
    return out


def get_forecast_leaderboard(*, conn_factory: Callable[[], Any], user_id: str, limit: int = 20, lookback_days: int = 720) -> list[dict[str, Any]]:
    uid = str(user_id or "default_user")
    since = (datetime.now(timezone.utc) - timedelta(days=max(60, int(lookback_days)))).isoformat()
    rows = forecast_repository.fetch_resolved_rows_for_leaderboard(
        conn_factory=conn_factory,
        user_id=uid,
        since_iso=since,
        limit=3000,
    )
    items = [dict(r) for r in rows]
    if not items:
        return []
    grouped: dict[str, list[dict[str, Any]]] = {}
    for x in items:
        sym = str(x.get("symbol") or "").upper()
        if not sym:
            continue
        grouped.setdefault(sym, []).append(x)
    out: list[dict[str, Any]] = []
    for sym, grp in grouped.items():
        n = len(grp)
        if n <= 0:
            continue
        hit = sum(int(v.get("direction_hit") or 0) for v in grp) / n * 100.0
        mape = sum(float(v.get("abs_error_pct") or 0.0) for v in grp) / n
        exp_avg = sum(float(v.get("expected_return_pct") or 0.0) for v in grp) / n
        real_avg = sum(float(v.get("realized_return_pct") or 0.0) for v in grp) / n
        alpha = real_avg - exp_avg
        score = (0.55 * hit) + (0.25 * max(-20.0, min(20.0, alpha + 10.0))) - (0.6 * mape) + min(8.0, n * 0.4)
        out.append({"symbol": sym, "samples": int(n), "hit_rate_pct": round(hit, 2), "mape_pct": round(mape, 2), "alpha_pct": round(alpha, 2), "score": round(score, 2)})
    out.sort(key=lambda x: (x["score"], x["samples"]), reverse=True)
    return out[: max(5, min(int(limit), 100))]


def get_forecast_group_benchmark(
    *,
    conn_factory: Callable[[], Any],
    user_id: str,
    symbols: list[str],
    lookback_days: int = 720,
) -> dict[str, Any]:
    uid = str(user_id or "default_user")
    syms = [str(s or "").strip().upper() for s in symbols if str(s or "").strip()]
    syms = sorted(set(syms))[:80]
    if not syms:
        return {"samples": 0, "hit_rate_pct": None, "mape_pct": None, "alpha_pct": None}
    since = (datetime.now(timezone.utc) - timedelta(days=max(60, int(lookback_days)))).isoformat()
    rows = forecast_repository.fetch_group_benchmark_rows(
        conn_factory=conn_factory,
        user_id=uid,
        since_iso=since,
        symbols=syms,
        limit=4000,
    )
    items = [dict(r) for r in rows]
    if not items:
        return {"samples": 0, "hit_rate_pct": None, "mape_pct": None, "alpha_pct": None}
    n = len(items)
    hit = sum(int(x.get("direction_hit") or 0) for x in items) / n * 100.0
    mape = sum(float(x.get("abs_error_pct") or 0.0) for x in items) / n
    exp_avg = sum(float(x.get("expected_return_pct") or 0.0) for x in items) / n
    real_avg = sum(float(x.get("realized_return_pct") or 0.0) for x in items) / n
    return {"samples": int(n), "hit_rate_pct": round(hit, 2), "mape_pct": round(mape, 2), "alpha_pct": round(real_avg - exp_avg, 2)}


def get_forecast_drift_signal(
    *,
    conn_factory: Callable[[], Any],
    user_id: str,
    symbol: str,
    recent_n: int = 20,
    baseline_n: int = 60,
) -> dict[str, Any]:
    uid = str(user_id or "default_user")
    sym = str(symbol or "").strip().upper()
    if not sym:
        return {"status": "unknown", "message": "Thiếu mã cổ phiếu.", "delta_hit_pct": None, "delta_mape_pct": None}
    rows = forecast_repository.fetch_resolved_drift_rows(conn_factory=conn_factory, user_id=uid, symbol=sym, limit=400)
    items = [dict(r) for r in rows]
    if len(items) < max(12, recent_n + 6):
        return {"status": "insufficient_data", "message": "Chưa đủ dữ liệu resolved để phát hiện drift.", "delta_hit_pct": None, "delta_mape_pct": None}
    recent = items[:recent_n]
    baseline = items[recent_n : recent_n + baseline_n]
    if not baseline:
        return {"status": "insufficient_data", "message": "Thiếu baseline để so sánh drift.", "delta_hit_pct": None, "delta_mape_pct": None}
    hit_recent = sum(int(x.get("direction_hit") or 0) for x in recent) / len(recent) * 100.0
    hit_base = sum(int(x.get("direction_hit") or 0) for x in baseline) / len(baseline) * 100.0
    mape_recent = sum(float(x.get("abs_error_pct") or 0.0) for x in recent) / len(recent)
    mape_base = sum(float(x.get("abs_error_pct") or 0.0) for x in baseline) / len(baseline)
    d_hit = hit_recent - hit_base
    d_mape = mape_recent - mape_base
    status = "stable"
    msg = "Hiệu năng dự báo ổn định."
    sample_scale = min(1.0, len(items) / 120.0)
    hit_drop_th = 6.0 + (1.0 - sample_scale) * 4.0
    mape_rise_th = 2.0 + (1.0 - sample_scale) * 2.0
    hit_up_th = 5.0 + (1.0 - sample_scale) * 2.0
    mape_down_th = 1.5 + (1.0 - sample_scale) * 1.5
    if d_hit <= -hit_drop_th or d_mape >= mape_rise_th:
        status = "drift_down"
        msg = "Có dấu hiệu drift xấu: hit-rate giảm hoặc sai số tăng."
    elif d_hit >= hit_up_th and d_mape <= -mape_down_th:
        status = "improving"
        msg = "Mô hình đang cải thiện so với baseline."
    return {
        "status": status,
        "message": msg,
        "delta_hit_pct": round(d_hit, 2),
        "delta_mape_pct": round(d_mape, 2),
        "recent_hit_pct": round(hit_recent, 2),
        "recent_mape_pct": round(mape_recent, 2),
        "baseline_hit_pct": round(hit_base, 2),
        "baseline_mape_pct": round(mape_base, 2),
        "hit_drop_threshold_pct": round(hit_drop_th, 2),
        "mape_rise_threshold_pct": round(mape_rise_th, 2),
    }


def get_forecast_drift_streak(
    *,
    get_forecast_drift_signal_func: Callable[..., dict[str, Any]],
    user_id: str,
    symbol: str,
    checks: int = 3,
) -> dict[str, Any]:
    uid = str(user_id or "default_user")
    sym = str(symbol or "").strip().upper()
    if not sym:
        return {"drift_down_streak": 0, "checks": checks}
    recent_window = [14, 20, 28, 36, 44]
    recent_window = recent_window[: max(1, min(checks, len(recent_window)))]
    streak = 0
    for n in recent_window:
        sig = get_forecast_drift_signal_func(uid, sym, recent_n=n, baseline_n=max(40, n * 2))
        if str(sig.get("status")) == "drift_down":
            streak += 1
        else:
            break
    return {"drift_down_streak": streak, "checks": len(recent_window)}
