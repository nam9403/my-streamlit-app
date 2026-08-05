"""Presentation tests for Decision Card dashboard HTML."""

from __future__ import annotations

from datetime import datetime, timedelta

from core.decision_card_dashboard import build_decision_dashboard_html, build_price_chart_svg


def test_dashboard_html_highlights_negative_mos_and_locked_plan() -> None:
    html = build_decision_dashboard_html(
        symbol="FPT",
        company_name="FPT Corporation",
        price_txt="67,000",
        fair_txt="56,955",
        mos_disp="-17.6%",
        mos_f=-17.6,
        mos_comment="Thị giá cao hơn định giá",
        legend="Theo dõi",
        badge="QUAN SÁT",
        accent="#b8860b",
        soft="#fbf5e6",
        fscore_txt="2/9 (Tạm tính - Đang chờ nạp BCTC)",
        fscore=2,
        fscore_prov=True,
        cfo_txt="Cần thêm dữ liệu",
        cfo=None,
        cfo_prior=None,
        cr_txt="Thanh khoản (CR): Đang cập nhật",
        cr_ready=False,
        pe_txt="P/E hiện tại: 11.18 — Đánh giá: Hợp lý",
        pe_num="11.18",
        eq_label="Ổn",
        dividend_line="Đang cập nhật",
        catalyst_lines=["FPT hợp tác AI", "FPT Retail doanh thu"],
        confidence_pct=34.0,
        readiness_vi="Thấp",
        show_plan=False,
        plan_html_inner="",
        locked_reason="Chưa đủ điều kiện (Khuyến nghị: QUAN SÁT).",
        radar=["Hạ khuyến nghị nếu F-Score < 3."],
        price_chart_html=build_price_chart_svg([100.0, 102.0, 98.0, 105.0, 110.0]),
    )
    assert "ii-dd-sym" in html
    assert "ii-dd-hero" in html
    assert "ii-dd-chart" in html
    assert "Biểu đồ giá" in html
    assert "1 năm" in html
    assert "67,000" in html
    assert "font-size: 32px" in html or "ii-dd-price" in html
    assert "neg" in html
    assert "-17.6%" in html
    assert "▼" in html
    assert "🔒" in html
    assert "Kế hoạch giao dịch bị khóa" in html
    assert "QUAN SÁT /" not in html
    assert "ii-dd-radar-item" in html
    assert "11.18" in html
    assert "34" in html
    assert "Cổ tức: Cổ tức:" not in html
    assert "🧭" not in html
    # Streamlit bug: blank lines split HTML blocks → raw tags on screen
    assert "\n\n" not in html


def test_price_chart_svg_empty_and_valid() -> None:
    empty = build_price_chart_svg([])
    assert "Chưa có dữ liệu biểu đồ giá" in empty
    chart = build_price_chart_svg([10, 11, 12, 11.5, 13])
    assert "stroke=\"#16a34a\"" in chart or "stroke=\"#dc2626\"" in chart
    assert "circle" in chart
    assert "Tăng" in chart and "Giảm" in chart


def test_price_chart_one_year_axes_and_phases() -> None:
    dates = [datetime(2025, 8, 1) + timedelta(days=i) for i in range(260)]
    # Rising then falling phases
    closes = [100 + i * 0.2 for i in range(130)] + [126 - i * 0.15 for i in range(130)]
    html = build_price_chart_svg(closes, dates=dates)
    assert "1 năm gần nhất" in html
    assert "Tăng" in html
    assert "Giảm" in html
    assert "T8" in html or "T1" in html or "/" in html
    assert "text-anchor=\"end\"" in html  # Y-axis labels
    assert html.count("stroke=\"#16a34a\"") >= 1
    assert html.count("stroke=\"#dc2626\"") >= 1


def test_price_chart_drops_unit_break_spikes() -> None:
    from core.decision_card_dashboard import sanitize_close_series_for_chart

    # ACB-like: ~23k with corrupt ticks at 3.5
    closes = [22000 + i * 10 for i in range(40)]
    closes[10] = 3.5
    closes[25] = 3.5
    dates = [datetime(2025, 6, 1) + timedelta(days=i) for i in range(40)]
    cleaned, _ = sanitize_close_series_for_chart(closes, dates)
    assert all(v > 1000 for v in cleaned)
    assert 3.5 not in cleaned
    html = build_price_chart_svg(closes, dates=dates)
    assert "-1763" not in html
    # Low marker must not be the corrupt 3.5 tick
    assert ">3.5<" not in html
    assert "3.5</text>" not in html
