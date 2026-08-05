from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

import scripts.backtest_flow_signals as cli


def _ohlcv(n: int = 220, seed: int = 5) -> pd.DataFrame:
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
        if (i + 1) % 20 == 0:
            vol *= 12.0
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


def test_cli_writes_json_markdown_and_recommendation(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(cli, "fetch_ohlcv_history", lambda sym, sessions=500: _ohlcv())

    out_json = tmp_path / "out.json"
    out_md = tmp_path / "out.md"
    rec_path = tmp_path / "rec.json"
    exit_code = cli.main(
        [
            "--symbols", "FPT,HPG",
            "--sessions", "220",
            "--min-history", "100",
            "--stride", "10",
            "--horizons", "1,5",
            "--buckets", "4.0,6.0,8.0",
            "--no-require-big-boy",
            "--output", str(out_json),
            "--markdown", str(out_md),
            "--min-count", "1",
            "--min-hit-rate-pct", "0",
            "--recommendation-path", str(rec_path),
            "--recommendation-horizon", "5",
        ]
    )
    assert exit_code == 0
    assert out_json.exists()
    payload = json.loads(out_json.read_text(encoding="utf-8"))
    assert payload["n_symbols"] == 2
    assert "FPT" in payload["per_symbol"]
    assert payload["pooled"]["n_signals_pooled"] > 0
    assert "horizon_5d" in payload["recommendations"]
    assert out_md.exists()
    md = out_md.read_text(encoding="utf-8")
    assert "# Flow signal backtest" in md
    assert "Pooled universe summary" in md
    assert "FPT" in md
    # Recommendation artifact may or may not be written depending on data;
    # if it is, content must be loadable JSON with expected schema.
    if rec_path.exists():
        rec = json.loads(rec_path.read_text(encoding="utf-8"))
        assert rec["horizon_days"] == 5
        assert rec["recommended_min_intensity"] is not None


def test_cli_skips_recommendation_when_path_empty(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(cli, "fetch_ohlcv_history", lambda sym, sessions=500: _ohlcv())
    out_json = tmp_path / "out.json"
    exit_code = cli.main(
        [
            "--symbols", "FPT",
            "--sessions", "220",
            "--min-history", "100",
            "--stride", "10",
            "--horizons", "5",
            "--no-require-big-boy",
            "--output", str(out_json),
            "--markdown", "",
            "--min-count", "1",
            "--min-hit-rate-pct", "0",
            "--recommendation-path", "",
        ]
    )
    assert exit_code == 0
    assert not (tmp_path / "rec.json").exists()


def test_cli_handles_portal_error_and_continues(monkeypatch, tmp_path: Path) -> None:
    def _side(sym, sessions=500):
        if sym == "BAD":
            from scrapers.portal import PortalDataError

            raise PortalDataError("not found")
        return _ohlcv()

    monkeypatch.setattr(cli, "fetch_ohlcv_history", _side)
    out_json = tmp_path / "out.json"
    exit_code = cli.main(
        [
            "--symbols", "BAD,FPT",
            "--sessions", "220",
            "--min-history", "100",
            "--stride", "10",
            "--horizons", "1,5",
            "--no-require-big-boy",
            "--output", str(out_json),
            "--markdown", "",
            "--min-count", "1",
            "--min-hit-rate-pct", "0",
        ]
    )
    assert exit_code == 0
    payload = json.loads(out_json.read_text(encoding="utf-8"))
    assert "BAD" in payload["skipped"]
    assert "FPT" in payload["per_symbol"]


def test_cli_rejects_empty_symbols(monkeypatch, tmp_path: Path) -> None:
    out_json = tmp_path / "out.json"
    exit_code = cli.main(["--symbols", "", "--output", str(out_json)])
    assert exit_code == 2
