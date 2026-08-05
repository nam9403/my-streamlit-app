# Rollback Drill Checklist

Checklist diễn tập rollback định kỳ (khuyến nghị mỗi tháng hoặc trước major release).

## Scope

- Môi trường: Staging / Production-like
- Phiên bản test:
- Phiên bản rollback target:
- Drill owner:
- Date:

## Pre-Drill

- [ ] Backup dữ liệu hiện tại (db + metadata) thành công.
- [ ] Có artifact của stable release để rollback.
- [ ] Đã thông báo khung giờ drill cho team liên quan.
- [ ] Chốt tiêu chí pass/fail cho drill.

## Drill Execution

- [ ] Deploy phiên bản mới mô phỏng có lỗi.
- [ ] Xác nhận lỗi/symptom theo kịch bản.
- [ ] Thực hiện rollback về stable release.
- [ ] Khôi phục dữ liệu từ backup (nếu kịch bản yêu cầu).
- [ ] Khởi động lại services theo runbook.

## Post-Rollback Validation

- [ ] Đăng nhập user test thành công.
- [ ] Chạy phân tích 1-2 mã chính thành công.
- [ ] Export report/PDF thành công.
- [ ] Queue/notification hoạt động bình thường.
- [ ] Không có lỗi blocker trong logs.

## Metrics Capture

- Time to detect:
- Time to rollback:
- Time to restore:
- Total recovery time:
- Issues found during drill:

## Exit Criteria

- [ ] Tất cả bước validation pass.
- [ ] Ghi lại lesson learned.
- [ ] Tạo action items với owner + deadline.

