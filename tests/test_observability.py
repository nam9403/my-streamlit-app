from __future__ import annotations

import logging

from core.observability import configure_observability, correlation_id, ensure_correlation_id


def test_configure_observability_sets_correlation_id(monkeypatch) -> None:
    monkeypatch.setenv("II_LOG_JSON", "0")
    monkeypatch.setenv("II_LOG_LEVEL", "INFO")
    cid = configure_observability("test_component")
    assert cid
    assert correlation_id() == cid


def test_ensure_correlation_id_is_stable() -> None:
    cid1 = ensure_correlation_id("seed-1")
    cid2 = ensure_correlation_id("seed-2")
    assert cid1 == cid2
    assert isinstance(logging.getLogger().handlers, list)
