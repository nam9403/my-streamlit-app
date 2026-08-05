"""
Chuẩn hóa EPS và kiểm tra P/E sanity — loại nhiễu lợi nhuận đột biến (one-off).

Mục tiêu: tránh MOS "đẹp giả" khi EPS bị thổi bởi Other Income / lãi bất thường.
"""

from __future__ import annotations

from typing import Any

# Cổ phiếu / ngành tài chính: không trừ Other Income theo rule phi tài chính.
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

_FINANCIAL_CLUSTER_HINTS = frozenset(
    {
        "financial",
        "bank",
        "banking",
        "insurance",
        "securities",
        "ngan hang",
        "ngân hàng",
        "bao hiem",
        "bảo hiểm",
        "chung khoan",
        "chứng khoán",
    }
)

OTHER_INCOME_RATIO_THRESHOLD = 0.20
PE_DROP_VS_3Y_THRESHOLD = 0.50  # P/E giảm > 50% so với TB 3 năm
EPS_GROWTH_SPIKE_PCT = 50.0  # tăng trưởng EPS đột biến kèm P/E sụt
DEFAULT_MOS_REQUIREMENT_BUMP_PCT = 12.0  # giữa 10–15%
PE_ANOMALY_TRUST_PENALTY = 18.0
EPS_ONEOFF_TRUST_PENALTY = 10.0

EPS_ANOMALY_WARNING_VI = (
    "P/E hiện tại có dấu hiệu bị méo mó do lợi nhuận đột biến. "
    "MOS đã được điều chỉnh thận trọng."
)


def _f(v: Any) -> float | None:
    if v is None or v == "":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _pick_float(data: dict[str, Any], keys: tuple[str, ...]) -> float | None:
    for k in keys:
        v = _f(data.get(k))
        if v is not None:
            return v
    return None


def is_financial_entity(symbol: str, financial_data: dict[str, Any] | None = None) -> bool:
    sym = str(symbol or "").strip().upper()
    if sym in _BANK_SYMBOLS:
        return True
    data = financial_data if isinstance(financial_data, dict) else {}
    for key in ("industry_cluster", "industry_cluster_id", "sector", "industry", "industry_subtype"):
        raw = str(data.get(key) or "").strip().lower()
        if not raw:
            continue
        for hint in _FINANCIAL_CLUSTER_HINTS:
            if hint in raw:
                return True
    if bool(data.get("is_bank_sector")) or bool(data.get("is_financial")):
        return True
    return False


class EPSNormalizer:
    """Chuẩn hóa EPS theo chất lượng lợi nhuận + cờ P/E anomaly."""

    other_income_ratio_threshold: float = OTHER_INCOME_RATIO_THRESHOLD
    pe_drop_vs_3y_threshold: float = PE_DROP_VS_3Y_THRESHOLD
    eps_growth_spike_pct: float = EPS_GROWTH_SPIKE_PCT
    mos_requirement_bump_pct: float = DEFAULT_MOS_REQUIREMENT_BUMP_PCT

    def normalize_eps(self, symbol: str, financial_data: dict[str, Any] | None) -> float:
        """
        Normalized_EPS = Normalized_Net_Income / Total_Shares.

        Với DN phi tài chính: nếu Other Income / One-off > 20% lợi nhuận trước thuế,
        trừ phần lợi nhuận bất thường (ước sau thuế) khỏi Net Income trước khi chia cổ phiếu.
        """
        detail = self.normalize_eps_detail(symbol, financial_data)
        return float(detail.get("normalized_eps") or 0.0)

    def normalize_eps_detail(self, symbol: str, financial_data: dict[str, Any] | None) -> dict[str, Any]:
        data = dict(financial_data) if isinstance(financial_data, dict) else {}
        net_income = _pick_float(
            data,
            (
                "net_income",
                "profit_after_tax",
                "ProfitAfterTax_MRQ",
                "ProfitAfterIncomeTaxes",
                "ni",
            ),
        )
        pretax = _pick_float(
            data,
            (
                "profit_before_tax",
                "pretax_income",
                "income_before_tax",
                "ebt",
                "ProfitBeforeTax",
            ),
        )
        other_income = _pick_float(
            data,
            (
                "other_income",
                "other_operating_income",
                "financial_income",
                "one_off_gains",
                "one_time_gains",
                "non_operating_income",
                "other_gains",
            ),
        )
        shares = _pick_float(
            data,
            (
                "shares_outstanding",
                "total_shares",
                "share_outstanding",
                "listed_shares",
            ),
        )
        raw_eps = _pick_float(data, ("eps", "eps_ttm", "eps_reported", "eps_raw"))

        is_fin = is_financial_entity(symbol, data)
        other_ratio: float | None = None
        one_off_adjusted = False
        after_tax_one_off = 0.0
        normalized_ni = net_income

        if (
            not is_fin
            and net_income is not None
            and other_income is not None
            and other_income > 0
            and pretax is not None
            and pretax > 0
        ):
            other_ratio = other_income / pretax
            if other_ratio > self.other_income_ratio_threshold:
                # Ước phần one-off sau thuế theo tỷ lệ NI/PBT (fallback 80%).
                tax_keep = (net_income / pretax) if pretax else 0.8
                tax_keep = max(0.0, min(1.0, float(tax_keep)))
                after_tax_one_off = float(other_income) * tax_keep
                normalized_ni = float(net_income) - after_tax_one_off
                one_off_adjusted = True

        normalized_eps: float | None = None
        basis = "unavailable"

        if normalized_ni is not None and shares is not None and shares > 0:
            normalized_eps = float(normalized_ni) / float(shares)
            basis = "normalized_ni_per_share" if one_off_adjusted else "ni_per_share"
        elif raw_eps is not None and raw_eps > 0:
            if one_off_adjusted and net_income and net_income != 0 and normalized_ni is not None:
                scale = float(normalized_ni) / float(net_income)
                normalized_eps = float(raw_eps) * max(0.0, scale)
                basis = "eps_scaled_by_one_off"
            else:
                normalized_eps = float(raw_eps)
                basis = "raw_eps"

        if normalized_eps is None:
            normalized_eps = 0.0

        notes: list[str] = []
        if one_off_adjusted and other_ratio is not None:
            notes.append(
                f"Other Income chiếm {other_ratio * 100:.1f}% LNTT (>20%) — "
                f"đã trừ ~{after_tax_one_off:,.0f} khỏi LNST trước khi tính EPS chuẩn."
            )
        elif is_fin:
            notes.append("DN tài chính: không trừ Other Income theo rule phi tài chính.")

        return {
            "symbol": str(symbol or "").strip().upper(),
            "is_financial": is_fin,
            "net_income": net_income,
            "normalized_net_income": normalized_ni,
            "pretax_income": pretax,
            "other_income": other_income,
            "other_income_ratio": other_ratio,
            "shares_outstanding": shares,
            "raw_eps": raw_eps,
            "normalized_eps": float(normalized_eps),
            "one_off_adjusted": one_off_adjusted,
            "eps_anomaly_flag": bool(one_off_adjusted),
            "basis": basis,
            "notes": notes,
            "data_trust_penalty": EPS_ONEOFF_TRUST_PENALTY if one_off_adjusted else 0.0,
        }

    def pe_sanity_check(
        self,
        symbol: str,
        current_pe: float | None,
        industry_pe: float | None,
        eps_growth: float | None,
        *,
        pe_avg_3y: float | None = None,
        base_trust_score: float = 100.0,
    ) -> dict[str, Any]:
        """
        Đánh giá P/E có bị méo do EPS tăng ảo / one-off.

        Cờ pe_anomaly_flag = True khi:
        - P/E hiện tại giảm > 50% so với P/E TB 3 năm, và EPS growth đột biến; hoặc
        - P/E << P/E ngành (>50% thấp hơn) kèm tăng trưởng EPS bất thường.
        """
        cur = _f(current_pe)
        ind = _f(industry_pe)
        growth = _f(eps_growth)
        pe3 = _f(pe_avg_3y)

        pe_anomaly_flag = False
        reasons: list[str] = []
        pe_drop_vs_3y: float | None = None
        pe_vs_industry: float | None = None

        growth_spike = growth is not None and growth >= self.eps_growth_spike_pct

        if cur is not None and cur > 0 and pe3 is not None and pe3 > 0:
            pe_drop_vs_3y = (pe3 - cur) / pe3
            if pe_drop_vs_3y > self.pe_drop_vs_3y_threshold and (growth_spike or growth is None):
                # Nếu không có eps_growth, vẫn cảnh báo khi P/E sụt mạnh bất thường.
                pe_anomaly_flag = True
                reasons.append(
                    f"P/E hiện tại ({cur:.2f}) thấp hơn >50% so với TB 3 năm ({pe3:.2f})"
                    + (f"; EPS growth={growth:.1f}%" if growth is not None else "")
                    + "."
                )

        if cur is not None and cur > 0 and ind is not None and ind > 0:
            pe_vs_industry = cur / ind
            if pe_vs_industry < (1.0 - self.pe_drop_vs_3y_threshold) and growth_spike:
                pe_anomaly_flag = True
                reasons.append(
                    f"P/E ({cur:.2f}) thấp hơn >50% P/E ngành ({ind:.2f}) kèm EPS growth đột biến ({growth:.1f}%)."
                )

        # P/E cực thấp tuyệt đối + growth spike → nghi EPS ảo.
        if cur is not None and 0 < cur < 5.0 and growth_spike:
            pe_anomaly_flag = True
            reasons.append(f"P/E={cur:.2f} rất thấp kèm EPS growth {growth:.1f}% — nghi lợi nhuận đột biến.")

        trust_penalty = PE_ANOMALY_TRUST_PENALTY if pe_anomaly_flag else 0.0
        data_trust_score = max(0.0, min(100.0, float(base_trust_score) - trust_penalty))

        return {
            "symbol": str(symbol or "").strip().upper(),
            "current_pe": cur,
            "industry_pe": ind,
            "pe_avg_3y": pe3,
            "eps_growth": growth,
            "pe_drop_vs_3y": pe_drop_vs_3y,
            "pe_vs_industry": pe_vs_industry,
            "pe_anomaly_flag": pe_anomaly_flag,
            "reasons": reasons,
            "data_trust_penalty": trust_penalty,
            "data_trust_score": data_trust_score,
            "mos_requirement_bump_pct": self.mos_requirement_bump_pct if pe_anomaly_flag else 0.0,
            "warning_vi": EPS_ANOMALY_WARNING_VI if pe_anomaly_flag else "",
        }

    def apply_to_snapshot(self, snapshot: dict[str, Any]) -> dict[str, Any]:
        """
        Gắn normalized_eps + pe sanity vào snapshot (in-place) và trả meta dict.
        financial_data lấy từ snapshot + piotroski + financials lồng nhau.
        """
        if not isinstance(snapshot, dict):
            return {}

        fin_block = snapshot.get("financials") if isinstance(snapshot.get("financials"), dict) else {}
        pio = snapshot.get("piotroski") if isinstance(snapshot.get("piotroski"), dict) else {}
        merged: dict[str, Any] = {}
        merged.update(fin_block)
        merged.update(pio)
        # Snapshot fields thắng khi trùng khóa (giá/EPS hiện hành).
        for k, v in snapshot.items():
            if k in ("financials", "piotroski", "valuation"):
                continue
            if v is not None and v != "":
                merged[k] = v

        symbol = str(snapshot.get("symbol") or merged.get("symbol") or "")
        eps_detail = self.normalize_eps_detail(symbol, merged)
        norm_eps = float(eps_detail.get("normalized_eps") or 0.0)

        price = _f(snapshot.get("price")) or 0.0
        raw_eps = _f(snapshot.get("eps")) or _f(snapshot.get("eps_ttm")) or 0.0

        if norm_eps > 0:
            snapshot["normalized_eps"] = round(norm_eps, 6)
            snapshot["eps_normalizer_meta"] = {
                "basis": eps_detail.get("basis"),
                "one_off_adjusted": eps_detail.get("one_off_adjusted"),
                "other_income_ratio": eps_detail.get("other_income_ratio"),
                "notes": list(eps_detail.get("notes") or []),
            }
            if eps_detail.get("one_off_adjusted"):
                snapshot["eps_anomaly_flag"] = True
                if price > 0:
                    snapshot["pe_ratio_normalized"] = round(price / norm_eps, 4)
            elif price > 0 and (snapshot.get("pe_ratio_normalized") in (None, "")):
                snapshot["pe_ratio_normalized"] = round(price / norm_eps, 4)

        current_pe = _f(snapshot.get("pe_ratio_normalized"))
        if current_pe is None and price > 0 and norm_eps > 0:
            current_pe = price / norm_eps
        if current_pe is None:
            current_pe = _f(snapshot.get("pe_ratio"))
        if current_pe is None and price > 0 and raw_eps > 0:
            current_pe = price / raw_eps

        industry_pe = _pick_float(
            merged,
            ("sector_pe_5y_avg", "industry_pe", "sector_pe", "pe_industry"),
        )
        pe_avg_3y = _pick_float(merged, ("pe_avg_3y", "pe_3y_avg", "avg_pe_3y", "historical_pe_3y"))
        eps_growth = _pick_float(
            merged,
            ("eps_growth", "eps_growth_pct", "growth_rate_pct", "earnings_growth_pct"),
        )

        pe_check = self.pe_sanity_check(
            symbol,
            current_pe,
            industry_pe,
            eps_growth,
            pe_avg_3y=pe_avg_3y,
            base_trust_score=float(_f(snapshot.get("data_trust_score")) or 100.0),
        )

        # One-off EPS cũng kích hoạt cảnh báo UI + bump MOS (dù P/E chưa sụt đủ 50%).
        if eps_detail.get("eps_anomaly_flag") and not pe_check.get("pe_anomaly_flag"):
            pe_check = dict(pe_check)
            pe_check["pe_anomaly_flag"] = True
            pe_check["reasons"] = list(pe_check.get("reasons") or []) + list(eps_detail.get("notes") or [])
            pe_check["mos_requirement_bump_pct"] = self.mos_requirement_bump_pct
            pe_check["warning_vi"] = EPS_ANOMALY_WARNING_VI
            pe_check["data_trust_penalty"] = float(pe_check.get("data_trust_penalty") or 0.0) + float(
                eps_detail.get("data_trust_penalty") or 0.0
            )
            pe_check["data_trust_score"] = max(
                0.0,
                min(100.0, float(_f(snapshot.get("data_trust_score")) or 100.0) - float(pe_check["data_trust_penalty"])),
            )

        snapshot["pe_sanity"] = pe_check
        snapshot["pe_anomaly_flag"] = bool(pe_check.get("pe_anomaly_flag"))
        if pe_check.get("pe_anomaly_flag"):
            snapshot["eps_pe_anomaly_warning_vi"] = EPS_ANOMALY_WARNING_VI
            snapshot["mos_requirement_bump_pct"] = float(pe_check.get("mos_requirement_bump_pct") or self.mos_requirement_bump_pct)

        return {
            "eps_detail": eps_detail,
            "pe_sanity": pe_check,
            "normalized_eps": norm_eps,
            "pe_anomaly_flag": bool(pe_check.get("pe_anomaly_flag")),
        }


_DEFAULT_NORMALIZER = EPSNormalizer()


def get_eps_normalizer() -> EPSNormalizer:
    return _DEFAULT_NORMALIZER
