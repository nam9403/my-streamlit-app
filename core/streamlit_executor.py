"""
ThreadPoolExecutor helper that attaches Streamlit ScriptRunContext to worker threads.

Eliminates `missing ScriptRunContext!` warnings when parallel scan/finder paths call
`@st.cache_data` wrappers from background threads.

IMPORTANT: ScriptRunContext must be captured on the *calling* (main) thread and then
attached to each worker. Capturing inside the worker initializer always yields None.
"""

from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Any


def capture_streamlit_script_context() -> Any | None:
    """Return the current ScriptRunContext from the calling thread (or None)."""
    try:
        from streamlit.runtime.scriptrunner import get_script_run_ctx

        return get_script_run_ctx(suppress_warning=True)
    except Exception:
        return None


def attach_streamlit_script_context(ctx: Any | None = None) -> None:
    """
    Bind Streamlit context to the current thread.

    If ``ctx`` is omitted, try to reuse an already-present context (no-op when absent).
    Prefer passing a context captured on the main thread via ``capture_streamlit_script_context``.
    """
    try:
        from streamlit.runtime.scriptrunner import add_script_run_ctx, get_script_run_ctx

        effective = ctx if ctx is not None else get_script_run_ctx(suppress_warning=True)
        if effective is not None:
            add_script_run_ctx(thread=threading.current_thread(), ctx=effective)
    except Exception:
        return


def streamlit_thread_pool_executor(max_workers: int, **kwargs: Any) -> ThreadPoolExecutor:
    """ThreadPoolExecutor with Streamlit context initializer for UI parallel workloads."""
    # Capture on the *caller* thread (usually the Streamlit script thread).
    parent_ctx = capture_streamlit_script_context()

    def _worker_init() -> None:
        attach_streamlit_script_context(parent_ctx)

    return ThreadPoolExecutor(
        max_workers=max_workers,
        initializer=_worker_init,
        **kwargs,
    )
