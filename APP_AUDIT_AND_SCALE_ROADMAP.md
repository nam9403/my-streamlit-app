# App Audit and Scale Roadmap

Mục tiêu: hoàn thiện logic/tính năng hiện tại và tạo nền tảng tăng trưởng lớn.

## 1) Core logic & strategy quality

- `core/strategy_backtest.py`
  - [x] Bổ sung mô phỏng phí + trượt giá (`fee_bps`, `slippage_bps`) để kết quả thực tế hơn.
  - [ ] Bổ sung transaction log (entry/exit date, size, pnl) để debug chiến lược theo từng lệnh.
  - [ ] Tách benchmark thành chuẩn cố định theo cấu hình (VNINDEX/VN30/ETF) để so sánh nhất quán.
- `core/ai_logic.py`
  - [ ] Nâng final action từ rule cứng sang scoring đa yếu tố có trọng số hiệu chỉnh theo data quality.
  - [ ] Thêm calibration: đo độ chính xác khuyến nghị theo rolling window và tự giảm confidence khi drift.

## 2) Data reliability (micro/macro/news)

- `scrapers/portal.py`, `scrapers/financial_data.py`
  - [ ] Chuẩn hóa schema chất lượng dữ liệu (freshness, source tier, completeness).
  - [ ] Thêm circuit breaker theo source để tránh retry kéo dài gây treo UX.
- `core/data_quality.py`
  - [ ] Dùng quality gate trước khi generate report; nếu thiếu dữ liệu quan trọng thì downgrade action -> WATCH.

## 3) Product trust & risk control

- `app.py`
  - [ ] Hiển thị rõ confidence + data source + freshness ngay cạnh khuyến nghị BUY/HOLD/WATCH.
  - [ ] Bổ sung cảnh báo risk panel (volatility, max drawdown gần nhất, concentration risk).
- `scripts/app_effectiveness_2025_2026.py`
  - [ ] Thêm transaction-cost scenario matrix (low/base/stress) để tránh overfit 1 kịch bản.

## 4) Commercial readiness

- CI/CD
  - [x] Có `ci.yml`, `release.yml`, preflight, secret scan.
  - [ ] Thêm smoke test headless cho 1-2 luồng UI chính (khởi tạo report + export PDF).
- Security
  - [x] Loại hardcoded key, nâng hash PIN, nâng encrypt secret.
  - [ ] Thêm lockout/rate-limit cho đăng nhập sai nhiều lần.

## 5) Priority execution order

1. **P0 (1-2 tuần):** benchmark consistency + transaction log + quality gate trước action.
2. **P1 (2-4 tuần):** calibration confidence + risk panel + scenario backtest matrix.
3. **P2 (4-8 tuần):** portfolio optimizer nhiều mã + automated model monitoring.

## 6) Success metrics

- Sai lệch giữa backtest và forward test giảm xuống < 30%.
- Tỷ lệ khuyến nghị bị hạ cấp do data-quality được ghi nhận minh bạch 100%.
- Thời gian tạo report < 3 giây ở chế độ cache-hit.
- Crash-free sessions > 99%.

