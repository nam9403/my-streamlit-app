"""
Investment Intelligence Dashboard (VN stocks).
Run: streamlit run app.py

Composition root: env bootstrap → Sentry/observability → DB init → UI shell.

Chat-first UI (Gemini-style + Decision Cards):
  - Implemented in ``core/app_chat_interface.py``, wired by ``core/ui_shell.py``.
  - Default ON via env ``II_CHAT_FIRST_UI=1`` (set ``0`` to prefer classic aisles).
  - Sidebar toggle: "Chat-first UI"; optional "Hiện thêm giao diện cổ điển".
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

# Nạp .env + kiểm tra strict env (prod) TRƯỚC khi import core/* — nhiều module đọc os.environ lúc import.
import env_bootstrap

env_bootstrap.init_app_environment()

# Sentry + logging càng sớm càng tốt (trước UI shell / DB).
from core.observability import configure_observability

configure_observability("streamlit_app")

from core.app_bootstrap import bootstrap_app_ui
from core.product_layer import initialize_database_connection
from core.ui_services import compute_top5_for_profile, universe_symbol_count
from core.ui_shell import VIEW_TAB_AI, VIEW_TAB_FIN, VIEW_TAB_WORK, render_app

# Re-exports kept for smoke/tests and external scripts that import from app.
__all__ = [
    "main",
    "universe_symbol_count",
    "compute_top5_for_profile",
    "VIEW_TAB_WORK",
    "VIEW_TAB_AI",
    "VIEW_TAB_FIN",
]


def main() -> None:
    try:
        initialize_database_connection()
    except Exception:
        logging.getLogger(__name__).exception("database_bootstrap_failed")
        raise
    bootstrap_app_ui()
    # UI composition (chat-first or classic aisles) lives in core.ui_shell.render_app
    render_app()


if __name__ == "__main__":
    main()
