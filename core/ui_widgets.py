"""
Defensive Streamlit widget helpers — avoid StreamlitAPIException on invalid ranges.
"""

from __future__ import annotations

from typing import Any

import streamlit as st


def safe_int_range_control(
    label: str,
    *,
    min_value: int,
    max_value: int,
    value: int | None = None,
    step: int = 1,
    key: str | None = None,
    disabled: bool = False,
) -> int:
    """
    Integer range control that never crashes when max_value <= min_value.

    - When max > min: normal ``st.slider``.
    - When max <= min: disabled ``st.number_input`` locked to a safe fixed value.
    """
    lo = int(min_value)
    hi = int(max_value)
    step_i = max(1, int(step or 1))

    if hi <= lo:
        fixed = lo if hi < lo else hi
        if value is not None:
            fixed = int(value)
            if hi < lo:
                fixed = lo
            else:
                fixed = hi
        if key is not None:
            st.session_state[key] = fixed
        ni_kwargs: dict[str, Any] = {
            "min_value": fixed,
            "max_value": fixed,
            "value": fixed,
            "step": step_i,
            "disabled": True,
        }
        if key is not None:
            ni_kwargs["key"] = f"{key}_fixed"
        return int(st.number_input(label, **ni_kwargs))

    default = lo if value is None else int(max(lo, min(hi, int(value))))
    sl_kwargs: dict[str, Any] = {
        "min_value": lo,
        "max_value": hi,
        "step": step_i,
    }
    if key is not None:
        if key not in st.session_state:
            st.session_state[key] = default
        sl_kwargs["key"] = key
    else:
        sl_kwargs["value"] = default
    if disabled:
        sl_kwargs["disabled"] = True
    return int(st.slider(label, **sl_kwargs))
