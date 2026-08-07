"""
Lõi định giá: Benjamin Graham, P/E Forward (EPS dự phóng × P/E ngành 5y),
P/B (BVPS × P/B tham chiếu — nhấn mạnh nhóm ngân hàng), tổng hợp trọng số,
Piotroski F-Score, Margin of Safety.
"""

from __future__ import annotations

import logging
import os
import re
from pathlib import Path
from typing import Any

from core.config import (
    GRAHAM_CLASSIC_AAA_YIELD_PCT,
    GRAHAM_GROWTH_G_CAP_PCT,
    resolve_vn_10y_bond_yield_pct,
)

_ROOT = Path(__file__).resolve().parent.parent
_logger = logging.getLogger(__name__)

# Mặc định khi snapshot không có P/E ngành 5 năm / P/B tham chiếu (nên thay bằng số liệu thật trong JSON/API)
_DEFAULT_SECTOR_PE_5Y_NON_BANK = 14.0
_DEFAULT_SECTOR_PE_5Y_BANK = 10.0
_DEFAULT_FAIR_PB_BANK = 1.25
_DEFAULT_FAIR_PB_BANK_ROE_STRONG = 1.45  # ROE ≥ 18%: NH chất lượng không bị kẹp P/B 1.25
_DEFAULT_FAIR_PB_NON_BANK = 2.25

# Ngưỡng cảnh báo khi Graham Growth lệch so với Graham Capped / P/E ngành
_GRAHAM_GROWTH_DIVERGENCE_PCT = 50.0

_BANK_SYMBOLS = frozenset(
    {
        "VCB",
        "BID",
        "CTG",
        "TCB",
        "VPB",
        "MBB",
        "ACB",
        "STB",
        "HDB",
        "TPB",
        "VIB",
        "MSB",
        "SSB",
        "NAB",
        "OCB",
        "SHB",
        "EIB",
        "PGB",
        "BAB",
        "NVB",
        "ABB",
    }
)


def normalize_graham_growth_pct(growth_rate_pct: float | None) -> dict[str, Any]:
    """
    Khống chế g cho Graham Growth:
    - g_calc < 0 → g = 0 (fallback về zero-growth / Graham Number ở tầng gọi)
    - g_calc > 15% → g = 15% (tránh fair value ảo ở đỉnh chu kỳ)
    """
    try:
        raw = float(growth_rate_pct) if growth_rate_pct is not None else 0.0
    except (TypeError, ValueError):
        raw = 0.0
    negative = raw < 0.0
    if negative:
        g = 0.0
    else:
        g = min(raw, float(GRAHAM_GROWTH_G_CAP_PCT))
    return {
        "g_pct": float(g),
        "g_raw_pct": float(raw),
        "g_capped": bool(not negative and raw > float(GRAHAM_GROWTH_G_CAP_PCT)),
        "g_negative": bool(negative),
        "g_cap_pct": float(GRAHAM_GROWTH_G_CAP_PCT),
        "fallback_to_graham_number": bool(negative),
    }


def benjamin_graham_value(
    eps: float,
    growth_rate_pct: float,
    bond_yield_pct: float | None = None,
    base_multiplier: float = 8.5,
    *,
    aaa_yield_pct: float = GRAHAM_CLASSIC_AAA_YIELD_PCT,
    apply_g_cap: bool = True,
) -> float:
    """
    Graham Growth Formula:
    V = EPS × (base_multiplier + 2 × g) × (4.4 / Y)

    - g: tăng trưởng EPS (%/năm), ví dụ 7 = 7%. Mặc định trần 15%; g < 0 → 0.
    - Y: lợi suất TPCP VN ~10Y (``VN_10Y_BOND_YIELD``), mặc định ~6.5%.
    - 4.4: AAA Mỹ thời Graham (numerator cố định theo sách).
    """
    if eps <= 0:
        return 0.0
    if apply_g_cap:
        g = float(normalize_graham_growth_pct(growth_rate_pct)["g_pct"])
    else:
        g = max(float(growth_rate_pct or 0.0), 0.0)
    y = resolve_vn_10y_bond_yield_pct(bond_yield_pct)
    aaa = float(aaa_yield_pct) if aaa_yield_pct and aaa_yield_pct > 0 else GRAHAM_CLASSIC_AAA_YIELD_PCT
    factor = aaa / y
    return float(eps * (base_multiplier + 2.0 * g) * factor)


def graham_growth_divergence_notes(
    graham_growth_fv: float,
    *,
    graham_capped: float = 0.0,
    sector_pe_fair: float = 0.0,
    threshold_pct: float = _GRAHAM_GROWTH_DIVERGENCE_PCT,
    symbol: str = "",
) -> list[str]:
    """Cảnh báo nếu Fair Value Graham Growth lệch > threshold so với Graham Capped hoặc P/E ngành."""
    notes: list[str] = []
    gg = float(graham_growth_fv or 0.0)
    if gg <= 0:
        return notes
    thr = max(float(threshold_pct), 1.0) / 100.0
    refs: list[tuple[str, float]] = []
    if float(graham_capped or 0.0) > 0:
        refs.append(("Graham Capped", float(graham_capped)))
    if float(sector_pe_fair or 0.0) > 0:
        refs.append(("P/E ngành", float(sector_pe_fair)))
    sym = str(symbol or "").strip().upper()
    prefix = f"{sym}: " if sym else ""
    for label, ref in refs:
        gap = abs(gg - ref) / ref
        if gap > thr:
            msg = (
                f"{prefix}Graham Growth FV ({gg:,.0f}) lệch {gap * 100:.0f}% so với {label} "
                f"({ref:,.0f}) — kiểm tra g / EPS / đơn vị trước khi dùng."
            )
            notes.append(msg)
            _logger.warning(msg)
    return notes


def margin_of_safety_pct(intrinsic_value: float, market_price: float) -> float | None:
    """
    Biên an toàn = (V - P) / V × 100. Trả None nếu V <= 0.
    """
    if intrinsic_value <= 0:
        return None
    return float((intrinsic_value - market_price) / intrinsic_value * 100.0)


def _safe_div(num: float, den: float) -> float:
    return num / den if den else 0.0


def piotroski_f_score(metrics: dict[str, Any]) -> tuple[int, list[str]]:
    """
    F-Score 0–9 từ một dict kỳ hiện tại & kỳ trước (số tuyệt đối, không cần /cổ).

    Khóa mong đợi (tên có thể map từ báo cáo):
    net_income, net_income_prior, operating_cash_flow, operating_cash_flow_prior,
    total_assets, total_assets_prior, long_term_debt, long_term_debt_prior,
    current_assets, current_liabilities, current_assets_prior, current_liabilities_prior,
    shares_outstanding, shares_outstanding_prior,
    revenue, revenue_prior, cogs, cogs_prior
    """
    reasons: list[str] = []

    ni = float(metrics.get("net_income") or 0)
    ni_p = float(metrics.get("net_income_prior") or 0)
    ocf = float(metrics.get("operating_cash_flow") or 0)
    ta = float(metrics.get("total_assets") or 0)
    ta_p = float(metrics.get("total_assets_prior") or 0)
    ltd = float(metrics.get("long_term_debt") or 0)
    ltd_p = float(metrics.get("long_term_debt_prior") or 0)
    ca = float(metrics.get("current_assets") or 0)
    cl = float(metrics.get("current_liabilities") or 0)
    ca_p = float(metrics.get("current_assets_prior") or 0)
    cl_p = float(metrics.get("current_liabilities_prior") or 0)
    sh = float(metrics.get("shares_outstanding") or 0)
    sh_p = float(metrics.get("shares_outstanding_prior") or 0)
    rev = float(metrics.get("revenue") or 0)
    rev_p = float(metrics.get("revenue_prior") or 0)
    cogs = float(metrics.get("cogs") or 0)
    cogs_p = float(metrics.get("cogs_prior") or 0)

    roa = _safe_div(ni, ta)
    roa_p = _safe_div(ni_p, ta_p)
    avg_assets = (ta + ta_p) / 2.0 if ta_p else ta
    avg_assets_p = ta_p
    ltd_ratio = _safe_div(ltd, avg_assets) if avg_assets else 0.0
    ltd_ratio_p = _safe_div(ltd_p, avg_assets_p) if avg_assets_p else 0.0
    cr = _safe_div(ca, cl)
    cr_p = _safe_div(ca_p, cl_p)
    gm = _safe_div(rev - cogs, rev) if rev else 0.0
    gm_p = _safe_div(rev_p - cogs_p, rev_p) if rev_p else 0.0
    # MVP: vòng quay tài sản so sánh năm n / n-1 (cùng cách định nghĩa mẫu số)
    ato = _safe_div(rev, avg_assets) if avg_assets else _safe_div(rev, ta)
    ato_p = _safe_div(rev_p, ta_p) if ta_p else 0.0

    score = 0

    if ni > 0:
        score += 1
        reasons.append("LNST dương (+1)")
    if ocf > 0:
        score += 1
        reasons.append("Dòng tiền HĐKD dương (+1)")
    if roa > roa_p:
        score += 1
        reasons.append("ROA cải thiện (+1)")
    if ocf > ni:
        score += 1
        reasons.append("OCF > LNST (chất lượng lợi nhuận) (+1)")
    if ltd_ratio < ltd_ratio_p:
        score += 1
        reasons.append("Tỷ lệ nợ dài hạn trên tài sản giảm (+1)")
    if cr > cr_p:
        score += 1
        reasons.append("Hệ số thanh toán hiện hành cải thiện (+1)")
    if sh <= sh_p:
        score += 1
        reasons.append("Không pha loãng (CP lưu hành không tăng) (+1)")
    if gm > gm_p:
        score += 1
        reasons.append("Biên lợi nhuận gộp cải thiện (+1)")
    if ato > ato_p:
        score += 1
        reasons.append("Vòng quay tài sản cải thiện (+1)")

    return score, reasons


def _bank_quality_score(metrics: dict[str, Any]) -> tuple[int, list[str]]:
    """
    Quality score for financial institutions (scaled to 0-9).
    Uses available proxy metrics when full bank-specific ratios are unavailable.
    """
    reasons: list[str] = []
    ni = float(metrics.get("net_income") or 0)
    ni_p = float(metrics.get("net_income_prior") or 0)
    ocf = float(metrics.get("operating_cash_flow") or 0)
    rev = float(metrics.get("revenue") or 0)
    rev_p = float(metrics.get("revenue_prior") or 0)
    sh = float(metrics.get("shares_outstanding") or 0)
    sh_p = float(metrics.get("shares_outstanding_prior") or 0)

    raw = 0
    if ni > 0:
        raw += 1
        reasons.append("LNST dương (+1)")
    if ni_p > 0 and ni > ni_p:
        raw += 1
        reasons.append("LNST tăng so với kỳ trước (+1)")
    if ocf > 0:
        raw += 1
        reasons.append("Dòng tiền HĐKD dương (+1)")
    if ni > 0 and ocf >= 0.8 * ni:
        raw += 1
        reasons.append("OCF bám sát LNST (chất lượng lợi nhuận) (+1)")
    if sh <= sh_p and sh_p > 0:
        raw += 1
        reasons.append("Không pha loãng cổ phần (+1)")
    if rev > rev_p and rev_p > 0:
        raw += 1
        reasons.append("Thu nhập/DT hoạt động tăng (+1)")

    # Scale 6-point raw score to 9-point convention for UI consistency.
    scaled = int(round(raw * 9.0 / 6.0))
    scaled = max(0, min(9, scaled))
    return scaled, reasons


def forward_pe_target_price(eps_forward: float, sector_pe_5y_avg: float) -> float:
    """
    Giá mục tiêu theo P/E Forward: EPS (dự phóng) × P/E trung bình ngành ~5 năm.
    """
    if eps_forward <= 0 or sector_pe_5y_avg <= 0:
        return 0.0
    return float(eps_forward * sector_pe_5y_avg)


def book_value_target_price(book_value_per_share: float, fair_pb_multiple: float) -> float:
    """
    Giá mục tiêu theo sổ sách: BVPS × hệ số P/B tham chiếu (thường dùng cho cổ phiếu ngân hàng).
    """
    if book_value_per_share <= 0 or fair_pb_multiple <= 0:
        return 0.0
    return float(book_value_per_share * fair_pb_multiple)


def get_industry_weights(industry_name: str) -> dict[str, float]:
    """
    Trọng số định giá theo ngành (P/E Forward, P/B, Graham).
    Khóa trả về: 'PE', 'PB', 'Graham' — tổng = 1.0.

    Phân nhóm (theo chuỗi mô tả ngành tiếng Việt/Anh từ metadata hoặc scraper):
    - Tài chính (NH, BH, CK): PE 0.2, PB 0.7, Graham 0.1
    - Bất động sản: 0.3 / 0.5 / 0.2
    - Công nghệ / Viễn thông: 0.75 / 0.1 / 0.15
    - Tiêu dùng / Bán lẻ / Vận tải: 0.6 / 0.1 / 0.3
    - Năng lượng / Dầu khí / Sản xuất: 0.5 / 0.3 / 0.2
    - Phòng thủ (Y tế, Điện nước): 0.4 / 0.1 / 0.5
    - Mặc định: 0.4 / 0.3 / 0.3
    """
    cluster, _ = _classify_industry_cluster(industry_name or "")
    pe, pb, gr = _INDUSTRY_WEIGHT_TABLE[cluster]
    return {"PE": pe, "PB": pb, "Graham": gr}


def weights_for_industry_cluster(cluster_id: str) -> dict[str, float]:
    """Trọng số theo mã nhóm cố định (dùng khi đã biết cluster từ metadata)."""
    cid = (cluster_id or "default").strip().lower()
    if cid not in _INDUSTRY_WEIGHT_TABLE:
        cid = "default"
    pe, pb, gr = _INDUSTRY_WEIGHT_TABLE[cid]
    return {"PE": pe, "PB": pb, "Graham": gr}


def _industry_cluster_label_vi(cluster: str) -> str:
    return _INDUSTRY_CLUSTER_LABELS_VI.get(cluster, _INDUSTRY_CLUSTER_LABELS_VI["default"])


# (PE, PB, Graham) — đúng thứ tự công thức: Final = PE_price*PE + PB_price*PB + Graham_price*Graham
_INDUSTRY_WEIGHT_TABLE: dict[str, tuple[float, float, float]] = {
    "financial": (0.2, 0.7, 0.1),
    "real_estate": (0.3, 0.5, 0.2),
    "tech_telecom": (0.75, 0.1, 0.15),
    "consumer_retail_transport": (0.6, 0.1, 0.3),
    "energy_manufacturing": (0.5, 0.3, 0.2),
    "defensive": (0.4, 0.1, 0.5),
    "default": (0.4, 0.3, 0.3),
}

_INDUSTRY_CLUSTER_LABELS_VI = {
    "financial": "Nhóm Tài chính (Ngân hàng, Bảo hiểm, Chứng khoán)",
    "real_estate": "Nhóm Bất động sản",
    "tech_telecom": "Nhóm Công nghệ / Viễn thông",
    "consumer_retail_transport": "Nhóm Tiêu dùng / Bán lẻ / Vận tải",
    "energy_manufacturing": "Nhóm Năng lượng / Dầu khí / Sản xuất",
    "defensive": "Nhóm phòng thủ (Y tế, Điện — nước)",
    "default": "Mặc định (đa ngành)",
}

_INDUSTRY_SUBTYPE_LABELS_VI = {
    "bank": "Ngân hàng",
    "securities": "Chứng khoán",
    "insurance": "Bảo hiểm",
    "real_estate_residential": "Bất động sản dân dụng",
    "real_estate_kcn": "Bất động sản khu công nghiệp",
    "consumer_staples": "Tiêu dùng thiết yếu",
    "consumer_retail": "Bán lẻ tiêu dùng",
    "oil_gas": "Dầu khí",
    "steel_materials": "Thép & vật liệu cơ bản",
    "pharma_healthcare": "Dược & y tế",
    "technology_services": "Công nghệ dịch vụ",
    "other": "Khác",
}

# (PE, PB, Graham) cho phân nhóm sâu; chỉ áp dụng khi nhận diện được subtype.
_INDUSTRY_SUBTYPE_WEIGHT_TABLE: dict[str, tuple[float, float, float]] = {
    "bank": (0.20, 0.55, 0.25),  # PE, PB, Graham — bớt kẹp P/B so với (0.15, 0.75, 0.10)
    "securities": (0.45, 0.45, 0.10),
    "insurance": (0.30, 0.55, 0.15),
    "real_estate_residential": (0.35, 0.50, 0.15),
    "real_estate_kcn": (0.45, 0.35, 0.20),
    "consumer_staples": (0.50, 0.20, 0.30),
    "consumer_retail": (0.60, 0.15, 0.25),
    "oil_gas": (0.45, 0.35, 0.20),
    "steel_materials": (0.40, 0.40, 0.20),
    "pharma_healthcare": (0.40, 0.20, 0.40),
    "technology_services": (0.75, 0.10, 0.15),
}


def _classify_industry_cluster(industry_text: str) -> tuple[str, str]:
    """
    Trả (cluster_id, chuỗi gốc đã chuẩn hóa để hiển thị).
    Thứ tự ưu tiên: tài chính → BĐS → công nghệ → tiêu dùng → năng lượng/sản xuất → phòng thủ.
    """
    raw = (industry_text or "").strip()
    t = raw.lower()
    t = re.sub(r"\s+", " ", t)

    def hit(keys: tuple[str, ...]) -> bool:
        return any(k in t for k in keys)

    # Tài chính (ưu tiên cao nếu có từ khóa CK/BH/NH)
    if hit(
        (
            "ngân hàng",
            "bank",
            "bao hiem",
            "bảo hiểm",
            "insurance",
            "chứng khoán",
            "chung khoan",
            "securities",
            "broker",
            "tài chính",
            "tai chinh",
            "finance",
            "đầu tư",
            "dau tu",
        )
    ):
        return "financial", raw or "Tài chính"

    if hit(("bất động sản", "bat dong san", "real estate", "bđs", "khu công nghiệp", "kcn")):
        return "real_estate", raw or "Bất động sản"

    if hit(
        (
            "công nghệ",
            "cong nghe",
            "technology",
            "software",
            "phần mềm",
            "phan mem",
            "viễn thông",
            "vien thong",
            "telecom",
            "it ",
            "cntt",
            "máy tính",
            "may tinh",
        )
    ):
        return "tech_telecom", raw or "Công nghệ / Viễn thông"

    if hit(
        (
            "tiêu dùng",
            "tieu dung",
            "bán lẻ",
            "ban le",
            "retail",
            "vận tải",
            "van tai",
            "logistics",
            "hàng không",
            "hang khong",
            "du lịch",
            "du lich",
        )
    ):
        return "consumer_retail_transport", raw or "Tiêu dùng / Bán lẻ / Vận tải"

    if hit(
        (
            "y tế",
            "y te",
            "health",
            "dược",
            "duoc",
            "pharma",
            "điện nước",
            "dien nuoc",
            "utility",
            "utilities",
            "nước sạch",
            "nuoc sach",
            "điện lực",
            "dien luc",
        )
    ):
        return "defensive", raw or "Y tế / Tiện ích"

    if hit(
        (
            "năng lượng",
            "nang luong",
            "dầu khí",
            "dau khi",
            "oil",
            "gas",
            "san xuat",
            "sản xuất",
            "manufacturing",
            "hóa chất",
            "hoa chat",
            "thép",
            "thep",
            "khai khoáng",
            "khai khoang",
        )
    ):
        return "energy_manufacturing", raw or "Năng lượng / Sản xuất"

    return "default", raw or "Chưa phân loại ngành"


def _classify_industry_subtype(industry_text: str, cluster_id: str) -> str:
    t = (industry_text or "").strip().lower()
    if cluster_id == "financial":
        if any(k in t for k in ("ngân hàng", "ngan hang", "bank")):
            return "bank"
        if any(k in t for k in ("chứng khoán", "chung khoan", "securities", "broker", "môi giới", "moi gioi")):
            return "securities"
        if any(k in t for k in ("bảo hiểm", "bao hiem", "insurance", "phi nhân thọ", "nhân thọ", "tai nan")):
            return "insurance"
    if cluster_id == "real_estate":
        if any(
            k in t
            for k in (
                "khu công nghiệp",
                "khu cong nghiep",
                "kcn",
                "industrial park",
                "bất động sản công nghiệp",
                "bat dong san cong nghiep",
                "hạ tầng khu công nghiệp",
                "ha tang khu cong nghiep",
            )
        ):
            return "real_estate_kcn"
        return "real_estate_residential"
    if cluster_id == "consumer_retail_transport":
        if any(k in t for k in ("bán lẻ", "ban le", "retail", "thế giới di động", "the gioi di dong")):
            return "consumer_retail"
        return "consumer_staples"
    if cluster_id == "energy_manufacturing":
        if any(k in t for k in ("dầu khí", "dau khi", "oil", "gas")):
            return "oil_gas"
        if any(k in t for k in ("thép", "thep", "steel", "vật liệu", "vat lieu")):
            return "steel_materials"
        return "other"
    if cluster_id == "defensive":
        if any(k in t for k in ("dược", "duoc", "pharma", "y tế", "y te", "health")):
            return "pharma_healthcare"
        return "other"
    if cluster_id == "tech_telecom":
        if any(k in t for k in ("công nghệ", "cong nghe", "technology", "software", "it", "dịch vụ công nghệ")):
            return "technology_services"
        return "other"
    return "other"


def _load_stock_metadata_file() -> dict[str, Any]:
    """
    Cùng nguồn với scrapers.financial_data (cache theo mtime) — tránh đọc JSON lặp + stale LRU.
    """
    from scrapers.financial_data import _load_stock_metadata

    return _load_stock_metadata()


def _metadata_for_symbol(symbol: str) -> dict[str, Any]:
    meta = _load_stock_metadata_file()
    entry = meta.get(symbol.strip().upper())
    return entry if isinstance(entry, dict) else {}


def resolve_industry_for_snapshot(snapshot: dict[str, Any]) -> tuple[str, str]:
    """
    Trả (industry_display_vi, cluster_id).
    Ưu tiên industry_cluster trong snapshot/metadata; sau đó chuỗi ngành; cuối cùng phân loại từ text.
    """
    sym = str(snapshot.get("symbol") or "").strip().upper()
    meta = _metadata_for_symbol(sym)

    cluster_override = snapshot.get("industry_cluster") or meta.get("industry_cluster")
    if isinstance(cluster_override, str):
        cid = cluster_override.strip().lower().replace("-", "_")
        if cid in _INDUSTRY_WEIGHT_TABLE:
            disp = str(
                snapshot.get("industry")
                or snapshot.get("industry_name")
                or meta.get("industry_vi")
                or meta.get("industry")
                or _industry_cluster_label_vi(cid)
            )
            return disp, cid

    text = (
        snapshot.get("industry")
        or snapshot.get("industry_name")
        or snapshot.get("sector_name")
        or snapshot.get("icb_industry")
        or meta.get("industry_vi")
        or meta.get("industry")
        or ""
    )
    text = str(text).strip()
    cluster, hint = _classify_industry_cluster(text)
    display = text if text else hint
    return display, cluster


def weighted_composite_target_price(
    graham_value: float,
    forward_pe_value: float,
    pb_value: float,
    weight_graham: float,
    weight_forward_pe: float,
    weight_pb: float,
) -> tuple[float, dict[str, Any]]:
    """
    Trung bình trọng số; chỉ tính các phương pháp có giá trị > 0, chuẩn hóa lại trọng số.
    Trả về (giá tổng hợp, meta: weights_effective, included).
    """
    candidates: list[tuple[str, float, float]] = []
    if graham_value > 0:
        candidates.append(("graham", graham_value, weight_graham))
    if forward_pe_value > 0:
        candidates.append(("forward_pe", forward_pe_value, weight_forward_pe))
    if pb_value > 0:
        candidates.append(("pb", pb_value, weight_pb))

    if not candidates:
        return 0.0, {"included": [], "weights_effective": {}}

    w_sum = sum(c[2] for c in candidates)
    if w_sum <= 0:
        return 0.0, {"included": [], "weights_effective": {}}

    total = sum(val * w / w_sum for _, val, w in candidates)
    eff_w = {name: w / w_sum for name, _, w in candidates}
    return float(total), {
        "included": [c[0] for c in candidates],
        "weights_effective": eff_w,
    }


def capped_graham_fair(
    graham: float,
    price: float,
    *,
    max_mos_pct: float = 60.0,
    max_multiple_of_price: float = 2.5,
) -> float:
    """
    Graham Number bị trần theo giá thị trường để tránh blow-up khi EPS lệch đơn vị.
    Không thay thế Graham thô (vẫn giữ để tham chiếu).
    """
    g = float(graham or 0.0)
    p = float(price or 0.0)
    if g <= 0:
        return 0.0
    if p <= 0:
        return g
    cap_mos = p * (1.0 + max(0.0, float(max_mos_pct)) / 100.0)
    cap_mult = p * max(1.0, float(max_multiple_of_price))
    return float(min(g, cap_mos, cap_mult))


_BEST_FAIR_LABELS_VI = {
    "graham_raw": "Graham Number (thô)",
    "graham_capped": "Graham Number (đã trần)",
    "sector_pe": "P/E ngành × EPS",
    "pb": "P/B hợp lý × BVPS",
    "industry_weighted": "Tổng hợp ngành (Graham+P/E+P/B)",
    "hybrid_legend": "Hybrid Legend",
}


def select_best_fair_value(
    *,
    graham_raw: float,
    graham_capped: float,
    pe_fair: float,
    pb_fair: float,
    price: float,
    eps_trusted: bool,
    mos_integrity_blocked: bool,
    pe_anomaly_flag: bool = False,
    industry_weights: dict[str, float] | None = None,
    is_bank: bool = False,
) -> dict[str, Any]:
    """
    Chọn định giá công bố (best fair) từ nhiều mô hình.

    - Luôn giữ graham_raw trong methods để UI tham chiếu.
    - Khi nghi EPS/P/E: ưu tiên pb / graham_capped / sector_pe (nếu EPS tin được).
    - Khi dữ liệu ổn: ưu tiên industry-weighted hoặc hybrid gần nhất.
    """
    methods: dict[str, float] = {
        "graham_raw": float(graham_raw or 0.0),
        "graham_capped": float(graham_capped or 0.0),
        "sector_pe": float(pe_fair or 0.0) if eps_trusted else 0.0,
        "pb": float(pb_fair or 0.0),
    }
    suspect = bool(mos_integrity_blocked or pe_anomaly_flag or not eps_trusted)

    scores: dict[str, float] = {}
    if methods["graham_raw"] > 0:
        scores["graham_raw"] = 0.25 if suspect else 0.55
    if methods["graham_capped"] > 0:
        scores["graham_capped"] = 0.55 if suspect else 0.50
    if methods["sector_pe"] > 0 and eps_trusted:
        scores["sector_pe"] = 0.55 if suspect else 0.70
    if methods["pb"] > 0:
        scores["pb"] = 0.70 if (suspect and is_bank) else (0.65 if suspect else (0.55 if is_bank else 0.50))

    weighted_val = 0.0
    weighted_meta: dict[str, Any] = {}
    if not suspect and industry_weights:
        w_g = float(industry_weights.get("graham") or industry_weights.get("weight_graham") or 0.34)
        w_pe = float(industry_weights.get("forward_pe") or industry_weights.get("weight_forward_pe") or 0.33)
        w_pb = float(industry_weights.get("pb") or industry_weights.get("weight_pb") or 0.33)
        # Use capped Graham inside weighted composite to avoid blow-ups.
        weighted_val, weighted_meta = weighted_composite_target_price(
            methods["graham_capped"] or methods["graham_raw"],
            methods["sector_pe"],
            methods["pb"],
            w_g,
            w_pe,
            w_pb,
        )
        if weighted_val > 0:
            methods["industry_weighted"] = float(weighted_val)
            scores["industry_weighted"] = 0.75

    # Selection pool: when suspect, never pick raw Graham as published best.
    pool = dict(scores)
    if suspect:
        pool.pop("graham_raw", None)

    best_method = ""
    best_val = 0.0
    best_conf = 0.0
    if pool:
        best_method = max(pool.items(), key=lambda kv: (kv[1], methods.get(kv[0], 0.0)))[0]
        best_val = float(methods.get(best_method) or 0.0)
        best_conf = float(pool.get(best_method) or 0.0)

    if best_val <= 0:
        # Fail-soft: any positive method, else price itself as last resort anchor.
        for key in ("pb", "graham_capped", "sector_pe", "graham_raw"):
            if methods.get(key, 0.0) > 0:
                best_method = key
                best_val = float(methods[key])
                best_conf = float(scores.get(key) or 0.35)
                break
        if best_val <= 0 and price > 0:
            # Không gắn nhãn Graham khi chỉ đang neo giá thị trường (thiếu EPS/BV).
            best_method = "price_anchor"
            best_val = float(price)
            best_conf = 0.15

    # Nhãn riêng cho neo giá — tránh UI hiện "Graham đã trần" khi fair == price.
    labels = dict(_BEST_FAIR_LABELS_VI)
    labels["price_anchor"] = "Chưa đủ BCTC — tạm neo giá thị trường"

    return {
        "methods": {k: (v if v > 0 else None) for k, v in methods.items()},
        "scores": scores,
        "best_fair_value": float(best_val) if best_val > 0 else None,
        "best_fair_method": best_method or None,
        "best_fair_confidence": round(float(best_conf), 3),
        "best_fair_label_vi": labels.get(best_method, best_method or "—"),
        "weighted_meta": weighted_meta,
        "eps_trusted": bool(eps_trusted),
        "suspect_inputs": bool(suspect),
        "fair_is_price_anchor": best_method == "price_anchor",
    }


def _is_bank_sector(snapshot: dict[str, Any]) -> bool:
    if snapshot.get("is_bank") is True:
        return True
    sec = str(snapshot.get("sector") or snapshot.get("sector_key") or "").lower()
    if "bank" in sec or "ngân hàng" in sec or sec in ("nh", "banks"):
        return True
    sym = str(snapshot.get("symbol") or "").strip().upper()
    return sym in _BANK_SYMBOLS


def _resolve_industry_subtype_id(
    snapshot: dict[str, Any],
    industry_display: str,
    cluster_id: str,
) -> str:
    sym = str(snapshot.get("symbol") or "").strip().upper()
    meta = _metadata_for_symbol(sym)
    subtype_override = (
        str(snapshot.get("industry_subtype") or meta.get("industry_subtype") or "")
        .strip()
        .lower()
    )
    if subtype_override in _INDUSTRY_SUBTYPE_LABELS_VI:
        return subtype_override
    return _classify_industry_subtype(industry_display, cluster_id)


def evaluate_quality_offset(
    *,
    f_score: int,
    roe_pct: float,
    cfo: float | None,
    net_income: float | None,
    roe_3y_avg: float | None = None,
) -> dict[str, Any]:
    """
    Quality Offset (bù trừ chất lượng): F-Score = 4 (ranh giới) nhưng ROE cao + CFO khỏe.

    - ROE trailing hoặc 3Y avg >= 20%
    - CFO > 0 và CFO / Net Income > 0.8
    → is_quality_compensated + conf_boost (+5..+10)
    """
    fs = int(f_score or 0)
    try:
        roe_trail = float(roe_pct or 0.0)
    except (TypeError, ValueError):
        roe_trail = 0.0
    try:
        roe_3y = float(roe_3y_avg) if roe_3y_avg is not None else 0.0
    except (TypeError, ValueError):
        roe_3y = 0.0
    # ROE có thể còn dạng tỉ lệ 0.22
    if 0 < roe_trail <= 1.5:
        roe_trail *= 100.0
    if 0 < roe_3y <= 1.5:
        roe_3y *= 100.0
    roe_use = max(roe_trail, roe_3y)

    try:
        cfo_v = float(cfo) if cfo is not None else None
    except (TypeError, ValueError):
        cfo_v = None
    try:
        ni_v = float(net_income) if net_income is not None else None
    except (TypeError, ValueError):
        ni_v = None

    cfo_ni_ratio: float | None = None
    if cfo_v is not None and ni_v is not None and ni_v > 0 and cfo_v > 0:
        cfo_ni_ratio = float(cfo_v / ni_v)

    eligible = bool(
        fs == 4
        and roe_use >= 20.0
        and cfo_v is not None
        and cfo_v > 0
        and cfo_ni_ratio is not None
        and cfo_ni_ratio > 0.8
    )

    boost = 0.0
    if eligible:
        # +5 cơ bản; +8 khi ROE/CFO khá; +10 khi rất mạnh.
        if roe_use >= 25.0 and cfo_ni_ratio is not None and cfo_ni_ratio >= 1.2:
            boost = 10.0
        elif roe_use >= 22.0 and cfo_ni_ratio is not None and cfo_ni_ratio >= 1.0:
            boost = 8.0
        else:
            boost = 5.0

    note_vi = ""
    if eligible:
        note_vi = (
            f"F-Score 4 được bù trừ nhờ ROE cao ({roe_use:.1f}%) & CFO khỏe "
            f"(CFO/LN={cfo_ni_ratio:.2f})."
        )

    return {
        "is_quality_compensated": bool(eligible),
        "quality_offset_eligible": bool(eligible),
        "conf_boost": float(boost),
        "f_score": fs,
        "roe_used_pct": round(roe_use, 4) if roe_use > 0 else 0.0,
        "cfo": cfo_v,
        "net_income": ni_v,
        "cfo_to_ni_ratio": round(cfo_ni_ratio, 4) if cfo_ni_ratio is not None else None,
        "note_vi": note_vi,
        "effective_f_score_for_buy_gate": 6 if eligible else fs,
    }


def _resolve_quality_offset_inputs(
    snapshot: dict[str, Any],
    *,
    f_score: int,
    roe_pct: float,
    pio_block: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Lấy ROE/CFO/NI từ snapshot + piotroski rồi chạy evaluate_quality_offset."""
    pio = pio_block if isinstance(pio_block, dict) else {}
    if not pio and isinstance(snapshot.get("piotroski"), dict):
        pio = snapshot["piotroski"]

    cfo = None
    for src in (
        snapshot.get("operating_cash_flow"),
        pio.get("operating_cash_flow"),
        snapshot.get("cfo"),
    ):
        try:
            if src is not None and float(src) != 0:
                cfo = float(src)
                break
        except (TypeError, ValueError):
            continue

    ni = None
    for src in (
        snapshot.get("net_income"),
        pio.get("net_income"),
    ):
        try:
            if src is not None and float(src) != 0:
                ni = float(src)
                break
        except (TypeError, ValueError):
            continue

    roe_3y = None
    for key in ("roe_3y_avg", "roe_3y", "roe_avg_3y"):
        if snapshot.get(key) not in (None, ""):
            try:
                roe_3y = float(snapshot.get(key))
                break
            except (TypeError, ValueError):
                continue

    return evaluate_quality_offset(
        f_score=int(f_score or 0),
        roe_pct=float(roe_pct or 0.0),
        cfo=cfo,
        net_income=ni,
        roe_3y_avg=roe_3y,
    )


def evaluate_graham_filter(
    *,
    is_bank: bool,
    de: float,
    cr: float,
    eps: float,
    bv: float,
    roe: float,
    pe: float,
    industry_cluster: str | None = None,
    industry_subtype: str | None = None,
    industry_text: str | None = None,
    bank_max_pe: float | None = None,
) -> dict[str, Any]:
    """
    Graham Filter động theo ngành + metadata lý do (UI tooltip).

    instant_conclusion vẫn dùng nhãn ngắn (Bỏ qua / …);
    fail_detail_vi / conclusion_detail_vi mang lý do cụ thể.
    """
    from core.sector_multiples import graham_filter_criteria_for_sector

    if bank_max_pe is None:
        try:
            bank_max_pe = float(os.environ.get("II_BANK_GRAHAM_MAX_PE", "12") or 12)
        except (TypeError, ValueError):
            bank_max_pe = 12.0

    criteria = graham_filter_criteria_for_sector(
        industry_cluster=industry_cluster,
        industry_subtype=industry_subtype,
        industry_text=industry_text,
        is_bank=bool(is_bank),
        bank_max_pe=bank_max_pe,
    )
    group_label = str(criteria.get("group_label_vi") or "Graham")
    fail_parts: list[str] = []
    missing: list[str] = []

    if criteria.get("mode") == "bank_pe_roe":
        has_inputs = bool(eps > 0 and bv > 0 and roe > 0)
        max_pe = float(criteria.get("bank_max_pe") or 12.0)
        passed = bool(has_inputs and pe > 0 and pe <= max_pe)
        if has_inputs and not passed:
            if pe <= 0:
                fail_parts.append("P/E không xác định")
            else:
                fail_parts.append(f"P/E {pe:.2f} > {max_pe:.0f}")
        if not has_inputs:
            if eps <= 0:
                missing.append("EPS")
            if bv <= 0:
                missing.append("BVPS")
            if roe <= 0:
                missing.append("ROE")
    else:
        max_de = float(criteria.get("max_debt_to_equity") or 0.5)
        min_cr = float(criteria.get("min_current_ratio") or 1.5)
        has_inputs = bool(de > 0 and cr > 0 and eps > 0 and bv > 0)
        passed = bool(has_inputs and de <= max_de and cr >= min_cr)
        if has_inputs and not passed:
            if de > max_de:
                fail_parts.append(f"D/E {de:.2f} > {max_de:.1f}")
            if cr < min_cr:
                fail_parts.append(f"CR {cr:.2f} < {min_cr:.1f}")
        if not has_inputs:
            if de <= 0:
                missing.append("D/E")
            if cr <= 0:
                missing.append("CR")
            if eps <= 0:
                missing.append("EPS")
            if bv <= 0:
                missing.append("BVPS")

    if fail_parts:
        fail_detail_vi = f"Bỏ qua: {'; '.join(fail_parts)} ({group_label})"
    else:
        fail_detail_vi = ""

    if missing:
        miss_txt = ", ".join(missing)
        missing_detail_vi = f"Theo dõi: thiếu {miss_txt} để chạy Graham Filter ({group_label})"
    else:
        missing_detail_vi = ""

    return {
        "pass": bool(passed),
        "has_inputs": bool(has_inputs),
        "criteria": criteria,
        "group_id": str(criteria.get("group_id") or ""),
        "group_label_vi": group_label,
        "max_debt_to_equity": criteria.get("max_debt_to_equity"),
        "min_current_ratio": criteria.get("min_current_ratio"),
        "bank_max_pe": criteria.get("bank_max_pe"),
        "fail_reasons_vi": fail_parts,
        "missing_inputs": missing,
        "fail_detail_vi": fail_detail_vi,
        "missing_detail_vi": missing_detail_vi,
        "debt_to_equity": float(de or 0.0),
        "current_ratio": float(cr or 0.0),
        "pe": float(pe or 0.0),
    }


def _legend_conclusion_detail_vi(
    decision: str,
    graham_eval: dict[str, Any],
    *,
    mos_composite: float | None = None,
    lynch_pass: bool = False,
) -> str:
    """Chuỗi lý do kèm nhãn Legend — dùng tooltip UI; không thay instant_conclusion ngắn."""
    d = str(decision or "").strip()
    if d == "Bỏ qua":
        fail = str(graham_eval.get("fail_detail_vi") or "").strip()
        if fail and not graham_eval.get("pass") and graham_eval.get("has_inputs"):
            return fail
        if mos_composite is not None and mos_composite < -10 and not lynch_pass:
            return f"Bỏ qua: MOS {mos_composite:.1f}% < -10% (định giá kém hấp dẫn)"
        return "Bỏ qua"
    if d == "Theo dõi":
        if not graham_eval.get("has_inputs"):
            return str(graham_eval.get("missing_detail_vi") or "Theo dõi: thiếu dữ liệu Graham")
        return "Theo dõi"
    if d == "Mua mạnh":
        label = str(graham_eval.get("group_label_vi") or "Graham")
        return f"Mua mạnh (Graham Đạt — {label})"
    return d


def _resolve_eps_forward(snapshot: dict[str, Any]) -> tuple[float | None, str]:
    raw = snapshot.get("eps_forward")
    if raw is not None:
        v = float(raw)
        if v > 0:
            return v, "eps_forward (dữ liệu cung cấp)"
    eps = float(snapshot.get("eps") or 0)
    g = float(snapshot.get("growth_rate_pct") or 0)
    if eps > 0:
        return eps * (1.0 + max(g, 0.0) / 100.0), "EPS × (1 + tăng trưởng%) — ước EPS năm tới"
    return None, ""


def _resolve_sector_pe_5y(snapshot: dict[str, Any]) -> tuple[float, str]:
    for key in ("sector_pe_5y_avg", "industry_pe", "sector_pe", "pe_industry"):
        raw = snapshot.get(key)
        if raw is not None:
            try:
                v = float(raw)
            except (TypeError, ValueError):
                continue
            if v > 0:
                src = str(snapshot.get("sector_pe_source") or key)
                if key == "sector_pe_5y_avg" and "peer" in src:
                    return v, f"sector_pe_5y_avg ({src} — median peer/spot, chưa phải TB 5Y lịch sử)"
                if key == "sector_pe_5y_avg" and ("5y" in src or "multi_year" in src or "reconstruct" in src):
                    return v, f"sector_pe_5y_avg ({src} — rolling đa năm EPS×giá cuối năm)"
                if key == "sector_pe_5y_avg" and "prior" in src:
                    return v, f"sector_pe_5y_avg ({src} — prior ngành VN)"
                if key == "sector_pe_5y_avg":
                    return v, "sector_pe_5y_avg (P/E TB ngành — cung cấp)"
                return v, f"{key} (P/E ngành — cung cấp)"
    if _is_bank_sector(snapshot):
        return _DEFAULT_SECTOR_PE_5Y_BANK, f"P/E ngành mặc định NH (~{_DEFAULT_SECTOR_PE_5Y_BANK})"
    return _DEFAULT_SECTOR_PE_5Y_NON_BANK, (
        f"P/E ngành mặc định phi-NH (~{_DEFAULT_SECTOR_PE_5Y_NON_BANK}) — nên cập nhật trong dữ liệu"
    )


def _resolve_fair_pb_multiple(snapshot: dict[str, Any]) -> tuple[float, str]:
    for key in ("sector_pb_5y_avg", "target_pb_multiple", "fair_pb_multiple"):
        raw = snapshot.get(key)
        if raw is not None:
            try:
                v = float(raw)
            except (TypeError, ValueError):
                continue
            if v > 0:
                src = str(snapshot.get("sector_pb_source") or key)
                # Peer/prior/5y PB: tinh chỉnh nhẹ theo ROE (NH / DN chất lượng).
                if key == "sector_pb_5y_avg" and (
                    "peer" in src
                    or "prior" in src
                    or "5y" in src
                    or "multi_year" in src
                    or "reconstruct" in src
                ):
                    roe = 0.0
                    for rk in ("roe_5y_avg", "roe", "roe_avg"):
                        try:
                            if snapshot.get(rk) not in (None, ""):
                                roe = float(snapshot.get(rk) or 0)
                                break
                        except (TypeError, ValueError):
                            continue
                    if 0 < roe <= 1.5:
                        roe *= 100.0
                    adj = v
                    note_extra = ""
                    if _is_bank_sector(snapshot) and roe >= 18.0:
                        # NH ROE tốt: cho phép premium tối đa +12% trên P/B ngành.
                        adj = min(v * 1.12, max(v, _DEFAULT_FAIR_PB_BANK_ROE_STRONG))
                        note_extra = f"; ROE {roe:.0f}% → premium P/B"
                    elif roe >= 20.0 and not _is_bank_sector(snapshot):
                        adj = min(v * 1.10, v + 0.35)
                        note_extra = f"; ROE {roe:.0f}% → premium P/B"
                    if "5y" in src or "multi_year" in src or "reconstruct" in src:
                        label = "rolling đa năm"
                    elif "peer" in src:
                        label = "peer/spot"
                    else:
                        label = "prior ngành"
                    return round(adj, 3), f"sector_pb_5y_avg ({src} — {label}{note_extra})"
                return v, f"{key} (P/B tham chiếu — cung cấp)"
    if _is_bank_sector(snapshot):
        roe = 0.0
        for key in ("roe_5y_avg", "roe", "roe_avg"):
            try:
                if snapshot.get(key) not in (None, ""):
                    roe = float(snapshot.get(key) or 0)
                    break
            except (TypeError, ValueError):
                continue
        # ROE đã % (normalize_roe); nếu nhầm tỉ lệ 0.2 → 20.
        if 0 < roe <= 1.5:
            roe *= 100.0
        if roe >= 20.0:
            pb = min(1.55, _DEFAULT_FAIR_PB_BANK_ROE_STRONG + 0.10)
            return pb, f"P/B NH theo ROE mạnh ({roe:.0f}% → ~{pb})"
        if roe >= 18.0:
            pb = _DEFAULT_FAIR_PB_BANK_ROE_STRONG
            return pb, f"P/B NH theo ROE tốt ({roe:.0f}% → ~{pb})"
        if roe >= 15.0:
            pb = round((_DEFAULT_FAIR_PB_BANK + _DEFAULT_FAIR_PB_BANK_ROE_STRONG) / 2.0, 2)
            return pb, f"P/B NH theo ROE đạt ngưỡng ({roe:.0f}% → ~{pb})"
        return _DEFAULT_FAIR_PB_BANK, f"P/B tham chiếu mặc định NH (~{_DEFAULT_FAIR_PB_BANK})"
    return _DEFAULT_FAIR_PB_NON_BANK, (
        f"P/B tham chiếu mặc định phi-NH (~{_DEFAULT_FAIR_PB_NON_BANK}) — BV ít ý nghĩa với nhiều DN tăng trưởng"
    )


def _composite_weights_from_industry(
    snapshot: dict[str, Any],
) -> tuple[float, float, float, dict[str, float], str, str, str]:
    """
    Trả (w_graham, w_pe, w_pb, weights_template dict PE/PB/Graham, industry_display, cluster_id).
    Cho phép ghi đè bằng weight_graham, weight_forward_pe, weight_pb nếu cả ba đều có.
    """
    industry_display, cluster_id = resolve_industry_for_snapshot(snapshot)
    subtype_id = _resolve_industry_subtype_id(snapshot, industry_display, cluster_id)
    w_tpl = weights_for_industry_cluster(cluster_id)
    if subtype_id in _INDUSTRY_SUBTYPE_WEIGHT_TABLE:
        pe, pb, gr = _INDUSTRY_SUBTYPE_WEIGHT_TABLE[subtype_id]
        w_tpl = {"PE": pe, "PB": pb, "Graham": gr}

    g_raw = snapshot.get("weight_graham")
    pe_raw = snapshot.get("weight_forward_pe")
    pb_raw = snapshot.get("weight_pb")
    if g_raw is not None and pe_raw is not None and pb_raw is not None:
        return float(g_raw), float(pe_raw), float(pb_raw), w_tpl, industry_display, cluster_id, subtype_id

    return (
        w_tpl["Graham"],
        w_tpl["PE"],
        w_tpl["PB"],
        w_tpl,
        industry_display,
        cluster_id,
        subtype_id,
    )


def _pick_positive_float(snapshot: dict[str, Any], keys: tuple[str, ...]) -> float:
    for k in keys:
        raw = snapshot.get(k)
        if raw is None:
            continue
        try:
            v = float(raw)
        except (TypeError, ValueError):
            continue
        if v > 0:
            return v
    return 0.0


def _safe_ratio(num: float, den: float) -> float:
    return float(num / den) if den else 0.0


def _resolve_hybrid_inputs(snapshot: dict[str, Any]) -> tuple[float, float, float, list[str]]:
    """
    Resolve D/E, CR, ROE with fallbacks from piotroski block.
    Returns (de, cr, roe_pct, notes).
    """
    notes: list[str] = []
    pio = snapshot.get("piotroski") if isinstance(snapshot.get("piotroski"), dict) else {}

    de = _pick_positive_float(snapshot, ("debt_to_equity", "d_e", "de"))
    if de <= 0 and pio:
        ltd = float(pio.get("long_term_debt") or 0)
        ta = float(pio.get("total_assets") or 0)
        equity_proxy = max(ta - ltd, 0.0)
        de = _safe_ratio(ltd, equity_proxy)
        if de > 0:
            notes.append("Suy luận D/E từ piotroski (nợ dài hạn / vốn chủ ước tính).")

    cr = _pick_positive_float(snapshot, ("current_ratio", "cr"))
    if cr <= 0 and pio:
        ca = float(pio.get("current_assets") or 0)
        cl = float(pio.get("current_liabilities") or 0)
        cr = _safe_ratio(ca, cl)
        if cr > 0:
            notes.append("Suy luận CR từ piotroski (tài sản NH / nợ NH).")

    roe = _pick_positive_float(snapshot, ("roe_5y_avg", "roe", "roe_avg_5y"))
    # vnstock hay trả ROE dạng tỉ lệ (0.27); Legend dùng ngưỡng % (15).
    if 0 < roe <= 1.5:
        roe = roe * 100.0
        notes.append("Chuẩn hóa ROE từ tỉ lệ → %.")
    if roe <= 0 and pio:
        ni = float(pio.get("net_income") or 0)
        ta = float(pio.get("total_assets") or 0)
        ltd = float(pio.get("long_term_debt") or 0)
        equity_proxy = max(ta - ltd, 0.0)
        roe = _safe_ratio(ni, equity_proxy) * 100.0
        if roe > 0:
            notes.append("Suy luận ROE từ piotroski (LNST / vốn chủ ước tính).")

    return de, cr, roe, notes


def _legend_thresholds(snapshot: dict[str, Any]) -> tuple[str, dict[str, float]]:
    """
    Risk profile for decision thresholds.
    Profiles:
    - defensive: stricter buy requirements
    - balanced: default
    - aggressive: allows earlier accumulation
    """
    profile = str(snapshot.get("legend_profile") or os.environ.get("II_LEGEND_PROFILE", "balanced")).strip().lower()
    if profile not in ("defensive", "balanced", "aggressive"):
        profile = "balanced"
    table = {
        "defensive": {"strong_buy_mos_min": 25.0, "max_peg_for_buy": 1.20, "watch_buy_mos_min": 8.0},
        "balanced": {"strong_buy_mos_min": 18.0, "max_peg_for_buy": 1.35, "watch_buy_mos_min": 8.0},
        "aggressive": {"strong_buy_mos_min": 12.0, "max_peg_for_buy": 1.50, "watch_buy_mos_min": 5.0},
    }
    out = dict(table[profile])

    mos_ovr = snapshot.get("legend_strong_buy_mos_min")
    if mos_ovr is None:
        mos_ovr = os.environ.get("II_LEGEND_STRONG_BUY_MOS_MIN")
    peg_ovr = snapshot.get("legend_max_peg_for_buy")
    if peg_ovr is None:
        peg_ovr = os.environ.get("II_LEGEND_MAX_PEG_FOR_BUY")
    watch_ovr = snapshot.get("legend_watch_buy_mos_min")
    if watch_ovr is None:
        watch_ovr = os.environ.get("II_LEGEND_WATCH_BUY_MOS_MIN")
    try:
        if mos_ovr is not None:
            out["strong_buy_mos_min"] = max(0.0, min(60.0, float(mos_ovr)))
    except (TypeError, ValueError):
        pass
    try:
        if peg_ovr is not None:
            out["max_peg_for_buy"] = max(0.5, min(3.0, float(peg_ovr)))
    except (TypeError, ValueError):
        pass
    try:
        if watch_ovr is not None:
            out["watch_buy_mos_min"] = max(-20.0, min(40.0, float(watch_ovr)))
    except (TypeError, ValueError):
        pass
    return profile, out


def value_investing_summary(snapshot: dict[str, Any], include_extensions: bool = True) -> dict[str, Any]:
    """Định giá theo Hybrid Legend Model + giữ tương thích key cũ."""
    # P0: neo P/E–P/B ngành (peer/prior) trước chuẩn hóa EPS / Graham.
    try:
        from core.sector_multiples import inject_sector_multiples_into_snapshot

        inject_sector_multiples_into_snapshot(snapshot)
    except Exception:
        pass

    # P0: chuẩn hóa đơn vị EPS (VND/cp) trước one-off normalizer / Graham.
    eps_unit_notes: list[str] = []
    try:
        from core.financial_enrichment import normalize_eps_in_snapshot

        eps_unit_notes = list(normalize_eps_in_snapshot(snapshot) or [])
    except Exception:
        eps_unit_notes = []

    # P0 data integrity: chuẩn hóa EPS one-off + P/E sanity trước khi Graham/Buffett/Lynch.
    eps_norm_meta: dict[str, Any] = {}
    try:
        from core.eps_normalizer import get_eps_normalizer

        eps_norm_meta = get_eps_normalizer().apply_to_snapshot(snapshot) or {}
    except Exception:
        eps_norm_meta = {}

    price = float(snapshot.get("price") or 0)
    eps_reported = float(snapshot.get("eps") or 0)
    eps_ttm = _pick_positive_float(snapshot, ("eps_ttm",))
    eps_normalized = _pick_positive_float(snapshot, ("normalized_eps",))
    # Chỉ ưu tiên normalized_eps khi one-off/NI-per-share thật (không phải copy raw).
    norm_meta = (
        snapshot.get("eps_normalizer_meta")
        if isinstance(snapshot.get("eps_normalizer_meta"), dict)
        else {}
    )
    norm_basis = str(norm_meta.get("basis") or "")
    use_normalized = eps_normalized > 0 and (
        bool(norm_meta.get("one_off_adjusted"))
        or norm_basis in ("normalized_ni_per_share", "ni_per_share", "eps_scaled_by_one_off")
    )
    if use_normalized:
        eps_for_graham = eps_normalized
        eps_basis_key = "normalized"
    elif eps_ttm > 0:
        eps_for_graham = eps_ttm
        eps_basis_key = "ttm"
    else:
        eps_for_graham = max(eps_reported, 0.0)
        eps_basis_key = "reported"
    g_raw = float(snapshot.get("growth_rate_pct") or 0)
    g_meta = normalize_graham_growth_pct(g_raw)
    g = float(g_meta["g_pct"])  # g đã trần 15% / sàn 0% cho công thức & PEG
    bond_explicit = snapshot.get("bond_yield_pct")
    try:
        bond_explicit_f = float(bond_explicit) if bond_explicit not in (None, "") else None
    except (TypeError, ValueError):
        bond_explicit_f = None
    bond = resolve_vn_10y_bond_yield_pct(bond_explicit_f)
    bv = _pick_positive_float(snapshot, ("book_value_per_share", "bvps"))

    de, cr, roe, fallback_notes = _resolve_hybrid_inputs(snapshot)
    is_bank = _is_bank_sector(snapshot)
    pe = (price / eps_for_graham) if price > 0 and eps_for_graham > 0 else 0.0
    pe_anomaly_flag = bool(snapshot.get("pe_anomaly_flag") or (eps_norm_meta or {}).get("pe_anomaly_flag"))
    try:
        mos_bump = float(snapshot.get("mos_requirement_bump_pct") or 0.0)
    except (TypeError, ValueError):
        mos_bump = 0.0
    if pe_anomaly_flag and mos_bump <= 0:
        mos_bump = 12.0

    w_g, w_pe, w_pb, w_tpl, industry_display, cluster_id, subtype_id = _composite_weights_from_industry(
        snapshot
    )
    industry_weights = {"graham": w_g, "forward_pe": w_pe, "pb": w_pb}

    # Step 1 - Graham survival + Graham Number (ngưỡng D/E–CR động theo ngành)
    graham_eval = evaluate_graham_filter(
        is_bank=is_bank,
        de=de,
        cr=cr,
        eps=eps_for_graham,
        bv=bv,
        roe=roe,
        pe=pe,
        industry_cluster=cluster_id,
        industry_subtype=subtype_id,
        industry_text=industry_display,
    )
    has_graham_inputs = bool(graham_eval.get("has_inputs"))
    graham_pass = bool(graham_eval.get("pass"))
    graham_number = float((22.5 * eps_for_graham * bv) ** 0.5) if eps_for_graham > 0 and bv > 0 else 0.0

    # Step 2 - Buffett quality / moat proxy
    if is_bank:
        buffett_pass = bool(roe >= 15)
    else:
        buffett_pass = bool(roe > 0 and de > 0 and roe >= 15 and de <= 0.5)

    # Step 3 - Lynch PEG/GARP
    peg = (pe / g) if pe > 0 and g > 0 else 0.0
    if peg <= 0:
        peg_label = "Không xác định"
    elif peg < 1:
        peg_label = "Cực kỳ hấp dẫn"
    elif peg <= 1.5:
        peg_label = "Hợp lý"
    else:
        peg_label = "Quá đắt"
    lynch_pass = bool(peg > 0 and peg <= 1.5)

    # Step 4 - Hybrid intrinsic value
    eps_fwd, eps_fwd_note = _resolve_eps_forward(snapshot)
    sector_pe, sector_pe_note = _resolve_sector_pe_5y(snapshot)
    # Graham Growth luôn tính (g đã cap) để so sánh / cảnh báo lệch.
    graham_growth_fv = (
        benjamin_graham_value(eps_for_graham, g, bond_yield_pct=bond)
        if eps_for_graham > 0
        else 0.0
    )
    # g < 0 → fallback Graham Number truyền thống (không dùng Growth Formula).
    use_graham_growth = bool(
        not g_meta.get("fallback_to_graham_number")
        and g > 5
        and roe > 15
        and eps_for_graham > 0
    )
    intrinsic = graham_number
    if use_graham_growth and graham_number > 0 and peg > 0:
        # Growth adjustment: blend Graham anchor with forward P/E target.
        growth_target = forward_pe_target_price(eps_fwd, sector_pe) if eps_fwd else 0.0
        peg_factor = max(0.75, min(1.4, 1.2 / peg))
        growth_adj = growth_target * peg_factor if growth_target > 0 else 0.0
        if growth_adj > 0:
            # Quality growth businesses should not be anchored too heavily to Graham number.
            blend_growth = 0.55 if peg <= 1.5 else 0.4
            intrinsic = graham_number * (1.0 - blend_growth) + growth_adj * blend_growth
        else:
            intrinsic = graham_number * peg_factor
    elif use_graham_growth:
        intrinsic = float(graham_growth_fv)
    intrinsic = float(intrinsic)

    mos = margin_of_safety_pct(graham_number, price)
    mos_composite = margin_of_safety_pct(intrinsic, price)
    safe_buy_price = intrinsic * 0.7 if intrinsic > 0 else 0.0

    profile, thresholds = _legend_thresholds(snapshot)
    # P/E anomaly → siết MOS requirement thêm 10–15% (mặc định +12pp).
    if pe_anomaly_flag and mos_bump > 0:
        thresholds = dict(thresholds)
        thresholds["strong_buy_mos_min"] = float(thresholds.get("strong_buy_mos_min", 30.0)) + mos_bump
        thresholds["watch_buy_mos_min"] = float(thresholds.get("watch_buy_mos_min", 15.0)) + mos_bump
    if not has_graham_inputs:
        decision = "Theo dõi"
    elif not graham_pass:
        decision = "Bỏ qua"
    elif (
        buffett_pass
        and lynch_pass
        and (mos_composite is not None and mos_composite >= thresholds["strong_buy_mos_min"])
        and (peg > 0 and peg <= thresholds["max_peg_for_buy"])
    ):
        decision = "Mua mạnh"
    elif mos_composite is not None and mos_composite < -10 and not lynch_pass:
        decision = "Bỏ qua"
    else:
        decision = "Theo dõi"

    # Backward-compatible blocks
    fair_pb, fair_pb_note = _resolve_fair_pb_multiple(snapshot)
    tgt_pe = forward_pe_target_price(eps_fwd, sector_pe) if eps_fwd is not None and eps_fwd > 0 else 0.0
    if tgt_pe <= 0 and eps_for_graham > 0 and sector_pe > 0:
        # Trailing EPS × sector PE as PE-method candidate when forward EPS missing.
        tgt_pe = forward_pe_target_price(eps_for_graham, sector_pe)
    tgt_pb = book_value_target_price(bv, fair_pb) if bv > 0 else 0.0
    graham_capped = capped_graham_fair(graham_number if graham_number > 0 else intrinsic, price)
    graham_growth_warns = graham_growth_divergence_notes(
        graham_growth_fv,
        graham_capped=graham_capped,
        sector_pe_fair=tgt_pe,
        symbol=str(snapshot.get("symbol") or ""),
    )
    comp_meta = {"included": ["hybrid_legend"], "weights_effective": {"hybrid_legend": 1.0}}

    cluster_label = _industry_cluster_label_vi(cluster_id)
    subtype_label = _INDUSTRY_SUBTYPE_LABELS_VI.get(subtype_id, _INDUSTRY_SUBTYPE_LABELS_VI["other"])
    valuation_transparency_line = (
        f"Hybrid Legend: Graham {'Đạt' if graham_pass else 'Trượt'}, Buffett {'Đạt' if buffett_pass else 'Trượt'}, "
        f"Lynch {'Đạt' if lynch_pass else 'Trượt'} · PEG={peg:.2f} ({peg_label}) · Ngành: {industry_display}."
    )
    if eps_unit_notes:
        valuation_transparency_line = (
            f"{valuation_transparency_line} · EPS đơn vị: {eps_unit_notes[0]}"
        )

    raw_pio = snapshot.get("piotroski")
    pio_block = raw_pio if isinstance(raw_pio, dict) else {}
    if pio_block:
        f_score, f_reasons = _bank_quality_score(pio_block) if cluster_id == "financial" else piotroski_f_score(pio_block)
    else:
        f_score, f_reasons = (0, [])

    quality_offset = _resolve_quality_offset_inputs(
        snapshot,
        f_score=int(f_score or 0),
        roe_pct=float(roe or 0.0),
        pio_block=pio_block,
    )

    if not has_graham_inputs:
        value_trap_warning = str(
            graham_eval.get("missing_detail_vi")
            or "Thiếu dữ liệu để chốt bộ lọc Graham/Buffett; xác minh BCTC trước khi giải ngân."
        )
    elif not graham_pass:
        value_trap_warning = str(
            graham_eval.get("fail_detail_vi")
            or "Đòn bẩy cao hoặc thanh khoản yếu theo chuẩn ngành là rủi ro lớn nhất."
        )
    elif roe < 15:
        value_trap_warning = "ROE chưa đủ mạnh, doanh nghiệp có thể rẻ nhưng thiếu chất lượng sinh lời bền vững."
    elif peg > 1.5:
        value_trap_warning = "Tăng trưởng không đủ bù định giá (PEG cao), dễ mua phải cổ phiếu đắt."
    else:
        value_trap_warning = "Không thấy bẫy giá trị lớn theo bộ lọc hiện tại."

    pe_sanity_notes: list[str] = []
    source_pe = None
    try:
        source_pe = float(snapshot.get("pe_ratio")) if snapshot.get("pe_ratio") not in (None, "") else None
    except (TypeError, ValueError):
        source_pe = None
    if price > 0 and eps_for_graham > 0:
        earnings_yield = eps_for_graham / price
        if pe > 0 and pe < 5.0 and earnings_yield > 0.2:
            pe_sanity_notes.append(
                f"P/E tính lại={pe:.2f} rất thấp (EPS/giá={earnings_yield:.1%}) — nghi EPS lệch đơn vị/scale; "
                "không tin MOS chỉ dựa P/E này."
            )
        if source_pe is not None and pe > 0:
            pe_gap = abs(source_pe - pe) / max(source_pe, pe, 1e-6)
            if pe_gap > 0.15:
                pe_sanity_notes.append(
                    f"P/E nguồn ({source_pe:.2f}) lệch {pe_gap * 100:.0f}% so với price/EPS ({pe:.2f})."
                )
    pe_sanity_block = snapshot.get("pe_sanity") if isinstance(snapshot.get("pe_sanity"), dict) else {}
    if pe_anomaly_flag:
        warn_vi = str(
            snapshot.get("eps_pe_anomaly_warning_vi")
            or pe_sanity_block.get("warning_vi")
            or "P/E hiện tại có dấu hiệu bị méo mó do lợi nhuận đột biến. MOS đã được điều chỉnh thận trọng."
        )
        pe_sanity_notes.append(warn_vi)
        for reason in pe_sanity_block.get("reasons") or []:
            if reason and str(reason) not in pe_sanity_notes:
                pe_sanity_notes.append(str(reason))
        value_trap_warning = (value_trap_warning + " " + warn_vi).strip()
    elif pe_sanity_notes:
        value_trap_warning = (value_trap_warning + " " + " ".join(pe_sanity_notes)).strip()

    if g_meta.get("g_capped"):
        pe_sanity_notes.append(
            f"g Graham Growth đã trần {float(g_meta.get('g_cap_pct') or GRAHAM_GROWTH_G_CAP_PCT):.0f}% "
            f"(g_calc={float(g_meta.get('g_raw_pct') or 0):.1f}%) — tránh fair value ảo đỉnh chu kỳ."
        )
    if g_meta.get("fallback_to_graham_number"):
        pe_sanity_notes.append(
            f"g_calc={float(g_meta.get('g_raw_pct') or 0):.1f}% < 0 — dùng Graham Number truyền thống "
            "(không áp Growth Formula)."
        )
    for w in graham_growth_warns:
        if w and w not in pe_sanity_notes:
            pe_sanity_notes.append(w)
    if graham_growth_warns:
        value_trap_warning = (value_trap_warning + " " + " ".join(graham_growth_warns)).strip()

    # Multi-method best fair (before MOS integrity clamp uses published fair).
    absurd_ey = False
    if price > 0 and eps_for_graham > 0:
        absurd_ey = (eps_for_graham / price) > 0.20 and (pe > 0 and pe < 5.0)
    eps_trusted = not (
        bool(pe_anomaly_flag)
        or bool(snapshot.get("eps_anomaly_flag"))
        or absurd_ey
        or any("lệch đơn vị" in str(n).lower() or "eps lệch" in str(n).lower() for n in pe_sanity_notes)
    )
    best_sel = select_best_fair_value(
        graham_raw=float(graham_number or intrinsic or 0.0),
        graham_capped=float(graham_capped or 0.0),
        pe_fair=float(tgt_pe or 0.0),
        pb_fair=float(tgt_pb or 0.0),
        price=float(price or 0.0),
        eps_trusted=bool(eps_trusted),
        mos_integrity_blocked=bool(pe_sanity_notes) or absurd_ey,
        pe_anomaly_flag=bool(pe_anomaly_flag),
        industry_weights=industry_weights,
        is_bank=bool(is_bank),
    )
    hybrid_intrinsic = float(intrinsic)
    best_fair = best_sel.get("best_fair_value")
    if best_fair is not None and float(best_fair) > 0:
        intrinsic = float(best_fair)
        mos_composite = margin_of_safety_pct(intrinsic, price)
        safe_buy_price = intrinsic * 0.7
        # Refresh Legend decision using best-fair MOS (not raw Graham blow-up).
        if not has_graham_inputs:
            decision = "Theo dõi"
        elif not graham_pass:
            decision = "Bỏ qua"
        elif (
            buffett_pass
            and lynch_pass
            and (mos_composite is not None and mos_composite >= thresholds["strong_buy_mos_min"])
            and (peg > 0 and peg <= thresholds["max_peg_for_buy"])
            and eps_trusted
        ):
            decision = "Mua mạnh"
        elif mos_composite is not None and mos_composite < -10 and not lynch_pass:
            decision = "Bỏ qua"
        else:
            decision = "Theo dõi"
        method = str(best_sel.get("best_fair_method") or "")
        if method and method != "hybrid_legend":
            comp_meta = {
                "included": [method],
                "weights_effective": {method: 1.0},
                "best_fair_confidence": best_sel.get("best_fair_confidence"),
            }
        valuation_transparency_line = (
            f"{valuation_transparency_line} · Đ.giá công bố: {best_sel.get('best_fair_label_vi')} "
            f"(tin cậy {float(best_sel.get('best_fair_confidence') or 0):.0%})."
        )

    # P0: MOS hard clamp + unit/PE sanity block
    mos_raw = mos
    mos_composite_raw = mos_composite
    mos_gate: dict[str, Any] = {
        "mos_integrity_blocked": False,
        "reasons": [],
        "note_vi": "",
        "mos_raw_pct": mos_composite,
        "mos_display_pct": mos_composite,
    }
    fv_review: dict[str, Any] = {
        "fair_value_suppressed": False,
        "fair_value_unreliable": bool(best_sel.get("suspect_inputs")),
        "composite_target_price": intrinsic,
        "composite_target_price_raw": hybrid_intrinsic if hybrid_intrinsic > 0 else graham_number,
        "fair_value_suppress_reason_vi": "",
        "publish_mos": True,
    }
    try:
        from core.data_integrity import apply_mos_integrity_clamp

        ey = (eps_for_graham / price) if price > 0 and eps_for_graham > 0 else None
        mos_gate = apply_mos_integrity_clamp(
            mos_composite,
            pe_sanity_notes=pe_sanity_notes,
            pe_anomaly_flag=bool(pe_anomaly_flag),
            eps_anomaly_flag=bool(snapshot.get("eps_anomaly_flag")),
            pe=pe if pe > 0 else None,
            earnings_yield=ey,
            price=price,
            eps=eps_for_graham,
        )
        mos_composite = mos_gate.get("mos_display_pct")
        if mos_gate.get("mos_integrity_blocked"):
            if decision == "Mua mạnh":
                decision = "Theo dõi"
            if mos_gate.get("note_vi"):
                value_trap_warning = (value_trap_warning + " " + str(mos_gate["note_vi"])).strip()
                if str(mos_gate["note_vi"]) not in pe_sanity_notes:
                    pe_sanity_notes.append(str(mos_gate["note_vi"]))
        # Re-review fair value: do not keep advertising inflated Graham when EPS/PE untrusted.
        try:
            from core.data_integrity import review_fair_value_after_integrity

            fv_review = review_fair_value_after_integrity(
                fair_value=float(intrinsic) if intrinsic and float(intrinsic) > 0 else None,
                mos_integrity_blocked=bool(mos_gate.get("mos_integrity_blocked")),
                reasons=list(mos_gate.get("reasons") or []),
                note_vi=str(mos_gate.get("note_vi") or ""),
            )
        except Exception:
            fv_review = {
                "fair_value_suppressed": False,
                "fair_value_unreliable": bool(best_sel.get("suspect_inputs")),
                "composite_target_price": intrinsic,
                "composite_target_price_raw": hybrid_intrinsic if hybrid_intrinsic > 0 else graham_number,
                "fair_value_suppress_reason_vi": "",
                "publish_mos": True,
            }
        # Best fair is published; Graham/hybrid kept as raw reference for transparency.
        raw_ref = hybrid_intrinsic if hybrid_intrinsic > 0 else float(graham_number or 0.0)
        fv_review["composite_target_price"] = float(intrinsic) if float(intrinsic or 0) > 0 else fv_review.get(
            "composite_target_price"
        )
        fv_review["composite_target_price_raw"] = raw_ref if raw_ref > 0 else fv_review.get(
            "composite_target_price_raw"
        )
        if best_sel.get("suspect_inputs"):
            fv_review["fair_value_unreliable"] = True
        mos_g_gate = apply_mos_integrity_clamp(
            mos,
            pe_sanity_notes=pe_sanity_notes,
            pe_anomaly_flag=bool(pe_anomaly_flag),
            eps_anomaly_flag=bool(snapshot.get("eps_anomaly_flag")),
            pe=pe if pe > 0 else None,
            earnings_yield=ey,
        )
        mos = mos_g_gate.get("mos_display_pct")
        if not fv_review.get("publish_mos", True):
            # Without trusted fair value, do not publish capped MOS as actionable.
            mos_composite = None
            mos = None
        # Annotate unreliable fair value (still published).
        if fv_review.get("fair_value_unreliable"):
            note_fv = str(fv_review.get("fair_value_suppress_reason_vi") or "").strip()
            if note_fv and note_fv not in pe_sanity_notes:
                pe_sanity_notes.append(note_fv)
            if note_fv:
                value_trap_warning = (value_trap_warning + " " + note_fv).strip()
    except Exception:
        fv_review = {
            "fair_value_suppressed": False,
            "fair_value_unreliable": bool(best_sel.get("suspect_inputs")),
            "composite_target_price": intrinsic,
            "composite_target_price_raw": hybrid_intrinsic if hybrid_intrinsic > 0 else graham_number,
            "fair_value_suppress_reason_vi": "",
            "publish_mos": True,
        }

    advice = (
        f"Kết luận: {decision}. "
        f"Giá mua an toàn <= {safe_buy_price:,.0f} {snapshot.get('currency', 'VND')}. "
        f"Pass/Fail: Graham={'Đạt' if graham_pass else 'Trượt'}, Buffett={'Đạt' if buffett_pass else 'Trượt'}, "
        f"Lynch={'Đạt' if lynch_pass else 'Trượt'}. "
        f"Cảnh báo: {value_trap_warning}"
    )

    result = {
        "symbol": snapshot.get("symbol", ""),
        "name": snapshot.get("name", ""),
        "piotroski_block": dict(pio_block),
        "price": price,
        "currency": snapshot.get("currency", "VND"),
        "eps": eps_reported,
        "eps_raw": snapshot.get("eps_raw"),
        "eps_unit_corrected": bool(snapshot.get("eps_normalized")) or bool(eps_unit_notes),
        "eps_unit_scale_factor": snapshot.get("eps_unit_scale_factor"),
        "eps_unit_notes": list(eps_unit_notes),
        "normalized_eps": eps_normalized if use_normalized else None,
        "eps_for_graham": eps_for_graham,
        "eps_basis_key": eps_basis_key,
        "eps_anomaly_flag": bool(snapshot.get("eps_anomaly_flag")),
        "pe_anomaly_flag": pe_anomaly_flag,
        "mos_requirement_bump_pct": mos_bump if pe_anomaly_flag else 0.0,
        "eps_pe_anomaly_warning_vi": (
            str(snapshot.get("eps_pe_anomaly_warning_vi") or "") if pe_anomaly_flag else ""
        ),
        "eps_normalizer_meta": (
            snapshot.get("eps_normalizer_meta")
            if isinstance(snapshot.get("eps_normalizer_meta"), dict)
            else {}
        ),
        "pe_sanity_detail": pe_sanity_block,
        "growth_rate_pct_source": str(snapshot.get("growth_rate_pct_source") or "unspecified"),
        "growth_rate_pct_source_label_vi": str(snapshot.get("growth_rate_pct_source_label_vi") or "Không chỉ định"),
        "bond_yield_pct_used": bond,
        "vn_10y_bond_yield_pct": bond,
        "graham_aaa_yield_pct": GRAHAM_CLASSIC_AAA_YIELD_PCT,
        "growth_rate_pct": g,
        "growth_rate_pct_raw": float(g_meta.get("g_raw_pct") or g_raw),
        "growth_rate_pct_capped": bool(g_meta.get("g_capped")),
        "graham_growth_g_cap_pct": float(g_meta.get("g_cap_pct") or GRAHAM_GROWTH_G_CAP_PCT),
        "graham_growth_value": float(graham_growth_fv or 0.0),
        "graham_growth_used": bool(use_graham_growth),
        "graham_growth_divergence_notes": list(graham_growth_warns),
        "book_value_per_share": bv,
        "debt_to_equity": de,
        "current_ratio": cr,
        "roe_5y_avg": roe,
        "intrinsic_value_graham": graham_number,
        "intrinsic_value_hybrid_legend": hybrid_intrinsic if hybrid_intrinsic > 0 else None,
        "graham_capped_fair": graham_capped if graham_capped > 0 else None,
        "best_fair_value": best_sel.get("best_fair_value"),
        "best_fair_method": best_sel.get("best_fair_method"),
        "best_fair_label_vi": best_sel.get("best_fair_label_vi"),
        "best_fair_confidence": best_sel.get("best_fair_confidence"),
        "fair_value_methods": best_sel.get("methods") if isinstance(best_sel.get("methods"), dict) else {},
        "fair_is_price_anchor": bool(best_sel.get("fair_is_price_anchor")),
        "margin_of_safety_pct": mos,
        "margin_of_safety_pct_raw": mos_raw,
        "target_price_forward_pe": tgt_pe,
        "target_price_pb_fair": tgt_pb,
        "composite_target_price": fv_review.get("composite_target_price"),
        "composite_target_price_raw": fv_review.get("composite_target_price_raw", intrinsic),
        "fair_value_suppressed": bool(fv_review.get("fair_value_suppressed")),
        "fair_value_unreliable": bool(fv_review.get("fair_value_unreliable"))
        or bool(best_sel.get("fair_is_price_anchor")),
        "fair_value_suppress_reason_vi": str(
            fv_review.get("fair_value_suppress_reason_vi")
            or (
                "Thiếu EPS/BVPS — định giá tạm neo giá thị trường, chưa phải Graham thật."
                if best_sel.get("fair_is_price_anchor")
                else ""
            )
        ),
        "margin_of_safety_composite_pct": mos_composite,
        "margin_of_safety_composite_pct_raw": mos_composite_raw,
        "mos_integrity_blocked": bool(mos_gate.get("mos_integrity_blocked")),
        "mos_integrity_reasons": list(mos_gate.get("reasons") or []),
        "mos_integrity_note_vi": str(
            fv_review.get("fair_value_suppress_reason_vi")
            or mos_gate.get("note_vi")
            or ""
        ),
        "composite_weights_base": {"graham": w_g, "forward_pe": w_pe, "pb": w_pb},
        "industry_weights_template": dict(w_tpl),
        "industry_display_vi": industry_display,
        "industry_cluster_id": cluster_id,
        "industry_cluster_label_vi": cluster_label,
        "industry_subtype_id": subtype_id,
        "industry_subtype_label_vi": subtype_label,
        "valuation_transparency_line": valuation_transparency_line,
        "composite_meta": comp_meta,
        "eps_forward_used": eps_fwd,
        "eps_forward_note": eps_fwd_note,
        "sector_pe_5y_used": sector_pe,
        "sector_pe_5y_note": sector_pe_note,
        "fair_pb_multiple_used": fair_pb,
        "fair_pb_note": fair_pb_note,
        "sector_multiples_meta": (
            snapshot.get("sector_multiples_meta")
            if isinstance(snapshot.get("sector_multiples_meta"), dict)
            else {}
        ),
        "is_bank_sector": _is_bank_sector(snapshot),
        "piotroski_score": f_score,
        "piotroski_detail": f_reasons,
        "is_quality_compensated": bool(quality_offset.get("is_quality_compensated")),
        "quality_offset": dict(quality_offset),
        "quality_offset_note_vi": str(quality_offset.get("note_vi") or ""),
        "advice": advice,
        "instant_conclusion": decision,
        "instant_conclusion_detail_vi": _legend_conclusion_detail_vi(
            decision,
            graham_eval,
            mos_composite=mos_composite if isinstance(mos_composite, (int, float)) else None,
            lynch_pass=lynch_pass,
        ),
        "safe_buy_price": safe_buy_price,
        "legend_scorecard": {
            "graham_pass": graham_pass,
            "buffett_pass": buffett_pass,
            "lynch_pass": lynch_pass,
        },
        "graham_filter": {
            "group_id": graham_eval.get("group_id"),
            "group_label_vi": graham_eval.get("group_label_vi"),
            "max_debt_to_equity": graham_eval.get("max_debt_to_equity"),
            "min_current_ratio": graham_eval.get("min_current_ratio"),
            "bank_max_pe": graham_eval.get("bank_max_pe"),
            "pass": graham_pass,
            "has_inputs": has_graham_inputs,
            "fail_reasons_vi": list(graham_eval.get("fail_reasons_vi") or []),
            "fail_detail_vi": str(graham_eval.get("fail_detail_vi") or ""),
            "missing_detail_vi": str(graham_eval.get("missing_detail_vi") or ""),
            "criteria": graham_eval.get("criteria") if isinstance(graham_eval.get("criteria"), dict) else {},
        },
        "legend_data_ready": {
            "has_graham_inputs": has_graham_inputs,
            "de_available": de > 0,
            "cr_available": cr > 0,
            "roe_available": roe > 0,
        },
        "legend_fallback_notes": fallback_notes,
        "legend_profile": profile,
        "legend_thresholds": dict(thresholds),
        "graham_number": graham_number,
        "pe_current": pe,
        "peg": peg if peg > 0 else None,
        "peg_label": peg_label,
        "value_trap_warning": value_trap_warning,
        "pe_sanity_notes": pe_sanity_notes,
        "data_trust": snapshot.get("data_trust") if isinstance(snapshot.get("data_trust"), dict) else {},
        "data_source": snapshot.get("source", "unknown"),
    }

    try:
        from core.decision_completeness import apply_completeness_to_valuation

        result = apply_completeness_to_valuation(snapshot, result)
    except Exception:
        pass

    if include_extensions:
        try:
            from core.elite_valuation import merge_elite_valuation

            return merge_elite_valuation(snapshot, result)
        except Exception:
            return result
    return result
