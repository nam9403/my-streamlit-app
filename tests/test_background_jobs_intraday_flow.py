from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

import core.background_jobs as bg
from core.intraday_flow_service import FlowSignal
from scrapers import intraday_vn


def _make_spike_ohlcv(n: int = 180, *, spike_at: int | None = None, mult: float = 12.0, seed: int = 7) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    base = 25_000.0
    rows = []
    last = base
    for i in range(n):
        drift = rng.normal(0.0, 250.0)
        open_ = max(1.0, last + rng.normal(0.0, 100.0))
        close_ = max(1.0, open_ + drift)
        high_ = max(open_, close_) + abs(rng.normal(150.0, 50.0))
        low_ = max(0.5, min(open_, close_) - abs(rng.normal(150.0, 50.0)))
        vol = 1_000_000.0 * (1.0 + abs(rng.normal(0.0, 0.15)))
        if spike_at is not None and i == spike_at:
            vol *= mult
            close_ = high_ - 1.0
        rows.append(
            {
                "date": pd.Timestamp("2024-01-01") + pd.Timedelta(days=i),
                "open": open_,
                "high": high_,
                "low": low_,
                "close": close_,
                "volume": vol,
            }
        )
        last = close_
    return pd.DataFrame(rows)


def _patch_env_and_paths(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(bg, "ROOT", tmp_path)
    monkeypatch.setenv("II_FLOW_MIN_INTENSITY", "5.0")
    monkeypatch.setenv("II_FLOW_MAX_SYMBOLS", "10")
    monkeypatch.setenv("II_FLOW_SESSIONS", "180")
    monkeypatch.setenv("II_FLOW_COOLDOWN_MINUTES", "120")
    monkeypatch.setenv("II_FLOW_GUARDIAN_STATE_PATH", str(tmp_path / "flow_state.json"))
    monkeypatch.setenv(
        "II_FLOW_GUARDIAN_HEALTH_PATH",
        str(tmp_path / "flow_health.json"),
    )


def test_run_intraday_flow_cycle_dispatches_alert(monkeypatch, tmp_path: Path) -> None:
    _patch_env_and_paths(monkeypatch, tmp_path)

    big = _make_spike_ohlcv(n=180, spike_at=179, mult=15.0, seed=21)
    flat = _make_spike_ohlcv(n=180, spike_at=None, seed=22)

    def ohlcv_loader(sym: str, sessions: int = 200) -> pd.DataFrame:
        return {"FPT": big, "VNM": flat}.get(sym, pd.DataFrame())

    sent_messages: list[dict[str, Any]] = []

    def fake_dispatch(text: str, *, telegram_bot_token: str, telegram_chat_id: str) -> dict[str, int]:
        sent_messages.append(
            {"text": text, "token": telegram_bot_token, "chat_id": telegram_chat_id}
        )
        return {"sent": 1, "failed": 0}

    def fake_load_secret(user_id: str, key: str, default: str) -> str:
        return {"telegram_bot_token": "tok_xyz", "telegram_chat_id": "chat_123"}.get(key, default)

    monkeypatch.setattr(bg, "fetch_ohlcv_history", ohlcv_loader)
    monkeypatch.setattr(bg, "dispatch_text_notifications", fake_dispatch)
    monkeypatch.setattr(bg, "load_secret", fake_load_secret)

    stat = bg._run_intraday_flow_cycle(["FPT", "VNM"])
    assert stat["checked"] == 2
    assert stat["alerts"] >= 1
    assert stat["notified"] >= 1
    assert stat["dispatch_enabled"] is True
    assert "FPT" in stat["symbols"]
    assert sent_messages, "expected dispatch to be called"
    assert "FPT" in sent_messages[0]["text"]

    health = (tmp_path / "flow_health.json")
    assert health.exists()


def test_run_intraday_flow_cycle_respects_cooldown(monkeypatch, tmp_path: Path) -> None:
    _patch_env_and_paths(monkeypatch, tmp_path)

    big = _make_spike_ohlcv(n=180, spike_at=179, mult=15.0, seed=31)

    def ohlcv_loader(sym: str, sessions: int = 200) -> pd.DataFrame:
        return big

    call_count = {"dispatch": 0}

    def fake_dispatch(text: str, *, telegram_bot_token: str, telegram_chat_id: str) -> dict[str, int]:
        call_count["dispatch"] += 1
        return {"sent": 1, "failed": 0}

    def fake_load_secret(user_id: str, key: str, default: str) -> str:
        return {"telegram_bot_token": "tok", "telegram_chat_id": "chat"}.get(key, default)

    monkeypatch.setattr(bg, "fetch_ohlcv_history", ohlcv_loader)
    monkeypatch.setattr(bg, "dispatch_text_notifications", fake_dispatch)
    monkeypatch.setattr(bg, "load_secret", fake_load_secret)

    first = bg._run_intraday_flow_cycle(["FPT"])
    assert first["notified"] == 1
    second = bg._run_intraday_flow_cycle(["FPT"])
    assert second["notified"] == 0
    assert second["suppressed"] >= 1
    assert call_count["dispatch"] == 1


def test_run_intraday_flow_cycle_no_secret_disables_dispatch(monkeypatch, tmp_path: Path) -> None:
    _patch_env_and_paths(monkeypatch, tmp_path)

    big = _make_spike_ohlcv(n=180, spike_at=179, mult=15.0, seed=41)

    def ohlcv_loader(sym: str, sessions: int = 200) -> pd.DataFrame:
        return big

    monkeypatch.setattr(bg, "fetch_ohlcv_history", ohlcv_loader)
    monkeypatch.setattr(bg, "dispatch_text_notifications", lambda *a, **k: {"sent": 0, "failed": 0})
    monkeypatch.setattr(bg, "load_secret", lambda *a, **k: "")

    stat = bg._run_intraday_flow_cycle(["FPT"])
    assert stat["dispatch_enabled"] is False
    assert stat["notified"] == 0


def test_run_intraday_flow_cycle_disabled_by_env(monkeypatch, tmp_path: Path) -> None:
    _patch_env_and_paths(monkeypatch, tmp_path)
    monkeypatch.setenv("II_FLOW_MAX_SYMBOLS", "0")
    stat = bg._run_intraday_flow_cycle(["FPT", "HPG"])
    assert stat == {
        "checked": 0,
        "alerts": 0,
        "notified": 0,
        "failures": 0,
        "suppressed": 0,
        "skipped_no_data": 0,
    }


def test_run_intraday_flow_cycle_handles_ohlcv_error(monkeypatch, tmp_path: Path) -> None:
    _patch_env_and_paths(monkeypatch, tmp_path)

    def bad_loader(sym: str, sessions: int = 200):
        raise RuntimeError("network down")

    monkeypatch.setattr(bg, "fetch_ohlcv_history", bad_loader)
    monkeypatch.setattr(bg, "dispatch_text_notifications", lambda *a, **k: {"sent": 0, "failed": 0})
    monkeypatch.setattr(bg, "load_secret", lambda *a, **k: "")

    stat = bg._run_intraday_flow_cycle(["FPT"])
    assert stat["failures"] >= 1
    assert stat["notified"] == 0


def test_run_intraday_flow_cycle_skips_outside_market_hours(monkeypatch, tmp_path: Path) -> None:
    _patch_env_and_paths(monkeypatch, tmp_path)
    monkeypatch.setenv("II_FLOW_RESOLUTION", "5")
    monkeypatch.setenv("II_FLOW_SKIP_OUTSIDE_HOURS", "1")
    monkeypatch.setattr(bg, "is_vn_market_open", lambda *a, **k: False)

    def _should_not_run(*a, **k):
        raise AssertionError("fetch_intraday_ohlcv should not be called outside hours")

    monkeypatch.setattr(bg, "fetch_intraday_ohlcv", _should_not_run)
    stat = bg._run_intraday_flow_cycle(["FPT", "HPG"])
    assert stat["checked"] == 0
    assert stat["skipped_reason"] == "market_closed"
    assert stat["resolution"] == "5"


def test_run_intraday_flow_cycle_persists_signals_to_journal(monkeypatch, tmp_path: Path) -> None:
    _patch_env_and_paths(monkeypatch, tmp_path)
    journal_dir = tmp_path / "journal"
    monkeypatch.setenv("II_FLOW_JOURNAL_DIR", str(journal_dir))

    spike = _make_spike_ohlcv(n=180, spike_at=179, mult=20.0, seed=61)

    def ohlcv_loader(sym: str, sessions: int = 200) -> pd.DataFrame:
        return spike

    monkeypatch.setattr(bg, "fetch_ohlcv_history", ohlcv_loader)
    monkeypatch.setattr(bg, "dispatch_text_notifications", lambda *a, **k: {"sent": 1, "failed": 0})
    monkeypatch.setattr(bg, "load_secret", lambda *a, **k: "tok_xyz")

    stat = bg._run_intraday_flow_cycle(["FPT"])
    assert stat["checked"] == 1
    journal_files = list(journal_dir.glob("flow_signals_*.jsonl"))
    assert len(journal_files) >= 1
    content = journal_files[0].read_text(encoding="utf-8").strip().splitlines()
    assert content
    import json as _json

    row = _json.loads(content[-1])
    assert row["symbol"] == "FPT"
    assert row["phase"] == "background_cycle"
    assert row["resolution"] == "D"


def test_run_intraday_flow_cycle_journal_failure_does_not_break_cycle(
    monkeypatch, tmp_path: Path
) -> None:
    _patch_env_and_paths(monkeypatch, tmp_path)
    monkeypatch.setenv("II_FLOW_JOURNAL_DIR", str(tmp_path / "journal"))

    spike = _make_spike_ohlcv(n=180, spike_at=179, mult=20.0, seed=62)
    monkeypatch.setattr(bg, "fetch_ohlcv_history", lambda *a, **k: spike)
    monkeypatch.setattr(bg, "dispatch_text_notifications", lambda *a, **k: {"sent": 0, "failed": 0})
    monkeypatch.setattr(bg, "load_secret", lambda *a, **k: "")

    def boom(*a, **k):
        raise OSError("disk full")

    monkeypatch.setattr(bg, "append_flow_signals_batch", boom)
    stat = bg._run_intraday_flow_cycle(["FPT"])
    assert stat["checked"] == 1


def test_run_intraday_flow_cycle_uses_intraday_scraper_when_resolution_intraday(
    monkeypatch, tmp_path: Path
) -> None:
    _patch_env_and_paths(monkeypatch, tmp_path)
    monkeypatch.setenv("II_FLOW_RESOLUTION", "5")
    monkeypatch.setenv("II_FLOW_SKIP_OUTSIDE_HOURS", "0")

    spike = _make_spike_ohlcv(n=180, spike_at=179, mult=18.0, seed=51)

    calls: dict[str, Any] = {"daily": 0, "intraday": 0}

    def fake_intraday(symbol, *, resolution, lookback_bars, primary_source):
        calls["intraday"] += 1
        assert resolution == "5"
        assert primary_source == "vndirect"
        return spike

    def fake_daily(*a, **k):
        calls["daily"] += 1
        return spike

    monkeypatch.setattr(bg, "fetch_intraday_ohlcv", fake_intraday)
    monkeypatch.setattr(bg, "fetch_ohlcv_history", fake_daily)
    monkeypatch.setattr(bg, "is_vn_market_open", lambda *a, **k: True)
    monkeypatch.setattr(bg, "dispatch_text_notifications", lambda *a, **k: {"sent": 1, "failed": 0})
    monkeypatch.setattr(
        bg,
        "load_secret",
        lambda *a, **k: "tok" if "token" in a or any("token" in str(x) for x in a) else "chat",
    )

    stat = bg._run_intraday_flow_cycle(["FPT"])
    assert calls["intraday"] == 1
    assert calls["daily"] == 0
    assert stat["resolution"] == "5"
    assert stat["primary_source"] == "vndirect"


def test_run_intraday_flow_cycle_handles_intraday_error_gracefully(
    monkeypatch, tmp_path: Path
) -> None:
    _patch_env_and_paths(monkeypatch, tmp_path)
    monkeypatch.setenv("II_FLOW_RESOLUTION", "5")
    monkeypatch.setenv("II_FLOW_SKIP_OUTSIDE_HOURS", "0")

    def bad_intraday(*a, **k):
        raise intraday_vn.IntradayDataError("no data")

    monkeypatch.setattr(bg, "fetch_intraday_ohlcv", bad_intraday)
    monkeypatch.setattr(bg, "is_vn_market_open", lambda *a, **k: True)
    monkeypatch.setattr(bg, "dispatch_text_notifications", lambda *a, **k: {"sent": 0, "failed": 0})
    monkeypatch.setattr(bg, "load_secret", lambda *a, **k: "")

    stat = bg._run_intraday_flow_cycle(["FPT", "HPG"])
    assert stat["skipped_no_data"] == 2
    assert stat["notified"] == 0
    assert stat["failures"] == 0


def test_flow_min_intensity_env_priority_uses_explicit_env(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("II_FLOW_MIN_INTENSITY", "7.5")
    monkeypatch.setenv("II_FLOW_USE_BACKTEST_RECOMMENDATION", "1")
    rec_path = tmp_path / "rec.json"
    import json as _json
    from datetime import datetime, timezone

    rec_path.write_text(
        _json.dumps(
            {
                "schema_version": 1,
                "generated_at_utc": datetime.now(timezone.utc).isoformat(),
                "horizon_days": 5,
                "recommended_min_intensity": 8.5,
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("II_FLOW_RECOMMENDATION_PATH", str(rec_path))
    value = bg._flow_min_intensity_env()
    snap = bg._flow_recommendation_source_snapshot()
    assert value == 7.5
    assert snap["source"] == "env"


def test_flow_min_intensity_env_uses_backtest_recommendation_when_enabled(
    monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.delenv("II_FLOW_MIN_INTENSITY", raising=False)
    monkeypatch.setenv("II_FLOW_USE_BACKTEST_RECOMMENDATION", "1")
    rec_path = tmp_path / "rec.json"
    import json as _json
    from datetime import datetime, timezone

    rec_path.write_text(
        _json.dumps(
            {
                "schema_version": 1,
                "generated_at_utc": datetime.now(timezone.utc).isoformat(),
                "horizon_days": 5,
                "recommended_min_intensity": 8.5,
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("II_FLOW_RECOMMENDATION_PATH", str(rec_path))
    value = bg._flow_min_intensity_env()
    snap = bg._flow_recommendation_source_snapshot()
    assert value == 8.5
    assert snap["source"] == "backtest_recommendation"
    assert snap["path"] == str(rec_path)


def test_flow_min_intensity_env_falls_back_to_default_for_stale_artifact(
    monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.delenv("II_FLOW_MIN_INTENSITY", raising=False)
    monkeypatch.setenv("II_FLOW_USE_BACKTEST_RECOMMENDATION", "1")
    rec_path = tmp_path / "rec.json"
    import json as _json
    from datetime import datetime, timedelta, timezone

    stale_ts = (datetime.now(timezone.utc) - timedelta(days=90)).isoformat()
    rec_path.write_text(
        _json.dumps(
            {
                "schema_version": 1,
                "generated_at_utc": stale_ts,
                "horizon_days": 5,
                "recommended_min_intensity": 8.5,
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("II_FLOW_RECOMMENDATION_PATH", str(rec_path))
    monkeypatch.setenv("II_FLOW_RECOMMENDATION_TTL_DAYS", "14")
    value = bg._flow_min_intensity_env()
    snap = bg._flow_recommendation_source_snapshot()
    assert value == 6.0
    assert snap["source"] == "default"


def test_flow_min_intensity_env_ignores_recommendation_when_flag_off(
    monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.delenv("II_FLOW_MIN_INTENSITY", raising=False)
    monkeypatch.setenv("II_FLOW_USE_BACKTEST_RECOMMENDATION", "0")
    rec_path = tmp_path / "rec.json"
    import json as _json
    from datetime import datetime, timezone

    rec_path.write_text(
        _json.dumps(
            {
                "schema_version": 1,
                "generated_at_utc": datetime.now(timezone.utc).isoformat(),
                "horizon_days": 5,
                "recommended_min_intensity": 8.5,
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("II_FLOW_RECOMMENDATION_PATH", str(rec_path))
    value = bg._flow_min_intensity_env()
    snap = bg._flow_recommendation_source_snapshot()
    assert value == 6.0
    assert snap["source"] == "default"


def test_flow_resolution_env_parser() -> None:
    import os

    backup = os.environ.get("II_FLOW_RESOLUTION")
    try:
        os.environ["II_FLOW_RESOLUTION"] = "D"
        assert bg._flow_resolution_env() == "D"
        os.environ["II_FLOW_RESOLUTION"] = "5"
        assert bg._flow_resolution_env() == "5"
        os.environ["II_FLOW_RESOLUTION"] = "999"
        assert bg._flow_resolution_env() == "D"
        os.environ["II_FLOW_RESOLUTION"] = "1d"
        assert bg._flow_resolution_env() == "D"
    finally:
        if backup is None:
            os.environ.pop("II_FLOW_RESOLUTION", None)
        else:
            os.environ["II_FLOW_RESOLUTION"] = backup


def test_intraday_flow_signal_dataclass_smoke() -> None:
    sig = FlowSignal(
        symbol="HPG",
        timeframe="1D",
        is_big_boy=True,
        aggregated_volume=5e6,
        delta_status="bullish",
        intensity_score=7.0,
        z_volume=2.4,
        pseudo_delta=0.4,
        cumulative_delta=1e6,
        anomaly_score=-0.1,
        last_close=27000.0,
        last_volume=5e6,
        context_note="ngành: steel_materials",
    )
    assert sig.to_dict()["delta_status"] == "bullish"
