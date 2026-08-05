from __future__ import annotations

from core.news_macro_service import detect_story_catalysts


def test_detect_story_catalysts_failsoft_when_fin_unavailable(monkeypatch) -> None:
    import scrapers.portal as portal

    monkeypatch.setattr(
        portal,
        "fetch_financial_indicators",
        lambda *a, **k: {"symbol": "PNJ", "source": "unavailable_fast_mode"},
    )
    monkeypatch.setattr(portal, "_read_fin_disk_cache", lambda *_a, **_k: None)

    out = detect_story_catalysts("PNJ")
    assert out["symbol"] == "PNJ"
    assert "story_score" in out
    assert isinstance(out.get("dividend"), dict)
    assert isinstance(out.get("earnings_growth"), dict)
    # Macro/events vẫn có thể fill; không raise.
    assert out.get("source")


def test_fetch_financial_indicators_fast_mode_returns_empty_dict(monkeypatch) -> None:
    import scrapers.portal as portal

    monkeypatch.setattr(portal, "_cache_get", lambda *_a, **_k: None)
    monkeypatch.setattr(portal, "_read_fin_disk_cache", lambda *_a, **_k: None)
    monkeypatch.setattr(portal, "_bool_env", lambda name, default=False: default)
    monkeypatch.setattr(portal, "_financial_force_live_refresh", lambda **_k: False)
    monkeypatch.setattr(portal, "_strict_real_financial_data", lambda: False)

    out = portal.fetch_financial_indicators("ZZZZ", fast_mode=True)
    assert isinstance(out, dict)
    assert str(out.get("source") or "").startswith("unavailable_fast_mode")
