# Investment Intelligence Dashboard

Ứng dụng web phân tích cổ phiếu Việt Nam bằng Streamlit, kết hợp định giá, chiến lược, cảnh báo và báo cáo PDF.

## Tính năng chính

- Snapshot dữ liệu tài chính và giá cho mã cổ phiếu.
- Báo cáo chiến lược tự động (valuation, MOS, luận điểm hành động).
- Xuất báo cáo PDF chuyên nghiệp.
- Backtest chiến lược cơ bản.
- Cảnh báo theo ngưỡng và theo dõi watchlist.

## Yêu cầu môi trường

- Python 3.11+ (khuyến nghị 3.12)
- Windows/macOS/Linux

## Cài đặt nhanh

```bash
python -m venv .venv
.venv\Scripts\activate
python -m pip install -r requirements.txt
python -m pip install -r requirements-dev.txt
```

## Cấu hình biến môi trường

1. Sao chép `.env.example` thành `.env` (hoặc set trực tiếp vào hệ thống).
2. Thiết lập API keys theo nhu cầu:

```bash
setx GROQ_API_KEYS "gsk_key_1;gsk_key_2"
setx OPENAI_API_KEYS "sk_key_1;sk_key_2"
setx GEMINI_API_KEYS "AIza_key_1;AIza_key_2"
```

3. (Khuyến nghị production) đặt key mã hóa app:

```bash
setx II_APP_SECRET_KEY "your_fernet_key_here"
```

> Lưu ý: không commit `.env` và không hardcode API key vào mã nguồn/batch script.

### PostgreSQL runtime (optional, production-ready path)

Nếu muốn chạy backend PostgreSQL thay cho SQLite:

```bash
docker compose -f docker-compose.postgres.yml up -d
setx II_DB_URL "postgresql://ii_user:ii_pass@localhost:5432/ii_app"
python scripts/bootstrap_postgres.py --check-only
python scripts/bootstrap_postgres.py
python scripts/migrate_sqlite_to_postgres.py --sqlite-path data/app_state.db --postgres-dsn postgresql://ii_user:ii_pass@localhost:5432/ii_app
```

`preflight_check.py --prod` sẽ tự fail nếu `II_DB_URL` là PostgreSQL nhưng thiếu driver `psycopg/psycopg2`.

## Chạy ứng dụng

```bash
python -m streamlit run app.py
```

Hoặc dùng script Windows:

```bash
run_app.bat             # DEV-FAST (mặc định)
run_app.bat dev
run_app.bat prod        # PROD-STRICT
run_app_prod.bat        # shortcut cho production
.\run_app.ps1
.\run_app.ps1 -Mode prod
```

Trước khi mở Streamlit, `run_app.bat` và `run_app.ps1` chạy nhanh `tests/test_candlestick_hover_compat.py`. Để bỏ qua: CMD `set SKIP_PREFLIGHT=1`, PowerShell `$env:SKIP_PREFLIGHT="1"` hoặc `.\run_app.ps1 -SkipPreflight`.

`PROD-STRICT` sẽ:
- Tắt đọc stale disk cache (`II_READ_STALE_DISK=0`).
- Tăng timeout/live budget để ưu tiên dữ liệu mới.
- Bắt buộc có `II_APP_SECRET_KEY` (`II_REQUIRE_APP_SECRET_KEY=1`).
- Bật gộp fundamentals live khi có mock (`II_MERGE_LIVE_FUNDAMENTALS=1`) và giới hạn tải scanner (`II_SCAN_*` trong script prod).

## Kiểm thử & health check

```bash
python -m pytest -q
python scripts/quality_gate.py
python scripts/quality_gate.py --strict-static
python scripts/architecture_gate.py --strict
python scripts/generate_engineering_scorecard.py
python scripts/update_engineering_scorecard_history.py
python scripts/release_readiness_summary.py
python scripts/check_secrets.py
python scripts/health_check.py
python scripts/health_check.py --full
python scripts/benchmark_runtime_6s.py --symbol FPT
python scripts/pre_release_perf_gate.py --max-regress-pct 20
```

Artifacts kiến trúc/sức khỏe kỹ thuật được sinh tại:
`artifacts/architecture/`

## Bảo mật

- Xem thêm tài liệu tại `SECURITY.md`.
- Nếu nghi ngờ lộ key: rotate key ngay, thu hồi key cũ, và kiểm tra log truy cập.

## Incident readiness

- Postmortem template: `INCIDENT_POSTMORTEM_TEMPLATE.md`
- Rollback drill checklist: `ROLLBACK_DRILL_CHECKLIST.md`
- Tạo nhanh incident report:

```bash
python scripts/create_incident_report.py --incident-id INC-2026-001 --severity SEV-2 --title "Service degradation" --owner "release-owner"
```

## Phát hành (Release)

- Checklist phát hành và rollback: `RELEASE_CHECKLIST.md`
- Hướng dẫn triển khai staging/production: `DEPLOYMENT.md`
- Checklist UAT trước public beta: `UAT_CHECKLIST.md`
- Runbook phát hành ngày go-live: `GO_LIVE_RUNBOOK.md`
- Lộ trình tách monolith an toàn: `ARCHITECTURE_REFACTOR_MAP.md`
- Release notes riêng cho module biểu đồ kỹ thuật: `CHART_MODULE_RELEASE_NOTES.md`
- CI tự động: `.github/workflows/ci.yml`
- Release workflow theo tag `vX.Y.Z`: `.github/workflows/release.yml`
- Cấu hình phân loại release notes: `.github/release.yml`
- Phiên bản hiện tại lấy từ file `VERSION`

Chuẩn bị phát hành nhanh:

```bash
python scripts/bump_version.py patch
python scripts/preflight_check.py
python scripts/preflight_check.py --prod
python scripts/prod_readiness_check.py
python scripts/architecture_gate.py --strict
python scripts/release_readiness_summary.py --strict
python scripts/scale_gate_check.py
python scripts/uat_gate.py
python scripts/export_pilot_kpi_snapshot.py
python scripts/release_prep.py
python scripts/release_prep.py --full
python scripts/generate_release_notes.py
python scripts/release_all_in_one.py --bump patch
```

`release_all_in_one.py` đã bao gồm bước sinh `dist/release-notes.md` thông qua `release_prep.py`.

## Monthly accountability automation

Chạy tay:

```bash
python scripts/run_monthly_accountability.py --force
python scripts/run_monthly_accountability.py --force --send-email
python scripts/run_monthly_accountability.py --force --retention-days 180
```

Script có idempotency theo tháng (tránh gửi trùng) và lưu run log tại:
`data/reports/logs/monthly_accountability_runs.jsonl`

Thiết lập Windows Task Scheduler:

```powershell
powershell -ExecutionPolicy Bypass -File "scripts/setup_monthly_accountability_scheduler.ps1" -SendEmail
```

## Trạng thái thương mại hóa

Project đã có nền tảng kỹ thuật tốt để chạy pilot/private beta. Trước public launch, cần đảm bảo:

- Quy trình CI/CD ổn định.
- Chính sách bảo mật và vận hành rõ ràng.
- Giám sát lỗi runtime và cảnh báo vận hành (Sentry/log aggregation).

