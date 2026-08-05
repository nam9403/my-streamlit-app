from __future__ import annotations


def test_get_kpi_dashboard_emits_timing(monkeypatch) -> None:
    import core.product_layer as pl

    metrics: list[dict] = []
    monkeypatch.setattr(pl, "log_timing", lambda metric, duration_ms, **fields: metrics.append({"metric": metric, **fields}))
    monkeypatch.setattr(
        pl.analytics_service,
        "get_kpi_dashboard",
        lambda **kwargs: {"events_30d": 7, "by_event": {}},
    )
    monkeypatch.setattr(pl, "get_user_plan", lambda uid: "free")

    out = pl.get_kpi_dashboard("u1", days=30)
    assert int(out.get("events_30d") or 0) == 7
    assert any(m.get("metric") == "product_layer.get_kpi_dashboard" for m in metrics)


def test_get_notification_queue_diagnostics_emits_timing(monkeypatch) -> None:
    import core.product_layer as pl

    metrics: list[dict] = []
    monkeypatch.setattr(pl, "log_timing", lambda metric, duration_ms, **fields: metrics.append({"metric": metric, **fields}))
    monkeypatch.setattr(
        pl.notif_queue_repo,
        "get_notification_queue_diagnostics",
        lambda **kwargs: [{"id": 1}, {"id": 2}],
    )

    out = pl.get_notification_queue_diagnostics(limit=20)
    assert len(out) == 2
    assert any(m.get("metric") == "product_layer.get_notification_queue_diagnostics" for m in metrics)


def test_retry_failed_notifications_emits_timing(monkeypatch) -> None:
    import core.product_layer as pl

    metrics: list[dict] = []
    monkeypatch.setattr(pl, "log_timing", lambda metric, duration_ms, **fields: metrics.append({"metric": metric, **fields}))
    monkeypatch.setattr(pl.notif_queue_repo, "retry_failed_notifications", lambda **kwargs: 3)

    out = pl.retry_failed_notifications(max_rows=20)
    assert int(out) == 3
    assert any(m.get("metric") == "product_layer.retry_failed_notifications" for m in metrics)

