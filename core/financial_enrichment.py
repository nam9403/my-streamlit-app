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


def _eps_scale_candidates() -> list[float]:
    """Thử các hệ số đơn vị phổ biến (nghìn/trăm/chục) + II_EPS_SCALE."""
    primary = _eps_scale()
    out: list[float] = []
    for f in (primary, 1000.0, 100.0, 10.0):
        try:
            fv = float(f)
        except (TypeError, ValueError):
            continue
        if fv >= 2.0 and fv not in out:
            out.append(fv)
    return out


def _eps_unit_score(
    eps: float,
    price: float,
    *,
    bvps: float | None = None,
    sector_pe: float | None = None,
    pe_src: float | None = None,
    reported_roe_pct: float | None = None,
) -> float:
    """Điểm càng cao càng hợp lý cho VND/cp (EY, P/E, ROE từ EPS/BV)."""
    if eps <= 0 or price <= 0:
        return -1e9
    ey = eps / price
    pe = price / eps
    score = 0.0
    # Earnings yield mục tiêu ~2–12%
    if 0.02 <= ey <= 0.12:
        score += 3.0
    elif ey <= 0.15:
        score += 1.5
    elif ey <= 0.20:
        score += 0.2
    else:
        score -= min(8.0, (ey - 0.20) * 20.0)
    # P/E phổ biến VN 5–35
    if 5.0 <= pe <= 35.0:
        score += 3.0
    elif 3.0 <= pe < 5.0 or 35.0 < pe <= 50.0:
        score += 1.0
    elif pe < 3.0:
        score -= 4.0
    elif pe > 80.0:
        score -= 3.0
    if sector_pe and sector_pe > 0:
        gap = abs(pe - sector_pe) / sector_pe
        score += max(-2.5, 2.0 - gap * 3.0)
    if pe_src and pe_src > 0 and 5.0 <= pe_src <= 40.0:
        # Chỉ thưởng khớp P/E nguồn khi P/E nguồn nằm vùng hợp lý.
        gap_src = abs(pe - pe_src) / max(pe_src, pe, 1e-6)
        score += max(-1.5, 1.5 - gap_src * 2.0)
    if bvps and bvps > 0:
        roe_from_eps = (eps / bvps) * 100.0
        if 5.0 <= roe_from_eps <= 35.0:
            score += 2.5
        elif roe_from_eps <= 50.0:
            score += 0.8
        elif roe_from_eps > 80.0:
            score -= min(6.0, (roe_from_eps - 80.0) / 20.0)
        if reported_roe_pct and reported_roe_pct > 0:
            # ROE báo cáo đã % — EPS không nên hàm ý ROE gấp đôi báo cáo.
            if roe_from_eps > reported_roe_pct * 2.0 and roe_from_eps > 40.0:
                score -= 2.5
    return score


def normalize_eps_to_vnd_per_share(
    eps: Any,
    price: Any,
    *,
    pe_ratio: Any = None,
    bvps: Any = None,
    sector_pe: Any = None,
    reported_roe: Any = None,
) -> tuple[float | None, list[str]]:
    """
    Chuẩn hóa EPS về VND/cp khi lệch đơn vị / yield bất thường.

    - Thử ÷ {II_EPS_SCALE, 1000, 100, 10} khi EY cao hoặc P/E nguồn lệch.
    - P/E nguồn khớp EPS thô vẫn có thể scale nếu ROE(EPS/BV) hoặc EY quá cao
      (trường hợp “P/E rẻ giả” cùng nguồn EPS sai đơn vị).
    """
    v = _as_float(eps)
    px = _as_float(price)
    notes: list[str] = []
    if v is None or v <= 0 or px is None or px <= 0:
        return v, notes

    pe_src = _as_float(pe_ratio)
    pe_calc = px / v
    ey = v / px
    bv = _as_float(bvps)
    sec_pe = _as_float(sector_pe)
    roe_pct = normalize_roe_to_pct(reported_roe)

    pe_matches = False
    if pe_src and pe_src > 0 and pe_calc > 0:
        gap_pe = abs(pe_src - pe_calc) / max(pe_src, pe_calc, 1e-6)
        pe_matches = gap_pe <= 0.20

    roe_from_eps = (v / bv) * 100.0 if bv and bv > 0 else None
    absurd_roe = roe_from_eps is not None and roe_from_eps > 80.0
    absurd_ey = ey > 0.20
    cheap_pe = pe_calc < 5.0
    # Khớp P/E + EY vừa phải + ROE ổn → giữ (P/E thấp thật).
    if pe_matches and not absurd_ey and not absurd_roe and ey <= 0.15:
        return v, notes
    if pe_matches and not absurd_ey and not absurd_roe and not cheap_pe:
        return v, notes

    need_fix = (
        (not pe_matches and pe_src is not None and pe_src > 0 and pe_calc > 0)
        or ey > 0.15
        or absurd_roe
        or (pe_matches and cheap_pe and absurd_ey)
    )
    if not need_fix:
        return v, notes

    # implied từ P/E nguồn khi P/E nguồn hợp lý và lệch rõ với EPS thô
    candidates: list[tuple[float, str]] = [(v, "raw")]
    if pe_src and pe_src >= 5.0 and pe_src <= 50.0:
        implied = px / pe_src
        if implied > 0:
            ratio = v / implied
            for fac in _eps_scale_candidates():
                if abs(ratio / fac - 1.0) <= 0.35:
                    candidates.append((v / fac, f"÷{fac:g}≈P/E"))
                    break
            if not pe_matches:
                candidates.append((implied, "implied_pe"))

    for fac in _eps_scale_candidates():
        scaled = v / fac
        if scaled > 0:
            candidates.append((scaled, f"÷{fac:g}"))

    # Chỉ neo P/E ngành khi tín hiệu đơn vị mạnh (tránh đè EPS thật bằng sector mid).
    if sec_pe and sec_pe >= 5.0 and (absurd_roe or absurd_ey or cheap_pe):
        implied_sec = px / sec_pe
        if implied_sec > 0:
            candidates.append((implied_sec, "implied_sector_pe"))

    best_eps = v
    best_score = _eps_unit_score(
        v, px, bvps=bv, sector_pe=sec_pe, pe_src=pe_src, reported_roe_pct=roe_pct
    )
    best_tag = "raw"
    for cand, tag in candidates:
        if cand <= 0:
            continue
        sc = _eps_unit_score(
            cand, px, bvps=bv, sector_pe=sec_pe, pe_src=pe_src, reported_roe_pct=roe_pct
        )
        # Ưu tiên điểm cao; với điểm gần bằng, giữ gần raw hơn (ít can thiệp).
        if sc > best_score + 0.15 or (abs(sc - best_score) <= 0.15 and abs(cand - v) < abs(best_eps - v)):
            best_score = sc
            best_eps = cand
            best_tag = tag

    # Chỉ chấp nhận khi cải thiện rõ (tránh chia scale lung tung).
    raw_score = _eps_unit_score(
        v, px, bvps=bv, sector_pe=sec_pe, pe_src=pe_src, reported_roe_pct=roe_pct
    )
    if abs(best_eps - v) <= 1e-6 or best_score < raw_score + 1.0:
        return v, notes

    pe_new = px / best_eps if best_eps > 0 else 0.0
    notes.append(
        f"EPS chuẩn hóa {v:,.2f}→{best_eps:,.2f} VND/cp ({best_tag}; "
        f"EY {v/px:.1%}→{best_eps/px:.1%}; P/E tính {pe_calc:.2f}→{pe_new:.2f})."
    )
    return round(float(best_eps), 4), notes


def normalize_eps_in_snapshot(snapshot: dict[str, Any]) -> list[str]:
    """In-place EPS normalize; giữ eps_raw khi đổi scale; đồng bộ eps_ttm."""
    if not isinstance(snapshot, dict):
        return []
    sector_pe = (
        snapshot.get("sector_pe_5y_avg")
        or snapshot.get("sector_pe")
        or snapshot.get("industry_pe")
    )
    eps_new, notes = normalize_eps_to_vnd_per_share(
        snapshot.get("eps"),
        snapshot.get("price"),
        pe_ratio=snapshot.get("pe_ratio"),
        bvps=snapshot.get("book_value_per_share") or snapshot.get("bvps"),
        sector_pe=sector_pe,
        reported_roe=snapshot.get("roe") or snapshot.get("roe_5y_avg"),
    )
    old = _as_float(snapshot.get("eps"))
    if eps_new is not None and old is not None and abs(eps_new - old) > 1e-6:
        factor = old / eps_new if eps_new > 0 else 1.0
        snapshot["eps_raw"] = old
        snapshot["eps"] = eps_new
        snapshot["eps_normalized"] = True  # bool: unit-scale applied
        snapshot["eps_unit_scale_factor"] = round(float(factor), 6)
        px = _as_float(snapshot.get("price"))
        if px and eps_new > 0:
            snapshot["pe_ratio_recalc"] = round(float(px) / eps_new, 4)
            # P/E nguồn cùng scale sai → cập nhật theo EPS đã chuẩn.
            pe_old = _as_float(snapshot.get("pe_ratio"))
            if pe_old is not None and pe_old > 0:
                pe_from_old = px / old if old > 0 else 0.0
                if pe_from_old > 0 and abs(pe_old - pe_from_old) / max(pe_old, pe_from_old) <= 0.25:
                    snapshot["pe_ratio_raw"] = pe_old
                    snapshot["pe_ratio"] = round(float(px) / eps_new, 4)
        # Đồng bộ TTM / normalized copy cùng đơn vị.
        ttm = _as_float(snapshot.get("eps_ttm"))
        if ttm is not None and ttm > 0 and factor >= 2.0:
            ratio_ttm = ttm / old if old > 0 else 0.0
            if abs(ratio_ttm - 1.0) <= 0.35 or ttm / (px or 1.0) > 0.15:
                snapshot.setdefault("eps_ttm_raw", ttm)
                snapshot["eps_ttm"] = round(ttm / factor, 4)
                notes.append(f"EPS TTM đồng bộ đơn vị ÷{factor:g}.")
        norm = _as_float(snapshot.get("normalized_eps"))
        if norm is not None and norm > 0 and factor >= 2.0:
            if abs(norm - old) / max(abs(old), 1e-6) <= 0.35:
                snapshot["normalized_eps"] = round(norm / factor, 6)
    # Nếu thiếu eps nhưng có eps_ttm lệch đơn vị — chuẩn hóa TTM.
    elif _as_float(snapshot.get("eps")) in (None, 0) or (
        _as_float(snapshot.get("eps")) is not None and _as_float(snapshot.get("eps")) <= 0
    ):
        ttm = _as_float(snapshot.get("eps_ttm"))
        if ttm and ttm > 0:
            ttm_new, ttm_notes = normalize_eps_to_vnd_per_share(
                ttm,
                snapshot.get("price"),
                pe_ratio=snapshot.get("pe_ratio"),
                bvps=snapshot.get("book_value_per_share") or snapshot.get("bvps"),
                sector_pe=sector_pe,
                reported_roe=snapshot.get("roe") or snapshot.get("roe_5y_avg"),
            )
            if ttm_new is not None and abs(ttm_new - ttm) > 1e-6:
                snapshot["eps_ttm_raw"] = ttm
                snapshot["eps_ttm"] = ttm_new
                snapshot["eps_normalized"] = True
                notes.extend(ttm_notes)
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

        # EPS / BVPS suy từ P/E–P/B khi scrape chỉ trả giá (tránh fair=giá, MOS=0).
        pe = _as_float(fin.get("pe_ratio"))
        pb = _as_float(fin.get("pb_ratio"))
        if pe is not None and pe > 0 and _missing_positive(snapshot, "pe_ratio"):
            snapshot["pe_ratio"] = pe
        if pb is not None and pb > 0 and _missing_positive(snapshot, "pb_ratio"):
            snapshot["pb_ratio"] = pb
        px = _as_float(snapshot.get("price")) or 0.0
        pe_use = _as_float(snapshot.get("pe_ratio")) or pe
        pb_use = _as_float(snapshot.get("pb_ratio")) or pb
        if px > 0 and pe_use is not None and pe_use > 0.5 and _missing_positive(snapshot, "eps"):
            snapshot["eps"] = round(px / pe_use, 4)
            snapshot["eps_source"] = "price_div_pe_indicator"
            notes.append(f"EPS suy từ giá/P/E ({src})")
        if px > 0 and pb_use is not None and pb_use > 0.05 and _missing_positive(
            snapshot, "book_value_per_share"
        ) and _missing_positive(snapshot, "bvps"):
            snapshot["book_value_per_share"] = round(px / pb_use, 4)
            snapshot["bvps_source"] = "price_div_pb_indicator"
            notes.append(f"BVPS suy từ giá/P/B ({src})")

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

    # Neo P/E–P/B ngành từ peer/ICB/prior trước định giá.
    try:
        from core.sector_multiples import inject_sector_multiples_into_snapshot

        notes.extend(inject_sector_multiples_into_snapshot(snapshot))
    except Exception:
        pass

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
