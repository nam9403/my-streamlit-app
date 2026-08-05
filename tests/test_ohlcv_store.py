import pandas as pd

from core import ohlcv_store as store


def test_ohlcv_store_upsert_and_load(monkeypatch, tmp_path):
    p = tmp_path / "ohlcv_store_test.db"
    monkeypatch.setattr(store, "DB_PATH", p)
    df = pd.DataFrame(
        [
            {"date": "2026-01-01", "open": 10, "high": 11, "low": 9, "close": 10.5, "volume": 1000},
            {"date": "2026-01-02", "open": 10.5, "high": 11.2, "low": 10.2, "close": 11.0, "volume": 1200},
        ]
    )
    n = store.upsert_ohlcv("FPT", df, source="test")
    assert n == 2
    out = store.load_recent_ohlcv("FPT", sessions=50)
    assert len(out) == 2
    assert store.last_ohlcv_date("FPT") == "2026-01-02"


def test_ohlcv_store_caps_rows_per_symbol(monkeypatch, tmp_path):
    p = tmp_path / "ohlcv_store_test.db"
    monkeypatch.setattr(store, "DB_PATH", p)
    monkeypatch.setenv("II_OHLCV_STORE_MAX_ROWS_PER_SYMBOL", "900")
    df = pd.DataFrame(
        {
            "date": pd.date_range("2020-01-01", periods=1200, freq="B"),
            "open": [10.0] * 1200,
            "high": [11.0] * 1200,
            "low": [9.0] * 1200,
            "close": [10.5] * 1200,
            "volume": [1000.0] * 1200,
        }
    )
    store.upsert_ohlcv("FPT", df, source="test")
    out = store.load_recent_ohlcv("FPT", sessions=2000)
    assert 850 <= len(out) <= 900

