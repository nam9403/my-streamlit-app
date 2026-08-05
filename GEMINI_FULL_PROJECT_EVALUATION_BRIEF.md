# Investment Intelligence — Brief đánh giá toàn diện (cho Gemini)

> **Mục đích:** Tài liệu này tổng hợp kiến trúc, tính năng, hoạt động gần đây và bằng chứng chạy thử để **Gemini đánh giá độc lập** chất lượng dự án (kỹ thuật + sản phẩm + thương mại).  
> **Phiên bản app:** `1.0.2`  
> **Thời điểm brief:** 2026-07-29 (UTC+7)  
> **Ngôn ngữ sản phẩm:** Tiếng Việt (thị trường chứng khoán VN)  
> **Stack chính:** Python 3.12 · Streamlit · SQLite (dev) / PostgreSQL (prod) · pytest

---

## 0. Prompt gợi ý cho Gemini (copy kèm)

```
Bạn là reviewer sản phẩm + kiến trúc phần mềm + quant product cho DSS chứng khoán Việt Nam.
Đọc brief dưới đây và đánh giá toàn diện theo các trục:
1) Kiến trúc & kỹ thuật
2) Chất lượng dữ liệu & logic phân tích
3) Chất lượng quyết định đầu tư (BUY/HOLD/WATCH/AVOID)
4) Sản phẩm / UX / vận hành
5) Độ sẵn sàng thương mại / go-live
6) Rủi ro, nợ kỹ thuật, điểm mù
7) Roadmap ưu tiên 30/90 ngày

Cho điểm từng trụ /10 và tổng /100. Nêu rõ: đâu là “đã đủ private beta”, đâu còn “chưa đủ public trust”.
Không khen chung chung — trích dẫn bằng chứng trong brief (artifact, kết quả PNJ/ACB/Autopilot).
Cuối cùng trả lời: hệ thống đã hoàn hảo chưa? Nếu chưa, khoảng cách đến 10/10 là gì.
```

---

## 1. Hệ thống là gì (north-star)

**Investment Intelligence Dashboard** — DSS hỗ trợ quyết định cổ phiếu Việt Nam:

- Snapshot giá + OHLCV + BCTC + tin tức
- Định giá (Graham/Buffett/Lynch hybrid, MOS, Piotroski F-Score)
- Báo cáo chiến lược “7 Whys” + confidence / reliability / completeness gates
- Autopilot quét đêm universe thanh khoản → Top 10 sáng
- Paper trade + forecast accountability (đo hiệu quả gợi ý theo thời gian)
- UI Streamlit: phân tích 1 mã, watchlist, Finder, morning digest, Trust/SLO panels
- AI đa nhà cung cấp (Groq / OpenAI / Gemini) với fallback không LLM

**Không phải:** broker, tự động giao dịch thật, cam kết lợi nhuận.

**Mục tiêu sản phẩm:** “đáng tin, nhanh, có bằng chứng hiệu quả, bán được” — không chỉ nhiều feature.

---

## 2. Quy mô codebase (hiện trạng)

| Hạng mục | Số lượng (approx) |
|---|---|
| `core/*.py` | ~139 module |
| `tests/test_*.py` | ~164 file test |
| `scripts/*.py` | ~85 script vận hành |
| `app.py` | ~55 dòng (composition root mỏng; logic tách panel/service) |
| VERSION | 1.0.2 |
| Go-live gate (2026-07-28 dry-run) | **PASS** |

Kiến trúc: **modular monolith** quanh Streamlit + `core/product_layer.py` (facade) + repositories/services theo miền.

---

## 3. Kiến trúc & luồng chính

### 3.1 Lớp chính

| Lớp | Vai trò | Ví dụ file |
|---|---|---|
| Presentation | Streamlit panels | `core/app_*_panel.py`, `core/analysis_*_panel.py` |
| Orchestration | Phân tích / cache / quota | `core/app_analysis_orchestration.py`, `core/analysis_runtime_service.py` |
| Decision engine | Snapshot→report→action | `core/engine.py`, `core/valuation.py`, `core/ai_logic.py` |
| Gates | Thống nhất khuyến nghị | `core/decision_action_gate.py`, `core/decision_completeness.py` |
| Scanner / Autopilot | Quét & board đêm | `core/scanner_service.py`, `core/autopilot_nightly_board.py` |
| News/Macro | Bias tin + macro disk-first | `core/news_macro_service.py` |
| Moat signal | Blend flow+val+phase+WF | `core/proprietary_signal.py` |
| Persistence | SQLite/PG + OHLCV store | `core/db_runtime.py`, `core/ohlcv_store.py` |
| Ops | Nightly, digest, SLO, trust page | `scripts/run_autopilot_nightly_scan.py`, `scripts/run_system_completion_jobs.py` |

### 3.2 Luồng phân tích 1 mã (user path)

1. Snapshot (quote + fundamentals merge)  
2. Valuation / Legend (instant_conclusion)  
3. OHLCV → phase (accumulation / breakout / neutral / distribution)  
4. Financial indicators (+ CFO backfill tùy chọn)  
5. News (CafeF/VietStock) + story/catalyst score  
6. Strategic report: 7 Whys, forecast, deep insight, confidence gates  
7. `decision_action_gate` → **BUY / HOLD / WATCH / AVOID**  
8. UI: Decision Card; **ẩn Entry/SL/TP** nếu không phải BUY/HOLD  

### 3.3 Luồng Autopilot (nightly → morning)

1. Universe: mặc định **`dynamic_liquid`** (rank theo avg volume OHLCV store)  
2. Prefilter vol ≥ 200k (VN30 luôn giữ) trước khi quét  
3. Batch scan → merge `data/runtime/autopilot_nightly_board.json`  
4. Meta tách: `ready` / `liquidity_filtered` / `data_error` / `prefilter_skipped`  
5. Top 10: score = action rank + ER + MOS − risk + proprietary + **News/Macro boost (disk-only)**  
6. Seed forecast + mở paper trades từ Top 10  
7. Sáng: serve board nếu fresh + coverage đủ; fallback live rotation nếu stale  

### 3.4 Ý nghĩa khuyến nghị (ưu tiên)

```
BUY (3) > HOLD (2) > WATCH (1) > AVOID (0)
```

- **BUY:** MOS/confidence đủ + pha accumulation/breakout (+ bank-aware Legend)  
- **HOLD:** value ổn, timing chưa confirm  
- **WATCH:** đáng theo dõi, chưa giải ngân (thiếu DL / pha xấu / gate)  
- **AVOID:** không ưu tiên đầu tư  

---

## 4. Các đợt hoàn thiện đã triển khai (execution log rút gọn)

Theo `SYSTEM_10_OF_10_COMPLETION_PLAN.md` + CHANGELOG + session 2026-07-28:

### P0 — Nền dữ liệu & board đêm
- Nightly liquid board + Autopilot serve Top 10  
- Force-live UI, board health, refresh giá Top 10  
- Seed forecast accountability  
- EPS normalize; `data_trust_score`; metadata liquid mở rộng  
- Prefetch financial liquid / top10  

### P1 — Chất lượng quyết định
- `decision_completeness` (thiếu CFO/NI → hạ Legend/readiness; bank-aware)  
- `decision_action_gate` thống nhất BUY/WATCH/HOLD/AVOID  
- Paper trade ledger + resolve + hit-rate 30/90/365d  
- News/Macro boost disk-only trên ranking  

### P2 — Bề mặt sản phẩm
- Onboarding: hồ sơ → Autopilot → 1 mã sâu  
- Decision Card mobile; plan Free/Pro matrix  
- Morning digest; Trust panel; SLO export + public trust page  

### P3 — Moat / growth
- `proprietary_signal` blend  
- Universe `dynamic_liquid`  
- Referral + weekly growth + cohort panel  
- Process audit pack; Postgres prod check  

### Hardening sau đánh giá FPT (2026-07-28)
- Ẩn trade plan khi WATCH/AVOID  
- Smart-money dedupe  
- CFO backfill (`II_CFO_BACKFILL`)  
- Walk-forward proxy trong proprietary signal  

### Autopilot UX/ops fix (2026-07-28)
- Prefilter volume trước quét (giảm “fail” hiểu nhầm)  
- Meta: `liquidity_filtered_count` vs `data_error_count`  
- Caption UI giải thích lọc thanh khoản ≠ lỗi hệ thống  
- Smoke: batch 40 `dynamic_liquid` → **40/40 ready (100%)**  

---

## 5. Bằng chứng chạy thử gần đây (artifact)

### 5.1 ACB & QTP (evaluate)

| | ACB | QTP |
|---|---|---|
| Ngành | Ngân hàng | Nhiệt điện |
| Display action | HOLD | HOLD |
| Verdict | CAUTION | CAUTION |
| MOS | ~53% | ~61% |
| Trust | 77 MEDIUM | 67 MEDIUM (cảnh báo P/E) |
| Ghi chú | Growth tốt, F-Score thấp, pha neutral | P/E nghi EPS scale; DT YoY âm |

→ Hệ thống **không đẩy BUY** dù MOS cao — gate timing/completeness hoạt động.

### 5.2 Autopilot

| Lần chạy | Kết quả |
|---|---|
| Liquid alphabet 120 mã | Ready 67/120; nhiều “fail” = lọc vol 200k (không crash) |
| `dynamic_liquid` 40+6 | **46/46 ready 100%**; pool liquid disk ~46 mã @ vol≥200k |
| Top picks (dynamic) | LDG, PNJ, SHB, HPX, HQC, TPB, CTG… — hầu hết **WATCH** |
| Paper trades | Đã mở nhiều lệnh giả từ Top 10 (cần resolve theo thời gian) |

### 5.3 PNJ — full pipeline (sau refresh CFO)

| Field | Kết quả |
|---|---|
| Giá | 32,650 |
| Legend | **Bỏ qua** |
| Action | **WATCH** |
| Verdict | **NO-GO** |
| CFO | **−302 tỷ** (âm) |
| D/E | 0.72 |
| Pha | **distribution** |
| News/Macro Bias | **−0.15** |
| Earnings quality | Cảnh báo **cao** |
| Trade plan | **inactive** (ẩn Entry/SL/TP) |
| Forecast 90d | ~+1% expected |

**Ý nghĩa đánh giá:** Ranking Autopilot có thể đưa PNJ lên cao vì MOS/ER; **full analysis** hạ xuống NO-GO nhờ CFO + pha + tin — đúng hướng “thận trọng hơn surface rank”.

### 5.4 Go-live / tests

- Go-live gate dry-run 2026-07-28: **PASS** (preflight + scale + SLO)  
- Offline pytest historically: **~670 passed** (có flaky mitigation disk-first)  
- Autopilot board unit tests: 8/8 pass sau cải tiến meta/prefilter  

---

## 6. Tự đánh giá nội bộ (trước khi Gemini chấm)

| Trụ | Nội bộ ~ | Ghi chú |
|---|---|---|
| A. Dữ liệu & độ tin cậy | 7.5–8.5 | Có trust score, CFO backfill; vẫn lệch EPS/stale/cache tin sparse |
| B. Quyết định & hiệu quả | 7.5–8 | Gate tốt; **chưa có hit-rate công khai 30–90d** |
| C. Phủ TT & hiệu năng | 8–8.5 | Dynamic liquid tốt; pool disk còn hẹp nếu chưa prefetch OHLCV rộng |
| D. Sản phẩm / UX | 7.5–8 | Decision card, onboarding; UX “tìm mã mua” yếu khi 0 BUY |
| E. Vận hành VPS / SLO | 7.5–8 | Script sẵn; cần cron thật ổn định |
| F. Thương mại & trust | ~5–7 | Trust page/digest có khung; thiếu evidence thị trường & retention |
| **Kỹ thuật tổng** | **~8.5–8.9/10** | **Chưa 10/10** |
| **Hoàn hảo?** | **Không** | Private-beta / controlled launch |

Scorecard cũ (`BILLION_APP_READINESS` ~82/100, 2026-05) cùng hướng nhưng **đã cũ** so với P0–P3 tháng 7.

---

## 7. Điểm mạnh cần Gemini xác nhận

1. Tách rõ **định giá hấp dẫn** vs **đủ điều kiện giải ngân** (Legend ≠ BUY).  
2. Completeness + trade-plan visibility giảm tín hiệu giả.  
3. Autopilot vận hành được đo (coverage, ready_rate, prefilter).  
4. News/Macro module đã wire vào ranking + UI (disk-first, fail-soft).  
5. Accountability path (paper + forecast seed) đã có — chờ thời gian.  
6. Fail-soft data providers + nhiều cache layer (phù hợp VPS VN).  

---

## 8. Điểm yếu / nợ / rủi ro (cần Gemini phản biện)

1. **Chưa có track record công khai** đủ dài cho Top pick.  
2. **EPS/P/E scale anomalies** vẫn xuất hiện (PNJ, QTP) — MOS có thể “đẹp giả”.  
3. Autopilot ranking (quick) vs full analysis có thể **lệch mức thận trọng** (PNJ #2 board vs NO-GO full).  
4. News boost lúc quét batch phụ thuộc **news_cache**; cache trống → bias ≈ 0.  
5. Smart money còn heuristic / thiếu event có cấu trúc trên nhiều mã.  
6. `product_layer` / monolith vẫn nặng; Drift tài liệu cũ vs code mới.  
7. Thương mại (billing, retention, CAC) chưa bằng lớp kỹ thuật.  
8. Universe `dynamic_liquid` phụ thuộc độ phủ OHLCV store trên máy/VPS.  

---

## 9. File & lệnh quan trọng (để Gemini / reviewer đối chiếu)

### Docs
- `README.md`, `DEPLOYMENT.md`, `GO_LIVE_RUNBOOK.md`
- `SYSTEM_10_OF_10_COMPLETION_PLAN.md`
- `SYSTEM_OPERATION_DESCRIPTION_FOR_GEMINI.md` *(mô tả vận hành cũ hơn — 2026-07-17)*
- Brief này: `GEMINI_FULL_PROJECT_EVALUATION_BRIEF.md`

### Artifacts bằng chứng
- `artifacts/operations/simulate_user_pnj_flow_full.json`
- `artifacts/operations/simulate_acb_qtp_eval.json`
- `artifacts/operations/autopilot_scan_dynamic40_latest.json`
- `artifacts/operations/go_live_gate_summary.json`
- `data/runtime/autopilot_nightly_board.json`

### Lệnh điển hình
```bash
python -m streamlit run app.py
python scripts/run_autopilot_nightly_scan.py --universe-mode dynamic_liquid --limit 40
python scripts/simulate_user_pnj_flow.py
python scripts/refresh_financial_indicators.py --symbols PNJ --force
python scripts/go_live_gate.py
python -m pytest -q
```

---

## 10. Câu hỏi bắt buộc Gemini trả lời

1. Với bằng chứng PNJ (WATCH/NO-GO sau CFO âm) và Autopilot (0 BUY, nhiều WATCH), hệ thống **quá thận trọng** hay **đúng mức** cho sản phẩm retail VN?  
2. Khoảng cách lớn nhất đến “public trust page đáng tin” là gì?  
3. Nên ưu tiên 30 ngày tới: (A) cron + paper hit-rate, (B) sửa EPS/MOS sanity, (C) align Autopilot score với full gate, hay (D) thương mại?  
4. Điểm tổng /100 và verdict: **private beta / soft launch / chờ thêm evidence**.  

---

## 11. Kết luận nội bộ một dòng (để Gemini đồng ý hoặc bác)

> Hệ thống là **DSS chứng khoán VN kỹ thuật khá chín (~8.5+/10), đã có gate thận trọng và bằng chứng chạy thử**, nhưng **chưa hoàn hảo**: thiếu track record thời gian, còn lệch dữ liệu (EPS/CFO/news cache), và lớp thương mại chưa theo kịp — phù hợp **controlled / private beta**, chưa tuyên bố 10/10.
