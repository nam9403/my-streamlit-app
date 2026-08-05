# Chart Module Release Notes

Date: 2026-04-27
Scope: `core/analysis_chart_panel.py`, `core/vn_market_calendar.py`, chart scheduler/scripts, chart tests.

## What Was Upgraded

- Stabilized candlestick rendering with 3 chart modes:
  - Candlestick stable mode (matplotlib)
  - Candlestick interactive mode (plotly)
  - Compatibility line mode fallback
- Added timeframe and lookback controls:
  - Timeframe: Day/Week/Month
  - Lookback: 3M/6M/1Y/3Y/5Y/All
  - Quick buttons: 1D/1W/1M/3M/6M/1Y/3Y/ALL
- Added technical overlays and subpanels:
  - MA20 / MA50
  - Volume
  - RSI(14)
  - MACD (line + signal + histogram)
  - Bollinger Bands
- Added professional UX improvements:
  - OHLC/Close change/Volume snapshot cards
  - Right-side price axis
  - Unified hover and crosshair spikes
  - Plotly range selector buttons
  - Last-price right annotation
  - Light/Dark chart theme
- Added technical decision layer:
  - Auto technical alerts (RSI/MA/MACD/Bollinger)
  - Technical signal score (0-100)
  - Decision label: STRONG BUY / BUY / WATCH / REDUCE / SELL

## Data Quality and Continuity

- Fixed discontinuity perception for daily chart:
  - Removed weekend/holiday spacing effect in stable mode axis mapping
  - Added Plotly weekend range breaks
- Added data integrity checks:
  - Daily session coverage ratio
  - Missing-session diagnostics output
  - Auto backfill merge from fallback source when coverage is weak
- Extracted VN market calendar to dedicated module:
  - `core/vn_market_calendar.py`
  - Backed by file store: `data/market_calendar_vn.json`
  - Supports year-range auto expansion

## Automation Added

- Calendar updater script:
  - `scripts/update_vn_market_calendar.py`
- Weekly runner:
  - `scripts/run_weekly_market_calendar_update.ps1`
- Weekly scheduler setup:
  - `scripts/setup_weekly_market_calendar_scheduler.ps1`
- Windows task configured:
  - `DuAn1_WeeklyMarketCalendarUpdate`
  - Runs weekly (Monday 06:30 by current setup)

## Quality Gates Added

- Existing regression test retained:
  - `tests/test_candlestick_hover_compat.py`
- New chart-quality lock tests:
  - `tests/test_analysis_chart_quality.py`
  - Covers: signal scoring, coverage detection, backfill merge, render-mode smoke
- Latest verification:
  - `7 passed` for chart-focused suite

## Known Tradeoffs

- Stable mode favors rendering reliability over advanced JS interactivity.
- VN holiday data for future years may start with estimated fixed holidays until curated updates are provided.
- Intraday realtime streaming is not included in this release scope.

## Recommended Next Steps (Operational)

- Freeze new chart features briefly and observe real usage feedback.
- Keep weekly calendar updater task enabled.
- If intraday trading is a priority, plan next release for:
  - realtime feed integration,
  - intraday intervals (1m/5m/15m),
  - push alerts from score/rules.
