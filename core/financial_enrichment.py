"""
Làm giàu snapshot cho định giá: gộp chỉ số đã cache (không mạng), ước ROE, BCTC tùy chọn.
"""

from __future__ import annotations

import os
from typing import Any

from scrapers.financial_statements import compute_trend_metrics, fetch_vndirect_financial_statement_rows


def _as_float(v: Any) -> float | None:
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def normalize_roe_to_pct(raw: Any) -> float | None:
    """
    Chuẩn hóa ROE về đơn vị % (Buffett dùng ngưỡng 15).
    vnstock thường trả tỉ lệ 0.27; nguồn khác có thể đã là %.
    """
    v = _as_float(raw)
    if v is None or v <= 0:
        return None
    if v <= 1.5:
        return round(v * 100.0, 4)
    return round(v, 4)


def _eps_scale() -> float:
    raw = str(os.environ.get("II_EPS_SCALE", "1000") or "1000").strip()
    try:
        return max(1.0, float(raw))
    except ValueError:
        return 1000.0


def normalize_eps_to_vnd_per_share(
    eps: Any,
    price: Any,
    *,
    pe_ratio: Any = None,
) -> tuple[float | None, list[str]]:
    """
    Chuẩn hóa EPS về VND/cp khi yield bất thường (vd. EPS nghìn VND vs giá VND).

    Heuristic: nếu EPS/price > 15% → thử chia II_EPS_SCALE (mặc định 1000).
    Cross-check thêm với P/E nguồn nếu có.
    """
    v = _as_float(eps)
    px = _as_float(price)
    notes: list[str] = []
    if v is None or v <= 0 or px is None or px <= 0:
        return v, notes

    scale = _eps_scale()
    earnings_yield = v / px
    pe_src = _as_float(pe_ratio)
    pe_calc = px / v

    # P/E nguồn khớp EPS thô → coi là P/E thấp thật, không chia scale (tránh MOS âm giả).
    if pe_src and pe_src > 0 and pe_calc > 0:
        gap_pe = abs(pe_src - pe_calc) / max(pe_src, pe_calc, 1e-6)
        if gap_pe <= 0.20:
            return v, notes

    if earnings_yield > 0.15:
        scaled = v / scale
        if scaled > 0 and scaled / px <= 0.15:
            notes.append(
                f"EPS chuẩn hóa {v:,.0f}→{scaled:,.2f} VND/cp (÷{scale:g}, earnings yield {scaled/px:.1%})."
            )
            return round(scaled, 4), notes

    if pe_src and pe_src > 0 and pe_calc > 0:
        gap = abs(pe_src - pe_calc) / max(pe_src, pe_calc, 1e-6)
        if gap > 0.25:
            scaled = v / scale
            pe_calc2 = px / scaled if scaled > 0 else 0.0
            gap2 = abs(pe_src - pe_calc2) / max(pe_src, pe_calc2, 1e-6) if pe_calc2 > 0 else 1.0
            if gap2 < gap and scaled > 0:
                notes.append(
                    f"EPS chuẩn hóa theo P/E nguồn ({pe_src:.2f} vs tính {pe_calc:.2f}→{pe_calc2:.2f})."
                )
                return round(scaled, 4), notes

    return v, notes


def normalize_eps_in_snapshot(snapshot: dict[str, Any]) -> list[str]:
    """In-place EPS normalize; giữ eps_raw khi đổi scale."""
    if not isinstance(snapshot, dict):
        return []
    eps_new, notes = normalize_eps_to_vnd_per_share(
        snapshot.get("eps"),
        snapshot.get("price"),
        pe_ratio=snapshot.get("pe_ratio"),
    )
    old = _as_float(snapshot.get("eps"))
    if eps_new is not None and old is not None and abs(eps_new - old) > 1e-6:
        snapshot["eps_raw"] = old
        snapshot["eps"] = eps_new
        snapshot["eps_normalized"] = True
        if snapshot.get("price") and eps_new > 0:
            snapshot["pe_ratio_recalc"] = round(float(snapshot["price"]) / eps_new, 4)
    return notes


def _missing_positive(snapshot: dict[str, Any], key: str) -> bool:
    v = _as_float(snapshot.get(key))
    return v is None or v <= 0


def _ensure_piotroski(snapshot: dict[str, Any]) -> dict[str, Any]:
    pio = snapshot.get("piotroski")
    if not isinstance(pio, dict):
        pio = {}
        snapshot["piotroski"] = pio
    return pio


def _apply_growth_from_yoy(snapshot: dict[str, Any], rev_yoy: float | None, profit_yoy: float | None) -> None:
    if rev_yoy is None and profit_yoy is None:
        return
    old_g = float(snapshot.get("growth_rate_pct") or 0)
    if old_g != 0 and not str(snapshot.get("source") or "").startswith("mock"):
        if rev_yoy is not None:
            snapshot.setdefault("revenue_growth_yoy", rev_yoy)
        if profit_yoy is not None:
            snapshot.setdefault("profit_growth_yoy", profit_yoy)
        return
    if rev_yoy is not None and profit_yoy is not None:
        blended = 0.65 * float(rev_yoy) + 0.35 * float(profit_yoy)
        src = "indicators_yoy_blend"
    elif profit_yoy is not None:
        blended = float(profit_yoy)
        src = "indicators_profit_yoy"
    else:
        blended = float(rev_yoy or 0)
        src = "indicators_revenue_yoy"
    snapshot["growth_rate_pct"] = round(blended, 2)
    snapshot["growth_rate_pct_source"] = src
    if rev_yoy is not None:
        snapshot["revenue_growth_yoy"] = float(rev_yoy)
    if profit_yoy is not None:
        snapshot["profit_growth_yoy"] = float(profit_yoy)


def merge_indicator_fundamentals_into_snapshot(
    snapshot: dict[str, Any],
    financials: dict[str, Any] | None = None,
) -> list[str]:
    """
    In-place: đổ ROE/D/E/CR/YoY từ dict indicators (hoặc disk cache) vào snapshot.
    Không gọi mạng. Trả danh sách ghi chú nguồn đã gộp.
    """
    notes: list[str] = []
    if not isinstance(snapshot, dict):
        return notes

    fin = financials if isinstance(financials, dict) else None
    if fin is None and os.environ.get("II_MERGE_FIN_DISK_INTO_SNAPSHOT", "1").strip().lower() not in (
        "0",
        "false",
        "no",
        "off",
    ):
        try:
            from scrapers.portal import _read_fin_disk_cache

            sym = str(snapshot.get("symbol") or "").strip().upper()
            if sym:
                fin = _read_fin_disk_cache(sym)
        except Exception:
            fin = None

    if isinstance(fin, dict) and fin:
        src = str(fin.get("source") or "financial_indicators")
        if _missing_positive(snapshot, "debt_to_equity"):
            de = _as_float(fin.get("debt_to_equity"))
            if de is not None and de > 0:
                snapshot["debt_to_equity"] = de
                notes.append(f"D/E từ {src}")
        if _missing_positive(snapshot, "current_ratio"):
            cr = _as_float(fin.get("current_ratio"))
            if cr is not None and cr > 0:
                snapshot["current_ratio"] = cr
                notes.append(f"CR từ {src}")
        if _missing_positive(snapshot, "roe") and _missing_positive(snapshot, "roe_5y_avg"):
            roe_pct = normalize_roe_to_pct(fin.get("roe"))
            if roe_pct is not None:
                snapshot["roe"] = roe_pct
                notes.append(f"ROE từ {src} (chuẩn hóa %)")
        _apply_growth_from_yoy(
            snapshot,
            _as_float(fin.get("revenue_growth_yoy")),
            _as_float(fin.get("profit_growth_yoy")),
        )
        if snapshot.get("growth_rate_pct_source") in (
            "indicators_yoy_blend",
            "indicators_profit_yoy",
            "indicators_revenue_yoy",
        ):
            notes.append(f"Tăng trưởng từ YoY ({src})")

        pio = _ensure_piotroski(snapshot)
        for src_key, dst_key in (
            ("net_income", "net_income"),
            ("net_income_prior", "net_income_prior"),
            ("operating_cash_flow", "operating_cash_flow"),
            ("operating_cash_flow_prior", "operating_cash_flow_prior"),
            ("current_assets", "current_assets"),
            ("current_liabilities", "current_liabilities"),
        ):
            if pio.get(dst_key) is None:
                val = _as_float(fin.get(src_key))
                if val is not None:
                    pio[dst_key] = val
                    snapshot.setdefault(dst_key, val)
                    if dst_key == "operating_cash_flow":
                        notes.append(f"CFO từ {src}")
            # Also promote top-level CFO when only present on fin.
            if dst_key == "operating_cash_flow" and snapshot.get("operating_cash_flow") is None:
                val = _as_float(fin.get(src_key)) or _as_float(pio.get(dst_key))
                if val is not None:
                    snapshot["operating_cash_flow"] = val
                    notes.append(f"CFO gắn snapshot từ {src}")
        # CR suy từ CA/CL nếu vẫn thiếu
        if _missing_positive(snapshot, "current_ratio"):
            ca = _as_float(snapshot.get("current_assets")) or _as_float(pio.get("current_assets"))
            cl = _as_float(snapshot.get("current_liabilities")) or _as_float(pio.get("current_liabilities"))
            if ca is not None and cl is not None and cl > 0:
                snapshot["current_ratio"] = round(ca / cl, 4)
                notes.append(f"CR suy từ CA/CL ({src})")
                pio.setdefault("current_assets", ca)
                pio.setdefault("current_liabilities", cl)

    # ROE ước từ EPS/BVPS khi vẫn thiếu (không mạng, ổn định cho Legend).
    if _missing_positive(snapshot, "roe") and _missing_positive(snapshot, "roe_5y_avg"):
        eps = _as_float(snapshot.get("eps")) or 0.0
        bv = _as_float(snapshot.get("book_value_per_share")) or _as_float(snapshot.get("bvps")) or 0.0
        if eps > 0 and bv > 0:
            snapshot["roe"] = round((eps / bv) * 100.0, 4)
            snapshot["roe_source"] = "eps_bvps_estimate"
            notes.append("ROE ước từ EPS/BVPS")

    # Chuẩn hóa ROE đã có trên snapshot nếu đang ở dạng tỉ lệ.
    for key in ("roe", "roe_5y_avg"):
        if key in snapshot and snapshot.get(key) is not None:
            norm = normalize_roe_to_pct(snapshot.get(key))
            if norm is not None and abs(norm - float(snapshot.get(key) or 0)) > 1e-9:
                snapshot[key] = norm
                notes.append(f"Chuẩn hóa {key} → %")

    # LNST proxy chỉ khi chưa có NI thật (tránh đè số liệu BCTC).
    pio = _ensure_piotroski(snapshot)
    if pio.get("net_income") is None and snapshot.get("net_income") is None:
        equity = _as_float(snapshot.get("shareholders_equity")) or 0.0
        roe_pct = normalize_roe_to_pct(snapshot.get("roe")) or normalize_roe_to_pct(snapshot.get("roe_5y_avg")) or 0.0
        if equity > 0 and roe_pct > 0:
            ni = equity * (roe_pct / 100.0)
            pio["net_income"] = ni
            snapshot.setdefault("net_income", ni)
            snapshot["net_income_source"] = "equity_roe_estimate"
            notes.append("LNST ước từ vốn chủ × ROE")
    elif snapshot.get("net_income") is not None and pio.get("net_income") is None:
        pio["net_income"] = float(snapshot["net_income"])
        snapshot["net_income_source"] = str(snapshot.get("net_income_source") or "indicators")

    if notes:
        snapshot["fundamentals_merge_notes"] = list(dict.fromkeys(notes))
    return notes


def merge_cached_fundamentals_into_snapshot(snapshot: dict[str, Any]) -> None:
    """Convenience: chỉ disk/ước lượng — dùng trước khi trả snapshot ra UI/valuation."""
    merge_indicator_fundamentals_into_snapshot(snapshot, financials=None)


def attach_financial_statements_to_snapshot(snapshot: dict[str, Any], symbol: str) -> None:
    """
    In-place: thêm financial_report_series, trend metrics, và cập nhật growth_rate_pct nếu có dữ liệu.
    Mặc định tắt (II_FETCH_FINANCIAL_STATEMENTS=0): API Finfo thường timeout → ROI âm trên hot path.
    Bật thủ công khi prefetch đêm/cuối tuần.
    """
    if os.environ.get("II_FETCH_FINANCIAL_STATEMENTS", "0").strip().lower() in ("0", "false", "no", "off"):
        return

    sym = (symbol or snapshot.get("symbol") or "").strip().upper()
    if not sym:
        return

    rows, src = fetch_vndirect_financial_statement_rows(sym, size=12)
    if not rows:
        snapshot["financial_report_fetch"] = {"ok": False, "source": "vndirect_finfo", "detail": src}
        return

    trends = compute_trend_metrics(rows)
    snapshot["financial_report_series"] = rows[:8]
    snapshot["financial_report_trends"] = trends
    snapshot["financial_report_fetch"] = {
        "ok": True,
        "source": "vndirect_finfo",
        "endpoint_hint": src,
        "disclaimer": "Số liệu tóm tắt từ API công khai, không thay thế BCTC niêm yết đầy đủ.",
    }

    ry = trends.get("revenue_yoy_pct")
    py = trends.get("profit_yoy_pct")
    if ry is not None:
        blended = float(ry)
        if py is not None:
            blended = 0.65 * float(ry) + 0.35 * float(py)
        old_g = float(snapshot.get("growth_rate_pct") or 0)
        if old_g == 0 or snapshot.get("source", "").startswith("mock"):
            snapshot["growth_rate_pct"] = round(blended, 2)
            snapshot["growth_rate_pct_source"] = "financial_report_yoy_blend"
        else:
            snapshot["growth_rate_pct_alternate_from_bctc"] = round(blended, 2)

    pio = snapshot.get("piotroski")
    if not isinstance(pio, dict):
        pio = {}
    if len(rows) >= 2 and pio.get("net_income") is None:
        a, b = rows[0], rows[1]
        ni0 = a.get("net_income")
        ni1 = b.get("net_income")
        r0, r1 = a.get("revenue"), b.get("revenue")
        if ni0 is not None:
            pio["net_income"] = float(ni0)
        if ni1 is not None:
            pio["net_income_prior"] = float(ni1)
        if r0 is not None:
            pio["revenue"] = float(r0)
        if r1 is not None:
            pio["revenue_prior"] = float(r1)
        ta0 = a.get("total_assets")
        ta1 = b.get("total_assets")
        if ta0 is not None:
            pio.setdefault("total_assets", float(ta0))
        if ta1 is not None:
            pio.setdefault("total_assets_prior", float(ta1))
        snapshot["piotroski"] = pio
        snapshot["piotroski_partial_from"] = "financial_report_api"
