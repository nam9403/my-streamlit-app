from __future__ import annotations

import pandas as pd

from scrapers.vnstock_provider import normalize_listing_frame


def test_normalize_listing_frame_filters_stock_and_exchange() -> None:
    raw = pd.DataFrame(
        {
            "symbol": ["FPT", "ABC", "ZZZ", "BOND1"],
            "exchange": ["HSX", "HNX", "UPCOM", "BOND"],
            "type": ["STOCK", "STOCK", "STOCK", "BOND"],
            "icb_code2": ["8300", "1700", "4500", "9999"],
        }
    )
    out = normalize_listing_frame(raw)
    assert set(out["symbol"]) == {"FPT", "ABC", "ZZZ"}
    assert set(out["exchange_norm"]) == {"HOSE", "HNX", "UPCOM"}
    assert out.loc[out["symbol"] == "FPT", "icb_code"].iloc[0] == "8300"


def test_fetch_vnstock_listing_codes_uses_snapshot(monkeypatch) -> None:
    import scrapers.vn_listing as vl
    import scrapers.vnstock_provider as vp

    monkeypatch.setattr(
        vp,
        "fetch_listing_snapshot",
        lambda **k: {
            "symbols": ["FPT", "HPG"],
            "records": [{"symbol": "FPT", "exchange_norm": "HOSE", "icb_code": "8300"}],
            "source": "vnstock_listing:vci",
        },
    )
    codes, detail, records = vl.fetch_vnstock_listing_codes(exchange="HOSE")
    assert codes == ["FPT", "HPG"]
    assert "vnstock_listing" in detail
    assert records
