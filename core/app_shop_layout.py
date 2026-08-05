"""Bố cục kiểu 'siêu thị': nhãn kệ — dễ thấy, dễ đi theo thứ tự."""

from __future__ import annotations

import html

import streamlit as st


def render_aisle_band(*, title: str, subtitle: str = "") -> None:
    """Một dải nhãn ngang (không chiếm nhiều dọc), tách vùng màn hình."""
    title_e = html.escape(title)
    sub_html = (
        f'<p class="shop-aisle-sub">{html.escape(subtitle)}</p>'
        if (subtitle or "").strip()
        else ""
    )
    st.markdown(
        f'<div class="shop-aisle-band"><div class="shop-aisle-inner">'
        f'<span class="shop-aisle-dot"></span>'
        f'<span class="shop-aisle-title">{title_e}</span>'
        f"{sub_html}</div></div>",
        unsafe_allow_html=True,
    )


__all__ = ["render_aisle_band"]
