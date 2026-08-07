"""
Decision Card — modern data-dashboard presentation (Streamlit HTML/CSS).

Presentation only: no valuation / gate / F-Score logic changes.
Streamlit cannot host Tailwind/Ant; we inject a self-contained design system.
"""

from __future__ import annotations

import html
import re
from typing import Any

import streamlit as st


def _compact_html(raw: str) -> str:
    """
    Streamlit st.markdown tách block theo dòng trống và escape HTML phía sau —
    phải gộp thành một khối HTML liền mạch.
    """
    s = str(raw or "")
    s = re.sub(r"[ \t]+\n", "\n", s)
    s = re.sub(r"\n\s*\n+", "\n", s)
    return s.strip()


def sanitize_close_series_for_chart(
    closes: list[float] | None,
    dates: list[Any] | None = None,
    *,
    max_day_change_pct: float = 35.0,
) -> tuple[list[float], list[Any]]:
    """
    Drop unit-break / spike outliers (vd. 3.5 lẫn trong series ~23_000).

    Keeps dates aligned with surviving closes.
    """
    series: list[float] = []
    date_objs: list[Any] = []
    raw_dates = list(dates or [])
    for i, v in enumerate(closes or []):
        try:
            f = float(v)
        except (TypeError, ValueError):
            continue
        if not (f == f and f > 0):
            continue
        series.append(f)
        date_objs.append(raw_dates[i] if i < len(raw_dates) else None)

    if len(series) < 2:
        return series, date_objs

    # Drop impossible day-to-day jumps (unit mix / bad ticks).
    kept_s: list[float] = [series[0]]
    kept_d: list[Any] = [date_objs[0]]
    for i in range(1, len(series)):
        prev = kept_s[-1]
        cur = series[i]
        if prev <= 0:
            continue
        chg = abs(cur - prev) / prev * 100.0
        if chg > float(max_day_change_pct):
            # Skip spike; do not update "prev" to the bad tick.
            continue
        kept_s.append(cur)
        kept_d.append(date_objs[i])

    series, date_objs = kept_s, kept_d
    if len(series) < 2:
        return series, date_objs

    # Scale cluster around recent median (handles mixed thousand vs absolute units).
    tail = series[-min(60, len(series)) :]
    med = sorted(tail)[len(tail) // 2]
    if med > 0:
        clustered_s: list[float] = []
        clustered_d: list[Any] = []
        for v, d in zip(series, date_objs):
            ratio = v / med
            if 0.25 <= ratio <= 4.0:
                clustered_s.append(v)
                clustered_d.append(d)
        if len(clustered_s) >= max(2, int(len(series) * 0.7)):
            series, date_objs = clustered_s, clustered_d

    return series, date_objs


def inject_decision_dashboard_css() -> None:
    css = _compact_html(
        """
<style>
@import url('https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@500;600;700;800&display=swap');
.ii-dd {
  font-family: "Plus Jakarta Sans", "Segoe UI", sans-serif;
  color: #0f172a;
  --ii-orange: #ea580c;
  --ii-green: #16a34a;
  --ii-red: #dc2626;
  --ii-amber: #b45309;
  --ii-muted: #64748b;
  --ii-radius: 18px;
  --ii-shadow: 0 8px 24px rgba(15, 23, 42, 0.07);
}
.ii-dd * { box-sizing: border-box; }
.ii-dd-shell {
  background: linear-gradient(180deg, #f8fafc 0%, #eef2f7 100%);
  border-radius: 22px;
  padding: 18px 16px 14px 16px;
  border: 1px solid #e2e8f0;
}
.ii-dd-header {
  display: flex; flex-wrap: wrap; gap: 16px; justify-content: space-between;
  align-items: flex-start; margin-bottom: 14px;
}
.ii-dd-hero {
  display: grid;
  grid-template-columns: minmax(0, 0.92fr) minmax(280px, 1.35fr);
  gap: 16px;
  align-items: start;
  margin-bottom: 14px;
}
.ii-dd-hero-right {
  display: flex; flex-direction: column; gap: 10px; align-items: stretch; min-width: 0;
}
.ii-dd-hero-right .ii-dd-badge { align-self: flex-end; }
.ii-dd-chart {
  background: #fff; border: 1px solid #e2e8f0; border-radius: 14px;
  padding: 10px 12px 8px; box-shadow: 0 4px 12px rgba(15,23,42,0.04);
  min-height: 248px;
}
.ii-dd-chart .clbl {
  font-size: 0.78rem; font-weight: 650; color: var(--ii-muted);
  text-transform: uppercase; letter-spacing: 0.03em; margin-bottom: 4px;
}
.ii-dd-chart .cmeta {
  display: flex; flex-wrap: wrap; gap: 8px 12px; align-items: center;
  margin-bottom: 6px; font-size: 0.78rem; font-weight: 650; color: #64748b;
}
.ii-dd-chart .cmeta .up { color: #15803d; }
.ii-dd-chart .cmeta .down { color: #b91c1c; }
.ii-dd-chart .cmeta .dot {
  display: inline-block; width: 8px; height: 8px; border-radius: 999px; margin-right: 4px;
}
.ii-dd-chart .cmeta .dot.up { background: #16a34a; }
.ii-dd-chart .cmeta .dot.down { background: #dc2626; }
.ii-dd-chart svg { width: 100%; height: 210px; display: block; }
.ii-dd-chart-empty {
  display: flex; align-items: center; justify-content: center;
  min-height: 210px; color: var(--ii-muted); font-size: 0.9rem; font-weight: 600;
}
.ii-dd-brand-row { display: flex; align-items: center; gap: 14px; }
.ii-dd-avatar {
  width: 56px; height: 56px; border-radius: 16px;
  background: linear-gradient(135deg, #fb923c, #ea580c);
  color: #fff; font-weight: 800; font-size: 1.05rem;
  display: flex; align-items: center; justify-content: center;
  box-shadow: 0 6px 16px rgba(234, 88, 12, 0.28);
  letter-spacing: 0.02em;
}
.ii-dd-sym {
  font-size: 2rem; font-weight: 800; letter-spacing: -0.04em;
  line-height: 1.1; margin: 0;
}
.ii-dd-name {
  font-size: 1rem; color: var(--ii-muted); font-weight: 600; margin-top: 2px;
}
.ii-dd-price-block { margin-top: 14px; }
.ii-dd-price-label {
  font-size: 0.85rem; font-weight: 650; color: var(--ii-muted);
  text-transform: uppercase; letter-spacing: 0.04em;
}
.ii-dd-price {
  font-size: 32px; font-weight: 800; letter-spacing: -0.03em;
  line-height: 1.15; margin-top: 2px;
}
.ii-dd-price small {
  font-size: 1rem; font-weight: 650; color: var(--ii-muted); margin-left: 4px;
}
.ii-dd-badge {
  border-radius: 16px; padding: 14px 18px; font-weight: 800; font-size: 1.05rem;
  text-align: center; min-width: 148px; border: 2px solid;
  box-shadow: var(--ii-shadow);
}
.ii-dd-mos-card {
  margin-top: 12px; display: flex; flex-wrap: wrap; gap: 10px;
}
.ii-dd-chip {
  flex: 1 1 160px; background: #fff; border-radius: 14px;
  padding: 12px 14px; border: 1px solid #e2e8f0;
  box-shadow: 0 4px 12px rgba(15,23,42,0.04);
}
.ii-dd-chip .lbl {
  font-size: 0.78rem; font-weight: 650; color: var(--ii-muted);
  text-transform: uppercase; letter-spacing: 0.03em;
}
.ii-dd-chip .val {
  font-size: 1.35rem; font-weight: 800; margin-top: 4px; letter-spacing: -0.02em;
}
.ii-dd-chip .hint { font-size: 0.82rem; color: var(--ii-muted); margin-top: 4px; font-weight: 550; }
.ii-dd-chip.neg { border-color: #fdba74; background: #fff7ed; }
.ii-dd-chip.neg .val { color: #c2410c; }
.ii-dd-chip.pos { border-color: #86efac; background: #f0fdf4; }
.ii-dd-chip.pos .val { color: #15803d; }
.ii-dd-chip.warn { border-color: #fcd34d; background: #fffbeb; }
.ii-dd-chip.warn .val { color: #b45309; }
.ii-dd-chip .tag {
  display: inline-block; margin-top: 6px; padding: 2px 8px; border-radius: 999px;
  font-size: 0.72rem; font-weight: 700; letter-spacing: 0.02em;
  background: #fef3c7; color: #92400e; border: 1px solid #fcd34d;
}
.ii-dd-integrity {
  margin-top: 10px; padding: 10px 12px; border-radius: 12px;
  border: 1px solid #fcd34d; background: #fffbeb; color: #92400e;
  font-size: 0.84rem; line-height: 1.45; font-weight: 550;
}
.ii-dd-integrity b { font-weight: 800; }
.ii-dd-section-title {
  font-size: 1.25rem; font-weight: 800; letter-spacing: -0.02em;
  margin: 18px 0 12px 0; display: flex; align-items: center; gap: 8px;
}
.ii-dd-grid {
  display: grid; grid-template-columns: 1fr 1fr; gap: 14px;
}
@media (max-width: 820px) {
  .ii-dd-grid { grid-template-columns: 1fr; }
  .ii-dd-hero { grid-template-columns: 1fr; }
  .ii-dd-hero-right .ii-dd-badge { align-self: stretch; }
  .ii-dd-price { font-size: 28px; }
  .ii-dd-sym { font-size: 1.7rem; }
}
.ii-dd-panel {
  background: #fff; border-radius: var(--ii-radius); padding: 16px;
  border: 1px solid #e2e8f0; box-shadow: var(--ii-shadow);
}
.ii-dd-panel h4 {
  margin: 0 0 14px 0; font-size: 1.05rem; font-weight: 800;
  color: #1e293b; letter-spacing: -0.01em;
}
.ii-dd-micro {
  background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 14px;
  padding: 12px 14px; margin-bottom: 10px;
}
.ii-dd-micro:last-child { margin-bottom: 0; }
.ii-dd-micro .top {
  display: flex; justify-content: space-between; align-items: baseline; gap: 8px;
}
.ii-dd-micro .k {
  font-size: 0.86rem; font-weight: 700; color: #475569;
}
.ii-dd-micro .n {
  font-size: 1.45rem; font-weight: 800; letter-spacing: -0.02em; color: #0f172a;
}
.ii-dd-micro .sub {
  font-size: 0.88rem; color: var(--ii-muted); margin-top: 6px; font-weight: 550; line-height: 1.4;
}
.ii-dd-bar {
  height: 10px; border-radius: 999px; background: #e2e8f0; overflow: hidden; margin-top: 10px;
}
.ii-dd-bar > div {
  display: block; height: 100%; border-radius: 999px;
}
.ii-dd-spark {
  display: flex; align-items: flex-end; gap: 5px; height: 42px; margin-top: 8px;
}
.ii-dd-spark span {
  flex: 1; border-radius: 5px 5px 2px 2px; min-height: 6px;
  background: #fb923c; opacity: 0.85;
}
.ii-dd-spark span.neg { background: #ef4444; }
.ii-dd-spark span.ok { background: #22c55e; }
.ii-dd-news {
  background: #fff; border: 1px solid #e2e8f0; border-radius: 12px;
  padding: 10px 12px; margin-bottom: 8px;
  border-left: 4px solid #fb923c;
}
.ii-dd-news .nt {
  font-size: 0.95rem; font-weight: 750; color: #0f172a; line-height: 1.35;
}
.ii-dd-news .ns {
  font-size: 0.8rem; color: var(--ii-muted); margin-top: 4px; font-weight: 550;
}
.ii-dd-locked {
  background: linear-gradient(135deg, #fffbeb, #ffedd5);
  border: 1.5px solid #fdba74; border-radius: 16px;
  padding: 18px 16px; text-align: center;
  box-shadow: 0 6px 18px rgba(234, 88, 12, 0.08);
}
.ii-dd-locked .lock {
  font-size: 2.2rem; line-height: 1; margin-bottom: 8px;
}
.ii-dd-locked .lt {
  font-size: 1.12rem; font-weight: 800; color: #9a3412;
}
.ii-dd-locked .ld {
  font-size: 0.95rem; color: #9a3412; margin-top: 8px; line-height: 1.45; font-weight: 550;
}
.ii-dd-plan-ok {
  background: #f0fdf4; border: 1.5px solid #86efac; border-radius: 16px;
  padding: 16px; font-size: 1rem; color: #14532d; line-height: 1.5; font-weight: 550;
}
.ii-dd-radar-item {
  display: flex; gap: 10px; align-items: flex-start;
  background: #fff; border: 1.5px solid #fca5a5; border-radius: 12px;
  padding: 12px 14px; margin-bottom: 8px;
  box-shadow: 0 3px 10px rgba(220, 38, 38, 0.06);
}
.ii-dd-radar-item .ico { font-size: 1.25rem; line-height: 1.2; }
.ii-dd-radar-item .tx {
  font-size: 0.98rem; font-weight: 650; color: #7f1d1d; line-height: 1.4;
}
.ii-dd-legend {
  margin-top: 10px; font-size: 0.92rem; color: var(--ii-muted); font-weight: 600;
}
.ii-dd-foot {
  margin-top: 12px; font-size: 0.8rem; color: #94a3b8; text-align: center;
}
</style>
"""
    )
    st.markdown(css, unsafe_allow_html=True)


# Palette — orange accent (WATCH) + traffic-light states
_ORANGE = "#ea580c"
_GREEN = "#16a34a"
_RED = "#dc2626"
_MUTED = "#64748b"


def _esc(v: Any) -> str:
    return html.escape(str(v if v is not None else ""))


def _avatar_letters(symbol: str) -> str:
    s = str(symbol or "").strip().upper()
    return (s[:3] if len(s) >= 3 else s) or "?"


def _fscore_pct(fscore: Any) -> float:
    try:
        n = float(fscore)
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, min(100.0, (n / 9.0) * 100.0))


def _fscore_bar_color(fscore: Any, *, provisional: bool) -> str:
    if provisional:
        return _ORANGE
    try:
        n = int(float(fscore))
    except (TypeError, ValueError):
        return _MUTED
    if n <= 3:
        return _RED
    if n <= 6:
        return _ORANGE
    return _GREEN


def _conf_bar_color(pct: Any) -> str:
    try:
        p = float(pct)
    except (TypeError, ValueError):
        return _MUTED
    if p < 40:
        return _ORANGE
    if p < 65:
        return "#ca8a04"
    return _GREEN


def _cfo_spark_html(cfo: Any, cfo_prior: Any) -> str:
    """CSS mini bars from available CFO points (fail-soft when history thin)."""
    vals: list[float] = []
    for v in (cfo_prior, None, None, cfo):
        if v is None or v == "":
            continue
        try:
            vals.append(float(v))
        except (TypeError, ValueError):
            continue
    if not vals:
        # Placeholder muted bars when waiting for BCTC
        bars = "".join(f'<span style="height:{h}%;opacity:0.35;background:#94a3b8;"></span>' for h in (28, 40, 34, 48, 36))
        return f'<div class="ii-dd-spark" title="Chưa đủ chuỗi CFO">{bars}</div>'
    if len(vals) == 1:
        vals = [vals[0] * 0.85, vals[0] * 0.9, vals[0] * 0.95, vals[0]]
    elif len(vals) == 2:
        a, b = vals
        vals = [a, a * 0.7 + b * 0.3, a * 0.35 + b * 0.65, b]
    mx = max(abs(x) for x in vals) or 1.0
    parts = []
    for x in vals[-5:]:
        h = max(8, int(abs(x) / mx * 100))
        cls = "neg" if x < 0 else "ok"
        parts.append(f'<span class="{cls}" style="height:{h}%;"></span>')
    return f'<div class="ii-dd-spark">{"".join(parts)}</div>'


def build_price_chart_svg(
    closes: list[float] | None,
    *,
    dates: list[Any] | None = None,
    width: int = 560,
    height: int = 210,
    stroke: str = "#0052FF",
) -> str:
    """
    Biểu đồ giá 1 năm gần nhất — có trục giá/tháng, tô màu giai đoạn tăng/giảm.
    """
    _ = stroke  # kept for API compatibility
    series, date_objs = sanitize_close_series_for_chart(closes, dates)

    if len(series) < 2:
        return (
            '<div class="ii-dd-chart">'
            '<div class="clbl">Biểu đồ giá · 1 năm</div>'
            '<div class="ii-dd-chart-empty">Chưa có dữ liệu biểu đồ giá</div>'
            "</div>"
        )

    # ~1 năm giao dịch (~252 phiên), lấy tối đa 280 điểm gần nhất.
    keep = 280
    if len(series) > keep:
        series = series[-keep:]
        date_objs = date_objs[-keep:]

    parsed_dates = _parse_chart_dates(date_objs, n=len(series))
    lo = min(series)
    hi = max(series)
    span = (hi - lo) or max(abs(hi) * 0.01, 1.0)
    # Pad 6% so labels/markers không sát mép. Floor at 0 — giá cổ phiếu không âm.
    y_pad = span * 0.06
    y_lo, y_hi = max(0.0, lo - y_pad), hi + y_pad
    y_span = (y_hi - y_lo) or 1.0

    left, right, top, bottom = 54.0, 14.0, 12.0, 28.0
    inner_w = max(1.0, float(width) - left - right)
    inner_h = max(1.0, float(height) - top - bottom)
    n = len(series)

    def _x(i: int) -> float:
        return left + (inner_w * i / (n - 1))

    def _y(v: float) -> float:
        return top + inner_h * (1.0 - (v - y_lo) / y_span)

    pts = [(_x(i), _y(v)) for i, v in enumerate(series)]

    # Area under full path (neutral).
    first, last = pts[0], pts[-1]
    area = (
        f"M {first[0]:.2f},{top + inner_h:.2f} "
        + " ".join(f"L {x:.2f},{y:.2f}" for x, y in pts)
        + f" L {last[0]:.2f},{top + inner_h:.2f} Z"
    )

    # Segmented polyline: xanh = tăng, đỏ = giảm.
    up_c, down_c = "#16a34a", "#dc2626"
    seg_html: list[str] = []
    for i in range(1, n):
        color = up_c if series[i] >= series[i - 1] else down_c
        x0, y0 = pts[i - 1]
        x1, y1 = pts[i]
        seg_html.append(
            f'<line x1="{x0:.2f}" y1="{y0:.2f}" x2="{x1:.2f}" y2="{y1:.2f}" '
            f'stroke="{color}" stroke-width="2.3" stroke-linecap="round"/>'
        )

    # Y grid + price labels.
    y_ticks = 4
    grid_parts: list[str] = []
    for t in range(y_ticks + 1):
        ratio = t / y_ticks
        yy = top + inner_h * ratio
        val = y_hi - ratio * y_span
        grid_parts.append(
            f'<line x1="{left}" y1="{yy:.2f}" x2="{width - right}" y2="{yy:.2f}" '
            f'stroke="#e2e8f0" stroke-width="1"/>'
            f'<text x="{left - 6:.1f}" y="{yy + 3.5:.2f}" text-anchor="end" '
            f'font-size="10" font-weight="650" fill="#64748b">{_esc(_fmt_price_axis(val))}</text>'
        )

    # Month labels on X.
    month_labels = _month_axis_labels(parsed_dates, pts)
    x_label_html = "".join(
        f'<text x="{x:.2f}" y="{height - 8:.1f}" text-anchor="middle" '
        f'font-size="10" font-weight="650" fill="#64748b">{_esc(lbl)}</text>'
        for x, lbl in month_labels
    )

    # High / low markers.
    i_hi = max(range(n), key=lambda i: series[i])
    i_lo = min(range(n), key=lambda i: series[i])
    markers = []
    for idx, color, anchor in ((i_hi, up_c, "start"), (i_lo, down_c, "start")):
        xx, yy = pts[idx]
        tx = min(max(xx + 4, left + 2), width - right - 40)
        ty = yy - 8 if idx == i_hi else yy + 14
        markers.append(
            f'<circle cx="{xx:.2f}" cy="{yy:.2f}" r="3.2" fill="{color}" stroke="#fff" stroke-width="1.2"/>'
            f'<text x="{tx:.2f}" y="{ty:.2f}" text-anchor="{anchor}" font-size="10" '
            f'font-weight="750" fill="{color}">{_esc(_fmt_price_axis(series[idx]))}</text>'
        )

    change = ((series[-1] / series[0]) - 1.0) * 100.0 if series[0] else 0.0
    chg_cls = "up" if change >= 0 else "down"
    range_txt = _year_range_caption(parsed_dates)
    chg_txt = f"{change:+.1f}% · {n} phiên"

    return (
        '<div class="ii-dd-chart">'
        '<div class="clbl">Biểu đồ giá · 1 năm gần nhất</div>'
        f'<div class="cmeta">'
        f'<span class="{chg_cls}">{_esc(chg_txt)}</span>'
        f'<span>{_esc(range_txt)}</span>'
        f'<span><span class="dot up"></span>Tăng</span>'
        f'<span><span class="dot down"></span>Giảm</span>'
        f"</div>"
        f'<svg viewBox="0 0 {width} {height}" preserveAspectRatio="none" role="img" '
        f'aria-label="Biểu đồ giá 1 năm">'
        f"{''.join(grid_parts)}"
        f'<path d="{area}" fill="rgba(15,23,42,0.04)" stroke="none"/>'
        f"{''.join(seg_html)}"
        f"{''.join(markers)}"
        f'<circle cx="{last[0]:.2f}" cy="{last[1]:.2f}" r="4" fill="#0f172a" stroke="#fff" stroke-width="1.5"/>'
        f"{x_label_html}"
        "</svg></div>"
    )


def _fmt_price_axis(v: float) -> str:
    try:
        n = float(v)
    except (TypeError, ValueError):
        return "—"
    if n >= 1_000_000:
        return f"{n / 1_000_000:.2f}Tr"
    if n >= 10_000:
        return f"{n / 1_000:.1f}k".replace(".0k", "k")
    if n >= 1_000:
        return f"{n:,.0f}"
    return f"{n:.1f}"


def _parse_chart_dates(raw: list[Any], *, n: int) -> list[Any]:
    out: list[Any] = [None] * n
    try:
        import pandas as pd
    except Exception:
        return out
    for i in range(min(n, len(raw))):
        v = raw[i]
        if v is None or v == "":
            continue
        try:
            ts = pd.to_datetime(v, errors="coerce")
            if ts is not None and str(ts) != "NaT":
                out[i] = ts.to_pydatetime() if hasattr(ts, "to_pydatetime") else ts
        except Exception:
            continue
    return out


def _month_axis_labels(dates: list[Any], pts: list[tuple[float, float]]) -> list[tuple[float, str]]:
    """Pick ~6 evenly spaced month labels across the series."""
    labeled: list[tuple[float, str]] = []
    if not pts:
        return labeled
    month_first: dict[str, tuple[float, str]] = {}
    for i, d in enumerate(dates):
        if d is None or i >= len(pts):
            continue
        try:
            key = f"{d.year}-{d.month:02d}"
            lbl = f"T{d.month}"
            if key not in month_first:
                month_first[key] = (pts[i][0], lbl)
        except Exception:
            continue
    items = list(month_first.values())
    if not items:
        # Fallback evenly spaced tick marks without dates.
        step = max(1, (len(pts) - 1) // 5)
        for i in range(0, len(pts), step):
            labeled.append((pts[i][0], f"{i + 1}"))
        return labeled[:6]
    if len(items) <= 6:
        return items
    # Subsample to ~6 labels.
    step = max(1, len(items) // 6)
    return items[::step][:6]


def _year_range_caption(dates: list[Any]) -> str:
    valid = [d for d in dates if d is not None]
    if len(valid) < 2:
        return "12 tháng gần nhất"
    try:
        a, b = valid[0], valid[-1]
        return f"{a.strftime('%d/%m/%Y')} → {b.strftime('%d/%m/%Y')}"
    except Exception:
        return "12 tháng gần nhất"


def extract_price_series(ohlcv: Any) -> tuple[list[Any], list[float]]:
    """Return (dates, closes) fail-soft from OHLCV frame/list."""
    if ohlcv is None:
        return [], []
    try:
        import pandas as pd

        if isinstance(ohlcv, pd.DataFrame):
            if ohlcv.empty or "close" not in ohlcv.columns:
                return [], []
            d = ohlcv.copy()
            closes_raw = pd.to_numeric(d["close"], errors="coerce")
            dates_raw = d["date"] if "date" in d.columns else ([None] * len(d))
            dates: list[Any] = []
            closes: list[float] = []
            for dt, v in zip(list(dates_raw), closes_raw.tolist()):
                try:
                    f = float(v)
                except (TypeError, ValueError):
                    continue
                if f == f and f > 0:
                    dates.append(dt)
                    closes.append(f)
            return dates, closes
    except Exception:
        pass
    if isinstance(ohlcv, (list, tuple)):
        closes2: list[float] = []
        for v in ohlcv:
            try:
                f = float(v)
            except (TypeError, ValueError):
                continue
            if f == f and f > 0:
                closes2.append(f)
        return [None] * len(closes2), closes2
    return [], []


def extract_close_series(ohlcv: Any) -> list[float]:
    """Fail-soft close series from DataFrame / list / dict payload."""
    _, closes = extract_price_series(ohlcv)
    return closes


def build_decision_dashboard_html(
    *,
    symbol: str,
    company_name: str,
    price_txt: str,
    fair_txt: str,
    mos_disp: str,
    mos_f: float | None,
    mos_comment: str,
    legend: str,
    badge: str,
    accent: str,
    soft: str,
    fscore_txt: str,
    fscore: Any,
    fscore_prov: bool,
    cfo_txt: str,
    cfo: Any,
    cfo_prior: Any,
    cr_txt: str,
    cr_ready: bool,
    pe_txt: str,
    pe_num: str,
    eq_label: str,
    dividend_line: str,
    catalyst_lines: list[str],
    confidence_pct: Any,
    readiness_vi: str,
    show_plan: bool,
    plan_html_inner: str,
    locked_reason: str,
    radar: list[str],
    price_chart_html: str = "",
    valuation_integrity_blocked: bool = False,
    valuation_integrity_note: str = "",
    fair_method_label: str = "",
    mos_raw_disp: str = "",
) -> str:
    sym = str(symbol or "").upper()
    name = company_name.strip() if company_name else "Đang cập nhật tên doanh nghiệp"
    blocked = bool(valuation_integrity_blocked)
    mos_cls = "warn" if blocked else (
        "neg" if (mos_f is not None and mos_f < 0) else ("pos" if (mos_f is not None and mos_f > 0) else "")
    )
    fair_cls = "warn" if blocked else ""
    mos_arrow = "▼" if (mos_f is not None and mos_f < 0) else ("▲" if (mos_f is not None and mos_f > 0) else "●")
    fs_pct = _fscore_pct(fscore)
    fs_color = _fscore_bar_color(fscore, provisional=fscore_prov)
    try:
        conf_v = float(confidence_pct) if confidence_pct not in (None, "") else None
    except (TypeError, ValueError):
        conf_v = None
    conf_pct = max(0.0, min(100.0, conf_v if conf_v is not None else 0.0))
    conf_color = _conf_bar_color(conf_v)
    conf_label = f"{conf_pct:.0f}%" if conf_v is not None else "—"

    cr_icon = "✅" if cr_ready else "⚠️"
    cr_color = _GREEN if cr_ready else _ORANGE

    fair_tag = (
        '<div class="tag">⚠ Tham khảo · không giải ngân</div>' if blocked else ""
    )
    mos_hint = mos_comment or "Đang cập nhật"
    if blocked and mos_raw_disp:
        mos_hint = f"Đã siết (MOS thô {mos_raw_disp}) — không dùng để giải ngân"
    elif blocked:
        mos_hint = "Graham tham khảo — nghi EPS/P/E lệch · không dùng để giải ngân"

    integrity_banner = ""
    if blocked:
        note = str(valuation_integrity_note or "").strip() or (
            "Định giá công bố đã chọn mô hình thận trọng hơn; Graham thô vẫn lưu tham chiếu — "
            "chưa đủ tin cậy giải ngân do nghi EPS/P/E lệch đơn vị."
        )
        integrity_banner = (
            f'<div class="ii-dd-integrity"><b>⚠ Cảnh báo định giá:</b> {_esc(note)}</div>'
        )
    fair_method = str(fair_method_label or "").strip()
    fair_method_html = (
        f'<div class="hint">{_esc(fair_method)}</div>' if fair_method else ""
    )

    news_html = []
    for i, line in enumerate(catalyst_lines[:4]):
        tag = "Tin / Vĩ mô" if i < 2 else "Tín hiệu"
        news_html.append(
            f'<div class="ii-dd-news"><div class="nt">{_esc(line)}</div>'
            f'<div class="ns">{_esc(tag)}</div></div>'
        )
    if not news_html:
        news_html.append(
            '<div class="ii-dd-news"><div class="nt">Chưa có chất xúc tác nổi bật</div>'
            '<div class="ns">Đang cập nhật tin tức / vĩ mô</div></div>'
        )

    if show_plan:
        plan_block = f'<div class="ii-dd-plan-ok">{_compact_html(plan_html_inner)}</div>'
    else:
        plan_block = (
            '<div class="ii-dd-locked">'
            '<div class="lock">🔒</div>'
            '<div class="lt">Kế hoạch giao dịch bị khóa</div>'
            f'<div class="ld">{_esc(locked_reason)}</div>'
            "</div>"
        )

    radar_html = []
    for rule in radar:
        radar_html.append(
            f'<div class="ii-dd-radar-item"><div class="ico">⚠️</div>'
            f'<div class="tx">{_esc(rule)}</div></div>'
        )
    if not radar_html:
        radar_html.append(
            '<div class="ii-dd-radar-item"><div class="ico">ℹ️</div>'
            '<div class="tx">Chưa có điều kiện gãy luận điểm cụ thể.</div></div>'
        )

    chart_block = _compact_html(price_chart_html) if str(price_chart_html or "").strip() else build_price_chart_svg(None)

    return _compact_html(
        f"""
<div class="ii-dd">
<div class="ii-dd-shell">
  <div class="ii-dd-hero">
    <div>
      <div class="ii-dd-brand-row">
        <div class="ii-dd-avatar">{_esc(_avatar_letters(sym))}</div>
        <div>
          <div class="ii-dd-sym">{_esc(sym)}</div>
          <div class="ii-dd-name">{_esc(name)}</div>
        </div>
      </div>
      <div class="ii-dd-price-block">
        <div class="ii-dd-price-label">Giá hiện tại</div>
        <div class="ii-dd-price">{_esc(price_txt)}<small>đ</small></div>
      </div>
      <div class="ii-dd-mos-card">
        <div class="ii-dd-chip {fair_cls}">
          <div class="lbl">Định giá hợp lý</div>
          <div class="val">{_esc(fair_txt)}{" đ" if fair_txt not in ("Chưa xác định", "Đang cập nhật", "—", "") else ""}</div>
          {fair_method_html}
          {fair_tag}
        </div>
        <div class="ii-dd-chip {mos_cls}">
          <div class="lbl">Biên an toàn (MOS)</div>
          <div class="val">{mos_arrow} {_esc(mos_disp)}</div>
          <div class="hint">{_esc(mos_hint)}</div>
        </div>
      </div>
      {integrity_banner}
      <div class="ii-dd-legend">Kết luận Legend: <b>{_esc(legend)}</b></div>
    </div>
    <div class="ii-dd-hero-right">
      <div class="ii-dd-badge" style="color:{accent};background:{soft};border-color:{accent};">
        {_esc(badge)}
      </div>
      {chart_block}
    </div>
  </div>
  <div class="ii-dd-section-title">Bản luận điểm đầu tư cốt lõi</div>
  <div class="ii-dd-grid">
    <div class="ii-dd-panel">
      <h4>Nội lực tài chính · Máy cân</h4>
      <div class="ii-dd-micro">
        <div class="top">
          <span class="k">Sức khỏe F-Score</span>
          <span class="n" style="color:{fs_color};">{_esc(str(fscore) if fscore not in (None,'') else '—')}<small style="font-size:0.85rem;color:#64748b;">/9</small></span>
        </div>
        <div class="ii-dd-bar"><div style="width:{fs_pct:.1f}%;background:{fs_color};"></div></div>
        <div class="sub">{_esc(fscore_txt)}</div>
      </div>
      <div class="ii-dd-micro">
        <div class="top"><span class="k">Dòng tiền HĐKD (CFO)</span></div>
        {_cfo_spark_html(cfo, cfo_prior)}
        <div class="sub">{_esc(cfo_txt)}</div>
      </div>
      <div class="ii-dd-micro">
        <div class="top">
          <span class="k">Thanh khoản (CR)</span>
          <span class="status" style="color:{cr_color};font-weight:800;">{cr_icon}</span>
        </div>
        <div class="sub">{_esc(cr_txt)}</div>
      </div>
      <div class="ii-dd-micro">
        <div class="top">
          <span class="k">P/E hiện tại</span>
          <span class="n">{_esc(pe_num)}</span>
        </div>
        <div class="sub">{_esc(pe_txt)}</div>
      </div>
      <div class="ii-dd-micro">
        <div class="top"><span class="k">Chất lượng lợi nhuận</span></div>
        <div class="n" style="font-size:1.15rem;">{_esc(eq_label)}</div>
      </div>
    </div>
    <div class="ii-dd-panel">
      <h4>Câu chuyện &amp; Chất xúc tác · Máy bỏ phiếu</h4>
      <div class="ii-dd-micro">
        <div class="top"><span class="k">Cổ tức</span></div>
        <div class="n" style="font-size:1.15rem;">{_esc(dividend_line)}</div>
      </div>
      <div style="margin:4px 0 10px 0;">
        <div class="k" style="font-size:0.86rem;font-weight:700;color:#475569;margin-bottom:8px;">Tin tức &amp; Vĩ mô</div>
        {''.join(news_html)}
      </div>
      <div class="ii-dd-micro">
        <div class="top">
          <span class="k">Độ tin cậy mô hình</span>
          <span class="n" style="color:{conf_color};">{_esc(conf_label)}</span>
        </div>
        <div class="ii-dd-bar"><div style="width:{conf_pct:.1f}%;background:{conf_color};"></div></div>
        <div class="sub">Sẵn sàng dữ liệu: <b>{_esc(readiness_vi)}</b></div>
      </div>
    </div>
  </div>
  <div class="ii-dd-section-title">Kế hoạch hành động &amp; Radar cảnh báo</div>
  <div class="ii-dd-grid">
    <div class="ii-dd-panel">
      <h4>Kế hoạch &amp; Quản trị tỷ trọng</h4>
      {plan_block}
    </div>
    <div class="ii-dd-panel">
      <h4>Radar Cảnh báo Gãy Luận điểm</h4>
      {''.join(radar_html)}
    </div>
  </div>
  <div class="ii-dd-foot">Không phải lời khuyên đầu tư. Kiểm tra BCTC gốc trước khi giải ngân.</div>
</div>
</div>
"""
    )


def render_decision_dashboard(html_body: str) -> None:
    """Render HTML dashboard — compact để tránh Streamlit escape raw HTML."""
    inject_decision_dashboard_css()
    body = _compact_html(html_body)
    # Một khối markdown duy nhất, không dòng trống → HTML không bị cắt giữa chừng.
    st.markdown(body, unsafe_allow_html=True)
