from __future__ import annotations

from types import SimpleNamespace


def test_strategic_report_impl_quick_mode_disables_llm(monkeypatch) -> None:
    import core.analysis_runtime_service as ars

    seen: dict[str, object] = {}

    def _fake_generate(ticker: str, snapshot: dict, **kwargs):
        seen["ticker"] = ticker
        seen["snapshot"] = snapshot
        seen.update(kwargs)
        return {"ok": True}

    monkeypatch.setattr(ars, "generate_strategic_report", _fake_generate)
    out = ars._strategic_report_impl("FPT", {"price": 100.0}, "growth", 100_000_000.0, quick_mode=True, llm_live=True)

    assert out == {"ok": True}
    assert seen["ticker"] == "FPT"
    assert seen["profile"] == "growth"
    assert seen["sessions"] == 60
    assert seen["news_limit"] == 5
    assert seen["enable_llm"] is False
    assert seen["fast_mode"] is True


def test_strategic_report_impl_full_mode_allows_llm(monkeypatch) -> None:
    import core.analysis_runtime_service as ars

    seen: dict[str, object] = {}

    def _fake_generate(ticker: str, snapshot: dict, **kwargs):
        seen["ticker"] = ticker
        seen.update(kwargs)
        return {"ok": True}

    monkeypatch.setattr(ars, "generate_strategic_report", _fake_generate)
    ars._strategic_report_impl("VCB", {"price": 80.0}, "safe_dividend", 200_000_000.0, quick_mode=False, llm_live=True)

    assert seen["ticker"] == "VCB"
    assert seen["sessions"] == 80
    assert seen["news_limit"] == 10
    assert seen["enable_llm"] is True
    assert seen["fast_mode"] is False


def test_prewarm_watchlist_cache_skips_empty_and_handles_failures(monkeypatch) -> None:
    import core.analysis_runtime_service as ars

    warmed: list[str] = []
    live_fetch: list[str] = []

    monkeypatch.setattr(ars, "_snapshot_impl", lambda sym: None if sym == "BAD" else {"symbol": sym})
    monkeypatch.setattr(
        ars,
        "fetch_financial_indicators",
        lambda sym, fast_mode=False: live_fetch.append(sym) if sym != "ERR" else (_ for _ in ()).throw(RuntimeError("x")),
    )

    def _fake_strategic(sym: str, *args, **kwargs):
        warmed.append(sym)
        if sym == "ERR":
            raise RuntimeError("strategic fail")
        return {"ok": True}

    monkeypatch.setattr(ars, "_strategic_report_impl", _fake_strategic)
    ars.prewarm_watchlist_cache(["FPT", "", "BAD", "ERR", "VCB"], "growth", 100_000_000.0, quick_mode=True)

    assert "BAD" not in warmed
    assert "FPT" in warmed and "VCB" in warmed
    assert "FPT" in live_fetch and "VCB" in live_fetch


def test_run_bg_warm_job_enforces_limits(monkeypatch) -> None:
    import core.analysis_runtime_service as ars

    seen = SimpleNamespace(universe_limit=None, watchlist=None, queue_jobs=None, warm_financial_live=None)

    def _fake_bg_cycle(**kwargs):
        seen.universe_limit = kwargs["universe_limit"]
        seen.watchlist = kwargs["watchlist"]
        seen.queue_jobs = kwargs["queue_jobs"]
        seen.warm_financial_live = kwargs["warm_financial_live"]
        return {"queued": kwargs["queue_jobs"]}

    monkeypatch.setattr(ars, "run_background_cycle", _fake_bg_cycle)
    out = ars.run_bg_warm_job(
        watchlist=[f"S{i}" for i in range(20)],
        universe_limit=-5,
        queue_jobs=0,
        warm_financial_live=True,
    )

    assert out == {"queued": 1}
    assert seen.universe_limit == 0
    assert isinstance(seen.watchlist, list) and len(seen.watchlist) == 12
    assert seen.queue_jobs == 1
    assert seen.warm_financial_live is True
