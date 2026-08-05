# Mô tả vận hành hệ thống để phân tích cải tiến

> Thời điểm rà soát: 17/07/2026. Tài liệu này mô tả code hiện tại, không xem các báo cáo readiness cũ là bằng chứng còn hiệu lực.

## 1. Hệ thống làm gì

Đây là ứng dụng Streamlit hỗ trợ phân tích cổ phiếu Việt Nam. Hệ thống kết hợp:

- dữ liệu giá, OHLCV, báo cáo tài chính và tin tức;
- định giá, chỉ báo kỹ thuật, Piotroski F-Score, MOS và nhận diện pha thị trường;
- phân tích chiến lược “7 Whys”, dự phóng xác suất và Monte Carlo;
- scanner, Auto Pilot, Finder, watchlist và bảng việc cần làm;
- quản lý danh mục, quyết định, giao dịch, cảnh báo và hậu kiểm dự báo;
- AI đa nhà cung cấp: Groq, OpenAI, Gemini, có xoay key, cooldown và fallback không dùng LLM;
- notification qua Telegram, webhook và SMTP;
- SQLite mặc định, PostgreSQL là đường triển khai production/multi-instance;
- background cycle, durable PostgreSQL jobs, health checks, release gates và runtime artifacts.

Hệ thống là một modular monolith: UI, domain service, data access và worker đã được tách thành nhiều file, nhưng vẫn chạy quanh một tiến trình Streamlit và một facade lớn là `core/product_layer.py`.

## 2. Thành phần và ranh giới kiến trúc

### 2.1 Presentation/orchestration

- `app.py`: entrypoint và composition root thực tế. File hiện có 768 dòng, import trực tiếp hơn 50 module và truyền nhiều hàm service vào panel.
- `core/app_bootstrap.py`: cấu hình page, style và observability.
- `core/app_sidebar_*`, `core/app_*_panel.py`, `core/analysis_*_panel.py`: UI Streamlit theo vùng chức năng.
- `st.session_state`: giữ trạng thái phiên như user, ticker, chế độ UI, report/OHLCV cache, job đang poll và kết quả scan.

### 2.2 Application services

- `core/app_analysis_orchestration.py`: điều phối phân tích đồng bộ/nền, quota, cache, logging và forecast snapshot.
- `core/analysis_runtime_service.py`: loader snapshot/OHLCV/report có `st.cache_data`.
- `core/scanner_service.py`: prefilter, quét song song, xếp hạng Auto Pilot và daily action.
- `core/background_jobs.py`: prewarm, super-stock, intraday flow, smart-money seed và notification queue.
- `core/warm_flow.py`, `core/ui_bg_analysis.py`, `core/pg_analysis_jobs.py`: warm-up và hai cơ chế job nền.

### 2.3 Domain/decision engine

- `core/engine.py`: chuẩn hóa OHLCV, MA20/MA50, RSI14, volume metrics, market phase và backtest rule.
- `core/valuation.py`, `core/elite_valuation.py`: định giá và biên an toàn.
- `core/ai_logic.py`: hợp nhất dữ liệu, 7 Whys, LLM routing, forecast, risk plan, confidence/reliability gates và action cuối.
- Các service forecast, decision, trade journal, portfolio protector, flow, opportunity và accountability phụ trách từng miền.

### 2.4 Persistence

- `core/product_layer.py`: facade public cho UI; đồng thời còn chứa schema, một phần SQL, notification transport và nhiều rule sản phẩm.
- Các repository/service đã tách: auth, secret, plan/usage, analytics, decision, trade, forecast và notification queue.
- `core/db_runtime.py` chọn backend từ `II_DB_URL`.
- `core/db_connection_factory.py` trả SQLite connection hoặc PostgreSQL connection bọc lớp tương thích placeholder.
- SQLite mặc định tại `data/app_state.db`, WAL mode; PostgreSQL dùng `psycopg`.
- OHLCV có store riêng, cache JSON và cache trong RAM; các runtime artifact khác nằm trong `data/` và `artifacts/`.

### 2.5 External integrations

- Giá/OHLCV: VNDirect, FireAnt, Yahoo chart API và tùy chọn yfinance.
- Tài chính: VNDirect ratios/statements, FireAnt, cache đĩa.
- Tin tức: CafeF và VietStock.
- AI: Groq, OpenAI, Gemini.
- Delivery: Telegram Bot API, webhook và SMTP.

## 3. Trình tự khởi động

1. Người vận hành chạy `run_app.bat`, `run_app.ps1` hoặc `python -m streamlit run app.py`.
2. Script chọn profile `dev` hoặc `prod` và thiết lập nhiều env:
   - dev ưu tiên app mở nhanh, cache/stale có kiểm soát, worker thấp và Lite UI;
   - prod không đọc stale OHLCV disk cache, timeout dài hơn, scan lớn hơn và bắt buộc `II_APP_SECRET_KEY`.
3. Có thể tự mở PostgreSQL analysis worker nếu `II_AUTO_START_PG_WORKER=1`.
4. Streamlit import `app.py`; import `core.product_layer` kéo theo `_init_db()` và tạo/migrate schema ngay lúc import.
5. `main()` gọi `bootstrap_app_ui()`, dựng sidebar account/runtime, xác định user, plan, profile, capital, watchlist và notification config.
6. `enforce_auth_gate()` chặn luồng chính nếu user cần PIN mà session chưa xác thực.
7. UI render theo thứ tự watch board, daily action, Auto Pilot, Finder/scan, ô nhập ticker, phân tích và các tab chi tiết.

Lưu ý drift tài liệu: README nói launcher chạy preflight chart trước khi mở app, nhưng `run_app.bat` hiện chỉ chạy khi `RUN_PREFLIGHT=1`; mặc định đi thẳng tới Streamlit.

## 4. Luồng người dùng chính

### 4.1 Account và entitlement

1. User nhập/đăng ký PIN.
2. PIN dùng PBKDF2-SHA256, 210.000 vòng.
3. App tải plan `free/pro/expert`, quota và feature flags.
4. Mỗi phân tích/scan gọi `can_use_feature()`, sau đó `record_usage()`.
5. Event được ghi vào bảng analytics để tính KPI, cohort, activation và upgrade funnel.

### 4.2 Mở app nhanh

- `II_FAST_SHELL_DEFAULT` mặc định bật.
- Lite UI giảm các panel nặng.
- Auto Pilot và Finder có thể bị defer tới khi user bấm mở.
- Watch board dùng snapshot cache để hiện thông tin có sớm.
- Warm/prefetch chỉ chạy khi không ở Lite UI và fast shell tắt.

### 4.3 Phân tích một mã

1. Ticker đến từ sidebar, Auto Pilot, Finder hoặc `st.chat_input`.
2. `resolve_analysis_report()` tạo cache key từ user, ticker, profile, capital, plan, quick mode và LLM mode.
3. Thứ tự đọc:
   - report hiện tại trong `st.session_state`;
   - day cache trên đĩa;
   - kết quả background job đã hoàn thành;
   - nếu chưa có, trả skeleton chỉ gồm snapshot + valuation.
4. Khi user yêu cầu full analysis:
   - kiểm tra quota;
   - chạy đồng bộ, thread nền cục bộ hoặc enqueue PostgreSQL job;
   - tải snapshot;
   - tính valuation;
   - tải OHLCV, financial indicators và news;
   - tính technical indicators, market phase và backtest;
   - tạo 7 Whys bằng LLM hoặc template fallback;
   - dựng probabilistic forecast, Monte Carlo, portfolio protector và deep insight;
   - tính confidence, data reliability, signal alignment và output quality;
   - áp guardrail để hạ BUY thành HOLD/WATCH khi dữ liệu hoặc cấu trúc risk plan không đạt;
   - calibrate forecast theo lịch sử, ghi forecast snapshot, event và day cache.
5. UI render quick dashboard, chart, action/risk plan, AI explanation, financial evidence, portfolio và accountability.

### 4.4 Scanner/Auto Pilot/Finder

1. Universe lấy từ danh sách mã Việt Nam và có thể xoay cửa sổ theo ngày.
2. Với universe lớn, scanner prefilter theo thanh khoản.
3. Deep scan chạy theo batch và `ThreadPoolExecutor`.
4. Mỗi mã tải snapshot, report quick mode và OHLCV.
5. Kết quả dùng action từ strategic report nếu có; nếu không thì dùng rule expected return/risk/phase.
6. Xếp hạng theo action, expected return, MOS, F-Score và risk.
7. Plan free bị giới hạn số dòng/cột hoặc quota.

## 5. Chuỗi dữ liệu và fallback

### 5.1 OHLCV

Thứ tự chính:

1. memory cache;
2. OHLCV store fast path;
3. incremental VNDirect delta;
4. disk cache fast path nếu cấu hình cho phép;
5. VNDirect live;
6. FireAnt;
7. Yahoo;
8. yfinance nếu cần độ sâu lớn hơn;
9. disk cache fallback.

Payload gắn `source`, `saved_at`, `age_sec`, `is_stale` và `fallback_chain`. Có guard tránh ticker Việt Nam bị trùng ticker thị trường Mỹ và sai thang giá.

### 5.2 Financial indicators

Thứ tự chính:

1. memory cache;
2. stale-while-revalidate/disk fast path;
3. VNDirect ratios;
4. VNDirect financial statements;
5. FireAnt;
6. disk cache;
7. snapshot-derived chỉ khi strict real-data mode không bắt buộc.

### 5.3 News

Memory cache -> disk cache còn fresh -> CafeF/VietStock chạy song song -> stale disk fallback trong giới hạn tuổi.

### 5.4 Cache layers

- Streamlit `st.cache_data`: snapshot 300 giây, OHLCV 300 giây, strategic report 240 giây.
- In-process memory cache trong portal.
- JSON disk cache cho OHLCV, financial và news.
- OHLCV store lâu dài.
- Day cache pickle cho full analysis.
- Session cache cho report đang xem.

## 6. AI và logic ra quyết định

### 6.1 LLM routing

- Nhận nhiều API key qua env.
- Sắp key theo fail count và latency trung bình.
- Key lỗi 401/403/429/quota/timeout bị cooldown.
- Mode speed/balanced/quality quyết định thứ tự Groq/OpenAI/Gemini.
- Response cache trong RAM theo fingerprint.
- Nếu confidence dữ liệu nền thấp, hệ thống có thể gọi lại provider theo quality mode.
- Nếu mọi provider lỗi hoặc không có key, dùng template 7 Whys deterministic.

### 6.2 Forecast và action

- Forecast kết hợp phase bias, tăng trưởng, D/E, valuation gap, volume và news.
- Monte Carlo dùng GBM với 8.000 simulations và random seed cố định.
- Confidence tính từ technical, financial quality, news, LLM và backtest.
- Reliability tách technical, financial, news và backtest.
- Action cơ sở:
  - confidence dưới gate: WATCH;
  - MOS/F-Score/phase tốt: BUY;
  - điều kiện trung bình: HOLD;
  - còn lại: AVOID.
- Guardrails có thể hạ action khi:
  - tín hiệu xung đột;
  - earnings quality cảnh báo;
  - smart-money reliability thấp;
  - Entry/SL/TP hoặc RR không hợp lệ;
  - data reliability dưới 55;
  - forecast drift.
- Mỗi recommendation được append vào audit JSONL với provenance và do-not-act reasons.

## 7. Dữ liệu người dùng và vòng lặp sản phẩm

Các entity chính:

- user/plan/usage;
- PIN auth và encrypted secrets;
- holdings và alerts;
- decisions và trades;
- forecast records;
- notification queue/sent markers;
- analytics events và CX score;
- premium trial.

Vòng lặp sản phẩm:

`phân tích -> lưu quyết định Entry/SL/TP -> mở/đóng trade -> hậu kiểm -> cập nhật discipline/forecast accuracy -> điều chỉnh coach, position sizing và next-best-action`.

## 8. Background processing

### 8.1 Local mode

- Full analysis chạy daemon thread.
- Status lưu JSON và payload lưu pickle trong `data/runtime/ui_bg_jobs`.
- Streamlit fragment poll mỗi 2 giây và rerun khi job xong.
- Cơ chế này chỉ phù hợp một máy/instance và phụ thuộc filesystem cục bộ.

### 8.2 PostgreSQL durable mode

- Job nằm trong `ii_async_jobs`.
- Worker dùng lease và `FOR UPDATE SKIP LOCKED`.
- Hỗ trợ idempotency key, reclaim lease hết hạn, result/error và nhiều worker.
- Payload kết quả vẫn serialize bằng pickle trong BYTEA.

### 8.3 Scheduled cycle

`run_background_cycle()` tuần tự thực hiện:

1. prefetch snapshot/financial/report;
2. super-stock signal + cooldown guardian;
3. intraday/daily flow analysis + sector adjustment + journal;
4. smart-money news seed;
5. notification queue.

Windows Task Scheduler được dùng để chạy cycle 24/7 và nightly gate.

## 9. Deployment, observability và quality gate

### Deployment

- Python 3.11+, CI dùng 3.12.
- Streamlit chạy headless trên VPS.
- SQLite cho local/single instance; PostgreSQL cho production/multi-instance.
- Khi scale cần reverse proxy, sticky session hoặc giảm phụ thuộc session state.

### Observability

- JSON console logging.
- Correlation ID qua `contextvars`.
- Timing metrics append vào JSONL.
- Source SLA lưu local JSON.
- Runtime incident, guardian health, queue health và benchmark lưu thành artifacts.
- Chưa thấy tích hợp production telemetry tập trung như Sentry/OpenTelemetry/APM trong runtime chính.

### CI

- Ubuntu + Python 3.12.
- Quality gate, secret scan, `pip-audit`, offline health check.
- PostgreSQL integration job riêng.
- Điểm quan trọng: CI gọi `quality_gate.py` không có `--strict-static`, nên ruff/mypy/architecture lỗi chỉ warning; test và pip-audit mới blocking.

## 10. Kết quả rà soát hiện tại

### Bằng chứng chạy ngày 17/07/2026

- Có 136 file `tests/test_*.py`.
- `python -m ruff check app.py core scrapers scripts`: FAIL, 5 lỗi.
  - import chưa sắp xếp trong `app.py`, `core/analysis_job_runner.py`, `core/app_analysis_orchestration.py`;
  - một import không dùng trong `app.py`;
  - biến `plan_id` gán nhưng không dùng trong `core/analysis_job_runner.py`.
- `python -m pytest -q`: tiến tới 65 test marker rồi không có tiến triển thêm trong hơn 2 phút; đã dừng sau khoảng 6 phút 43 giây. Không thể tuyên bố suite hiện tại PASS.
- Báo cáo ngày 01/05/2026 từng ghi 203 pass, coverage 44,17% và GO controlled rollout, nhưng không còn đủ để chứng minh trạng thái hiện tại:
  - `app.py` tăng từ 615 lên 768 dòng;
  - test files tăng từ 106 lên 136;
  - dependency map và readiness artifacts chưa phản ánh toàn bộ thay đổi mới.

## 11. Điểm mạnh

1. Có guardrail quyết định rõ hơn nhiều dashboard phân tích thông thường.
2. Data path có nhiều fallback, freshness metadata và source SLA.
3. Có quick shell, Lite UI, prefilter và cache nhiều lớp để phù hợp VPS thấp.
4. Đã có domain service/repository cho các miền quan trọng.
5. Có PostgreSQL integration và durable job queue, không chỉ dừng ở SQLite prototype.
6. Có forecast accountability, audit log, postmortem và vòng lặp học từ lịch sử.
7. Test footprint rộng, gồm data, AI, forecast, DB, UI smoke, release và operations.

## 12. Rủi ro và nợ kỹ thuật

### P0

1. Không có bằng chứng test suite hiện tại hoàn thành; cần xác định test treo và đặt timeout.
2. Static gate trong CI không blocking, trong khi branch hiện có lỗi ruff.
3. Readiness artifacts bị stale nhưng vẫn có thể tạo cảm giác hệ thống đang GO; nhiều gate có thể PASS dù UAT chưa ký, runtime critical hoặc live-data đang HOLD.
4. `product_layer.py` khởi tạo/migrate DB khi import, làm import có side effect và khó test/deploy an toàn.
5. Auth session hiện lưu boolean `auth_ok`, không gắn `user_id`; đổi sang user khác đã tồn tại có thể tái dùng trạng thái xác thực cũ. Các mutation kế hoạch/secret/queue có thể chạy trước auth gate.
6. Notification queue chưa claim nguyên tử; hai scheduler đồng thời có thể gửi trùng. Credential Telegram/SMTP có thể nằm plaintext trong payload queue.
7. PostgreSQL worker lease không heartbeat; job dài hơn lease có thể bị claim lại. Một số SQL repository chưa portable hoàn toàn (ví dụ `LIMIT -1`).
8. Chưa có telemetry tập trung; sự cố multi-instance khó điều tra bằng JSONL cục bộ. `.env` không được tự nạp trong runtime/launcher.

### P1

1. `app.py`, `product_layer.py`, `ai_logic.py`, `portal.py`, `background_jobs.py` vẫn là các điểm tập trung trách nhiệm lớn.
2. UI truyền hàng chục callable qua panel: giảm hidden import coupling nhưng tạo signature coupling rất cao.
3. Nhiều `except Exception` nuốt lỗi hoặc hạ cấp im lặng; user khó phân biệt dữ liệu thật, fallback và lỗi.
4. Cache/session/filesystem khiến local mode không phù hợp scale ngang.
5. Scanner tạo nhiều request và thread; `fetch_ohlcv_history_batch()` hiện bỏ qua `max_concurrency` và chạy tuần tự.
6. Job/result pickle chỉ an toàn khi toàn bộ storage là trusted; không nên coi là định dạng trao đổi giữa trust boundary.
7. PostgreSQL compatibility wrapper thay `?` bằng `%s` theo chuỗi đơn giản, có thể rủi ro khi SQL phức tạp.
8. Schema tự quản bằng DDL trong code, chưa phải migration framework có revision/rollback chuẩn.
9. Forecast accountability còn điểm yếu: resolve bằng giá hiện tại thay vì giá đúng due date; metric “MAPE” thực chất là MAE theo điểm phần trăm; horizon lịch và phiên giao dịch chưa đồng nhất.
10. JSON cache/guardian artifacts thiếu khóa liên tiến trình và atomic replace; flow cooldown fingerprint dùng `hash()` không ổn định sau process restart.

### P2

1. Business rule, transport, persistence và analytics còn lẫn trong facade.
2. Nhiều cấu hình env phân tán, khó biết profile hiệu lực và khó validate drift.
3. Tài liệu launcher/preflight không khớp code.
4. Forecast hiện chứa nhiều heuristic; cần calibration theo out-of-sample, regime và dữ liệu đủ lớn trước khi dùng như lợi thế thương mại.
5. Streamlit phù hợp pilot nhưng sẽ thành giới hạn nếu cần API/mobile, multi-tenant và tải đồng thời cao.

## 13. Đề xuất cải tiến theo thứ tự

### 0-2 tuần: khôi phục bằng chứng tin cậy

1. Cô lập test treo bằng `pytest-timeout`, report test duration và split unit/integration/network.
2. Sửa ruff và bật `quality_gate.py --strict-static` trong CI; release phải blocking cả Mypy/performance.
3. Regenerate dependency map/readiness artifacts trong CI từ commit hiện tại; gắn commit SHA và expiry.
4. Sửa README để đúng với launcher preflight; thêm loader `.env` hoặc bỏ hướng dẫn copy `.env`.
5. Sửa auth identity binding, đưa auth gate trước mutation nhạy cảm, claim notification nguyên tử và loại credential khỏi queue payload.
6. Thêm startup smoke và critical journey: auth -> analyze -> save decision -> alert -> report.

### 2-6 tuần: giảm coupling và side effects

1. Tạo `AppServices`/container typed thay vì truyền hàng chục callable.
2. Tách `product_layer` thành portfolio, notification, growth và DB bootstrap modules.
3. Chuyển schema sang Alembic hoặc migration framework tương đương.
4. Không init DB ở import; bootstrap explicit, health check riêng.
5. Chuẩn hóa exception taxonomy và response envelope gồm source/freshness/fallback/error.
6. Đưa config vào typed settings với validation và profile dev/prod rõ ràng.

### 6-12 tuần: production scale

1. PostgreSQL mặc định cho production; loại bỏ state quan trọng khỏi local filesystem.
2. Durable queue cho scan/report/notification, object storage cho artifact lớn.
3. Sentry/OpenTelemetry + metrics tập trung: latency p50/p95, error rate, stale rate, queue age, provider health.
4. Rate limit và bulkhead riêng cho từng data/LLM provider.
5. Load test các mixed workloads: dashboard, 1-symbol analysis, full scan, PDF và notification.
6. Nếu concurrent usage tăng, tách API/worker khỏi Streamlit và giữ Streamlit như presentation client.

## 14. Prompt đề nghị đưa cho Gemini

Hãy phân tích kiến trúc mô tả trong tài liệu này như một Principal Engineer cho hệ thống fintech/decision-support. Không giả định các báo cáo GO cũ còn đúng. Hãy:

1. vẽ lại kiến trúc hiện tại và chỉ ra dependency/coupling nguy hiểm;
2. đánh giá correctness, data freshness, failure modes, security, operability và scalability;
3. tìm các cải tiến có ROI cao nhất, phân loại P0/P1/P2;
4. đề xuất target architecture cho 3 mốc: pilot 100 user, 1.000 user đăng ký/50 concurrent, và 1.000 concurrent;
5. thiết kế kế hoạch refactor incremental, không big-bang rewrite;
6. đề xuất SLO, dashboard, alert và release gates định lượng;
7. đánh giá mô hình forecast/heuristic và cách validation out-of-sample để tránh overfitting;
8. nêu rõ phần nào nên giữ, phần nào nên thay và bằng chứng cần thu thập trước mỗi quyết định;
9. trả về backlog theo epic/task, effort, dependency, acceptance criteria và rủi ro rollback;
10. chỉ ra mọi mâu thuẫn giữa mục tiêu “app đầu tư đáng tin cậy” với thiết kế hiện tại.

Ưu tiên kết luận có thể kiểm chứng, không khen chung chung và không đề xuất công nghệ chỉ vì phổ biến.
