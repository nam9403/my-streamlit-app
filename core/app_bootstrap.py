"""
Application bootstrap helpers for Streamlit entrypoint.
"""

from __future__ import annotations

import logging
import os

import streamlit as st

from app_constants import get_app_version
from core.observability import configure_observability
from core.ui_styles import inject_custom_styles


def bootstrap_app_ui() -> logging.Logger:
    correlation_id = configure_observability("streamlit_app")
    logger = logging.getLogger(__name__)
    logger.info("app_main_started correlation_id=%s", correlation_id)
    env = str(os.environ.get("II_ENV") or "dev").strip().lower()
    if env == "prod":
        try:
            from scripts.ensure_production_profile import check_production_profile

            profile = check_production_profile(strict=True)
            if not profile.get("ok"):
                for issue in profile.get("issues") or []:
                    logger.error("production_profile_issue %s", issue)
                raise RuntimeError(
                    "Production profile check failed: " + "; ".join(profile.get("issues") or ["unknown"])
                )
            for warn in profile.get("warnings") or []:
                logger.warning("production_profile_warning %s", warn)
        except RuntimeError:
            raise
        except Exception as exc:
            logger.warning("production_profile_check_skipped error=%s", exc.__class__.__name__)
    app_version = get_app_version()
    st.set_page_config(page_title="Investment Intelligence Dashboard", page_icon="📊", layout="wide")
    inject_custom_styles()
    st.title("📡 Investment Intelligence Dashboard")
    st.caption(f"v{app_version} | Technical + Fundamental + News + AI 7 Whys")
    st.caption("Giao diện kiểu siêu thị: đi từng kệ từ trên xuống — mỗi kệ một việc, dễ nhìn, dễ làm lại.")
    return logger

