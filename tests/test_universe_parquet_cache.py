import pandas as pd

from core import universe_parquet_cache as upc


def test_universe_parquet_cache_roundtrip_or_graceful_fail(monkeypatch, tmp_path):
    test_path = tmp_path / "universe_scan_cache_test.parquet"
    monkeypatch.setattr(upc, "CACHE_PATH", test_path)
    df = pd.DataFrame([{"Mã": "FPT", "MOS%": 12.5}])
    ok = upc.save_universe_scan_cache(df)
    if ok:
        loaded = upc.load_universe_scan_cache(max_age_minutes=180)
        assert not loaded.empty
        assert "Mã" in loaded.columns
    else:
        # Nếu máy chưa có engine parquet (pyarrow/fastparquet), hàm phải fail an toàn.
        loaded = upc.load_universe_scan_cache(max_age_minutes=180)
        assert loaded.empty
    if test_path.exists():
        test_path.unlink()

