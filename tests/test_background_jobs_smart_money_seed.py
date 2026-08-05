from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any

import core.background_jobs as bg


def _patch_paths(monkeypatch, tmp_path: Path) -> tuple[Path, Path]:
    state = tmp_path / "runtime" / "smart_money_seed_last_run.txt"
    out = tmp_path / "smart_money_events.json"
    monkeypatch.setenv("II_SMART_MONEY_SEED_STATE_PATH", str(state))
    monkeypatch.setenv("II_SMART_MONEY_SEED_OUTPUT_PATH", str(out))
    monkeypatch.setenv("II_SMART_MONEY_SEED_ENABLED", "1")
    monkeypatch.setenv("II_SMART_MONEY_SEED_NEWS_LIMIT", "5")
    monkeypatch.setenv("II_SMART_MONEY_SEED_MAX_PER_SYMBOL", "50")
    return state, out


def _news_for(symbol: str, limit: int = 5) -> list[dict[str, Any]]:
    if symbol == "FPT":
        return [
            {"title": "Khối ngoại mua ròng 120 tỷ cổ phiếu FPT", "source": "cafef", "url": "u1"},
            {"title": "Cổ đông lớn đăng ký bán 35 tỷ cổ phiếu FPT", "source": "vietstock", "url": "u2"},
        ]
    if symbol == "VNM":
        return [
            {"title": "Khối ngoại mua ròng 80 tỷ cổ phiếu VNM", "source": "cafef", "url": "u3"},
        ]
    return []


def test_smart_money_seed_cycle_ingests_and_writes_json(monkeypatch, tmp_path: Path) -> None:
    state, out = _patch_paths(monkeypatch, tmp_path)

    def loader(sym: str, *, limit: int) -> list[dict[str, Any]]:
        return _news_for(sym, limit)

    stat = bg._run_smart_money_seed_cycle(["FPT", "VNM"], news_loader=loader)
    assert stat["checked"] == 2
    assert stat["ingested"] >= 3
    assert stat["stored"] >= 3
    assert state.exists()
    assert out.exists()
    data = json.loads(out.read_text(encoding="utf-8"))
    assert isinstance(data, list)
    fpt_rows = [r for r in data if r.get("symbol") == "FPT"]
    assert len(fpt_rows) >= 2


def test_smart_money_seed_cycle_skips_when_already_run_today(monkeypatch, tmp_path: Path) -> None:
    state, out = _patch_paths(monkeypatch, tmp_path)

    def loader(sym: str, *, limit: int) -> list[dict[str, Any]]:
        return _news_for(sym, limit)

    first = bg._run_smart_money_seed_cycle(["FPT"], news_loader=loader)
    assert first["checked"] == 1

    def loader_should_not_call(sym: str, *, limit: int) -> list[dict[str, Any]]:
        raise AssertionError("Should not be called on same-day re-run")

    second = bg._run_smart_money_seed_cycle(["FPT"], news_loader=loader_should_not_call)
    assert second["skipped_reason"] == "already_run_today"


def test_smart_money_seed_cycle_disabled_via_env(monkeypatch, tmp_path: Path) -> None:
    _patch_paths(monkeypatch, tmp_path)
    monkeypatch.setenv("II_SMART_MONEY_SEED_ENABLED", "0")

    def loader_should_not_call(sym: str, *, limit: int) -> list[dict[str, Any]]:
        raise AssertionError("Should not be called when disabled")

    stat = bg._run_smart_money_seed_cycle(["FPT"], news_loader=loader_should_not_call)
    assert stat["skipped_reason"] == "disabled"


def test_smart_money_seed_cycle_handles_news_loader_error(monkeypatch, tmp_path: Path) -> None:
    _patch_paths(monkeypatch, tmp_path)

    def bad_loader(sym: str, *, limit: int) -> list[dict[str, Any]]:
        raise RuntimeError("network blip")

    stat = bg._run_smart_money_seed_cycle(["FPT", "HPG"], news_loader=bad_loader)
    assert stat["failures"] >= 2
    assert stat["ingested"] == 0


def test_smart_money_seed_cycle_merges_with_existing_events(monkeypatch, tmp_path: Path) -> None:
    state, out = _patch_paths(monkeypatch, tmp_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    seed = [
        {
            "symbol": "FPT",
            "event_date": "2025-12-31",
            "actor_type": "insider",
            "actor_name": "Ong A",
            "side": "buy",
            "net_value_vnd": 50_000_000_000.0,
            "confidence": 0.8,
            "source": "exchange_disclosure",
            "headline": "Insider buy",
            "url": "old",
            "synced_at_utc": "2025-12-31T00:00:00+00:00",
        }
    ]
    out.write_text(json.dumps(seed, ensure_ascii=False), encoding="utf-8")

    def loader(sym: str, *, limit: int) -> list[dict[str, Any]]:
        return _news_for(sym, limit)

    stat = bg._run_smart_money_seed_cycle(["FPT"], news_loader=loader)
    data = json.loads(out.read_text(encoding="utf-8"))
    assert any(r.get("headline") == "Insider buy" for r in data)
    assert any("Khối ngoại" in str(r.get("headline") or "") for r in data)
    assert stat["stored"] >= 3


def test_smart_money_seed_due_returns_true_for_new_state_file(tmp_path: Path) -> None:
    state = tmp_path / "smart_money_seed_last_run.txt"
    assert bg._smart_money_seed_due(state, today=date(2026, 5, 11)) is True


def test_smart_money_seed_due_returns_false_for_same_day(tmp_path: Path) -> None:
    state = tmp_path / "smart_money_seed_last_run.txt"
    state.write_text("2026-05-11", encoding="utf-8")
    assert bg._smart_money_seed_due(state, today=date(2026, 5, 11)) is False


def test_smart_money_seed_due_returns_true_for_different_day(tmp_path: Path) -> None:
    state = tmp_path / "smart_money_seed_last_run.txt"
    state.write_text("2026-05-10", encoding="utf-8")
    assert bg._smart_money_seed_due(state, today=date(2026, 5, 11)) is True


def test_run_background_cycle_includes_smart_money_seed_block(monkeypatch, tmp_path: Path) -> None:
    _patch_paths(monkeypatch, tmp_path)

    monkeypatch.setattr(bg, "list_universe_symbols", lambda **k: [])
    monkeypatch.setattr(bg, "prefetch_symbols", lambda *a, **k: {"ok": 0, "fail": 0, "total": 0})
    monkeypatch.setattr(bg, "_run_super_stock_cycle", lambda *a, **k: {"checked": 0, "passed": 0, "notified": 0})
    monkeypatch.setattr(bg, "_run_intraday_flow_cycle", lambda *a, **k: {"checked": 0, "alerts": 0, "notified": 0})
    monkeypatch.setattr(bg, "process_notification_queue", lambda max_jobs: {"sent": 0, "failed": 0, "retried": 0, "processed": 0})
    monkeypatch.setattr(bg, "fetch_latest_news", lambda sym, limit=20: _news_for(sym, limit))

    result = bg.run_background_cycle(universe_limit=0, watchlist=["FPT"])
    assert "smart_money_seed" in result
    assert result["smart_money_seed"]["checked"] >= 1
