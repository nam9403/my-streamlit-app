# Architecture Refactor Map

Mục tiêu: giảm dần monolith `app.py` theo phương pháp an toàn, không big-bang rewrite.

## 1) Trạng thái hiện tại (đã tách module)

Các module đã tách khỏi `app.py`:

- `core/admin_growth_panel.py`
  - Admin KPI, queue diagnostics, fail reason summary, guided fix.
- `core/command_center_panel.py`
  - Smart Command Center, health snapshot, CX score, auto-fix.
- `core/watchlist_controls_panel.py`
  - Watchlist controls, mode toggles, prewarm triggers, command center hook.
- `core/experience_panel.py`
  - Experience readiness panel.
- `core/portfolio_alert_panel.py`
  - Portfolio position + alert creation flow.
- `core/decision_trade_panel.py`
  - Decision journal + trade journal.
- `core/opportunity_filter_panel.py`
  - Opportunity filter/top5/scan controls.
- `core/warm_flow.py`
  - Warm lifecycle orchestration (sync/async/auto background warm).
- `core/analysis_outlook_panel.py`
  - Macro/micro outlook + probabilistic forecast render.
- `core/analysis_forecast_panel.py`
  - Forecast accuracy/benchmark/drift + forecast dashboards (portfolio/regime/leaderboard/sector mode).
- `core/analysis_forecast_service.py`
  - Forecast mode recommendation, drift guardrails, forecast calibration.
- `core/analysis_ai_panel.py`
  - Risk box + AI chat style + AI health panel.
- `core/analysis_financial_panel.py`
  - Financial health tab render.
- `core/analysis_view_panel.py`
  - 5S panel, health/readiness cards, evidence/downloads, detailed risk plan render.
- `core/action_center_panel.py`
  - Action center builders/render + portfolio option/final opportunity builders.
- `core/portfolio_kpi_panel.py`
  - Trade journal, alert dispatch summary, KPI/cohort/outcome tracker, smart upgrade prompt.
- `core/ops_tail_panel.py`
  - SLA + 5S, daily playbook dispatch/retry, scan overview, admin growth render tail.
- `core/analysis_runtime_service.py`
  - Snapshot/OHLCV/strategic-report cached loaders + prewarm orchestration + background warm wrapper.
- `core/analysis_chart_panel.py`
  - Candlestick/RSI/MOS chart render + OHLCV fallback + chart tab render wrapper.
- `core/portfolio_overview_panel.py`
  - Personal portfolio snapshot render block.
- `core/analysis_helper_service.py`
  - Shared helper logic: ticker extraction, health badge, profile-fit note.
- `core/engagement_panel.py`
  - Aha/value journey panel + Next Best Action 1-click CTA panel.
- `core/opportunity_3m_service.py`
  - Opportunity 3M board builder + benchmark 3M return loader.
- `core/scanner_service.py`
  - Scanner/autopilot/daily-action builders and free-plan simple-view helper.
- `core/ui_styles.py`
  - Global Streamlit custom style injector separated from app orchestration.
- `core/notification_contracts.py`
  - Unified notification channel contract (`NotificationChannels`) for cross-panel/service wiring.
- `core/runtime_flow_contracts.py`
  - Unified runtime flow contract (`RuntimeFlowConfig`) for watchlist/autopilot/warm orchestration.
- `core/auth_repository.py` + `core/auth_service.py`
  - Auth/PIN persistence and business rules extracted from `product_layer`.
- `core/secret_repository.py` + `core/secret_service.py`
  - Secret storage, encryption/decryption policy, and strict env-key handling extracted.
- `core/plan_usage_repository.py` + `core/plan_usage_service.py`
  - Plan/trial/usage gates and persistence extracted.
- `core/analytics_repository.py` + `core/analytics_service.py`
  - Event/KPI/cohort/admin/funnel analytics extracted.
- `core/trade_journal_repository.py` + `core/trade_journal_service.py`
  - Trade journal lifecycle + execution-vs-plan + realized performance extracted.
- `core/decision_repository.py` + `core/decision_service.py`
  - Decision journal/evaluation/scorecard/postmortem/monthly value extracted.
- `core/forecast_repository.py` + `core/forecast_service.py` + `core/forecast_accountability_service.py`
  - Forecast record lifecycle, benchmark/drift dashboards, accountability export/email extracted.

Kết quả: `app.py` đã giảm coupling rõ rệt ở các cụm sidebar + admin + ops.

## 2) Cụm còn lại nên refactor tiếp (ưu tiên)

### P0 — Nên làm sớm (1-2 tuần)

1. **Analysis render block** ✅ ĐÃ HOÀN THÀNH (small-batch)
   - Bao gồm: valuation summary, strategy highlights, indicator cards, evidence sections.
   - Đã tách thành các module: `core/analysis_summary_panel.py`, `core/analysis_outlook_panel.py`, `core/analysis_view_panel.py`, `core/analysis_ai_panel.py`, `core/analysis_financial_panel.py`.
2. **Action center & scan result render** ✅ ĐÃ HOÀN THÀNH CORE + UI CHÍNH
   - Bao gồm bảng cơ hội, portfolio suggestion render, explainability section.
   - Đã tách phần builder cốt lõi và UI chính vào `core/action_center_panel.py`.
   - Phần còn lại chủ yếu là tinh gọn naming/typing và gom thêm accountability export.

### P1 — Làm tiếp sau khi P0 ổn định (2-4 tuần)

3. **Forecast / accountability UI block** ✅ ĐÃ HOÀN THÀNH PHẦN FORECAST CORE
   - Các phần leaderboard, drift, benchmark, export report.
   - Đã tách phần forecast chính vào `core/analysis_forecast_panel.py` + `core/analysis_forecast_service.py`.
   - Đã gom accountability export/action vào `core/forecast_accountability_panel.py`.
4. **Notification configuration block** ✅ ĐÃ TÁCH
   - Gom input + validate + save secret.
   - Đã tách thành `core/notification_settings_panel.py`.

### P2 — Giai đoạn scale (4-8 tuần)

5. **Repository/Data access layer** 🔄 ĐANG TRIỂN KHAI MẠNH
   - SQL access đã tách đáng kể khỏi `product_layer` cho các domain: auth, secret, plan/usage, analytics, trade, decision, forecast.
   - Phần còn lại: chuẩn hóa các cụm chưa tách hết và chuẩn bị đường nâng cấp SQLite -> Postgres.
6. **Domain services chuẩn hóa** 🔄 ĐANG TRIỂN KHAI
   - Service interface đã thống nhất theo dependency injection ở phần lớn domain chính.
   - Phần còn lại: gom chuẩn naming/signature và loại bỏ hoàn toàn logic dữ liệu còn sót trong facade.

## 3) Quy tắc refactor bắt buộc

- Mỗi lần chỉ tách 1 cụm chức năng (small batch).
- Không đổi hành vi người dùng trong cùng PR nếu không bắt buộc.
- Sau mỗi lần tách:
  - chạy lint
  - chạy regression tests
  - kiểm tra manual flow chính: login -> analyze -> alert -> report.
- Module mới phải truyền dependency qua function arguments để giảm hidden coupling.

## 4) KPI theo dõi hiệu quả refactor

KPI kỹ thuật:
- `app.py` giảm dần số dòng và số khối logic đa nhiệm.
- Regression suite giữ ổn định (pass rate >= 99% trên CI).
- Không tăng lỗi runtime sau refactor.
- Trạng thái hiện tại: `app.py` chủ yếu còn vai trò orchestration (`main`); style injector và phần lớn business/panel logic đã tách module.

KPI vận hành:
- Queue fail ratio không tăng sau refactor.
- CX avg không giảm sau refactor.
- Thời gian xử lý incident không tăng.

## 5) Điều kiện dừng refactor để ưu tiên business

Tạm dừng refactor và quay lại feature/reliability nếu:
- CX avg < 70 liên tiếp.
- Queue fail ratio > 25%.
- Có incident P0/P1 cần xử lý nóng.

## 6) Next concrete step

Bước kế tiếp khuyến nghị: chạy regression rộng + chuẩn hóa naming/signature giữa các service để chốt trạng thái “facade-first” cho `product_layer`.
