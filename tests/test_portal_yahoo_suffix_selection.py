from __future__ import annotations

from datetime import datetime, timezone


class _Resp:
    def __init__(self, payload: dict, status_code: int = 200):
        self._payload = payload
        self.status_code = status_code

    def json(self):
        return self._payload


def _build_yahoo_payload(n: int) -> dict:
    ts0 = int(datetime(2023, 1, 1, tzinfo=timezone.utc).timestamp())
    timestamps = [ts0 + i * 86400 for i in range(n)]
    vals = [10.0 + (i * 0.01) for i in range(n)]
    return {
        "chart": {
            "result": [
                {
                    "timestamp": timestamps,
                    "indicators": {
                        "quote": [
                            {
                                "open": vals,
                                "high": [x + 0.2 for x in vals],
                                "low": [x - 0.2 for x in vals],
                                "close": vals,
                                "volume": [1000.0] * n,
                            }
                        ]
                    },
                }
            ]
        }
    }


def test_yahoo_fallback_selects_longest_suffix(monkeypatch) -> None:
    import scrapers.portal as portal

    def _fake_get(url, headers=None, timeout=None):  # noqa: ARG001
        if "/v8/finance/chart/" in url:
            if ".VN" in url:
                return _Resp(_build_yahoo_payload(682), status_code=200)
            if ".HN" in url:
                return _Resp(_build_yahoo_payload(1247), status_code=200)
            if ".HM" in url:
                return _Resp(_build_yahoo_payload(900), status_code=200)
        return _Resp({}, status_code=404)

    monkeypatch.setattr(portal.requests, "get", _fake_get)
    monkeypatch.setattr(portal, "_norm_ticker", lambda t: "FPT")
    monkeypatch.setattr(portal, "_float_env", lambda *a, **k: 12.0)
    monkeypatch.setattr(portal, "_timeout_ladder", lambda: [1.0, 1.0, 1.0])

    out = portal._fetch_ohlcv_yahoo_uncached("FPT", sessions=1300)
    assert len(out) == 1247
