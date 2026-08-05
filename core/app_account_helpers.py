"""
Account and session helper utilities for app flow.
"""

from __future__ import annotations


def is_auth_ready(*, has_auth_user: bool, auth_ok_in_session: bool) -> bool:
    """Legacy boolean helper; guest accounts are never considered authenticated."""
    return bool(has_auth_user and auth_ok_in_session)


def resolve_plan_index(persisted_plan: str, options: list[str]) -> int:
    normalized = [item.lower() for item in options]
    plan = str(persisted_plan or "").strip().lower()
    if plan not in normalized:
        return 0
    return max(0, normalized.index(plan))


def normalize_notify_channels(notify_cfg: object) -> dict[str, object]:
    return {
        "tg_bot": str(getattr(notify_cfg, "tg_bot", "") or ""),
        "tg_chat": str(getattr(notify_cfg, "tg_chat", "") or ""),
        "webhook_url": str(getattr(notify_cfg, "webhook_url", "") or ""),
        "email_to": str(getattr(notify_cfg, "email_to", "") or ""),
        "smtp_host": str(getattr(notify_cfg, "smtp_host", "") or ""),
        "smtp_port": int(getattr(notify_cfg, "smtp_port", 587) or 587),
        "smtp_user": str(getattr(notify_cfg, "smtp_user", "") or ""),
        "smtp_password": str(getattr(notify_cfg, "smtp_password", "") or ""),
        "smtp_from": str(getattr(notify_cfg, "smtp_from", "") or ""),
    }

