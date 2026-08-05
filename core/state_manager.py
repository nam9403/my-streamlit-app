"""
Type-safe Streamlit session-state accessors for the UI layer.

Panels and the composition shell should read/write UI state through this module
instead of scattering raw ``st.session_state[...]`` keys.
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass
from typing import Any, Callable

import streamlit as st

# --- Canonical session keys (registry) ---
KEY_AUTH_OK = "auth_ok"
KEY_USER_ID = "user_id"
KEY_SESSION_TOKEN = "session_token"
KEY_VN_UNIVERSE_TOTAL = "vn_universe_total"
KEY_VN_UNIVERSE_TOTAL_TS = "_vn_universe_total_ts"
KEY_DEFER_AUTOPILOT = "defer_autopilot_runtime"
KEY_AUTOPILOT_REQUESTED = "autopilot_requested"
KEY_FINDER_SHELL_UNLOCKED = "finder_shell_unlocked"
KEY_CHAT_TICKER = "chat_ticker"
KEY_FORCE_SYNC_ANALYSIS = "force_sync_analysis"
KEY_ANALYSIS_BG_REQUEST_JOB_ID = "analysis_bg_request_for_job_id"
KEY_ANALYSIS_BG_POLL_JID = "analysis_bg_poll_jid"
KEY_FINDER_PG_POLL_JID = "finder_pg_poll_jid"
KEY_SCAN_PG_POLL_JID = "scan_pg_poll_jid"
KEY_AUTOPILOT_PG_POLL_JID = "autopilot_pg_poll_jid"
KEY_ANALYSIS_VIEW_MODE = "analysis_view_mode"
KEY_LITE_UI_MODE = "lite_ui_mode"
KEY_REPORT_CACHE = "report_cache"


@dataclass(frozen=True)
class FastShellFlags:
    fast_shell: bool
    defer_autopilot: bool
    autopilot_requested: bool
    finder_unlocked: bool
    should_defer_autopilot: bool


def _state() -> Any:
    return st.session_state


def get(key: str, default: Any = None) -> Any:
    return _state().get(key, default)


def set_value(key: str, value: Any) -> None:
    _state()[key] = value


def pop(key: str, default: Any = None) -> Any:
    return _state().pop(key, default)


def get_selected_ticker() -> str:
    return str(get(KEY_CHAT_TICKER) or "").strip().upper()


def set_selected_ticker(ticker: str) -> None:
    t = str(ticker or "").strip().upper()
    if t:
        set_value(KEY_CHAT_TICKER, t)


def get_current_user_id() -> str:
    return str(get(KEY_USER_ID) or "").strip()


def is_auth_ok() -> bool:
    return bool(get(KEY_AUTH_OK, False))


def get_watchlist_state() -> list[str]:
    """Watchlist may live on RuntimeFlowConfig; this is a session fallback bag."""
    raw = get("watchlist") or get("watch_seed") or []
    if isinstance(raw, str):
        return [x.strip().upper() for x in raw.replace(";", ",").split(",") if x.strip()]
    return [str(x).strip().upper() for x in list(raw or []) if str(x).strip()]


def get_scan_results() -> Any:
    return get("scan_results")


def set_scan_results(payload: Any) -> None:
    set_value("scan_results", payload)


def _vn_universe_total_refresh_sec() -> float:
    try:
        return max(15.0, float(os.environ.get("II_VN_UNIVERSE_TOTAL_REFRESH_SEC", "120")))
    except ValueError:
        return 120.0


def refresh_vn_universe_total(count_fn: Callable[[], int]) -> int:
    """TTL-cached VN listing count for sidebar captions."""
    try:
        now_ts = time.time()
        last_ts = float(get(KEY_VN_UNIVERSE_TOTAL_TS) or 0.0)
        refresh_sec = _vn_universe_total_refresh_sec()
        if KEY_VN_UNIVERSE_TOTAL not in _state() or (now_ts - last_ts) >= refresh_sec:
            total = int(count_fn())
            set_value(KEY_VN_UNIVERSE_TOTAL, total)
            set_value(KEY_VN_UNIVERSE_TOTAL_TS, now_ts)
            return total
        return int(get(KEY_VN_UNIVERSE_TOTAL) or 0)
    except Exception:
        return int(get(KEY_VN_UNIVERSE_TOTAL) or 0)


def get_vn_universe_total() -> int:
    return int(get(KEY_VN_UNIVERSE_TOTAL) or 0)


def resolve_fast_shell_flags(*, run_analysis: bool = False, autopilot_refresh: bool = False) -> FastShellFlags:
    fast_shell = str(os.environ.get("II_FAST_SHELL_DEFAULT", "1") or "").strip().lower() not in (
        "0",
        "false",
        "no",
        "off",
    )
    defer_default = str(os.environ.get("II_DEFER_AUTOPILOT_DEFAULT", "0")).strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    ) or bool(fast_shell)
    defer = bool(get(KEY_DEFER_AUTOPILOT, defer_default))
    requested = bool(get(KEY_AUTOPILOT_REQUESTED, False))
    finder_unlocked = bool(get(KEY_FINDER_SHELL_UNLOCKED, False))
    should_defer = defer and not requested and not run_analysis and not autopilot_refresh
    return FastShellFlags(
        fast_shell=fast_shell,
        defer_autopilot=defer,
        autopilot_requested=requested,
        finder_unlocked=finder_unlocked,
        should_defer_autopilot=should_defer,
    )


def request_autopilot_load() -> None:
    set_value(KEY_AUTOPILOT_REQUESTED, True)


def unlock_finder_shell() -> None:
    set_value(KEY_FINDER_SHELL_UNLOCKED, True)


def consume_force_sync_analysis() -> bool:
    return bool(pop(KEY_FORCE_SYNC_ANALYSIS, False))


def request_force_sync_analysis() -> None:
    set_value(KEY_FORCE_SYNC_ANALYSIS, True)


def request_analysis_bg_job(job_id: str) -> None:
    set_value(KEY_ANALYSIS_BG_REQUEST_JOB_ID, str(job_id))


def get_analysis_bg_poll_jid() -> str | None:
    jid = get(KEY_ANALYSIS_BG_POLL_JID)
    return str(jid) if jid else None


def get_finder_pg_poll_jid() -> str | None:
    jid = get(KEY_FINDER_PG_POLL_JID)
    return str(jid) if jid else None


def set_scan_pg_poll_jid(job_id: str | None) -> None:
    if job_id:
        set_value(KEY_SCAN_PG_POLL_JID, str(job_id))
    else:
        pop(KEY_SCAN_PG_POLL_JID, None)


def get_scan_pg_poll_jid() -> str | None:
    jid = get(KEY_SCAN_PG_POLL_JID)
    return str(jid) if jid else None


def set_autopilot_pg_poll_jid(job_id: str | None) -> None:
    if job_id:
        set_value(KEY_AUTOPILOT_PG_POLL_JID, str(job_id))
    else:
        pop(KEY_AUTOPILOT_PG_POLL_JID, None)


def get_autopilot_pg_poll_jid() -> str | None:
    jid = get(KEY_AUTOPILOT_PG_POLL_JID)
    return str(jid) if jid else None


def poll_async_job_status(job_id: str) -> dict[str, Any] | None:
    """Lightweight DB status read for Streamlit fragments (no heavy work)."""
    from core.ui_bg_analysis import read_analysis_job_status

    return read_analysis_job_status(str(job_id))


def render_job_progress_placeholder(label: str = "Đang xử lý trên worker Postgres…") -> None:
    """Lightweight waiting UI — no computation in Streamlit process."""
    import streamlit as st

    st.info(label)
    try:
        st.progress(0.45, text="Worker đang chạy (polling nhẹ)…")
    except TypeError:
        st.progress(45)


def is_lite_ui_mode(default: bool = False) -> bool:
    if KEY_LITE_UI_MODE in _state():
        return bool(get(KEY_LITE_UI_MODE))
    return bool(default)


def set_lite_ui_mode(enabled: bool) -> None:
    set_value(KEY_LITE_UI_MODE, bool(enabled))
