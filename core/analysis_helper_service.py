from __future__ import annotations

import re
from typing import Any


def extract_ticker(text: str) -> str | None:
    m = re.search(r"\b([A-Z0-9]{2,6})\b", (text or "").strip().upper())
    return m.group(1) if m else None


def health_badge(score: int) -> tuple[str, str]:
    if score >= 7:
        return "🟢 Khỏe", "#0ea35a"
    if score >= 4:
        return "🟡 Trung tính", "#c99800"
    return "🔴 Yếu", "#c9342f"


def profile_match_note(profile: str, report: dict[str, Any]) -> str:
    val = report.get("valuation", {})
    fin = report.get("financials", {})
    phase = report.get("phase", {})
    if profile == "safe_dividend":
        cond = int(val.get("piotroski_score") or 0) >= 7 and (
            fin.get("debt_to_equity") is None or float(fin.get("debt_to_equity") or 0) < 0.7
        )
        return "Phù hợp profile an toàn." if cond else "Mức phù hợp profile an toàn: trung bình."
    if profile == "growth":
        rev = fin.get("revenue_growth_yoy")
        cond = rev is not None and float(rev) > 15
        return "Phù hợp profile tăng trưởng." if cond else "Mức phù hợp tăng trưởng: trung bình."
    vol_mult = float((phase.get("metrics") or {}).get("vol_multiple") or 0)
    return "Phù hợp profile lướt sóng." if vol_mult > 1.3 else "Mức phù hợp lướt sóng: thấp/trung bình."
