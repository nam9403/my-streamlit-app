from __future__ import annotations


def test_kpi_and_cohort_dashboard_refactor(tmp_path, monkeypatch) -> None:
    import core.product_layer as pl

    monkeypatch.setattr(pl, "DB_PATH", tmp_path / "app_state.db")
    monkeypatch.setattr(pl, "SECRETS_PATH", tmp_path / "secrets.json")
    monkeypatch.setattr(pl, "APP_SECRET_PATH", tmp_path / ".app_secret.key")
    pl._init_db()

    uid = "analytics_user"
    pl.log_event(uid, "analysis_completed", {"ticker": "FPT"})
    pl.log_event(uid, "alert_created", {})
    kpi = pl.get_kpi_dashboard(uid, days=30)
    assert int(kpi.get("events_total") or 0) >= 2
    assert int((kpi.get("by_event") or {}).get("analysis_completed") or 0) >= 1

    cohort = pl.get_cohort_kpi(uid)
    assert int(cohort.get("analysis_30") or 0) >= 1
    assert int(cohort.get("alerts_created_30") or 0) >= 1


def test_upgrade_funnel_and_variant_selection_refactor(tmp_path, monkeypatch) -> None:
    import core.product_layer as pl

    monkeypatch.setattr(pl, "DB_PATH", tmp_path / "app_state.db")
    monkeypatch.setattr(pl, "SECRETS_PATH", tmp_path / "secrets.json")
    monkeypatch.setattr(pl, "APP_SECRET_PATH", tmp_path / ".app_secret.key")
    pl._init_db()

    pl.log_event("u1", "upgrade_prompt_view", {"variant": "high_engagement"})
    pl.log_event("u1", "upgrade_cta_click", {"variant": "high_engagement"})
    pl.log_event("u1", "upgrade_success", {"variant": "high_engagement"})

    funnel = pl.get_upgrade_funnel(days=30)
    assert any(str(r.get("variant")) == "high_engagement" for r in funnel)
    pick = pl.select_upgrade_variant_auto(days=30)
    assert str(pick.get("variant") or "")
