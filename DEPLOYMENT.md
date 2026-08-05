# Deployment Guide

Tài liệu triển khai tối thiểu cho môi trường staging/production.

## 1) Chuẩn bị môi trường

- Python 3.12 (khuyến nghị đồng nhất với CI).
- Cài dependencies:

```bash
python -m pip install -r requirements.txt
python -m pip install -r requirements-dev.txt
```

- Thiết lập biến môi trường bắt buộc:
  - `II_APP_SECRET_KEY`
  - ít nhất một trong các nhóm key LLM nếu dùng AI live:
    - `GROQ_API_KEYS`
    - `OPENAI_API_KEYS`
    - `GEMINI_API_KEYS`

Mẹo nhanh cho VPS 4GB:

```bash
copy .env.vps4gb.example .env
```

Sau đó chỉ cần điền thêm các secret thực tế (`II_APP_SECRET_KEY`, Telegram/SMTP, API keys).

### Quét đêm Autopilot (khuyến nghị VPS)

Ban đêm chạy batch liquid (~400 mã HOSE/VN30), sáng UI lấy Top 10 từ board đã lưu:

```bash
python scripts/run_autopilot_nightly_scan.py --batch-size 40 --workers 3
python scripts/autopilot_nightly_board_health.py --min-coverage 80 --require-ok
```

Windows Task Scheduler:

```powershell
powershell -File scripts/setup_autopilot_nightly_scan_scheduler.ps1 -RunHour 22 -RunMinute 30 -BatchSize 40
```

Env: `II_AUTOPILOT_NIGHTLY_BOARD=1`, `II_AUTOPILOT_NIGHTLY_MAX_AGE_HOURS=36`,
`II_AUTOPILOT_NIGHTLY_REFRESH_PRICES=1`.

Morning digest (Telegram/webhook):

```bash
python scripts/send_morning_digest.py --dry-run
powershell -File scripts/setup_morning_digest_scheduler.ps1 -RunHour 7 -RunMinute 30
```

Telegram bot daemon (interactive `/p`, `/top`, `/watch` + auto digest 08:15 + watchlist alerts):

```bash
# Cần TELEGRAM_BOT_TOKEN + TELEGRAM_CHAT_ID trong .env
python scripts/run_telegram_bot_daemon.py --dry-run
python scripts/run_telegram_bot_daemon.py
```

PowerShell (chạy nền trên máy local):

```powershell
Start-Process -WindowStyle Hidden -FilePath python `
  -ArgumentList "scripts/run_telegram_bot_daemon.py" `
  -WorkingDirectory (Get-Location) `
  -RedirectStandardOutput "data\runtime\telegram_bot.out.log" `
  -RedirectStandardError "data\runtime\telegram_bot.err.log"
```

Kế hoạch hoàn thiện 10/10: `SYSTEM_10_OF_10_COMPLETION_PLAN.md`.

Fallback cho VPS 2GB (ưu tiên ổn định):

```bash
copy .env.vps2gb.example .env
```

## 2) Kiểm tra trước deploy

```bash
python scripts/check_secrets.py
python -m pytest -q
python scripts/health_check.py
```

Staging smoke (có mạng):

```bash
python scripts/health_check.py --full
python scripts/verify_streamlit_startup.py
```

## 3) Chạy ứng dụng

```bash
python -m streamlit run app.py --server.headless true
```

Hoặc Windows local:

```bash
run_app.bat
```

## 4) Dữ liệu runtime cần backup

- `data/app_state.db`
- `data/app_state.db-wal` (nếu tồn tại)
- `data/app_state.db-journal` (nếu tồn tại)
- `data/.app_secret.key` (nếu không dùng `II_APP_SECRET_KEY` từ env)

## 5) Rollback nhanh

1. Dừng service bản hiện tại.
2. Checkout tag ổn định gần nhất.
3. Khôi phục DB backup tương ứng (nếu schema khác biệt).
4. Thiết lập lại env vars của phiên bản cũ.
5. Khởi động lại app.
6. Chạy smoke test:
   - mở dashboard
   - chạy 1 phân tích mã
   - xuất PDF
   - kiểm tra cảnh báo

## 6) Sau deploy

- Theo dõi lỗi runtime và timeout upstream.
- Kiểm tra hàng đợi notification/background job.
- Kiểm tra tỷ lệ request thất bại trong 30-60 phút đầu.

## 6.1) Thiết lập 24/7 trên VPS (khuyến nghị)

Thiết lập một lần:

```powershell
powershell -ExecutionPolicy Bypass -File "scripts/setup_vps_24x7_scheduler.ps1" -Env preprod -EveryMinutes 15 -Watchlist "FPT,HPG,VNM" -UniverseLimit 30 -QueueJobs 30 -NightlyRunHour 23 -NightlyRunMinute 30
```

Lệnh trên sẽ tạo/cập nhật 2 task:
- `DuAn1_BackgroundJobs`: quét nền + xử lý queue theo chu kỳ phút.
- `DuAn1_NightlyRuntimeCheck`: chạy gate runtime mỗi đêm.

Health artifact quan trọng để theo dõi từ xa:
- `artifacts/operations/runtime_guardian_health.json`
- `artifacts/operations/runtime_alert_guard_nightly.json`
- `data/reports/logs/runtime_incidents.jsonl`

## 7) Hướng mở rộng (~1000 người dùng đăng ký)

**Phân biệt:** 1000 *tài khoản* khác 1000 người *cùng lúc* trên Streamlit. Một tiến trình Streamlit phục vụ nhiều phiên bằng session; tải thực tế phụ thuộc **số phiên đồng thời** và các thao tác nặng (scanner, PDF, LLM).

**Ưu tiên kỹ thuật (theo thứ tự):**

1. **PostgreSQL** (`II_DB_URL`) thay SQLite cho dữ liệu người dùng/watchlist/notification khi vượt ~1 máy hoặc cần backup HA — repo đã có `docker-compose.postgres.yml`, `bootstrap_postgres.py`, migrate.
2. **Giới hạn tải song song** phía app và upstream: biến `II_SCAN_*`, budget portal (`II_PORTAL_*`) — tránh burst API/throttling khi nhiều người bấm cùng lúc.
3. **Nhiều bản chạy Streamlit** sau reverse proxy (hoặc orchestrator) khi đo được **đồng thời** cao; cần session sticky hoặc giảm trạng thái phụ thuộc server (ưu tiên state trong DB).
4. **Hàng đợi cho việc nặng** (xuất PDF, batch scan, email): tách worker (RQ/Celery/cron) khỏi luồng request UI khi độ trễ chấp nhận được vài giây–vài phút.
5. **Quan sát & SLO:** log tập trung, health check định kỳ, cảnh báo khi timeout/error rate tăng.

**Mốc thực tế:** Với web Streamlit đơn giản, **hàng trăm user đồng thời** thường đã cần **nhân bản + DB tách + cache/giới hạn**; 1000 user *đăng ký* với vài chục đồng thời có thể đủ với **1–2 instance + Postgres + giới hạn scanner** nếu không ép mọi người chạy scan toàn thị trường cùng lúc.

