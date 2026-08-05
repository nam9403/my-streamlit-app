# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- **P2 product surface**: onboarding funnel (hồ sơ → Autopilot → phân tích 1 mã),
  Autopilot limit clamp theo `plan.scan_limit`, morning digest
  (`scripts/send_morning_digest.py` + scheduler), Trust panel (paper hit-rate ẩn danh)
  + SLO ops panel (nightly coverage / timing artifacts).

- **P1 decision quality**: `core/decision_completeness.py` — thiếu CFO/NI (non-bank)
  hạ Legend "Mua mạnh"→"Theo dõi" và cap `decision_readiness`; ngân hàng không bị phạt CFO/CR.
- **P1 paper-trade ledger**: `core/paper_trade_ledger.py` +
  `scripts/resolve_paper_trades.py` — mở lệnh giả lập từ nightly Top 10, resolve theo
  horizon, báo cáo hit-rate; Autopilot UI hiện News/Macro bias + paper stats.

- **Autopilot nightly liquid board**: quét HOSE/VN30 theo batch ban đêm, lưu
  `data/runtime/autopilot_nightly_board.json`; sáng Auto Pilot phục vụ **Top 10
  từ toàn bộ mã đã quét** (không chỉ cửa sổ rotation ~40). Script
  `scripts/run_autopilot_nightly_scan.py`, scheduler
  `scripts/setup_autopilot_nightly_scan_scheduler.ps1`, env
  `II_AUTOPILOT_NIGHTLY_BOARD*` (mặc định bật). Fallback live rotation khi board
  thiếu/stale/coverage thấp.

### Added
- Hardened intraday flow detector with multi-vendor resilience &
  cross-process journal safety:
  - **Circuit breaker + retry-on-rate-limit** in `scrapers/intraday_vn.py`:
    sources that return 429/503 now raise the new `IntradayRateLimitError`
    and are retried with exponential backoff (`II_INTRADAY_RETRY_ATTEMPTS`,
    `II_INTRADAY_RETRY_BACKOFF_SEC`). After
    `II_INTRADAY_BREAKER_FAILURES` consecutive failures a source is
    skipped from the chain for `II_INTRADAY_BREAKER_COOLDOWN_SEC` seconds.
    Public helpers `register_intraday_source`, `list_intraday_sources`,
    `get_intraday_breaker_state`, `reset_intraday_breaker` make custom
    sources (DNSE, SSI, …) pluggable; `II_INTRADAY_EXTRA_SOURCES`
    appends them to the chain. **Bug fix**: `IntradayFetchConfig.normalize`
    now honors `cache_ttl_sec=0` (previously coerced to default 30s by `or`).
  - **File lock for `core/intraday_flow_journal.py`**: `_acquire_file_lock`
    wraps `fcntl.flock` on POSIX and `msvcrt.locking` (non-blocking poll
    on byte 0 with timeout/interval env knobs) on Windows so multiple
    processes can append the same JSONL safely. Toggle via
    `II_FLOW_JOURNAL_FILE_LOCK` (default ON). Performance: ~1 ms/append
    after fixing the byte-offset bug that previously caused
    `Permission denied` on unlock and ~1 s/call latency.
  - Tests: `tests/test_intraday_vn_scraper.py` (+8 cases for rate-limit
    fallback, breaker open/reset, registry, env-driven extra source) and
    `tests/test_intraday_flow_journal.py` (concurrent appends).

- Enriched FlowSignal with technical context & buy/sell ratio (B1+B3):
  `core/intraday_flow_service.py` exposes new helpers
  `compute_price_context` (resistance/support from rolling
  high/low, `price_position_pct`, `near_resistance/support`,
  `distance_to_resistance/support_pct`) and `compute_buy_sell_ratio`
  (buy/sell volume + `imbalance_direction`). `FlowSignal` gains these
  fields with defaults (backward-compat with existing journal rows).
  `analyze_flow` calls `apply_context_intensity_adjustment` to:
  cap bullish-near-resistance at 7.0 (bull-trap risk), boost
  bullish/absorption-near-support, cap bearish-near-support, and boost
  distribution-near-resistance — directly addressing the user's
  Contextual Overlay requirement.

- Added sector-aware orchestrator (B2): two new public helpers
  `apply_sector_intensity_adjustment` and
  `adjust_signals_with_sector_context` (idempotent post-pass on existing
  signals), plus convenience `batch_analyze_flow_with_sector_context`.
  Mã bullish cùng chiều bias ngành ⇒ boost (×1.10 default); mã bullish
  lẻ loi trong ngành đang bearish ⇒ penalty (×0.85), filtering out
  "fund-rebalance" outliers per the user's spec. Wired into
  `core/background_jobs._run_intraday_flow_cycle` (gated by
  `II_FLOW_SECTOR_ADJUST_ENABLED`, default ON) using
  `scrapers.financial_data.universe_subtype_map` for industry context.
  Health payload + return dict carry `sector_adjust_enabled` and
  `sector_adjusted_count`.

- Enriched Telegram / in-app alert payload (C3):
  `core/intraday_flow_alert_service.FlowAlertPayload` now carries
  `last_close`, `resistance_level`, `support_level`, `buy_sell_ratio`,
  `imbalance_direction`, plus `suggested_entry_low / _high`,
  `suggested_stop_loss`, and `entry_action`
  (`BUY_NOW` / `WAIT_BREAKOUT` / `WATCH` / `AVOID`).
  `render_alert_message_vi` shows price levels, action-aware entry zone
  & stop-loss with Vietnamese-formatted prices. Tests:
  `tests/test_intraday_flow_alert_service.py` (+8 cases).

- Added weekly flow-backtest scheduler scaffolding:
  `scripts/run_weekly_flow_backtest.ps1` (CLI wrapper) +
  `scripts/setup_weekly_flow_backtest_scheduler.ps1` (Windows Task
  Scheduler installer). Output `recommendation_latest.json` is picked
  up automatically by `_flow_min_intensity_env`, closing the
  self-tuning loop without human action.

### Added
- Added scanner re-rank by flow journal (opt-in):
  `core/scanner_flow_integration.py` provides
  `rerank_candidates_with_flow_journal(candidates) -> (df, meta)` which reads
  the most recent `FlowSignal` per symbol from
  `data/runtime/flow_journal/` and applies `apply_flow_boost_to_dataframe`,
  closing the loop **"Big Boy detector → ranking"**. No new network calls (it
  only reads local JSONL written by `background_jobs._run_intraday_flow_cycle`)
  and graceful-degrades on empty / corrupt journal.
  Wired into `core/app_scan_flow.run_scan_flow` behind the new env flag
  `II_SCANNER_FLOW_RERANK_ENABLED` (default OFF, backward-compatible).
  Tunables: `II_SCANNER_FLOW_RERANK_LOOKBACK_HOURS` (default 24h),
  `II_SCANNER_FLOW_RERANK_WEIGHT` (default 0.25). Caption rendered on cache
  miss when ≥1 candidate intersects a journaled signal.
  Tests: `tests/test_scanner_flow_integration.py` (16 cases) +
  2 new cases in `tests/test_app_scan_flow.py` validating both enabled and
  disabled paths through `run_scan_flow`.

### Added
- Added core project docs: `README.md`, `SECURITY.md`, `RELEASE_CHECKLIST.md`, and `LICENSE`.
- Added CI workflow for automated tests and offline health checks.
- Added release workflow for tag-based verification and source artifact packaging.
- Added automated secret scanning script for local/CI quality gates.
- Added intraday flow detection service (Tier 1): `core/intraday_flow_service.py` with
  frequency-agnostic `analyze_flow`, dynamic Z-score thresholds, Isolation Forest
  anomaly detection, pseudo-delta tick rule, super-bar aggregation, universe screener,
  and sector flow bias. Implements the "Big Boys" detection contract
  (`is_big_boy`, `aggregated_volume`, `delta_status`, `intensity_score`).
- Added smart-money confirmation (Tier 2): `confirm_smart_money_flow` in
  `core/deep_insight_service.py` to fuse tape signals with foreign / insider /
  put-through events, flagging bull-trap and accumulation patterns.
- Added flow alert dispatch service: `core/intraday_flow_alert_service.py` reusing
  the existing `RealtimeGuardian` cooldown without changing its public surface.
- Added flow UI panel: `core/intraday_flow_panel.py` with a pure `build_flow_view_model`
  (testable offline) plus a Streamlit `render_intraday_flow_panel`.
- Added tests: `tests/test_intraday_flow_service.py`,
  `tests/test_intraday_flow_alert_service.py`, `tests/test_intraday_flow_panel.py`.
- Wired intraday flow panel into the primary analysis tab via
  `core/app_analysis_tab_primary.render_primary_analysis_tab` (new optional
  `render_intraday_flow_panel` injection) and `app.py`, sourcing
  `smart_money_summary` from `report["deep_insight"]["smart_money_flow"]`.
- Wired intraday flow alerts into the background scheduler:
  `core/background_jobs._run_intraday_flow_cycle` evaluates dynamic Z + Isolation
  Forest signals on the rotating watchlist, dispatches Telegram notifications via
  a dedicated `RealtimeGuardian` state file (`data/flow_guardian_state.json`),
  and emits a guardian-health artifact under
  `artifacts/operations/intraday_flow_guardian_health.json`.
  Tunables: `II_FLOW_MIN_INTENSITY`, `II_FLOW_MAX_SYMBOLS`, `II_FLOW_SESSIONS`,
  `II_FLOW_COOLDOWN_MINUTES`, `II_FLOW_GUARDIAN_STATE_PATH`,
  `II_FLOW_GUARDIAN_HEALTH_PATH`.
- Added integration tests for the new cycle:
  `tests/test_background_jobs_intraday_flow.py` (dispatch, cooldown,
  no-secret guard, env disable, OHLCV failure path).
- Added **free-source intraday OHLCV scraper** `scrapers/intraday_vn.py`
  with a VNDirect dchart-api → TCBS apipubaws fallback chain (no paid
  license required). Public API:
  `fetch_intraday_ohlcv(symbol, resolution="5", lookback_bars=400, ...)`,
  `batch_fetch_intraday`, `is_vn_market_open`, `next_vn_market_open`.
  Returns the same DataFrame schema as `scrapers.portal.fetch_ohlcv_history`
  so Tier 1 `analyze_flow` is fully plug-and-play. 30-second in-memory cache.
  Tests: `tests/test_intraday_vn_scraper.py` (19 cases including fallback,
  cache, SLA recorder, market-hours, payload parsers).
- Wired intraday resolution into `_run_intraday_flow_cycle`. New env knobs:
  `II_FLOW_RESOLUTION` (`D` default; `1`/`3`/`5`/`15`/`30`/`60` enables the
  free intraday scraper), `II_FLOW_PRIMARY_SOURCE` (`vndirect`/`tcbs`),
  `II_FLOW_SKIP_OUTSIDE_HOURS` (default `1` — skip cycle outside 09:00–11:30
  and 13:00–14:45 VN time to spare free APIs). Health artifact now records
  the resolution and primary source actually used.
- Added **smart money auto-seed cycle** `_run_smart_money_seed_cycle` in
  `core/background_jobs.py`: once-per-day refresh of
  `data/smart_money_events.json` from `fetch_latest_news` (CafeF / VietStock
  public news chain). Gated by a plain-text timestamp at
  `data/runtime/smart_money_seed_last_run.txt`. Tunables:
  `II_SMART_MONEY_SEED_ENABLED`, `II_SMART_MONEY_SEED_NEWS_LIMIT`,
  `II_SMART_MONEY_SEED_MAX_PER_SYMBOL`, `II_SMART_MONEY_SEED_STATE_PATH`,
  `II_SMART_MONEY_SEED_OUTPUT_PATH`. `run_background_cycle` now returns a
  `smart_money_seed` block alongside `prefetch`, `super_stock`,
  `intraday_flow`, and `queue`.
- Added tests `tests/test_background_jobs_smart_money_seed.py` (8 cases:
  ingest + write, daily gating, env disable, loader error, merge with
  existing JSON, due-detection, run_background_cycle integration).
- Added **FlowSignal persistence (JSONL journal)** `core/intraday_flow_journal.py`
  with append-only weekly rotation (`flow_signals_<ISO_year>W<NN>.jsonl`),
  `read_recent_flow_signals`, `summarize_recent_flow_signals`, and
  `prune_old_journal_files`. Provides the audit trail and historical
  dataset required to backtest / tune `min_intensity` empirically.
  `_run_intraday_flow_cycle` now appends every computed signal (not only
  those that triggered an alert), tagged with `phase=background_cycle`,
  `resolution`, `primary_source`, and `min_intensity`. Tunables:
  `II_FLOW_JOURNAL_DIR`, `II_FLOW_JOURNAL_MAX_FILE_MB`,
  `II_FLOW_JOURNAL_RETENTION_WEEKS`, `II_FLOW_JOURNAL_PRUNE_PER_CYCLE`.
  Tests: `tests/test_intraday_flow_journal.py` (11 cases) plus 2 cases in
  `tests/test_background_jobs_intraday_flow.py` covering write + failure
  isolation.
- Added **flow-aware re-ranking helper** `core/flow_ranking_service.py`:
  `compute_flow_boost(signal)` returns `(boost ∈ [bearish_cap, bullish_cap],
  note_vi)` plus `apply_flow_boost_to_dataframe` / `apply_flow_boost_to_candidates`
  that adjust scanner confidence and re-sort by action rank → confidence →
  flow boost, idempotently. Designed as an opt-in *post-processor*: no
  modification of the critical-tier `core/scanner_service.py`. Exposed at
  the `core` package level for scanner / UI integration. Tests:
  `tests/test_flow_ranking_service.py` (16 cases).
- Added **FlowSignal backtest harness** `core/flow_backtest_service.py`:
  `replay_flow_signals_on_ohlcv` (look-ahead-free rolling window),
  `compute_forward_returns` (T+1/T+5/T+20 by default),
  `backtest_flow_signals`, `summarize_backtest_by_intensity`,
  `recommend_min_intensity` (empirical auto-tune), and
  `aggregate_universe_backtest` (pool signals across symbols to avoid
  per-symbol overfit). Lets us **prove or disprove** the Big-Boy detector
  on existing free historical OHLCV before scaling alerts to real users —
  the answer to "what `min_intensity` should we ship with?" is now
  data-driven instead of guessed.
- Added **CLI** `scripts/backtest_flow_signals.py` that downloads OHLCV via
  `fetch_ohlcv_history`, runs the backtest, and writes both a JSON report
  (`artifacts/flow_backtest/flow_backtest_latest.json`) and a
  human-readable Markdown summary with per-symbol + pooled tables and
  per-horizon `min_intensity` recommendations. Example:
  `python scripts/backtest_flow_signals.py --symbols FPT,HPG,VNM,VCB,MWG --sessions 500 --stride 5 --horizons 1,5,20`.
- Added tests `tests/test_flow_backtest_service.py` (16 cases including a
  dedicated look-ahead-bias test that proves signal values at index *i*
  do not change when later bars are appended) and
  `tests/test_backtest_flow_signals_cli.py` (3 cases covering happy path,
  portal-error skip, and empty-symbol validation).
- Added **closed-loop backtest → runtime feedback** (self-tuning):
  - `save_recommendation_artifact` / `load_recommendation_artifact` in
    `core/flow_backtest_service.py` write/read
    `artifacts/flow_backtest/recommendation_latest.json` with a TTL guard
    so stale recommendations cannot silently override defaults.
  - `scripts/backtest_flow_signals.py` now writes the recommendation
    artifact on every successful run (controlled via
    `--recommendation-path` and `--recommendation-horizon`).
  - `core/background_jobs._flow_min_intensity_env` now resolves
    `min_intensity` from three sources in priority order:
    explicit `II_FLOW_MIN_INTENSITY` env → backtest recommendation
    (when `II_FLOW_USE_BACKTEST_RECOMMENDATION=1`) → default `6.0`.
    The actual source used is exposed in the guardian health artifact
    under `min_intensity_source` for ops audit.
  - Tunables: `II_FLOW_USE_BACKTEST_RECOMMENDATION`,
    `II_FLOW_RECOMMENDATION_PATH`, `II_FLOW_RECOMMENDATION_TTL_DAYS`.
  - Tests: 8 additional cases in `tests/test_flow_backtest_service.py`
    (save/load round-trip, stale rejection, corrupt JSON, null
    recommendation) plus 4 cases in
    `tests/test_background_jobs_intraday_flow.py` covering all three
    priority levels of the resolution chain.

### Fixed
- Stabilised `tests/test_portal_ohlcv_store_integration.py` and
  `tests/test_portal_data_trust_metadata.py` after the VN price-scale guard
  was added to `scrapers/portal.fetch_ohlcv_history`: the synthetic store
  payload now uses VND-realistic prices and stubs `_is_suspicious_vn_price_scale`.
- Updated `tests/test_ui_panels_smoke.py` smoke to pass the new
  `render_forecast_backtesting_report`, `get_forecast_backtesting_report`,
  `render_dss_readiness_panel`, `get_dss_readiness_report`, and
  `render_intraday_flow_panel` DI keyword arguments.

### Changed
- Hardened credential handling in `run_app.bat` by removing hardcoded API keys.
- Upgraded PIN authentication hashing to PBKDF2 with legacy hash migration.
- Upgraded secret storage encryption in app layer to Fernet with transparent migration.

### Security
- Removed exposed key material from runtime startup script.
- Added stronger secret-management guidance through docs and env-based configuration.

