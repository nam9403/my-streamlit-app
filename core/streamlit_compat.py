"""
Streamlit API compatibility across versions (local vs VPS).

Newer Streamlit accepts width=\"stretch\"; older builds raise TypeError
on sidebar auth buttons. Prefer use_container_width=True (works on both).
"""

from __future__ import annotations

from typing import Any


def stretch_kwargs() -> dict[str, Any]:
    """Kwargs to make buttons/inputs full width on old and new Streamlit."""
    return {"use_container_width": True}
