from __future__ import annotations


def test_prefetch_symbols_counts_success_and_failure(monkeypatch) -> None:
    import core.background_jobs as bg

    monkeypatch.setattr(bg, "fetch_financial_snapshot", lambda s: {"symbol": s} if s != "BAD" else None)
    monkeypatch.setattr(bg, "fetch_financial_indicators", lambda *args, **kwargs: None)
    monkeypatch.setattr(bg, "generate_strategic_report", lambda *args, **kwargs: {"ok": True})

    stat = bg.prefetch_symbols(["FPT", "BAD", "HPG"])
    assert int(stat["ok"]) == 2
    assert int(stat["fail"]) == 1
    assert int(stat["total"]) == 3


def test_prefetch_symbols_handles_strategy_exceptions(monkeypatch) -> None:
    import core.background_jobs as bg

    monkeypatch.setattr(bg, "fetch_financial_snapshot", lambda s: {"symbol": s})
    monkeypatch.setattr(bg, "fetch_financial_indicators", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        bg,
        "generate_strategic_report",
        lambda sym, *args, **kwargs: (_ for _ in ()).throw(RuntimeError("boom")) if sym == "FPT" else {"ok": True},
    )

    stat = bg.prefetch_symbols(["FPT", "HPG"])
    assert int(stat["ok"]) == 1
    assert int(stat["fail"]) == 1


def test_run_background_cycle_merges_watchlist_and_universe(monkeypatch) -> None:
    import core.background_jobs as bg

    monkeypatch.setattr(bg, "list_universe_symbols", lambda limit=30, offset=0: ["HPG", "VNM"])
    monkeypatch.setattr(bg, "prefetch_symbols", lambda syms, **kwargs: {"symbols": syms, "ok": len(syms), "fail": 0, "total": len(syms)})
    monkeypatch.setattr(bg, "_run_super_stock_cycle", lambda *a, **k: {"checked": 0, "passed": 0, "notified": 0})
    monkeypatch.setattr(bg, "_run_intraday_flow_cycle", lambda *a, **k: {"checked": 0, "alerts": 0, "notified": 0})
    monkeypatch.setattr(bg, "_run_smart_money_seed_cycle", lambda *a, **k: {"checked": 0, "ingested": 0, "stored": 0})
    monkeypatch.setattr(bg, "process_notification_queue", lambda max_jobs=30: {"processed": max_jobs, "sent": 0, "failed": 0, "retried": 0})

    out = bg.run_background_cycle(watchlist=["FPT", "HPG"], universe_limit=10, queue_jobs=7)
    syms = out["prefetch"]["symbols"]
    assert syms == ["FPT", "HPG", "VNM"]
    assert int(out["queue"]["processed"]) == 7


def test_run_background_cycle_propagates_authenticated_user(monkeypatch) -> None:
    import core.background_jobs as bg

    seen: list[tuple[str, str]] = []
    monkeypatch.setattr(bg, "list_universe_symbols", lambda **kwargs: [])
    monkeypatch.setattr(bg, "prefetch_symbols", lambda *args, **kwargs: {"ok": 0, "fail": 0, "total": 0})
    monkeypatch.setattr(
        bg,
        "_run_super_stock_cycle",
        lambda symbols, *, user_id: seen.append(("super", user_id)) or {},
    )
    monkeypatch.setattr(
        bg,
        "_run_intraday_flow_cycle",
        lambda symbols, *, user_id: seen.append(("flow", user_id)) or {},
    )
    monkeypatch.setattr(bg, "process_notification_queue", lambda **kwargs: {})

    bg.run_background_cycle(user_id="u-auth", watchlist=["FPT"])

    assert seen == [("super", "u-auth"), ("flow", "u-auth")]

