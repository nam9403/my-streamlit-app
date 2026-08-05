from __future__ import annotations

from scripts.smart_money_event_sync import extract_events_from_news, merge_events


def test_extract_events_from_news_detects_buy_sell() -> None:
    rows = [
        {"title": "Khối ngoại mua ròng 120 tỷ cổ phiếu FPT", "source": "cafef", "url": "u1"},
        {"title": "Cổ đông lớn đăng ký bán 35 tỷ cổ phiếu FPT", "source": "vietstock", "url": "u2"},
    ]
    out = extract_events_from_news("FPT", rows)
    assert len(out) == 2
    assert out[0]["side"] == "buy"
    assert out[1]["side"] == "sell"
    assert float(out[0]["net_value_vnd"]) > 0
    assert "actor_name" in out[0]
    assert 0.0 <= float(out[0]["confidence"]) <= 1.0


def test_merge_events_dedups_and_caps_per_symbol() -> None:
    existing = [
        {
            "symbol": "FPT",
            "event_date": "2026-05-07",
            "actor_type": "foreign",
            "side": "buy",
            "source": "cafef",
            "headline": "Khối ngoại mua ròng 100 tỷ cổ phiếu FPT",
            "synced_at_utc": "2026-05-07T00:00:00+00:00",
        }
    ]
    incoming = existing + [
        {
            "symbol": "FPT",
            "event_date": "2026-05-07",
            "actor_type": "major_shareholder",
            "side": "sell",
            "source": "vietstock",
            "headline": "Cổ đông lớn đăng ký bán 20 tỷ FPT",
            "synced_at_utc": "2026-05-07T01:00:00+00:00",
        }
    ]
    out = merge_events(existing, incoming, max_per_symbol=1)
    assert len(out) == 1
    assert out[0]["symbol"] == "FPT"
