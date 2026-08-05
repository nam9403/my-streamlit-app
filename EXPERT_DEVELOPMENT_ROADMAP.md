# Lộ trình phát triển kiểu chuyên gia hàng đầu

Cập nhật: 2026-08-02  
North-star: **DSS VN có kỷ luật research-grade, edge đo được (hist + live), vận hành như sản phẩm đầu tư chuyên nghiệp** — không cam kết lợi nhuận, không tuyên bố “số 1 thế giới” trước track record.

## Nguyên tắc làm việc (non-negotiable)

1. **Evidence before narrative** — mọi rule mới phải có hist + (sau này) paper; không ship “cảm giác thông minh”.
2. **No look-ahead** — PIT lag, walk-forward, embargo giữa train/test.
3. **Protect first** — AVOID/HOLD đúng còn quan trọng hơn thêm BUY.
4. **One change, one measure** — mỗi wave một giả thuyết, một artifact, một gate PASS/FAIL.
5. **Live > backtest** — hist chỉ mở cửa; paper 60d mới được gọi là edge vận hành.
6. **LLM không phải alpha** — LLM giải thích / challenge; quyết định tiền nằm ở playbook + gate đã đo.

## Baseline đã khóa (2026-08-02)

| Metric | Giá trị |
|---|---|
| Universe | VN30 full, Yahoo 5y, cost 0.3% RT |
| Rule | PIT + Rev&LN YoY ≥ 0 + ARMED/READY (`pit_quality`) |
| Entry vs WATCH | **4/4** horizons thắng |
| Excess vs bench | +4.8% (20d) … **+7.9% (60d)** … +1.7% (90d) |
| AVOID protective | **4/4** |
| Samples | n≈101 entry |
| Paper default | 60d + growth gate |

**Trạng thái chuyên môn:** tín hiệu **in-sample / same-window** có cạnh — **chưa** chứng minh OOS walk-forward. Wave 1 bắt buộc.

---

## Bản đồ năng lực → mục tiêu “chuyên gia”

| Tầng | Nội dung chuyên gia | Mục tiêu hệ thống |
|---|---|---|
| L1 Research | PIT, peers, earnings quality | Data warehouse tối thiểu + as-of API |
| L2 Signal | Entry có edge, ổn định OOS | Playbook + WF gate |
| L3 Risk | Exit, size, correlation, DD | Trade lifecycle + portfolio caps |
| L4 Process | Journal, post-mortem, change control | Artifacts + release gates |
| L5 Product | Quyết định 1 màn hình, trust | Decision card + public accountability |
| L6 Franchise | Users trả tiền, retention | Billing + cohort (sau edge live) |

---

## Wave 0 — Governance & baseline lock (1–2 ngày) ✅ phần lớn xong

**Giả thuyết:** Không khóa baseline → mọi “cải tiến” đều nhiễu.

| # | Việc | Done when |
|---|---|---|
| 0.1 | Artifact backtest chuẩn + disclaimer | `playbook_backtest_latest.*` |
| 0.2 | Rule mặc định `pit_quality` + paper 60d | code + nightly |
| 0.3 | Execution log / roadmap này | file này + `SYSTEM_10_…` pointer |

---

## Wave 1 — Scientific validation (3–7 ngày) ← **ĐANG LÀM**

**Giả thuyết:** Edge còn nếu train trên quá khứ, test trên tương lai (walk-forward).

| # | Việc | Deliverable | Gate |
|---|---|---|---|
| 1.1 | Walk-forward OOS (cửa sổ rolling / expanding) | `walk_forward_playbook.py` + CLI | Report có train/test tách |
| 1.2 | Embargo ≥ 5–10 phiên giữa train và test | config | Không overlap labels |
| 1.3 | Ổn định: ≥ nửa fold test thắng WATCH **hoặc** excess@60>0 | artifact `walk_forward_latest` | PASS/FAIL rõ |
| 1.4 | Purge: không dùng bar test để chọn filter | sweep chỉ trên train folds | Documented |
| 1.5 | Baseline scorecard JSON | `expert_edge_scorecard.json` | So sánh theo thời gian |

**FAIL xử lý:** siết rule / giảm tần suất / giữ AVOID-only mode — **không** thêm filter đến khi OOS xanh.

---

## Wave 2 — Full trade lifecycle (1–2 tuần)

**Giả thuyết:** Entry có edge nhưng exit kém → không có P&L nghề nghiệp.

| # | Việc | Done when |
|---|---|---|
| 2.1 | Time-stop khớp horizon tối ưu (40–60d) | backtest exit_at_h |
| 2.2 | Invalidation / stop từ playbook trigger | exit khi INVALID hoặc dưới invalidation |
| 2.3 | Trailing / give-back cap đơn giản (ATR-based) | so sánh expectancy |
| 2.4 | Max concurrent positions + sector cap | portfolio sim |
| 2.5 | Cost model VN (fee+tax+slip) profile | config |

---

## Wave 3 — Research brain (2–4 tuần)

**Giả thuyết:** Valuation proxy không đủ để “như chuyên gia”; cần research stack.

| # | Việc | Done when |
|---|---|---|
| 3.1 | PIT statements coverage ≥ 90% liquid universe | cache health |
| 3.2 | Sector-relative value (PE/PB/MOS vs peer median as-of) | feature + backtest delta |
| 3.3 | Earnings quality / one-off flags vào thesis | attractive gate |
| 3.4 | Flow / smart-money chỉ như **nudge có weight đo được** | WF weight |
| 3.5 | Event calendar (KQKD, cổ tức) blacklist quanh ngày | skip window |

---

## Wave 4 — Live paper as production (song song Wave 1–2, 60–90 ngày)

**Giả thuyết:** Chỉ paper mới chứng minh vận hành.

| # | Việc | Done when |
|---|---|---|
| 4.1 | Nightly seed chỉ rule WF-PASS | paper opens đúng filter |
| 4.2 | Resolve tự động + báo cáo tuần | markdown/JSON |
| 4.3 | SLO: % ngày seed thành công, % resolve đúng hạn | dashboard |
| 4.4 | Kill-switch nếu 20 lệnh liên tiếp dưới kỳ vọng | config |
| 4.5 | Public trust (ẩn danh) cập nhật từ paper | trust page |

**Gate “edge live”:** sau ≥40 lệnh đóng @60d: hit ≥52% **và** avg excess ≥0 (hoặc đánh FAIL trung thực).

---

## Wave 5 — Expert product surface (2–3 tuần, song song)

| # | Việc | Done when |
|---|---|---|
| 5.1 | Decision card: Thesis/Setup/Trigger/Risk/Exit một khung | mobile OK |
| 5.2 | “Vì sao không BUY” luôn hiện khi HOLD/AVOID | UX |
| 5.3 | Journal tay 1 click từ card | persistence |
| 5.4 | Morning digest = playbook + paper P&L | Telegram |

---

## Wave 6 — Commercial readiness (sau Wave 4 xanh)

| # | Việc |
|---|---|
| 6.1 | Free vs Pro: limit gắn edge features |
| 6.2 | Onboarding đo conversion |
| 6.3 | Referral + weekly report |
| 6.4 | Pilot 50 MAU → 10% pay hoặc waitlist rõ |

---

## Wave 7 — Moat (3–6 tháng)

| # | Việc |
|---|---|
| 7.1 | Proprietary blend chỉ giữ weight OOS-pass |
| 7.2 | Dynamic liquid + capacity aware |
| 7.3 | Audit pack độc lập (quy trình, không cam kết LN) |
| 7.4 | Multi-tenant Postgres prod cứng |

---

## Lịch triển khai đề xuất (90 ngày)

```
Tuần 1–2   Wave1 WF + scorecard + (start) Wave2 exit
Tuần 3–4   Wave2 portfolio/cost + Wave4 paper cứng
Tuần 5–8   Wave3 research features (từng cái một + đo)
Tuần 5–12  Wave4 paper tích lũy (không tắt)
Tuần 9–12  Wave5 UX chuyên gia
Tuần 13+   Wave6 nếu paper gate PASS; else iterate Wave1–3
```

## Definition of Done — “chuyên nghiệp như chuyên gia” (nội bộ)

Không phải “AI nói hay”, mà:

1. OOS walk-forward **PASS** trên rule production  
2. Paper ≥40 closed trades, excess/hit đạt ngưỡng hoặc báo FAIL trung thực  
3. AVOID vẫn protective trên cửa sổ gần nhất  
4. Mọi thay đổi rule có PR note + artifact trước/sau  
5. User nhìn thẻ quyết định hiểu **vào / không vào / hủy / rủi ro** trong <30 giây  

“Số 1 thế giới” = Wave 6–7 + nhiều năm track record — **ngoài phạm vi sprint**; roadmap này đưa hệ thống tới **chuẩn chuyên gia vận hành được**.

---

## Execution log (roadmap này)

- 2026-08-02: Tạo lộ trình Waves 0–7; bắt đầu Wave 1.1 walk-forward OOS.
- 2026-08-02 (Wave 1 PASS): `walk_forward_playbook` locked pit_quality — **GATE_PASS=True** (3/3 fold đủ mẫu); OOS n=62, beats WATCH 4/4, excess@60d ~+8.0%; artifacts `walk_forward_latest.*` + `expert_edge_scorecard.json`.
- 2026-08-02 (Wave 2 start): `playbook_exit_rules` — time-stop / ATR stop / giveback path sim + tests.
- 2026-08-02 (Wave 2 pilot): exit bake-off 15 mã — **time40** tốt nhất trên mẫu (avg +4.9%, hit 76%) > time60; **chưa** đổi paper mặc định cho đến khi full VN30 xác nhận.
- 2026-08-02 (Wave 2 lock): full VN30 exit n=101 — raw-avg `time90`; **vận hành = time40_atr2 @40d**; paper/nightly horizon **40d**; `vn_trade_cost` RT≈0.50%; `portfolio_caps` (8/3/3) wire paper.
- 2026-08-02 (Wave 4): `paper_ops_guard` kill-switch; `export_paper_weekly_report`; nightly resolve→open→weekly; Trust/SLO hiện 40d + halt status; completion `--paper-weekly`.
- 2026-08-02 (Wave 3): `sector_relative` PE/PB vs ICB peer median → thesis nudge; EQ high / rich-vs-peer chặn attractive; PIT VN30 coverage **100%**; `audit_pit_coverage.py`.
- 2026-08-02 (Wave 3 done): `event_calendar_gate` (season + news KQKD/cổ tức) demote BUY; flow weight theo `smart_money_reliability` trong proprietary blend; paper skip `EventBlackout`.
- 2026-08-02 (Wave 5 start): decision card `why_not_buy` + event note; **journal 1-click** từ thẻ; morning digest kèm paper P&L 90d.
- 2026-08-02 (Wave 5.4): digest/Telegram HTML gắn paper **40d** + playbook T/S/Tr; board field `Why not BUY`; Trust hiện trạng digest gần nhất; `send_morning_digest --dry-run` artifact có `paper`.
- 2026-08-02 (Wave 6): Free/Pro edge gates (journal/digest/paper weekly/peer); onboarding event funnel + `growth_conversion_service`; commercial waitlist/referral panel; weekly growth + conversion snapshot (`PILOT=BUILDING`, MAU=2).
