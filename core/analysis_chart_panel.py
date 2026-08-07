from __future__ import annotations

from typing import Any, Callable

import matplotlib.pyplot as plt
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from matplotlib.patches import Rectangle
from plotly.subplots import make_subplots

from core.vn_market_calendar import expected_vn_trading_days
from core.indicators import add_chart_technical_indicators


def _get_state_cache(name: str) -> dict[Any, Any]:
    cache = st.session_state.get(name)
    if isinstance(cache, dict):
        return cache
    cache = {}
    st.session_state[name] = cache
    return cache


def _normalize_ohlcv_frame(ohlcv: pd.DataFrame) -> pd.DataFrame:
    d = ohlcv.copy()
    if d.empty:
        return pd.DataFrame(columns=["date", "open", "high", "low", "close", "volume"])
    d["date"] = pd.to_datetime(d["date"], errors="coerce")
    for c in ("open", "high", "low", "close", "volume"):
        if c in d.columns:
            d[c] = pd.to_numeric(d[c], errors="coerce")
    d = d.dropna(subset=["date", "open", "high", "low", "close"]).sort_values("date").reset_index(drop=True)
    if "volume" not in d.columns:
        d["volume"] = 0.0
    return d[["date", "open", "high", "low", "close", "volume"]]


def _dataset_signature(d: pd.DataFrame) -> tuple[int, str, str]:
    if d.empty:
        return (0, "", "")
    return (len(d), str(d["date"].iloc[0]), str(d["date"].iloc[-1]))


def _merge_ohlcv_primary_with_fallback(primary: pd.DataFrame, fallback: pd.DataFrame) -> pd.DataFrame:
    """Merge two OHLCV frames by date, preferring primary values."""
    p = _normalize_ohlcv_frame(primary)
    f = _normalize_ohlcv_frame(fallback)
    if p.empty:
        return f
    if f.empty:
        return p
    p = p.set_index("date")
    f = f.set_index("date")
    combined = p.combine_first(f).reset_index()
    combined = combined.sort_values("date").reset_index(drop=True)
    combined.attrs.update(primary.attrs)
    combined.attrs["source"] = f"{primary.attrs.get('source', 'primary')}+backfill"
    return combined


def _expected_vn_trading_days(start: pd.Timestamp, end: pd.Timestamp) -> pd.DatetimeIndex:
    return expected_vn_trading_days(start, end)


def _daily_coverage_ratio(ohlcv: pd.DataFrame) -> tuple[float, int, int, list[str]]:
    """Estimate VN trading-day coverage ratio and list missing sessions."""
    d = _normalize_ohlcv_frame(ohlcv)
    if d.empty:
        return 0.0, 0, 0, []
    start = d["date"].min()
    end = d["date"].max()
    expected = _expected_vn_trading_days(start, end)
    expected_n = int(len(expected))
    actual_dates = pd.DatetimeIndex(pd.to_datetime(d["date"]).dt.normalize().unique())
    actual_n = int(len(actual_dates))
    if expected_n <= 0:
        return 1.0, actual_n, expected_n, []
    missing = sorted(set(expected.strftime("%Y-%m-%d")) - set(actual_dates.strftime("%Y-%m-%d")))
    return (actual_n / expected_n), actual_n, expected_n, missing


def _inject_chart_panel_styles() -> None:
    st.markdown(
        """
        <style>
        .chart-toolbar {
            background: rgba(148, 163, 184, 0.10);
            border: 1px solid rgba(148, 163, 184, 0.35);
            border-radius: 12px;
            padding: 8px 10px;
            margin: 4px 0 8px 0;
        }
        .chart-toolbar-title {
            font-weight: 700;
            font-size: 13px;
            margin-bottom: 4px;
            color: #475569;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def _indicator_bundle(ohlcv: pd.DataFrame) -> pd.DataFrame:
    """Normalized OHLCV + unified chart indicators from core.indicators."""
    d = _normalize_ohlcv_frame(ohlcv)
    if d.empty:
        return d
    return add_chart_technical_indicators(d)


def _build_technical_alerts(ohlcv: pd.DataFrame) -> list[str]:
    d = _indicator_bundle(ohlcv)
    if len(d) < 30:
        return ["Dữ liệu chưa đủ dài để phát hiện tín hiệu kỹ thuật mạnh (cần >= 30 nến)."]

    close = d["close"]
    ma20 = d["ma20"]
    ma50 = d["ma50"]
    rsi14 = d["rsi14"]
    macd = d["macd"]
    macd_signal = d["macd_signal"]
    macd_hist = d["macd_hist"]
    bb_upper = d["bb_upper"]
    bb_lower = d["bb_lower"]

    alerts: list[str] = []
    last = len(d) - 1
    prev = max(0, last - 1)

    # RSI alerts
    last_rsi = float(rsi14.iloc[last]) if pd.notna(rsi14.iloc[last]) else None
    if last_rsi is not None:
        if last_rsi >= 70:
            alerts.append(f"RSI(14) = {last_rsi:.1f}: vùng quá mua (cân nhắc quản trị rủi ro).")
        elif last_rsi <= 30:
            alerts.append(f"RSI(14) = {last_rsi:.1f}: vùng quá bán (theo dõi nhịp hồi).")

    # MA cross alerts
    if pd.notna(ma20.iloc[last]) and pd.notna(ma50.iloc[last]):
        if ma20.iloc[prev] <= ma50.iloc[prev] and ma20.iloc[last] > ma50.iloc[last]:
            alerts.append("Tín hiệu Golden Cross: MA20 cắt lên MA50.")
        if ma20.iloc[prev] >= ma50.iloc[prev] and ma20.iloc[last] < ma50.iloc[last]:
            alerts.append("Tín hiệu Death Cross: MA20 cắt xuống MA50.")

    # MACD alerts
    if pd.notna(macd.iloc[last]) and pd.notna(macd_signal.iloc[last]):
        if macd.iloc[prev] <= macd_signal.iloc[prev] and macd.iloc[last] > macd_signal.iloc[last]:
            alerts.append("MACD cắt lên Signal: động lượng tăng đang cải thiện.")
        if macd.iloc[prev] >= macd_signal.iloc[prev] and macd.iloc[last] < macd_signal.iloc[last]:
            alerts.append("MACD cắt xuống Signal: động lượng giảm đang chiếm ưu thế.")
    if pd.notna(macd_hist.iloc[last]) and pd.notna(macd_hist.iloc[prev]):
        if macd_hist.iloc[prev] <= 0 < macd_hist.iloc[last]:
            alerts.append("MACD Histogram chuyển dương: xác suất tạo nhịp tăng ngắn hạn cao hơn.")
        if macd_hist.iloc[prev] >= 0 > macd_hist.iloc[last]:
            alerts.append("MACD Histogram chuyển âm: cần thận trọng với rủi ro điều chỉnh.")

    # Bollinger alerts
    if pd.notna(bb_upper.iloc[last]) and pd.notna(bb_lower.iloc[last]):
        c = float(close.iloc[last])
        if c > float(bb_upper.iloc[last]):
            alerts.append("Giá đóng cửa vượt Bollinger Upper Band: breakout mạnh, dễ rung lắc cao.")
        elif c < float(bb_lower.iloc[last]):
            alerts.append("Giá đóng cửa dưới Bollinger Lower Band: suy yếu mạnh, theo dõi lực cầu hồi phục.")

    if not alerts:
        alerts.append("Chưa có tín hiệu kỹ thuật bất thường ở cây nến gần nhất.")
    return alerts


def _technical_signal_score(ohlcv: pd.DataFrame) -> tuple[int, str, list[str]]:
    """Return score (0-100), label, and reason bullets."""
    d = _indicator_bundle(ohlcv)
    if len(d) < 30:
        return 50, "WATCH", ["Dữ liệu ngắn, tín hiệu trung tính."]

    ma20 = d["ma20"]
    ma50 = d["ma50"]
    rsi14 = d["rsi14"]
    macd = d["macd"]
    macd_signal = d["macd_signal"]

    score = 50
    reasons: list[str] = []
    last = len(d) - 1
    prev = max(0, last - 1)

    if pd.notna(ma20.iloc[last]) and pd.notna(ma50.iloc[last]):
        if ma20.iloc[last] > ma50.iloc[last]:
            score += 12
            reasons.append("MA20 > MA50 (xu hướng tăng).")
        else:
            score -= 12
            reasons.append("MA20 < MA50 (xu hướng yếu).")
        if ma20.iloc[prev] <= ma50.iloc[prev] and ma20.iloc[last] > ma50.iloc[last]:
            score += 10
            reasons.append("Golden Cross mới xuất hiện.")
        if ma20.iloc[prev] >= ma50.iloc[prev] and ma20.iloc[last] < ma50.iloc[last]:
            score -= 10
            reasons.append("Death Cross mới xuất hiện.")

    if pd.notna(macd.iloc[last]) and pd.notna(macd_signal.iloc[last]):
        if macd.iloc[last] > macd_signal.iloc[last]:
            score += 10
            reasons.append("MACD > Signal.")
        else:
            score -= 10
            reasons.append("MACD < Signal.")

    if pd.notna(rsi14.iloc[last]):
        rsi = float(rsi14.iloc[last])
        if 45 <= rsi <= 65:
            score += 6
            reasons.append(f"RSI cân bằng ({rsi:.1f}).")
        elif 65 < rsi <= 78:
            score += 2
            reasons.append(f"RSI cao ({rsi:.1f}) nhưng chưa quá nóng.")
        elif rsi > 78:
            score -= 8
            reasons.append(f"RSI quá nóng ({rsi:.1f}).")
        elif rsi < 28:
            score += 4
            reasons.append(f"RSI quá bán ({rsi:.1f}), có thể hồi kỹ thuật.")
        else:
            score -= 2
            reasons.append(f"RSI yếu ({rsi:.1f}).")

    score = max(0, min(100, int(round(score))))
    if score >= 75:
        label = "STRONG BUY"
    elif score >= 60:
        label = "BUY"
    elif score >= 45:
        label = "WATCH"
    elif score >= 30:
        label = "REDUCE"
    else:
        label = "SELL"
    return score, label, reasons


def _fmt_compact_number(v: float, digits: int = 1) -> str:
    x = float(v)
    ax = abs(x)
    if ax >= 1_000_000_000:
        return f"{x/1_000_000_000:.{digits}f}B"
    if ax >= 1_000_000:
        return f"{x/1_000_000:.{digits}f}M"
    if ax >= 1_000:
        return f"{x/1_000:.{digits}f}K"
    return f"{x:.0f}"


def _resample_ohlcv(ohlcv: pd.DataFrame, timeframe: str) -> pd.DataFrame:
    """Resample OHLCV to daily/weekly/monthly candles."""
    if timeframe == "Ngày":
        return ohlcv
    if ohlcv.empty:
        return ohlcv

    freq = "W-FRI" if timeframe == "Tuần" else "ME"
    d = ohlcv.copy()
    d["date"] = pd.to_datetime(d["date"], errors="coerce")
    d = d.dropna(subset=["date"]).sort_values("date")
    if d.empty:
        return d

    d = d.set_index("date")
    agg = {
        "open": "first",
        "high": "max",
        "low": "min",
        "close": "last",
        "volume": "sum",
    }
    out = d.resample(freq).agg(agg).dropna(subset=["open", "high", "low", "close"]).reset_index()
    out.attrs.update(ohlcv.attrs)
    out.attrs["timeframe"] = timeframe
    return out


def _apply_lookback_window(ohlcv: pd.DataFrame, window: str) -> pd.DataFrame:
    """Filter OHLCV by lookback window."""
    if ohlcv.empty or window == "Tất cả":
        return ohlcv
    d = ohlcv.copy()
    d["date"] = pd.to_datetime(d["date"], errors="coerce")
    d = d.dropna(subset=["date"]).sort_values("date")
    if d.empty:
        return d
    latest = d["date"].max()
    days_map = {"3M": 92, "6M": 183, "1Y": 366, "3Y": 1096, "5Y": 1827}
    days = days_map.get(window)
    if not days:
        return d
    start = latest - pd.Timedelta(days=days)
    out = d[d["date"] >= start].copy()
    out.attrs.update(ohlcv.attrs)
    out.attrs["lookback"] = window
    return out


def _lookback_target_days(window: str) -> int | None:
    return {"3M": 92, "6M": 183, "1Y": 366, "3Y": 1096, "5Y": 1827}.get(window)


def _resolve_effective_lookback(lookback: str, raw_ohlcv: pd.DataFrame) -> tuple[str, str | None]:
    """
    Return effective lookback and optional fallback message when data depth is insufficient.
    """
    target_days = _lookback_target_days(lookback)
    if target_days is None or raw_ohlcv.empty:
        return lookback, None
    d = raw_ohlcv.copy()
    d["date"] = pd.to_datetime(d["date"], errors="coerce")
    d = d.dropna(subset=["date"]).sort_values("date")
    if d.empty:
        return lookback, None
    actual_days = int((d["date"].max() - d["date"].min()).days)
    if actual_days >= int(target_days * 0.9):
        return lookback, None
    # Preserve continuity: render full available range instead of pretending requested range exists.
    effective = "Tất cả"
    msg = (
        f"Khung `{lookback}` cần ~{target_days/365.25:.1f} năm nhưng dữ liệu hiện có "
        f"~{actual_days/365.25:.1f} năm. Tự động chuyển sang `{effective}` để hiển thị toàn bộ dữ liệu khả dụng."
    )
    return effective, msg


def _render_matplotlib_candles(
    d: pd.DataFrame,
    *,
    show_ma20: bool,
    show_ma50: bool,
    show_bollinger: bool,
    show_volume: bool,
    show_rsi: bool,
    show_macd: bool,
    theme: str,
) -> None:
    """Robust server-side candlestick rendering (independent from Plotly/browser JS)."""
    d = _indicator_bundle(d)
    close = d["close"]
    ma20 = d["ma20"]
    ma50 = d["ma50"]
    rsi14 = d["rsi14"]
    bb_upper = d["bb_upper"]
    bb_lower = d["bb_lower"]
    macd = d["macd"]
    macd_signal = d["macd_signal"]
    macd_hist = d["macd_hist"]

    rows = 1 + (1 if show_volume else 0) + (1 if show_rsi else 0) + (1 if show_macd else 0)
    if rows == 3:
        fig, axes = plt.subplots(3, 1, sharex=True, figsize=(12, 8), gridspec_kw={"height_ratios": [6, 2, 2]})
        ax_price, ax_vol, ax_rsi = axes
        ax_macd = None
    elif rows == 4:
        fig, axes = plt.subplots(4, 1, sharex=True, figsize=(12, 9), gridspec_kw={"height_ratios": [6, 2, 2, 2]})
        ax_price, ax_vol, ax_rsi, ax_macd = axes
    elif rows == 2 and show_volume:
        fig, axes = plt.subplots(2, 1, sharex=True, figsize=(12, 7), gridspec_kw={"height_ratios": [7, 2]})
        ax_price, ax_vol = axes
        ax_rsi = None
        ax_macd = None
    elif rows == 2:
        fig, axes = plt.subplots(2, 1, sharex=True, figsize=(12, 7), gridspec_kw={"height_ratios": [7, 3]})
        ax_price, ax_rsi = axes
        ax_vol = None
        ax_macd = None
    else:
        fig, ax_price = plt.subplots(1, 1, figsize=(12, 6))
        ax_vol = None
        ax_rsi = None
        ax_macd = None

    if theme == "dark":
        fig.patch.set_facecolor("#0f172a")
        ax_price.set_facecolor("#111827")
        if ax_vol is not None:
            ax_vol.set_facecolor("#111827")
        if ax_rsi is not None:
            ax_rsi.set_facecolor("#111827")
        if ax_macd is not None:
            ax_macd.set_facecolor("#111827")
        text_color = "#e5e7eb"
        grid_alpha = 0.22
    else:
        text_color = "#111827"
        grid_alpha = 0.35

    # Use ordinal trading-session axis (0..N-1) to remove weekend/holiday gaps.
    x = list(range(len(d)))
    width = 0.7

    dt_series = pd.to_datetime(d["date"])
    for i, xi in enumerate(x):
        o = float(d["open"].iloc[i])
        h = float(d["high"].iloc[i])
        low = float(d["low"].iloc[i])
        c = float(d["close"].iloc[i])
        color = "#16a34a" if c >= o else "#dc2626"
        ax_price.vlines(xi, low, h, color=color, linewidth=1.1, alpha=0.95)
        body_low = min(o, c)
        body_h = max(abs(c - o), 0.02)
        rect = Rectangle((xi - width / 2, body_low), width, body_h, facecolor=color, edgecolor=color, linewidth=1.0)
        ax_price.add_patch(rect)

    if show_ma20:
        ax_price.plot(x, ma20, color="#f59e0b", linewidth=1.4, label="MA20")
    if show_ma50:
        ax_price.plot(x, ma50, color="#0f766e", linewidth=1.4, label="MA50")
    if show_bollinger:
        ax_price.plot(x, bb_upper, color="#6366f1", linewidth=1.1, alpha=0.9, label="BB Upper")
        ax_price.plot(x, bb_lower, color="#6366f1", linewidth=1.1, alpha=0.9, label="BB Lower")
        ax_price.fill_between(x, bb_lower.to_numpy(), bb_upper.to_numpy(), color="#6366f1", alpha=0.08)
    ax_price.set_ylabel("Giá")
    ax_price.grid(True, linestyle="--", linewidth=0.4, alpha=grid_alpha)
    ax_price.legend(loc="upper left", fontsize=9, ncol=3)
    ax_price.tick_params(colors=text_color)
    ax_price.yaxis.label.set_color(text_color)

    if show_volume and ax_vol is not None:
        bar_colors = ["#16a34a" if c >= o else "#dc2626" for o, c in zip(d["open"], d["close"])]
        ax_vol.bar(x, d["volume"], color=bar_colors, alpha=0.7, width=0.8)
        ax_vol.set_ylabel("Vol")
        ax_vol.grid(True, linestyle="--", linewidth=0.35, alpha=grid_alpha)
        ax_vol.tick_params(colors=text_color)
        ax_vol.yaxis.label.set_color(text_color)

    if show_rsi and ax_rsi is not None:
        ax_rsi.plot(x, rsi14, color="#ea580c", linewidth=1.4)
        ax_rsi.axhline(30, color="#ef4444", linestyle="--", linewidth=1.0)
        ax_rsi.axhline(70, color="#ef4444", linestyle="--", linewidth=1.0)
        ax_rsi.set_ylim(0, 100)
        ax_rsi.set_ylabel("RSI")
        ax_rsi.grid(True, linestyle="--", linewidth=0.35, alpha=grid_alpha)
        ax_rsi.tick_params(colors=text_color)
        ax_rsi.yaxis.label.set_color(text_color)

    if show_macd and ax_macd is not None:
        hist_colors = ["#16a34a" if v >= 0 else "#dc2626" for v in macd_hist]
        ax_macd.bar(x, macd_hist, color=hist_colors, alpha=0.55, width=0.8)
        ax_macd.plot(x, macd, color="#60a5fa", linewidth=1.2, label="MACD")
        ax_macd.plot(x, macd_signal, color="#f59e0b", linewidth=1.2, label="Signal")
        ax_macd.axhline(0, color="#9ca3af", linewidth=1.0, alpha=0.8)
        ax_macd.set_ylabel("MACD")
        ax_macd.grid(True, linestyle="--", linewidth=0.35, alpha=grid_alpha)
        ax_macd.tick_params(colors=text_color)
        ax_macd.yaxis.label.set_color(text_color)
        ax_macd.legend(loc="upper left", fontsize=8, ncol=2)

    tick_step = max(1, len(d) // 8)
    ticks = list(range(0, len(d), tick_step))
    if ticks[-1] != len(d) - 1:
        ticks.append(len(d) - 1)
    tick_labels = [dt_series.iloc[t].strftime("%Y-%m-%d") for t in ticks]
    target_ax = ax_macd if ax_macd is not None else (ax_rsi if ax_rsi is not None else (ax_vol if ax_vol is not None else ax_price))
    target_ax.set_xticks(ticks)
    target_ax.set_xticklabels(tick_labels, rotation=0, fontsize=8)
    fig.autofmt_xdate(rotation=0)
    plt.tight_layout()
    st.pyplot(fig, use_container_width=True)
    plt.close(fig)


def render_candlestick_with_intrinsic(
    ohlcv: pd.DataFrame,
    valuation: dict[str, Any],
    *,
    show_mos_zone: bool = True,
    show_ma20: bool = True,
    show_ma50: bool = True,
    show_bollinger: bool = False,
    show_rsi: bool = True,
    show_volume: bool = True,
    show_macd: bool = False,
    compatibility_mode: bool = False,
    chart_engine: str = "plotly",
    theme: str = "light",
) -> None:
    d = ohlcv.copy()
    d["date"] = pd.to_datetime(d["date"], errors="coerce")
    for c in ("open", "high", "low", "close", "volume"):
        if c in d.columns:
            d[c] = pd.to_numeric(d[c], errors="coerce")
    d = d.dropna(subset=["date", "open", "high", "low", "close"]).sort_values("date").reset_index(drop=True)
    if d.empty:
        st.warning("Dữ liệu OHLCV rỗng sau làm sạch.")
        return

    if chart_engine == "matplotlib":
        _render_matplotlib_candles(
            d,
            show_ma20=show_ma20,
            show_ma50=show_ma50,
            show_bollinger=show_bollinger,
            show_volume=show_volume,
            show_rsi=show_rsi,
            show_macd=show_macd,
            theme=theme,
        )
        src = str(ohlcv.attrs.get("source") or "")
        if src in ("disk_cache", "disk_cache_fastpath"):
            st.caption(f"OHLCV từ cache đĩa (source={src}, saved_at={ohlcv.attrs.get('saved_at', 'unknown')}).")
        elif src:
            st.caption(f"OHLCV source: {src}")
        else:
            st.caption("OHLCV source: unknown")
        return

    intrinsic = float(valuation.get("composite_target_price") or valuation.get("intrinsic_value_graham") or 0)
    ind = add_chart_technical_indicators(d)
    close = ind["close"]
    median_close = float(close.median()) if not close.empty else 0.0
    intrinsic_for_plot = intrinsic
    if intrinsic_for_plot > 0 and median_close > 0:
        ratio = intrinsic_for_plot / median_close
        # Prevent valuation overlays from blowing out Y-axis scale and hiding candles.
        if ratio < 0.2 or ratio > 5.0:
            intrinsic_for_plot = 0.0
    ma20 = ind["ma20"]
    ma50 = ind["ma50"]
    rsi14 = ind["rsi14"]
    macd_line = ind["macd"]
    macd_signal = ind["macd_signal"]
    macd_hist = ind["macd_hist"]

    # Build a robust y-range for price subplot to avoid outliers flattening candles.
    price_vals = pd.concat([d["open"], d["high"], d["low"], d["close"]], axis=0)
    price_vals = pd.to_numeric(price_vals, errors="coerce").dropna()
    y_min: float | None = None
    y_max: float | None = None
    if not price_vals.empty:
        q01 = float(price_vals.quantile(0.01))
        q99 = float(price_vals.quantile(0.99))
        if q99 <= q01:
            q01 = float(price_vals.min())
            q99 = float(price_vals.max())
        span = max(q99 - q01, max(abs(q99), 1.0) * 0.03)
        pad = span * 0.08
        y_min = q01 - pad
        y_max = q99 + pad

    mos_series = pd.Series(0.0, index=d.index)
    if intrinsic_for_plot > 0:
        mos_series = ((intrinsic_for_plot - close) / intrinsic_for_plot) * 100.0
    mos_safe = (mos_series >= 20.0) & (close < intrinsic_for_plot if intrinsic_for_plot > 0 else False)
    hover_text: list[str] = []
    for i, row in d.iterrows():
        mos_text = f"{float(mos_series.iloc[i]):.1f}%" if intrinsic > 0 else "N/A"
        hover_text.append(
            f"O:{float(row['open']):.2f}<br>"
            f"H:{float(row['high']):.2f}<br>"
            f"L:{float(row['low']):.2f}<br>"
            f"C:{float(row['close']):.2f}<br>"
            f"Biên an toàn hiện tại: {mos_text}"
        )

    if compatibility_mode:
        base = d[["date", "close"]].copy().rename(columns={"date": "Ngày", "close": "Giá đóng cửa"})
        if show_ma20:
            base["MA20"] = ma20
        if show_ma50:
            base["MA50"] = ma50
        base = base.set_index("Ngày")
        st.line_chart(base, use_container_width=True)
        if show_volume and "volume" in d.columns:
            vol_df = pd.DataFrame({"Ngày": d["date"], "Volume": d["volume"]}).set_index("Ngày")
            st.bar_chart(vol_df, use_container_width=True)
        if show_rsi:
            rsi_df = pd.DataFrame({"Ngày": d["date"], "RSI (14)": rsi14}).set_index("Ngày")
            st.line_chart(rsi_df, use_container_width=True)
        st.caption("Đang dùng chế độ tương thích: line chart (ổn định hơn trên một số máy/browser).")
        src = str(ohlcv.attrs.get("source") or "")
        if src in ("disk_cache", "disk_cache_fastpath"):
            st.caption(f"OHLCV từ cache đĩa (source={src}, saved_at={ohlcv.attrs.get('saved_at', 'unknown')}).")
        elif src:
            st.caption(f"OHLCV source: {src}")
        else:
            st.caption("OHLCV source: unknown")
        return

    price_row = 1
    next_row = 2
    volume_row = None
    rsi_row = None
    macd_row = None
    if show_volume:
        volume_row = next_row
        next_row += 1
    if show_rsi:
        rsi_row = next_row
        next_row += 1
    if show_macd:
        macd_row = next_row
        next_row += 1
    rows = next_row - 1
    if rows == 4:
        row_heights = [0.54, 0.16, 0.15, 0.15]
        vertical_spacing = 0.03
    elif rows == 3:
        row_heights = [0.62, 0.18, 0.20]
        vertical_spacing = 0.04
    elif rows == 2 and show_volume:
        row_heights = [0.78, 0.22]
        vertical_spacing = 0.04
    elif rows == 2:
        row_heights = [0.72, 0.28]
        vertical_spacing = 0.06
    else:
        row_heights = [1.0]
        vertical_spacing = 0.02
    fig = make_subplots(
        rows=rows,
        cols=1,
        shared_xaxes=True,
        vertical_spacing=vertical_spacing,
        row_heights=row_heights,
    )
    fig.add_trace(
        go.Candlestick(
            x=d["date"],
            open=d["open"],
            high=d["high"],
            low=d["low"],
            close=d["close"],
            name="Giá thị trường",
            increasing_line_color="#16a34a",
            decreasing_line_color="#dc2626",
            increasing_fillcolor="#22c55e",
            decreasing_fillcolor="#ef4444",
            whiskerwidth=0.7,
            opacity=1.0,
            text=hover_text,
            hoverinfo="x+text+name",
        ),
        row=price_row,
        col=1,
    )
    axis_line_color = "#9ca3af" if theme == "dark" else "#6b7280"
    x_grid_color = "#334155" if theme == "dark" else "#e5e7eb"
    y_grid_color = "#475569" if theme == "dark" else "#d1d5db"
    spike_color = "#94a3b8" if theme == "dark" else "#9ca3af"
    if show_ma20:
        fig.add_trace(
            go.Scatter(
                x=d["date"],
                y=ma20,
                mode="lines",
                name="MA20",
                line={"width": 1.8, "color": "#f59e0b"},
            ),
            row=price_row,
            col=1,
        )
    if show_ma50:
        fig.add_trace(
            go.Scatter(
                x=d["date"],
                y=ma50,
                mode="lines",
                name="MA50",
                line={"width": 1.8, "color": "#0f766e"},
            ),
            row=price_row,
            col=1,
        )
    if show_bollinger:
        bb_mid = close.rolling(20, min_periods=10).mean()
        bb_std = close.rolling(20, min_periods=10).std()
        bb_upper = bb_mid + (2.0 * bb_std)
        bb_lower = bb_mid - (2.0 * bb_std)
        fig.add_trace(
            go.Scatter(
                x=d["date"],
                y=bb_upper,
                mode="lines",
                name="BB Upper",
                line={"width": 1.1, "color": "#6366f1"},
            ),
            row=price_row,
            col=1,
        )
        fig.add_trace(
            go.Scatter(
                x=d["date"],
                y=bb_lower,
                mode="lines",
                name="BB Lower",
                line={"width": 1.1, "color": "#6366f1"},
                fill="tonexty",
                fillcolor="rgba(99,102,241,0.10)",
            ),
            row=price_row,
            col=1,
        )
    if intrinsic_for_plot > 0:
        fig.add_trace(
            go.Scatter(
                x=d["date"],
                y=[intrinsic_for_plot] * len(d),
                mode="lines",
                name="Giá trị nội tại",
                line={"dash": "dot", "width": 2.4, "color": "#7c3aed"},
            ),
            row=price_row,
            col=1,
        )
        if show_mos_zone:
            safe_close = d["close"].where(mos_safe)
            safe_intrinsic = pd.Series([intrinsic_for_plot] * len(d)).where(mos_safe)
            fig.add_trace(
                go.Scatter(
                    x=d["date"],
                    y=safe_close,
                    mode="lines",
                    line={"width": 0, "color": "rgba(34,197,94,0.00)"},
                    showlegend=False,
                    hoverinfo="skip",
                ),
                row=price_row,
                col=1,
            )
            fig.add_trace(
                go.Scatter(
                    x=d["date"],
                    y=safe_intrinsic,
                    mode="lines",
                    line={"width": 0, "color": "rgba(34,197,94,0.00)"},
                    fill="tonexty",
                    fillcolor="rgba(34,197,94,0.20)",
                    name="Vùng MOS >= 20%",
                    hoverinfo="skip",
                ),
                row=price_row,
                col=1,
            )

    if show_volume and volume_row is not None and "volume" in d.columns:
        bar_colors = ["#16a34a" if c >= o else "#dc2626" for o, c in zip(d["open"], d["close"])]
        fig.add_trace(
            go.Bar(
                x=d["date"],
                y=d["volume"],
                name="Khối lượng",
                marker_color=bar_colors,
                opacity=0.65,
            ),
            row=volume_row,
            col=1,
        )

    if show_rsi:
        fig.add_trace(
            go.Scatter(
                x=d["date"],
                y=rsi14,
                mode="lines",
                name="RSI (14)",
                line={"width": 2.2, "color": "#ea580c"},
            ),
            row=rsi_row,
            col=1,
        )
        fig.add_hline(y=30, line_dash="dot", line_color="#ef4444", row=rsi_row, col=1)
        fig.add_hline(y=70, line_dash="dot", line_color="#ef4444", row=rsi_row, col=1)
    if show_macd and macd_row is not None:
        hist_colors = ["#16a34a" if v >= 0 else "#dc2626" for v in macd_hist]
        fig.add_trace(
            go.Bar(
                x=d["date"],
                y=macd_hist,
                name="MACD Hist",
                marker_color=hist_colors,
                opacity=0.55,
            ),
            row=macd_row,
            col=1,
        )
        fig.add_trace(
            go.Scatter(
                x=d["date"],
                y=macd_line,
                mode="lines",
                name="MACD",
                line={"width": 1.4, "color": "#60a5fa"},
            ),
            row=macd_row,
            col=1,
        )
        fig.add_trace(
            go.Scatter(
                x=d["date"],
                y=macd_signal,
                mode="lines",
                name="MACD Signal",
                line={"width": 1.3, "color": "#f59e0b"},
            ),
            row=macd_row,
            col=1,
        )
    fig.update_yaxes(title_text="Giá", row=price_row, col=1)
    if y_min is not None and y_max is not None and y_max > y_min:
        fig.update_yaxes(range=[y_min, y_max], row=price_row, col=1)
    if show_volume and volume_row is not None:
        fig.update_yaxes(title_text="Vol", row=volume_row, col=1)
    if show_rsi:
        fig.update_yaxes(title_text="RSI", range=[0, 100], row=rsi_row, col=1)
    if show_macd and macd_row is not None:
        fig.update_yaxes(title_text="MACD", row=macd_row, col=1)
    fig.update_layout(
        height=860 if rows == 4 else (760 if rows == 3 else (660 if rows == 2 else 520)),
        xaxis_rangeslider_visible=False,
        template="plotly_dark" if theme == "dark" else "plotly_white",
        plot_bgcolor="#111827" if theme == "dark" else "#f8fafc",
        paper_bgcolor="#0f172a" if theme == "dark" else "#ffffff",
        font={"color": "#e5e7eb" if theme == "dark" else "#111827"},
        legend={"orientation": "h", "yanchor": "bottom", "y": 1.01, "xanchor": "left", "x": 0.0},
        hovermode="x unified",
        hoverdistance=60,
        spikedistance=1000,
        margin={"l": 10, "r": 10, "t": 20, "b": 10},
    )
    fig.update_xaxes(
        showgrid=True,
        gridcolor=x_grid_color,
        zeroline=False,
        showline=True,
        linecolor=axis_line_color,
        ticks="outside",
        showspikes=True,
        spikemode="across",
        spikesnap="cursor",
        spikecolor=spike_color,
        spikethickness=1,
        rangeslider_visible=False,
        rangeselector={
            "buttons": [
                {"count": 1, "label": "1M", "step": "month", "stepmode": "backward"},
                {"count": 3, "label": "3M", "step": "month", "stepmode": "backward"},
                {"count": 6, "label": "6M", "step": "month", "stepmode": "backward"},
                {"count": 1, "label": "1Y", "step": "year", "stepmode": "backward"},
                {"step": "all", "label": "All"},
            ]
        },
        rangebreaks=[{"bounds": ["sat", "mon"]}],
    )
    fig.update_yaxes(
        showgrid=True,
        gridcolor=y_grid_color,
        zeroline=False,
        showline=True,
        linecolor=axis_line_color,
        ticks="outside",
        side="right",
        showspikes=True,
        spikemode="across",
        spikesnap="cursor",
        spikecolor=spike_color,
        spikethickness=1,
    )
    last_price = float(d["close"].iloc[-1])
    fig.add_hline(
        y=last_price,
        line_dash="dot",
        line_color="#f43f5e",
        annotation_text=f"{last_price:,.2f}",
        annotation_position="right",
        row=price_row,
        col=1,
    )
    try:
        st.plotly_chart(fig, use_container_width=True)
    except Exception as exc:
        st.warning(f"Plotly render lỗi, chuyển sang biểu đồ dự phòng. Chi tiết: {exc}")
        fallback = d[["date", "close"]].copy().rename(columns={"date": "Ngày", "close": "Giá đóng cửa"})
        if not fallback.empty:
            fallback = fallback.set_index("Ngày")
            st.line_chart(fallback, use_container_width=True)
        else:
            st.warning("Không có dữ liệu dự phòng để hiển thị biểu đồ.")
    if intrinsic > 0 and intrinsic_for_plot <= 0 and median_close > 0:
        st.caption(
            f"Tạm ẩn đường giá trị nội tại vì lệch lớn so với giá thị trường "
            f"(intrinsic={intrinsic:,.0f}, median_close={median_close:,.2f})."
        )
    if y_min is not None and y_max is not None:
        st.caption(f"Dải giá hiển thị: {y_min:,.2f} -> {y_max:,.2f}")
    src = str(ohlcv.attrs.get("source") or "")
    if src in ("disk_cache", "disk_cache_fastpath"):
        st.caption(f"OHLCV từ cache đĩa (source={src}, saved_at={ohlcv.attrs.get('saved_at', 'unknown')}).")
    elif src:
        st.caption(f"OHLCV source: {src}")
    else:
        st.caption("OHLCV source: unknown")


def fetch_ohlcv_yfinance_fallback(symbol: str, sessions: int = 200) -> pd.DataFrame:
    try:
        import yfinance as yf  # type: ignore
    except Exception:
        return pd.DataFrame(columns=["date", "open", "high", "low", "close", "volume"])
    candidates = [symbol.upper(), f"{symbol.upper()}.VN", f"{symbol.upper()}.HM"]
    for t in candidates:
        try:
            hist = yf.Ticker(t).history(period="5y", interval="1d")
            if hist is None or hist.empty:
                continue
            out = hist.reset_index().rename(
                columns={
                    "Date": "date",
                    "Open": "open",
                    "High": "high",
                    "Low": "low",
                    "Close": "close",
                    "Volume": "volume",
                }
            )
            out = out[["date", "open", "high", "low", "close", "volume"]].tail(max(260, sessions)).copy()
            out.attrs["source"] = "yfinance_fallback"
            return out
        except Exception:
            continue
    return pd.DataFrame(columns=["date", "open", "high", "low", "close", "volume"])


def render_analysis_chart_tab(
    ticker: str,
    report: dict[str, Any],
    valuation: dict[str, Any],
    ohlcv: pd.DataFrame,
    *,
    fetch_ohlcv_history: Callable[..., pd.DataFrame],
) -> None:
    c1, c2 = st.columns([2, 1])
    with c1:
        _inject_chart_panel_styles()
        ticker_key = str(ticker or "").upper().strip()
        raw_cache = _get_state_cache("_chart_raw_ohlcv_cache")
        prepared_cache = _get_state_cache("_chart_prepared_ohlcv_cache")

        chart_mode = st.selectbox(
            "Kiểu biểu đồ",
            options=["Nến chuyên nghiệp (ổn định)", "Nến Plotly", "Đường tương thích (máy yếu/kén Plotly)"],
            index=0,
        )
        st.markdown(f"#### {ticker_key} · Biểu đồ kỹ thuật")
        st.markdown('<div class="chart-toolbar"><div class="chart-toolbar-title">Bảng điều khiển nhanh</div></div>', unsafe_allow_html=True)
        if "_chart_timeframe_sel" not in st.session_state:
            st.session_state["_chart_timeframe_sel"] = "Ngày"
        if "_chart_lookback_sel" not in st.session_state:
            st.session_state["_chart_lookback_sel"] = "1Y"

        st.caption("Chuyển nhanh")
        quick_map = {
            "1D": ("Ngày", "3M"),
            "1W": ("Tuần", "1Y"),
            "1M": ("Tháng", "5Y"),
            "3M": ("Ngày", "3M"),
            "6M": ("Ngày", "6M"),
            "1Y": ("Ngày", "1Y"),
            "3Y": ("Tuần", "3Y"),
            "ALL": ("Tháng", "Tất cả"),
        }
        quick_cols = st.columns(len(quick_map))
        for idx, (label, (tf_val, lb_val)) in enumerate(quick_map.items()):
            if quick_cols[idx].button(label, key=f"_chart_quick_{label}", use_container_width=True):
                st.session_state["_chart_timeframe_sel"] = tf_val
                st.session_state["_chart_lookback_sel"] = lb_val
                st.rerun()

        ctl1, ctl2 = st.columns(2)
        with ctl1:
            timeframe = st.radio(
                "Khung thời gian",
                options=["Ngày", "Tuần", "Tháng"],
                key="_chart_timeframe_sel",
                horizontal=True,
            )
        with ctl2:
            lookback = st.radio(
                "Khoảng xem",
                options=["3M", "6M", "1Y", "3Y", "5Y", "Tất cả"],
                key="_chart_lookback_sel",
                horizontal=True,
            )
        show_mos_zone = st.toggle("Hiển thị vùng MOS >= 20%", value=True)
        show_ma20 = st.toggle("Hiển thị MA20", value=True)
        show_ma50 = st.toggle("Hiển thị MA50", value=True)
        show_bollinger = st.toggle("Hiển thị Bollinger Bands", value=True)
        show_volume = st.toggle("Hiển thị khối lượng", value=True)
        show_rsi = st.toggle("Hiển thị RSI(14)", value=True)
        show_macd = st.toggle("Hiển thị MACD", value=False)
        theme = st.selectbox("Giao diện chart", options=["light", "dark"], index=0)
        compatibility_mode = chart_mode == "Đường tương thích (máy yếu/kén Plotly)"
        chart_engine = "matplotlib" if chart_mode == "Nến chuyên nghiệp (ổn định)" else "plotly"
        min_sessions_by_lookback = {"3M": 70, "6M": 140, "1Y": 280, "3Y": 800, "5Y": 1300, "Tất cả": 1300}
        min_required_sessions = int(min_sessions_by_lookback.get(lookback, 280))

        ohlcv_to_plot = _normalize_ohlcv_frame(ohlcv)
        if not ohlcv_to_plot.empty:
            raw_cache[ticker_key] = ohlcv_to_plot.copy()
            cov_ratio, actual_n, expected_n, missing_days = _daily_coverage_ratio(ohlcv_to_plot)
            if cov_ratio < 0.78:
                fallback = fetch_ohlcv_yfinance_fallback(ticker, sessions=1300)
                merged = _merge_ohlcv_primary_with_fallback(ohlcv_to_plot, fallback)
                new_ratio, _, _, _ = _daily_coverage_ratio(merged)
                if new_ratio > cov_ratio:
                    ohlcv_to_plot = merged
                    raw_cache[ticker_key] = ohlcv_to_plot.copy()
            if len(ohlcv_to_plot) < min_required_sessions:
                try:
                    extended = fetch_ohlcv_history(ticker, sessions=1300)
                    extended = _normalize_ohlcv_frame(extended)
                    if not extended.empty:
                        ohlcv_to_plot = _merge_ohlcv_primary_with_fallback(extended, ohlcv_to_plot)
                        raw_cache[ticker_key] = ohlcv_to_plot.copy()
                except Exception:
                    pass
        elif ticker_key in raw_cache:
            ohlcv_to_plot = raw_cache[ticker_key].copy()

        if ohlcv_to_plot.empty:
            try:
                ohlcv_to_plot = fetch_ohlcv_history(ticker, sessions=1300)
            except Exception:
                ohlcv_to_plot = pd.DataFrame(columns=["date", "open", "high", "low", "close", "volume"])
            ohlcv_to_plot = _normalize_ohlcv_frame(ohlcv_to_plot)
        if ohlcv_to_plot.empty:
            ohlcv_to_plot = fetch_ohlcv_yfinance_fallback(ticker, sessions=1300)
            ohlcv_to_plot = _normalize_ohlcv_frame(ohlcv_to_plot)
        if not ohlcv_to_plot.empty:
            raw_cache[ticker_key] = ohlcv_to_plot.copy()

        if not ohlcv_to_plot.empty:
            import time
            render_start = time.perf_counter()
            raw_daily_for_quality = ohlcv_to_plot.copy()
            data_sig = _dataset_signature(ohlcv_to_plot)
            prepared_key = (ticker_key, timeframe, lookback, data_sig)
            cached_prepared = prepared_cache.get(prepared_key)
            if isinstance(cached_prepared, pd.DataFrame):
                ohlcv_to_plot = cached_prepared.copy()
            else:
                effective_lookback, fallback_msg = _resolve_effective_lookback(lookback, ohlcv_to_plot)
                ohlcv_to_plot = _resample_ohlcv(ohlcv_to_plot, timeframe)
                ohlcv_to_plot = _apply_lookback_window(ohlcv_to_plot, effective_lookback)
                prepared_cache[prepared_key] = ohlcv_to_plot.copy()
                if fallback_msg:
                    st.info(fallback_msg)

            st.caption(f"Dữ liệu chart cache: {ticker_key} | {timeframe} | {lookback} | {len(ohlcv_to_plot)} nến")
            target_days = _lookback_target_days(lookback)
            if target_days is not None and not ohlcv_to_plot.empty:
                actual_days = int((ohlcv_to_plot["date"].max() - ohlcv_to_plot["date"].min()).days)
                # Guardrail: for some symbols, upstream providers only return ~2.7Y.
                # Show explicit message instead of silently displaying a short series.
                if actual_days < int(target_days * 0.9):
                    actual_years = actual_days / 365.25
                    expected_years = target_days / 365.25
                    st.warning(
                        f"Dữ liệu thực tế hiện có ~{actual_years:.1f} năm, thấp hơn mức "
                        f"yêu cầu ~{expected_years:.1f} năm cho khung `{lookback}`. "
                        "Ứng dụng vẫn hiển thị tối đa dữ liệu khả dụng để tránh lỗi biểu đồ."
                    )
            cov_ratio, actual_n, expected_n, missing_days = _daily_coverage_ratio(raw_daily_for_quality)
            st.caption(f"Độ phủ phiên ngày: {cov_ratio*100:.1f}% ({actual_n}/{expected_n} phiên kinh doanh)")
            if missing_days:
                sample = ", ".join(missing_days[:6])
                tail = "..." if len(missing_days) > 6 else ""
                st.caption(f"Phiên thiếu (VN market calendar): {sample}{tail}")
            if len(ohlcv_to_plot) > 0:
                last = ohlcv_to_plot.iloc[-1]
                prev_close = float(ohlcv_to_plot["close"].iloc[-2]) if len(ohlcv_to_plot) > 1 else float(last["close"])
                change = float(last["close"]) - prev_close
                pct = (change / prev_close * 100.0) if prev_close else 0.0
                r1c1, r1c2, r1c3 = st.columns(3)
                r1c1.metric("Mở cửa", _fmt_compact_number(float(last["open"])))
                r1c2.metric("Cao", _fmt_compact_number(float(last["high"])))
                r1c3.metric("Thấp", _fmt_compact_number(float(last["low"])))
                r2c1, r2c2 = st.columns(2)
                r2c1.metric("Đóng", _fmt_compact_number(float(last["close"])), delta=f"{change:+,.2f} ({pct:+.2f}%)")
                r2c2.metric("KL", _fmt_compact_number(float(last["volume"])))
            render_candlestick_with_intrinsic(
                ohlcv_to_plot,
                report.get("valuation", valuation),
                show_mos_zone=show_mos_zone,
                show_ma20=show_ma20,
                show_ma50=show_ma50,
                show_bollinger=show_bollinger,
                show_volume=show_volume,
                show_rsi=show_rsi,
                show_macd=show_macd,
                compatibility_mode=compatibility_mode,
                chart_engine=chart_engine,
                theme=theme,
            )
            with st.expander("Tín hiệu kỹ thuật tự động", expanded=False):
                for msg in _build_technical_alerts(ohlcv_to_plot):
                    st.markdown(f"- {msg}")
            score, label, reasons = _technical_signal_score(ohlcv_to_plot)
            score_ratio = min(max(score / 100.0, 0.0), 1.0)
            st.progress(score_ratio, text=f"Điểm tín hiệu kỹ thuật: {score}/100 · {label}")
            with st.expander("Giải thích điểm tín hiệu", expanded=False):
                for r in reasons:
                    st.markdown(f"- {r}")
            render_ms = (time.perf_counter() - render_start) * 1000.0
            st.caption(f"Tốc độ render: {render_ms:.1f} ms")
        else:
            st.warning("Chưa lấy được OHLCV để vẽ nến. Kiểm tra kết nối dữ liệu hoặc bấm phân tích lại.")
    with c2:
        phase = report.get("phase", {})
        st.metric("Pha hiện tại", str(phase.get("phase", "neutral")).upper())
        st.caption(phase.get("reason", ""))
        vm = float((phase.get("metrics") or {}).get("vol_multiple") or 0)
        st.progress(min(max(vm / 2.0, 0.0), 1.0), text=f"Volume multiple: {vm:.2f}")
