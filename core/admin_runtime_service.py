from __future__ import annotations

from typing import Any, Callable

from core import analytics_service, notification_queue_repository as notif_queue_repo


def get_admin_kpi_enriched(
    *,
    conn_factory: Callable[[], Any],
    days: int = 30,
    fail_reason_limit: int = 10,
    retry_tier_limit: int = 20,
) -> dict[str, Any]:
    base = analytics_service.get_admin_kpi(conn_factory=conn_factory, days=days)
    base["notification_observability"] = {
        "fail_reasons": notif_queue_repo.get_notification_fail_reason_summary(
            conn_factory=conn_factory,
            days=days,
            limit=fail_reason_limit,
        ),
        "retry_tiers": notif_queue_repo.get_notification_retry_tier_summary(
            conn_factory=conn_factory,
            days=days,
            limit=retry_tier_limit,
        ),
        "runtime_health": notif_queue_repo.get_notification_runtime_health(
            conn_factory=conn_factory,
        ),
    }
    return base

