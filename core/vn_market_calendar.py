from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
CALENDAR_PATH = ROOT / "data" / "market_calendar_vn.json"

_cal_file_mtime: float = -2.0
_cal_file_data: dict[int, list[str]] | None = None

# Curated baseline holidays (extend safely via file-backed store).
_BASE_HOLIDAYS: dict[int, list[str]] = {
    2024: [
        "2024-01-01",
        "2024-02-08",
        "2024-02-09",
        "2024-02-12",
        "2024-02-13",
        "2024-02-14",
        "2024-04-18",
        "2024-04-29",
        "2024-04-30",
        "2024-05-01",
        "2024-09-02",
    ],
    2025: [
        "2025-01-01",
        "2025-01-28",
        "2025-01-29",
        "2025-01-30",
        "2025-01-31",
        "2025-02-03",
        "2025-04-07",
        "2025-04-30",
        "2025-05-01",
        "2025-09-02",
    ],
    2026: [
        "2026-01-01",
        "2026-02-16",
        "2026-02-17",
        "2026-02-18",
        "2026-02-19",
        "2026-02-20",
        "2026-04-27",
        "2026-04-30",
        "2026-05-01",
        "2026-09-02",
    ],
    2027: [
        "2027-01-01",
        "2027-02-08",
        "2027-02-09",
        "2027-02-10",
        "2027-02-11",
        "2027-02-12",
        "2027-04-19",
        "2027-04-30",
        "2027-09-02",
    ],
}


def _estimated_fixed_holidays(year: int) -> list[str]:
    # Conservative fallback for years not curated yet.
    return [f"{year}-01-01", f"{year}-04-30", f"{year}-05-01", f"{year}-09-02"]


def _invalidate_calendar_file_cache() -> None:
    global _cal_file_mtime, _cal_file_data
    _cal_file_mtime = -2.0
    _cal_file_data = None


def _read_calendar_file() -> dict[int, list[str]]:
    global _cal_file_mtime, _cal_file_data
    try:
        mt = float(CALENDAR_PATH.stat().st_mtime) if CALENDAR_PATH.exists() else -1.0
    except OSError:
        mt = -1.0
    if _cal_file_data is not None and _cal_file_mtime == mt:
        return _cal_file_data
    if not CALENDAR_PATH.exists():
        empty: dict[int, list[str]] = {}
        _cal_file_data = empty
        _cal_file_mtime = mt
        return empty
    try:
        raw = json.loads(CALENDAR_PATH.read_text(encoding="utf-8"))
    except Exception:
        empty = {}
        _cal_file_data = empty
        _cal_file_mtime = mt
        return empty
    years = raw.get("years") if isinstance(raw, dict) else {}
    out: dict[int, list[str]] = {}
    if isinstance(years, dict):
        for k, v in years.items():
            try:
                y = int(k)
            except Exception:
                continue
            if isinstance(v, list):
                out[y] = [str(x) for x in v if isinstance(x, str)]
    try:
        mt = float(CALENDAR_PATH.stat().st_mtime) if CALENDAR_PATH.exists() else -1.0
    except OSError:
        mt = -1.0
    _cal_file_data = out
    _cal_file_mtime = mt
    return out


def _write_calendar_file(year_map: dict[int, list[str]]) -> None:
    CALENDAR_PATH.parent.mkdir(parents=True, exist_ok=True)
    payload: dict[str, Any] = {
        "meta": {
            "calendar": "VN stock market holidays",
            "note": "Years may include curated and estimated entries.",
        },
        "years": {str(y): sorted(set(days)) for y, days in sorted(year_map.items())},
    }
    CALENDAR_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    _invalidate_calendar_file_cache()


def ensure_calendar_years(start_year: int, end_year: int) -> dict[int, list[str]]:
    merged: dict[int, list[str]] = {y: list(days) for y, days in _BASE_HOLIDAYS.items()}
    file_map = _read_calendar_file()
    for y, days in file_map.items():
        merged[y] = list(set(merged.get(y, []) + days))

    updated = False
    for y in range(start_year, end_year + 1):
        if y not in merged:
            merged[y] = _estimated_fixed_holidays(y)
            updated = True
    if updated or not CALENDAR_PATH.exists():
        _write_calendar_file(merged)
    return merged


def expected_vn_trading_days(start: pd.Timestamp, end: pd.Timestamp) -> pd.DatetimeIndex:
    start = pd.to_datetime(start)
    end = pd.to_datetime(end)
    year_map = ensure_calendar_years(start.year, end.year)
    holiday_set = {d for days in year_map.values() for d in days}
    weekdays = pd.bdate_range(start=start, end=end)
    return pd.DatetimeIndex([d for d in weekdays if d.strftime("%Y-%m-%d") not in holiday_set])
