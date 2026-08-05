# Kế hoạch hoàn thiện hệ thống → mục tiêu 10/10

Cập nhật: 2026-07-24  
North-star: **DSS chứng khoán VN đáng tin, nhanh, có bằng chứng hiệu quả, bán được** — không chỉ “nhiều feature”.

Thang điểm mục tiêu (cân bằng kỹ thuật + sản phẩm + thương mại):

| Trụ | Hiện ~ | Mục tiêu 10/10 | Ý nghĩa |
|---|---|---|---|
| A. Dữ liệu & độ tin cậy | 6.5 | 10 | Giá/CFO/OHLCV đủ, nguồn rõ, ít lệch |
| B. Quyết định & hiệu quả | 7 | 10 | Top pick có track record, ít WATCH mơ hồ |
| C. Phủ thị trường & hiệu năng | 7 | 10 | Đêm ~400 liquid ổn; sáng Top 10 <3s |
| D. Sản phẩm / UX quyết định | 7 | 10 | 1 màn hình: vì sao / làm gì / rủi ro |
| E. Vận hành VPS / SLO | 7.5 | 10 | Nightly/health/alert/rollback chuẩn |
| F. Thương mại & trust | 2 | 10 | User trả tiền + retention + minh bạch P&L gợi ý |

**Lưu ý:** “10/10 sản phẩm kỹ thuật” có thể đạt trước; “10/10 tỷ đô” cần F (thị trường) — kế hoạch tách rõ.

---

## Phase P0 — Nền phục vụ đúng ý tưởng (1–2 tuần) ✅ đang triển khai

Mục tiêu: **đêm quét → lưu board → sáng Top 10 từ ~400**, có quan sát & an toàn.

1. Nightly liquid board bền + Autopilot serve Top 10 *(đã có khung)*
2. UI: coverage / tuổi board / nút **Ép quét live**
3. Health: coverage < ngưỡng → cảnh báo (artifact + optional Telegram)
4. Freshness guard: làm mới nhẹ giá Top 10 khi serve (tránh OHLCV lệch snapshot)
5. Seed forecast accountability từ Top 10 đêm (bắt đầu đo hiệu quả)

**Done when:** VPS chạy 1 đêm full liquid; sáng Autopilot hiện caption nightly; health PASS; có bản ghi Top 10 để resolve sau 30–90 ngày.

---

## Phase P1 — Chất lượng quyết định (2–4 tuần)

1. Completeness gate: thiếu CFO/NI quan trọng → hạ readiness, không “Mua mạnh” giả
2. Bank-aware Legend ổn định (D/E/CR không làm nhiễu ngân hàng)
3. Thống nhất BUY/WATCH gates (Autopilot ↔ Simple View ↔ DSS)
4. Paper-trade ledger: mỗi Top pick ghi entry giả định + resolve tự động
5. Macro/News boost mặc định an toàn (disk-only) + giải thích bias trên UI

**Done when:** backtest/paper 30 ngày có báo cáo hit-rate; missing_items giảm rõ trên VN30.

---

## Phase P2 — Sản phẩm bán được (1–2 tháng)

1. Onboarding 3 bước: hồ sơ → Autopilot → 1 mã phân tích sâu
2. Gói Free/Pro rõ: limit quét, Simple View, alert
3. Mobile-friendly decision card + Telegram digest sáng
4. Public trust page: lịch sử gợi ý (ẩn danh) + disclaimer
5. SLO dashboard: p95 Autopilot serve, nightly coverage, fail rate

**Done when:** pilot ≥50 user active; ≥10% trả phí hoặc waitlist có conversion rõ.

---

## Phase P3 — Moat & “số 1 niche” (3–6 tháng)

1. Proprietary signal: flow + valuation + phase blend có WF ổn
2. Universe thông minh (thanh khoản động, không chỉ HOSE tĩnh)
3. Multi-tenant / Postgres mặc định production
4. Audit độc lập / chứng nhận quy trình (không phải cam kết lợi nhuận)
5. Growth loop: referral, weekly report, retention cohort

**Done when:** thắng đối thủ niche về **độ tin cậy khuyến nghị + tốc độ quyết định**, có doanh thu lặp lại.

---

## Lộ trình chuyên gia (2026-08+)

Chi tiết Waves 0–7, gate OOS/paper, nguyên tắc research-grade: **[`EXPERT_DEVELOPMENT_ROADMAP.md`](EXPERT_DEVELOPMENT_ROADMAP.md)**.

---

## Thứ tự thực thi ngay (session này → tiếp)

| # | Việc | Trụ |
|---|---|---|
| 1 | Force-live UI + nightly health script | C, E |
| 2 | Refresh giá nhẹ Top 10 khi serve board | A |
| 3 | Seed accountability từ nightly Top 10 | B |
| 4 | Runbook ngắn trong DEPLOYMENT | E |
| 5 | Completeness flag trên row board | A, B |

Theo dõi tiến độ: cập nhật mục “Execution log” cuối file này mỗi milestone.

---

## Execution log

- 2026-07-24: Tạo kế hoạch 10/10; bắt đầu P0 (UI force-live, health, freshness, accountability seed).
- 2026-07-24 (P0 done khung): force-live toggle, `board_health_report` + script health, refresh giá Top 10 khi serve, seed forecast Top 10 sau nightly scan, missing_items trên row quét đêm.
- 2026-07-24 (P1): `decision_completeness` (hạ Legend/readiness khi thiếu CFO/NI; bank-aware), `paper_trade_ledger` + resolve/hitrate script, Autopilot caption News/Macro + paper hit-rate, wire mở paper trade sau nightly Top 10.
- 2026-07-24 (P2): Onboarding funnel hồ sơ→Autopilot→phân tích sâu; plan-cap Autopilot; morning digest + scheduler; Trust panel + SLO panel; packaging caption Free/Pro.
- 2026-07-28 (P0 data): EPS normalize (conservative); `data_trust_score`; metadata liquid +404; `refresh_financial_indicators --liquid/--top10`; completion jobs liquid-financial; UI trust score in analysis readiness.
- 2026-07-28 (P1 decision): `decision_action_gate` thống nhất BUY/WATCH (Autopilot/Simple View); cột Readiness/Thiếu DL/Ghi chú Legend; paper accountability 30/90/365d + export script; VN30 completeness audit; Trust panel 30d hit-rate.
- 2026-07-28 (P2 product): Decision Card mobile UI; plan usage caption + feature matrix billing; morning digest P1 fields; export SLO snapshot + public trust page; SLO panel fail-rate/p95; completion jobs digest/trust/slo.
- 2026-07-28 (P3 moat): `proprietary_signal` blend (flow+val+phase+WF); `dynamic_liquid` universe; referral + weekly growth report + cohort panel; process audit pack; `ensure_production_profile` Postgres prod.
- 2026-07-28 (weakpoint harden): ẩn Entry/SL/TP khi WATCH/AVOID; smart-money dedupe; CFO backfill vnstock; proprietary WF store+light proxy; data trust FPT ↑.
- 2026-08-02 (P0 integrity): `core/data_integrity.py` — OHLCV sanitize + absurd range/gap gate; price cross-check ≥3% note / ≥8% hard; MOS clamp khi PE/EPS sanity; RSI≈0/100 = indicator fail; paper LONG chỉ BUY/CONDITIONAL_BUY; chặn MC forecast + trade plan khi integrity fail.
- 2026-08-02 (P1 playbook): `decision_playbook` Thesis/Setup/Trigger + `market_regime` VNINDEX/macro; action `CONDITIONAL_BUY`; MC range sanity vs ATR; gate/UI/autopilot/paper rank; size_cap theo regime.
- 2026-08-02 (P2 product): digest + board persist Thesis/Setup/Trigger/Playbook; mobile card render playbook; Trust wire forecast; public trust + forecast section; quickstart progress thật + CTA; Free Simple View giữ readiness; `can_use_feature(llm)`; SLO live paper fallback; matrix từ PLAN_FEATURES.
- 2026-08-02 (P3 moat wire): live Autopilot = nightly `score_rows` + Proprietary Score; playbook nudge trong blend; mặc định universe `dynamic_liquid`; referral signup (`?ref=` + form); Postgres driver check + bootstrap fail-fast prod; audit pack P0/P1; tests `test_p3_moat`.
- 2026-08-02 (historical eval): `decision_playbook_backtest` replay P0/P1 no-lookahead + CLI `replay_decision_playbook_backtest.py`; valuation proxy percentile/MA200; sanitize unit-break OHLCV; artifact `playbook_backtest_latest`.
- 2026-08-02 (critical fix): Wilder RSI `loss=(-delta).clip(lower=0)` — trước đó `clip(upper=0)` làm loss≤0 → RSI kẹt 100, abort mọi setup playbook.
- 2026-08-02 (alpha tune): siết COND→chỉ ARMED+READY (attractive+WAIT = HOLD); alignment không promote COND sớm; paper đòi Setup/Trigger; backtest entry_style + verdict vs WATCH — **chưa beat WATCH** với proxy kỹ thuật.
- 2026-08-02 (PIT+alpha): `fundamentals_pit` (Fireant/VNDirect, lag 45d) wire vào replay; filter sweep → **pit_quality = PIT bắt buộc + Rev&LN YoY ≥0** thắng WATCH 2/3 horizon (n=19; 20d +2.43% / 60d +3.41%); AVOID protective 3/3; thesis `attractive` đòi đồng thuận growth; artifact `playbook_backtest_latest`.
- 2026-08-02 (VN30 validate): full VN30 n=101 — entry **thắng WATCH 4/4** horizon; excess vs bench dương mọi cửa (20d +4.8 / 40d +3.4 / 60d +7.9 / 90d +1.7); AVOID protective 4/4; paper default horizon **60d** + gate Rev&LN; board thêm Profit YoY%.
- 2026-08-02 (Expert roadmap): `EXPERT_DEVELOPMENT_ROADMAP.md` Waves 0–7; Wave1 walk-forward **GATE_PASS**; Wave2 exit rules module khởi tạo.
- 2026-08-02 (Wave 2): full exit bake-off → paper **40d** (`time40_atr2`); VN cost 0.5% RT; portfolio caps trên paper open.
- 2026-08-02 (Wave 4): paper kill-switch + weekly report; nightly harden resolve/open/report.
- 2026-08-02 (Wave 3): sector-relative + EQ gate; PIT coverage VN30 100%.
- 2026-08-02 (Wave 3+5): event blackout gate + SM flow weight; card `why_not_buy` + journal 1-click; digest paper P&L.
- 2026-08-02 (Wave 5.4): Telegram/morning digest = playbook + paper 40d; Trust digest status; board `Why not BUY`.
- 2026-08-02 (Wave 6): PLAN edge features Free vs Pro; conversion/pilot snapshot; waitlist CTA; journal quota.
