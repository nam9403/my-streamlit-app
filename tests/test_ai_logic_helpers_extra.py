from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path


def test_llm_extractors_and_json_parsing_helpers() -> None:
    import core.ai_logic as ai

    openai_text = ai._extract_llm_text_openai_style({"choices": [{"message": {"content": "ok"}}]})
    gemini_text = ai._extract_llm_text_gemini({"candidates": [{"content": {"parts": [{"text": "hello"}]}}]})
    assert openai_text == "ok"
    assert gemini_text == "hello"

    assert ai._extract_llm_text_openai_style({"choices": [{"message": {"content": 123}}]}) == "123"
    assert ai._try_parse_json("```json\n{\"a\": 1}\n```") == {"a": 1}
    assert ai._try_parse_json("") is None
    assert ai._try_parse_json("[]") is None


def test_key_collection_sort_and_health_snapshot(monkeypatch) -> None:
    import core.ai_logic as ai

    ai._KEY_HEALTH.clear()
    monkeypatch.setenv("OPENAI_API_KEY", "k3")
    monkeypatch.setenv("OPENAI_API_KEYS", "k1;k2,k1")
    keys = ai._collect_api_keys("OPENAI_API_KEY", "OPENAI_API_KEYS")
    assert keys == ["k1", "k2", "k1", "k3"]

    monkeypatch.setattr(ai.time, "time", lambda: 1000.0)
    ai._record_key_health("openai", "k1", 200.0, True)
    ai._record_key_health("openai", "k2", 300.0, False, "429 rate limit")
    sorted_keys = ai._sort_keys_by_health("openai", ["k2", "k1"])
    assert sorted_keys[0] == "k1"

    snap = ai.get_provider_health_snapshot()
    assert any(r["key_masked"].endswith("k1") for r in snap)
    assert any(int(r["cooldown_sec"]) > 0 for r in snap if r["key_masked"].endswith("k2"))


def test_llm_cache_and_fingerprint(monkeypatch) -> None:
    import core.ai_logic as ai

    ai._LLM_RESPONSE_CACHE.clear()
    monkeypatch.setenv("AI_LLM_CACHE_TTL_SEC", "2")

    now = {"t": 100.0}
    monkeypatch.setattr(ai.time, "time", lambda: now["t"])
    fp1 = ai._messages_fingerprint([{"role": "user", "content": "A"}])
    fp2 = ai._messages_fingerprint([{"content": "A", "role": "user"}])
    assert fp1 == fp2

    ai._llm_cache_set("k", "text", "openai")
    got = ai._llm_cache_get("k")
    assert got == ("text", "openai")
    now["t"] = 103.0
    assert ai._llm_cache_get("k") is None

    monkeypatch.setenv("AI_LLM_CACHE_TTL_SEC", "-1")
    assert ai._get_llm_cache_ttl_sec() == 0
    monkeypatch.setenv("AI_LLM_CACHE_TTL_SEC", "99999")
    assert ai._get_llm_cache_ttl_sec() == 3600


def test_provider_order_and_confidence_threshold(monkeypatch) -> None:
    import core.ai_logic as ai

    available = {"openai": object(), "groq": object(), "gemini": object()}
    monkeypatch.setenv("AI_AUTO_PROVIDER_ORDER_SPEED", "gemini,groq,openai")
    order = ai._build_auto_provider_order(available, fast_mode=True, news_count=0)
    assert [x[0] for x in order][:2] == ["gemini", "groq"]

    monkeypatch.setenv("AI_ESCALATE_CONFIDENCE_BELOW", "abc")
    assert ai._confidence_escalation_threshold() == 70.0
    monkeypatch.setenv("AI_ESCALATE_CONFIDENCE_BELOW", "10")
    assert ai._confidence_escalation_threshold() == 40.0


def test_forecast_and_reliability_helpers() -> None:
    import core.ai_logic as ai

    no_price = ai._probabilistic_forecast({}, {}, {}, [])
    assert no_price["expected_price"] is None

    fc = ai._probabilistic_forecast(
        {"price": 100.0, "composite_target_price": 120.0},
        {"phase": "accumulation", "metrics": {"vol_multiple": 1.1}},
        {"revenue_growth_yoy": 15.0, "debt_to_equity": 0.6},
        [{"title": "x"}],
    )
    assert isinstance(fc.get("scenarios"), list) and len(fc["scenarios"]) == 3
    rel = ai._forecast_reliability_summary(fc, {"buy_win_rate_pct": 60.0, "buy_signals": 10, "samples": 100}, 80.0)
    assert rel["quality_label"] in ("high", "medium", "low")

    rel_empty = ai._forecast_reliability_summary({"scenarios": []}, {}, 0.0)
    assert rel_empty["quality_label"] == "insufficient_data"


def test_risk_plan_and_financial_derivation_helpers() -> None:
    import core.ai_logic as ai

    rp = ai.calculate_risk_allocation("AAA", 100.0, 105.0, 95.0, 100_000_000.0, support_price=90.0)
    assert float(rp["buy_zone_low"]) <= float(rp["buy_zone_high"])
    assert float(rp["stop_loss_price"]) < float(rp["entry_price"])

    low, high = ai._normalize_buy_zone_with_market_price(100.0, 10.0, 20.0)
    assert round(low, 2) == 97.0 and round(high, 2) == 103.0

    fin = ai._derive_financials_from_snapshot(
        "AAA",
        {
            "shareholders_equity": 0,
            "book_value_per_share": 10,
            "piotroski": {
                "shares_outstanding": 100,
                "revenue": 200,
                "revenue_prior": 100,
                "net_income": 50,
                "net_income_prior": 25,
                "cogs": 80,
                "long_term_debt": 200,
            },
        },
    )
    assert fin["source"] == "snapshot_derived"
    assert fin["debt_to_equity"] is not None


def test_action_quality_and_provenance_helpers(monkeypatch, tmp_path: Path) -> None:
    import core.ai_logic as ai

    monkeypatch.setenv("II_STRICT_REAL_FINANCIAL_DATA", "yes")
    assert ai._strict_real_financial_data() is True

    score = ai._confidence_score(
        {"phase": "accumulation", "metrics": {"vol_multiple": 1.0}},
        {"data_quality_score": 4, "source": "portal", "debt_to_equity": 0.5, "gross_margin": 20, "revenue_growth_yoy": 10},
        [{"title": "n"}],
        True,
        {"buy_win_rate_pct": 60, "buy_signals": 5},
    )
    assert score >= 60.0
    assert ai._final_action({"margin_of_safety_composite_pct": 20, "piotroski_score": 7}, {"phase": "breakout"}, 80.0) == "BUY"
    # Định giá tốt + Legend pass nhưng F-Score thấp / pha trung tính → WATCH (không AVOID)
    assert (
        ai._final_action(
            {
                "margin_of_safety_composite_pct": 40,
                "piotroski_score": 2,
                "legend_scorecard": {"buffett_pass": True, "graham_pass": True},
                "is_bank_sector": True,
            },
            {"phase": "neutral"},
            70.0,
        )
        == "WATCH"
    )
    align = ai._decision_alignment(
        {
            "instant_conclusion": "Mua mạnh",
            "margin_of_safety_composite_pct": 40.0,
            "mos_integrity_blocked": False,
        },
        "WATCH",
        {"phase": "neutral"},
    )
    # P1-tune: valuation attractive + timing not ready → HOLD (not early CONDITIONAL_BUY)
    assert align["unified_action"] == "HOLD"
    assert align["alignment"] == "valuation_vs_timing"

    gate = ai._output_quality_gate({"price": 100.0}, {"entry_price": 150.0, "stop_loss_price": 100.0, "take_profit_price": 160.0})
    assert gate["passed"] is False
    assert "entry_too_far_from_market" in gate["reasons"]

    now = datetime(2026, 1, 2, tzinfo=timezone.utc)
    prov = ai._build_data_provenance(
        financials={"source": "snapshot_derived", "as_of_utc": "2026-01-01T00:00:00+00:00"},
        phase={"phase": "neutral", "metrics": {}},
        news=[],
        used_fallback=True,
        now_utc=now,
    )
    assert bool(prov["financials"]["fallback_used"]) is True
    assert bool(prov["news"]["fallback_used"]) is True
    assert ai._parse_iso_utc("bad-ts") is None
    assert ai._freshness_hours("2030-01-01T00:00:00+00:00", now) == 0.0

    reasons = ai._do_not_act_reasons(
        {
            "gate_passed": False,
            "output_gate_passed": False,
            "data_reliability_gate_passed": False,
            "analysis_verdict": "NO-GO",
        }
    )
    assert "analysis_verdict_no_go" in reasons

    audit_file = tmp_path / "audit.jsonl"
    monkeypatch.setattr(ai, "RECOMMENDATION_AUDIT_PATH", audit_file)
    out_path = ai._write_recommendation_audit({"ticker": "AAA", "as_of_utc": now.isoformat()})
    assert out_path is not None
    assert audit_file.exists()


def test_fallback_7whys_and_data_reliability_helpers() -> None:
    import core.ai_logic as ai

    fb = ai._build_fallback_7whys(
        "AAA",
        {"phase": "accumulation", "reason": "ok", "metrics": {"vol_multiple": 1.1}},
        {"price": 100.0, "intrinsic_value_graham": 120.0, "piotroski_score": 7, "valuation_transparency_line": "line"},
        {"debt_to_equity": 0.5, "revenue_growth_yoy": 10, "profit_growth_yoy": 8},
        [{"title": "headline"}],
        "growth",
        100_000_000.0,
    )
    assert fb["llm_used"] is False
    assert len(fb["whys_steps"]) == 8

    rel = ai._data_reliability(
        {"phase": "accumulation", "metrics": {"x": 1}},
        {"data_quality_score": 4, "source": "portal"},
        [{"title": "n"}],
        True,
        {"samples": 50, "buy_signals": 4, "buy_win_rate_pct": 55.0},
    )
    assert bool(rel["technical"]["ok"]) is True
    assert bool(rel["backtest"]["ok"]) is True


def test_call_openai_with_key_rotation(monkeypatch) -> None:
    import core.ai_logic as ai

    class _Resp:
        def __init__(self, ok: bool, payload: dict[str, object] | None = None) -> None:
            self._ok = ok
            self._payload = payload or {}

        def raise_for_status(self) -> None:
            if not self._ok:
                raise ai.requests.RequestException("429")

        def json(self) -> dict[str, object]:
            return self._payload

    calls = {"n": 0}
    monkeypatch.setattr(ai, "_collect_api_keys", lambda *a, **k: ["k1", "k2"])
    monkeypatch.setattr(ai, "_sort_keys_by_health", lambda provider, keys: keys)
    monkeypatch.setattr(ai.time, "sleep", lambda *a, **k: None)
    monkeypatch.setattr(ai, "_record_key_health", lambda *a, **k: None)

    def fake_post(url: str, headers: dict[str, str], json: dict[str, object], timeout: int):
        _ = (url, headers, json, timeout)
        calls["n"] += 1
        if calls["n"] == 1:
            return _Resp(False)
        return _Resp(True, {"choices": [{"message": {"content": "ok-openai"}}]})

    monkeypatch.setattr(ai.requests, "post", fake_post)
    out = ai._call_openai([{"role": "user", "content": "hi"}])
    assert out == "ok-openai"
    assert calls["n"] == 2


def test_call_groq_and_gemini_success(monkeypatch) -> None:
    import core.ai_logic as ai

    class _Resp:
        def __init__(self, payload: dict[str, object]) -> None:
            self._payload = payload

        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, object]:
            return self._payload

    monkeypatch.setattr(ai, "_collect_api_keys", lambda *a, **k: ["k"])
    monkeypatch.setattr(ai, "_sort_keys_by_health", lambda provider, keys: keys)
    monkeypatch.setattr(ai, "_record_key_health", lambda *a, **k: None)

    monkeypatch.setattr(
        ai.requests,
        "post",
        lambda *a, **k: _Resp({"choices": [{"message": {"content": "ok-groq"}}]}),
    )
    groq = ai._call_groq([{"role": "user", "content": "x"}])
    assert groq == "ok-groq"

    monkeypatch.setattr(
        ai.requests,
        "post",
        lambda *a, **k: _Resp({"candidates": [{"content": {"parts": [{"text": "ok-gemini"}]}}]}),
    )
    gem = ai._call_gemini([{"role": "user", "content": "x"}])
    assert gem == "ok-gemini"


def test_generate_report_fallback_context_and_auto_llm(monkeypatch, tmp_path: Path) -> None:
    import core.ai_logic as ai

    class _PhaseObj:
        phase = "accumulation"
        reason = "trend ok"
        metrics = {"vol_multiple": 1.2}

    monkeypatch.setattr(ai, "RECOMMENDATION_AUDIT_PATH", tmp_path / "audit.jsonl")
    monkeypatch.setattr(ai, "value_investing_summary", lambda snap: {"price": 100.0, "margin_of_safety_composite_pct": 18.0, "piotroski_score": 7})
    monkeypatch.setattr(ai, "build_investment_context", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("ctx err")))
    monkeypatch.setattr(ai, "fetch_ohlcv_history", lambda *a, **k: [{"close": 100}])
    monkeypatch.setattr(ai, "detect_market_phase_from_ohlcv", lambda *a, **k: _PhaseObj())
    monkeypatch.setattr(ai, "backtest_action_strategy", lambda *a, **k: {"samples": 60, "buy_signals": 4, "buy_win_rate_pct": 55.0})
    monkeypatch.setattr(ai, "fetch_financial_indicators", lambda *a, **k: (_ for _ in ()).throw(ai.PortalDataError("no live")))
    monkeypatch.setattr(ai, "_derive_financials_from_snapshot", lambda *a, **k: {"source": "snapshot_derived", "data_quality_score": 3})
    monkeypatch.setattr(ai, "fetch_latest_news", lambda *a, **k: (_ for _ in ()).throw(ai.PortalDataError("no news")))
    monkeypatch.setenv("II_STRICT_REAL_FINANCIAL_DATA", "0")
    monkeypatch.setenv("GROQ_API_KEY", "x")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setattr(ai, "_build_auto_provider_order", lambda available, **k: [("groq", available["groq"])])
    monkeypatch.setattr(
        ai,
        "_call_groq",
        lambda messages: '{"buy_zone":{"low":97,"high":101},"take_profit":112,"stop_loss":95,"analysis_text":"ok"}',
    )

    rep = ai.generate_strategic_report("AAA", {"symbol": "AAA", "price": 100.0}, preferred_llm="auto", enable_llm=True)
    assert rep["llm_used"] is True
    assert rep["llm_provider"] == "groq"
    assert isinstance(rep["risk_plan"], dict)
    assert isinstance(rep["recommendation_audit_log"], str)


def test_generate_report_auto_escalation_uses_quality_provider(monkeypatch, tmp_path: Path) -> None:
    import core.ai_logic as ai

    monkeypatch.setattr(ai, "RECOMMENDATION_AUDIT_PATH", tmp_path / "audit_escalation.jsonl")
    monkeypatch.setattr(
        ai,
        "build_investment_context",
        lambda *a, **k: {
            "technical": {"market_phase": {"phase": "breakout", "reason": "x", "metrics": {"vol_multiple": 1.1}}, "ohlcv": []},
            "valuation": {"price": 100.0, "margin_of_safety_composite_pct": 20.0, "piotroski_score": 8},
            "financials": {"source": "portal", "data_quality_score": 4},
            "news": [{"title": "n", "published_at": "2026-01-01T00:00:00+00:00"}],
        },
    )
    monkeypatch.setattr(ai, "backtest_action_strategy", lambda *a, **k: {"samples": 100, "buy_signals": 10, "buy_win_rate_pct": 60.0})
    monkeypatch.setenv("OPENAI_API_KEY", "x")
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setattr(ai, "_llm_cache_get", lambda key: None)
    monkeypatch.setattr(ai, "_llm_cache_set", lambda *a, **k: None)

    def fake_confidence(phase, financials, news, llm_used, backtest=None):
        _ = (phase, financials, news, backtest)
        return 50.0 if not llm_used else 82.0

    monkeypatch.setattr(ai, "_confidence_score", fake_confidence)

    def fake_build_order(available, *, fast_mode, news_count, force_mode=None):
        _ = (fast_mode, news_count)
        if force_mode == "quality":
            return [("openai", lambda messages: '{"buy_zone":{"low":99,"high":101},"take_profit":112,"stop_loss":96,"analysis_text":"quality"}')]
        return [("openai", lambda messages: '{"buy_zone":{"low":98,"high":102},"take_profit":110,"stop_loss":95,"analysis_text":"base"}')]

    monkeypatch.setattr(ai, "_build_auto_provider_order", fake_build_order)
    rep = ai.generate_strategic_report("AAA", {"symbol": "AAA", "price": 100.0}, preferred_llm="auto", enable_llm=True)
    assert rep["llm_used"] is True
    assert rep["llm_escalation_attempted"] is True
    assert rep["llm_escalated"] is True
