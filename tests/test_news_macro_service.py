from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from core import news_macro_service as nms


def test_get_macro_snapshot_corrupt_or_missing_returns_safe_default(tmp_path: Path, monkeypatch) -> None:
    path = tmp_path / "macro_snapshot.json"
    path.write_text("{not-json", encoding="utf-8")
    monkeypatch.setenv("II_MACRO_SNAPSHOT_PATH", str(path))
    monkeypatch.setenv("II_MACRO_SNAPSHOT_TTL_SEC", "7200")
    monkeypatch.setattr(nms, "_try_refresh_macro_live", lambda prev=None: nms.default_macro_snapshot())

    snap = nms.get_macro_snapshot()
    assert isinstance(snap, dict)
    assert float(snap.get("market_bias") or 0.0) == 0.0
    assert snap.get("source") == "default"

    # Missing file
    missing = tmp_path / "missing_macro.json"
    monkeypatch.setenv("II_MACRO_SNAPSHOT_PATH", str(missing))
    snap2 = nms.get_macro_snapshot()
    assert float(snap2.get("market_bias") or 0.0) == 0.0


def test_score_catalyst_clamped_and_fail_soft_on_bad_ticker(monkeypatch) -> None:
    monkeypatch.setattr(nms, "get_macro_snapshot", lambda: {"market_bias": 99.0, "source": "t"})
    monkeypatch.setattr(
        nms,
        "get_micro_bundle",
        lambda *_a, **_k: {
            "symbol": "FPT",
            "news": [{"title": "Cổ tức và mua ròng khối ngoại"}],
            "source": "test",
            "events_hint": [],
        },
    )
    monkeypatch.setattr(nms, "_smart_money_component", lambda *_a, **_k: 0.9)

    score = nms.score_catalyst("FPT", allow_network=False)
    assert -1.0 <= score <= 1.0

    assert nms.score_catalyst("") == 0.0
    assert nms.score_catalyst("   ") == 0.0


def test_apply_news_macro_boost_disabled_returns_same_frame(monkeypatch) -> None:
    monkeypatch.setenv("II_SCANNER_NEWS_MACRO_BOOST", "0")
    df = pd.DataFrame(
        {
            "Mã": ["FPT", "HPG"],
            "Khuyến nghị": ["BUY", "WATCH"],
            "__score": [70.0, 40.0],
            "MOS%": [10.0, 5.0],
            "Expected Return %": [12.0, 6.0],
        }
    )
    out = nms.apply_news_macro_boost(df)
    assert out is df or out.equals(df)
    assert "News/Macro Bias" not in out.columns


def test_apply_news_macro_boost_enabled_adds_bias_and_fail_soft(monkeypatch) -> None:
    monkeypatch.setenv("II_SCANNER_NEWS_MACRO_BOOST", "1")
    monkeypatch.setenv("II_NEWS_MACRO_SCORE_WEIGHT", "1.0")
    monkeypatch.setattr(nms, "score_catalyst", lambda ticker, **_k: 0.5 if ticker == "FPT" else -0.25)
    monkeypatch.setattr(nms, "get_macro_snapshot", lambda: {"market_bias": 0.0, "source": "t"})

    df = pd.DataFrame(
        {
            "Mã": ["FPT", "HPG"],
            "__score": [70.0, 40.0],
            "MOS%": [10.0, 5.0],
            "Expected Return %": [12.0, 6.0],
        }
    )
    out = nms.apply_news_macro_boost(df)
    assert "News/Macro Bias" in out.columns
    assert float(out.loc[0, "News/Macro Bias"]) == 0.5
    assert float(out.loc[0, "__score"]) == 75.0  # 70 + 0.5*10
    assert float(out.loc[1, "__score"]) == 37.5  # 40 + (-0.25)*10

    # Fail-soft: broken scorer must not raise
    def _boom(*_a, **_k):
        raise RuntimeError("boom")

    monkeypatch.setattr(nms, "score_catalyst", _boom)
    out2 = nms.apply_news_macro_boost(df)
    assert isinstance(out2, pd.DataFrame)


def test_null_analyzer_returns_zero() -> None:
    z = nms.NullNewsAnalyzer().analyze(["tin xấu", "tin tốt"])
    assert float(z["score"]) == 0.0
    assert z["label"] == "neutral"


def test_macro_snapshot_valid_file_respected(tmp_path: Path, monkeypatch) -> None:
    path = tmp_path / "macro_ok.json"
    payload = {
        "saved_at": nms._utc_now_iso(),
        "ttl_sec": 7200,
        "market_bias": 0.2,
        "source": "unit",
    }
    path.write_text(json.dumps(payload), encoding="utf-8")
    monkeypatch.setenv("II_MACRO_SNAPSHOT_PATH", str(path))
    snap = nms.get_macro_snapshot()
    assert float(snap["market_bias"]) == 0.2
    assert snap["source"] == "unit"
