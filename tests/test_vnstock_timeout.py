from __future__ import annotations

import time


def test_vnstock_call_timeout_aborts_hang(monkeypatch) -> None:
    import scrapers.vnstock_provider as vp

    monkeypatch.setenv("II_PORTAL_FAIL_FAST", "1")
    monkeypatch.setenv("II_VNSTOCK_TIMEOUT_SEC", "0.4")
    monkeypatch.setenv("II_VNSTOCK_RETRY_MAX", "1")
    monkeypatch.setattr(vp, "configure_vnstock_credentials", lambda force=False: True)

    def hang():
        time.sleep(5)
        return "never"

    t0 = time.perf_counter()
    try:
        vp._call_with_retry("test_hang", hang)
        assert False, "expected VnstockProviderError"
    except vp.VnstockProviderError as e:
        assert "exceeded" in str(e).lower() or "timeout" in str(e).lower()
    elapsed = time.perf_counter() - t0
    assert elapsed < 2.5, f"timeout wrapper too slow: {elapsed:.2f}s"
