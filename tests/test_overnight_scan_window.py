from __future__ import annotations

from datetime import datetime, time
from zoneinfo import ZoneInfo

from core.overnight_scan_window import (
    is_in_overnight_window,
    load_overnight_state,
    overnight_session_date,
    parse_hhmm,
    save_overnight_state,
    seconds_until_window_opens,
)


TZ = ZoneInfo("Asia/Ho_Chi_Minh")


def _dt(y: int, m: int, d: int, hh: int, mm: int = 0) -> datetime:
    return datetime(y, m, d, hh, mm, tzinfo=TZ)


def test_parse_hhmm() -> None:
    assert parse_hhmm("17:00", default=time(0, 0)) == time(17, 0)
    assert parse_hhmm("7:30", default=time(0, 0)) == time(7, 30)
    assert parse_hhmm("bad", default=time(9, 0)) == time(9, 0)


def test_overnight_window_cross_midnight() -> None:
    start, end = time(17, 0), time(7, 0)
    assert is_in_overnight_window(_dt(2026, 8, 6, 17, 0), start=start, end=end)
    assert is_in_overnight_window(_dt(2026, 8, 6, 23, 59), start=start, end=end)
    assert is_in_overnight_window(_dt(2026, 8, 7, 0, 0), start=start, end=end)
    assert is_in_overnight_window(_dt(2026, 8, 7, 6, 59), start=start, end=end)
    assert not is_in_overnight_window(_dt(2026, 8, 7, 7, 0), start=start, end=end)
    assert not is_in_overnight_window(_dt(2026, 8, 6, 16, 59), start=start, end=end)
    assert not is_in_overnight_window(_dt(2026, 8, 6, 12, 0), start=start, end=end)


def test_overnight_session_date_cross_midnight() -> None:
    start, end = time(17, 0), time(7, 0)
    assert overnight_session_date(_dt(2026, 8, 6, 18, 0), start=start, end=end).isoformat() == "2026-08-06"
    assert overnight_session_date(_dt(2026, 8, 7, 2, 0), start=start, end=end).isoformat() == "2026-08-06"
    assert overnight_session_date(_dt(2026, 8, 7, 17, 30), start=start, end=end).isoformat() == "2026-08-07"


def test_seconds_until_window_opens() -> None:
    start, end = time(17, 0), time(7, 0)
    noon = _dt(2026, 8, 6, 12, 0)
    wait = seconds_until_window_opens(noon, start=start, end=end)
    assert 4.9 * 3600 <= wait <= 5.1 * 3600
    assert seconds_until_window_opens(_dt(2026, 8, 6, 18, 0), start=start, end=end) == 0.0


def test_overnight_state_roundtrip(tmp_path) -> None:
    p = tmp_path / "overnight_scan_state.json"
    save_overnight_state({"next_offset": 40, "session_date": "2026-08-06", "batches_run": 2}, path=p)
    loaded = load_overnight_state(path=p)
    assert int(loaded["next_offset"]) == 40
    assert loaded["session_date"] == "2026-08-06"
    assert int(loaded["batches_run"]) == 2
    assert "updated_at" in loaded
