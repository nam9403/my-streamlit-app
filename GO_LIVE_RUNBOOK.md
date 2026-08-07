# Go-Live Runbook

Runbook vận hành ngày phát hành, tối ưu để team có thể thao tác theo từng bước với tiêu chí pass/fail rõ ràng.

## 1) Mục tiêu

- Đưa bản mới lên production an toàn.
- Có tiêu chí dừng/rollback ngay khi phát hiện lỗi nghiêm trọng.
- Có bằng chứng kiểm tra sau deploy (log + checklist).

## 2) Vai trò tối thiểu

- **Release Owner**: điều phối toàn bộ phiên go-live.
- **Technical Owner**: xử lý sự cố kỹ thuật, quyết định rollback.
- **Product Owner**: xác nhận chất lượng nghiệp vụ/sign-off cuối.

## 3) Điều kiện trước giờ phát hành (T-60 đến T-15)

Tất cả lệnh chạy tại thư mục root dự án:

```bash
python scripts/preflight_check.py --prod
python scripts/prod_readiness_check.py
python scripts/smart_money_event_sync.py --symbols FPT,VNM,HPG,VCB
python scripts/dss_release_gate.py --symbol FPT --user-id default_user --strict
python scripts/live_data_stability_benchmark.py --window-days 14 --min-sessions 7 --require-go
python scripts/scale_gate_check.py
python scripts/slo_gate_check.py
python scripts/uat_gate.py
```

Tùy chọn chạy gộp (khuyến nghị):

```bash
python scripts/go_live_gate.py --env preprod
```

Dry-run để kiểm tra pipeline trước:

```bash
python scripts/go_live_gate.py --env preprod --dry-run
```

Pass khi:
- Tất cả lệnh trả exit code `0`.
- Không còn lỗi `critical`/`failed` trong output.
- Manual UAT checklist đã được tick đầy đủ bởi PO + TO.
- `scale_gate_check` không trả `FIX`.
- `slo_gate_check` không trả `FIX`.
- `dss_release_gate.py --strict` trả `COMMERCIAL_READY`.
- `smart_money_event_sync.py` ghi được events cấu trúc vào `data/smart_money_events.json`.
- `live_data_stability_benchmark.py --require-go` trả `GO` (đủ số phiên và không vi phạm ngưỡng).
- `artifacts/operations/go_live_gate_summary.json` có `decision=PASS` (nếu dùng lệnh gộp).
- `artifacts/operations/runtime_alert_guard_go_live.json` không ở trạng thái `critical`.

Nếu fail:
- Không triển khai.
- Ghi rõ nguyên nhân và mở ticket xử lý trước khi chạy lại.

## 4) Backup trước deploy (T-15 đến T-5)

Backup tối thiểu:
- `data/app_state.db`
- `data/app_state.db-wal` (nếu có)
- `data/app_state.db-journal` (nếu có)

Yêu cầu:
- Lưu bản backup có timestamp.
- Xác nhận restore thử được trên máy staging/instance test.

## 5) Triển khai production (T-0)

1. Chốt phiên bản (`VERSION`, release notes, tag `vX.Y.Z`).
2. Deploy artifact đúng môi trường.
3. Khởi chạy app bằng profile strict:

```bash
run_app.bat prod
```

hoặc:

```powershell
.\run_app.ps1 -Mode prod
```

## 6) Smoke test sau deploy (T+0 đến T+10)

Checklist bắt buộc:
- Mở dashboard thành công.
- Đăng nhập user test thành công.
- Phân tích 1-2 mã tiêu biểu (`FPT`, `VNM`) trả kết quả hợp lệ.
- Xuất PDF thành công.
- Chạy alert scan không lỗi.

Pass khi:
- Tất cả bước trên đạt.
- Không có lỗi nghiêm trọng trong terminal/log app.

## 7) Hypercare 60 phút đầu (T+10 đến T+70)

Theo dõi liên tục:
- Tỷ lệ lỗi request upstream (data provider/LLM).
- Latency tăng đột biến.
- Notification queue có tăng retry bất thường.
- Lỗi đăng nhập/báo cáo/timeout diện rộng.

Lệnh check nhanh khuyến nghị mỗi 10-15 phút:

```bash
python scripts/runtime_alert_guard.py --notify-on none --out artifacts/operations/runtime_alert_guard_hypercare.json
```

Khuyến nghị:
- Ghi snapshot trạng thái mỗi 15 phút.
- Lưu correlation id của các lỗi nổi bật để truy vết.

## 8) Tiêu chí rollback ngay lập tức

Rollback ngay nếu có một trong các điều kiện:
- Không đăng nhập được hoặc lỗi auth diện rộng.
- Không tạo được báo cáo phân tích/PDF trên luồng chính.
- Downtime liên tục > 5 phút.
- Tỷ lệ lỗi nghiêm trọng cao liên tục và không có workaround.

## 9) Quy trình rollback nhanh

1. Dừng phiên bản hiện tại.
2. Deploy lại tag ổn định gần nhất.
3. Khôi phục DB backup tương ứng nếu cần.
4. Khởi động lại app bằng cấu hình đã biết ổn định.
5. Chạy lại smoke test bắt buộc.
6. Thông báo trạng thái rollback cho stakeholder.

## 10) Kết thúc phiên go-live

Điều kiện đóng phiên:
- 60 phút hypercare không có sự cố blocker.
- Product Owner + Technical Owner cùng sign-off.
- Cập nhật release log: thời gian phát hành, sự cố (nếu có), hành động khắc phục.

## 11) Nightly operational check (khuyến nghị bắt buộc)

Sau go-live, bật kiểm tra nightly để phát hiện sớm regression:

```powershell
powershell -ExecutionPolicy Bypass -File "scripts/setup_nightly_runtime_scheduler.ps1" -Env preprod
```

Chạy tay ngay lập tức để xác minh:

```powershell
powershell -ExecutionPolicy Bypass -File "scripts/run_nightly_runtime_check.ps1" -Env preprod -SkipAudit
```

Artifacts theo dõi:
- `artifacts/performance/timing_dashboard.md`
- `artifacts/performance/pilot_kpi_snapshot_nightly.json`
- `artifacts/operations/runtime_guardian_health.json`
- `data/reports/logs/runtime_incidents.jsonl`

## 12) Overnight Autopilot scan (17:00–07:00, VPS 24/7)

Quét định kỳ universe thanh khoản sau giờ đóng cửa đến sáng hôm sau:

```powershell
# Một lệnh sau khi đưa code lên VPS (overnight scan mặc định BẬT)
powershell -ExecutionPolicy Bypass -File "scripts/bootstrap_vps.ps1" -Env preprod

# Chỉ overnight scan
powershell -ExecutionPolicy Bypass -File "scripts/setup_overnight_scan_scheduler.ps1" -EveryMinutes 30 -BatchSize 40 -Workers 3
```

- Task: `DuAn1_OvernightScan` (mỗi 30 phút; Python tự bỏ qua ngoài 17:00–07:00 giờ VN) — **bật sẵn** khi bootstrap VPS.
- State: `data/runtime/overnight_scan_state.json`
- Summary: `artifacts/operations/overnight_scan_tick_latest.json`
- Chạy tay một tick: `python scripts/run_overnight_scan_tick.py --force`
- Tắt nếu cần: `bootstrap_vps.ps1 -SkipOvernightScan`

## 13) Daily operations checklist (VPS 24/7)

Mỗi ngày (5-10 phút), kiểm tra nhanh:

1. Task Scheduler có trạng thái `Ready/Running` cho:
   - `DuAn1_BackgroundJobs`
   - `DuAn1_NightlyRuntimeCheck`
   - `DuAn1_OvernightScan` (mặc định sau bootstrap VPS)
2. Mở `artifacts/operations/runtime_guardian_health.json`:
   - `failures` không tăng bất thường
   - `suppressed_cooldown` không chiếm đa số kéo dài nhiều chu kỳ
3. Mở `data/reports/logs/runtime_incidents.jsonl`:
   - Không xuất hiện dồn dập cùng một `error_type` trong thời gian ngắn
4. Chạy tay nếu cần xác minh tức thời:

```powershell
python scripts/run_background_jobs.py --watchlist FPT,HPG,VNM --universe-limit 30 --queue-jobs 30
python scripts/guardian_health_check.py --in artifacts/operations/runtime_guardian_health.json --require-ok
```

## 14) Cấu hình khuyến nghị VPS 4GB

- Dùng preset: `.env.vps4gb.example` -> copy thành `.env`.
- Mục tiêu preset:
  - Giảm tải đồng thời (workers + batch) để tránh peak RAM.
  - Giữ đủ độ phủ thị trường nhờ auto-rotate thay vì quét full một lần.
  - Duy trì cảnh báo ổn định với Guardian cooldown và incident log.
- Nếu VPS yếu hơn hoặc giờ cao điểm: chuyển sang preset `.env.vps2gb.example`.
