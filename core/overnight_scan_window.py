"""
Overnight scan window helpers (default 17:00 → 07:00 next day, Asia/Ho_Chi_Minh).

Used by VPS 24/7 tick/loop: skip outside window, rotate Autopilot batch inside window.
"""

from __future__ import annotations

import json
import os
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
_DEFAULT_STATE_REL = Path("data") / "runtime" / "overnight_scan_state.json"
_DEFAULT_TZ = "Asia/Ho_Chi_Minh"


def overnight_tz_name() -> str:
    return str(os.environ.get("II_OVERNIGHT_SCAN_TZ") or _DEFAULT_TZ).strip() or _DEFAULT_TZ


def overnight_tz() -> ZoneInfo:
    try:
        return ZoneInfo(overnight_tz_name())
    except Exception:
        return ZoneInfo(_DEFAULT_TZ)


def parse_hhmm(raw: str, *, default: time) -> time:
    text = str(raw or "").strip()
    if not text:
        return default
    parts = text.replace(".", ":").split(":")
    try:
        h = max(0, min(23, int(parts[0])))
        m = max(0, min(59, int(parts[1]))) if len(parts) > 1 else 0
        return time(hour=h, minute=m)
    except (TypeError, ValueError):
        return default


def configured_window() -> tuple[time, time]:
    start = parse_hhmm(os.environ.get("II_OVERNIGHT_SCAN_START", "17:00"), default=time(17, 0))
    end = parse_hhmm(os.environ.get("II_OVERNIGHT_SCAN_END", "07:00"), default=time(7, 0))
    return start, end


def is_in_overnight_window(
    now: datetime,
    *,
    start: time | None = None,
    end: time | None = None,
) -> bool:
    """
    True when local time is inside [start, end) spanning midnight when start > end.

    Example: 17:00–07:00 → active at 17:00..23:59 and 00:00..06:59.
    """
    start_t = start if start is not None else configured_window()[0]
    end_t = end if end is not None else configured_window()[1]
    local = now.astimezone(overnight_tz()) if now.tzinfo else now.replace(tzinfo=overnight_tz())
    t = local.timetz().replace(tzinfo=None) if hasattr(local, "timetz") else local.time()
    # Normalize to naive time for compare
    t = time(hour=local.hour, minute=local.minute, second=local.second, microsecond=local.microsecond)
    if start_t == end_t:
        return True  # full day
    if start_t < end_t:
        return start_t <= t < end_t
    return t >= start_t or t < end_t


def overnight_session_date(
    now: datetime,
    *,
    start: time | None = None,
    end: time | None = None,
) -> date:
    """
    Stable date key for one overnight session.

    For 17:00–07:00: at 18:00 Monday → Monday; at 02:00 Tuesday → Monday.
    """
    start_t = start if start is not None else configured_window()[0]
    end_t = end if end is not None else configured_window()[1]
    local = now.astimezone(overnight_tz()) if now.tzinfo else now.replace(tzinfo=overnight_tz())
    d = local.date()
    t = time(hour=local.hour, minute=local.minute, second=local.second)
    if start_t > end_t:
        if t < end_t:
            return d - timedelta(days=1)
        return d
    # Same-calendar-day window
    return d


def seconds_until_window_opens(
    now: datetime,
    *,
    start: time | None = None,
    end: time | None = None,
) -> float:
    if is_in_overnight_window(now, start=start, end=end):
        return 0.0
    start_t = start if start is not None else configured_window()[0]
    local = now.astimezone(overnight_tz()) if now.tzinfo else now.replace(tzinfo=overnight_tz())
    candidate = datetime.combine(local.date(), start_t, tzinfo=overnight_tz())
    if candidate <= local:
        candidate = candidate + timedelta(days=1)
    return max(0.0, (candidate - local).total_seconds())


def state_path() -> Path:
    raw = str(os.environ.get("II_OVERNIGHT_SCAN_STATE") or "").strip()
    if raw:
        p = Path(raw)
        return p if p.is_absolute() else (ROOT / p)
    return ROOT / _DEFAULT_STATE_REL


def load_overnight_state(path: Path | None = None) -> dict[str, Any]:
    p = path or state_path()
    if not p.exists():
        return {
            "next_offset": 0,
            "session_date": None,
            "batches_run": 0,
            "last_status": None,
        }
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
        return raw if isinstance(raw, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {"next_offset": 0, "session_date": None, "batches_run": 0}


def save_overnight_state(state: dict[str, Any], path: Path | None = None) -> Path:
    p = path or state_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    payload = dict(state or {})
    payload["updated_at"] = datetime.now(timezone.utc).isoformat()
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(p)
    return p
