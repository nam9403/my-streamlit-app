"""
Wave 3 — event / blackout gate around earnings season & corporate actions.

Soft gate: demote new BUY/CONDITIONAL_BUY when inside a blackout window.
Sources (best-effort, no look-ahead invent):
- Fixed VN earnings-season windows (quarterly report lag seasons)
- Recent news titles mentioning KQKD / chốt quyền / cổ tức
- Explicit event dates on snapshot/financials when present
"""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta
from typing import Any

_EARNINGS_KW = (
    "kết quả kinh doanh",
    "kqkd",
    "báo cáo tài chính",
    "bctc",
    "công bố lợi nhuận",
    "earnings",
)
_DIV_KW = (
    "chốt quyền",
    "ex-right",
    "ex right",
    "ngày giao dịch không hưởng quyền",
    "cổ tức bằng tiền",
    "tạm ứng cổ tức",
    "trả cổ tức",
)


def _to_date(v: Any) -> date | None:
    if v is None:
        return None
    if isinstance(v, date) and not isinstance(v, datetime):
        return v
    if isinstance(v, datetime):
        return v.date()
    try:
        s = str(v).replace("Z", "+00:00")
        if "T" in s:
            return datetime.fromisoformat(s).date()
        return datetime.strptime(s[:10], "%Y-%m-%d").date()
    except Exception:
        return None


def vn_earnings_season_windows(year: int) -> list[tuple[date, date, str]]:
    """
    Conservative seasons when many VN names publish quarterly results.
    Window = soft blackout for *new* entries (not forced exits).
    """
    y = int(year)
    # Q4 prior → Jan15–Feb28; Q1 → Apr15–May20; Q2 → Jul15–Aug20; Q3 → Oct15–Nov20
    return [
        (date(y, 1, 15), date(y, 2, 28), "earnings_season_Q4"),
        (date(y, 4, 15), date(y, 5, 20), "earnings_season_Q1"),
        (date(y, 7, 15), date(y, 8, 20), "earnings_season_Q2"),
        (date(y, 10, 15), date(y, 11, 20), "earnings_season_Q3"),
    ]


def _in_any_window(as_of: date, windows: list[tuple[date, date, str]]) -> tuple[bool, str | None]:
    for a, b, label in windows:
        if a <= as_of <= b:
            return True, label
    return False, None


def _news_blackout(
    news: list[dict[str, Any]] | None,
    *,
    as_of: date,
    lookback_days: int = 7,
    forward_days: int = 3,
) -> tuple[bool, str | None]:
    if not news:
        return False, None
    cut = as_of - timedelta(days=max(1, lookback_days))
    for row in news[:30]:
        if not isinstance(row, dict):
            continue
        title = str(row.get("title") or row.get("headline") or "").lower()
        if not title:
            continue
        nd = _to_date(row.get("date") or row.get("published_at") or row.get("time"))
        if nd is not None and nd < cut:
            continue
        if any(k in title for k in _EARNINGS_KW):
            # blackout a few days after headline
            if nd is None or nd <= as_of <= nd + timedelta(days=forward_days):
                return True, "news_earnings"
        if any(k in title for k in _DIV_KW):
            if nd is None or nd <= as_of <= nd + timedelta(days=forward_days):
                return True, "news_dividend_exright"
    return False, None


def _explicit_event_blackout(
    snapshot: dict[str, Any] | None,
    financials: dict[str, Any] | None,
    *,
    as_of: date,
    pre_days: int = 3,
    post_days: int = 2,
) -> tuple[bool, str | None]:
    snap = snapshot if isinstance(snapshot, dict) else {}
    fin = financials if isinstance(financials, dict) else {}
    candidates: list[tuple[str, Any]] = []
    for key in (
        "next_earnings_date",
        "earnings_date",
        "ex_dividend_date",
        "ex_right_date",
        "dividend_ex_date",
        "latest_dividend_ex_date",
    ):
        if snap.get(key) is not None:
            candidates.append((key, snap.get(key)))
        if fin.get(key) is not None:
            candidates.append((key, fin.get(key)))
    # list of events
    for key in ("corporate_events", "dividend_events", "upcoming_events"):
        evs = snap.get(key) or fin.get(key)
        if isinstance(evs, list):
            for ev in evs[:20]:
                if isinstance(ev, dict):
                    candidates.append((key, ev.get("ex_date") or ev.get("date") or ev.get("payout_date")))
                else:
                    candidates.append((key, ev))
    for label, raw in candidates:
        d = _to_date(raw)
        if d is None:
            continue
        if d - timedelta(days=pre_days) <= as_of <= d + timedelta(days=post_days):
            return True, f"explicit:{label}"
    return False, None


def assess_event_blackout(
    *,
    as_of: date | str | datetime | None = None,
    news: list[dict[str, Any]] | None = None,
    snapshot: dict[str, Any] | None = None,
    financials: dict[str, Any] | None = None,
    use_season: bool = True,
) -> dict[str, Any]:
    """
    Return blackout decision for *new entries*.
    """
    today = _to_date(as_of) or date.today()
    reasons: list[str] = []
    active = False

    if use_season:
        hit, lab = _in_any_window(today, vn_earnings_season_windows(today.year))
        if hit:
            active = True
            reasons.append(str(lab))

    n_hit, n_lab = _news_blackout(news, as_of=today)
    if n_hit:
        active = True
        reasons.append(str(n_lab))

    e_hit, e_lab = _explicit_event_blackout(snapshot, financials, as_of=today)
    if e_hit:
        active = True
        reasons.append(str(e_lab))

    return {
        "blackout": active,
        "as_of": today.isoformat(),
        "reasons": reasons,
        "severity": "high" if any(str(r).startswith("explicit:") or r.startswith("news_") for r in reasons) else (
            "medium" if active else "none"
        ),
        "note_vi": (
            "Blackout sự kiện — tạm không mở mua mới (KQKD/chốt quyền/mùa BCTC)."
            if active
            else "Không trong cửa sổ sự kiện hạn chế."
        ),
    }


def apply_event_blackout_to_action(
    action: str,
    blackout: dict[str, Any] | None,
) -> tuple[str, list[str]]:
    """
    Demote entries when blackout active.
    - severity high (news/explicit): BUY/COND → HOLD
    - severity medium (earnings season only): BUY → CONDITIONAL_BUY
    """
    act = str(action or "WATCH").upper()
    bo = blackout if isinstance(blackout, dict) else {}
    notes: list[str] = []
    if not bo.get("blackout"):
        return act, notes
    sev = str(bo.get("severity") or "medium").lower()
    note = str(bo.get("note_vi") or "Event blackout.")
    if sev == "high":
        if act in ("BUY", "CONDITIONAL_BUY"):
            notes.append(note + " → HOLD.")
            return "HOLD", notes
        return act, notes
    # medium (season): only soften hard BUY
    if act == "BUY":
        notes.append(note + " → CONDITIONAL_BUY (mùa BCTC).")
        return "CONDITIONAL_BUY", notes
    return act, notes
