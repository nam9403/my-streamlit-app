# Decision playbook historical backtest

Generated: `2026-08-02T11:45:58.629120+00:00`

Backtest học tập — valuation proxy + fundamentals cache, không cam kết lợi nhuận tương lai. So sánh excess vs VNINDEX/ETF (nếu có). Paper live vẫn cần để xác nhận.

- Symbols OK: **10/10**
- Pooled entry trades (BUY/CONDITIONAL_BUY): **25**
- Method: `Replay playbook P1 tuned; entry_style=value_accum; ARMED+READY+filters; cost=0.3% round-trip; stride=5.`

## Entry signals (BUY / CONDITIONAL_BUY)

| Horizon | Samples | Hit% | Avg% | Median% | Excess vs bench% |
|---|---:|---:|---:|---:|---:|
| 20d | 25 | 56.00 | -2.56 | 1.27 | -0.58 |
| 60d | 25 | 44.00 | -1.68 | -3.12 | -3.61 |
| 90d | 25 | 48.00 | -0.97 | -0.87 | -10.47 |

## Control: nếu mua khi WATCH/HOLD

| Horizon | Samples | Hit% | Avg% | Median% | Excess vs bench% |
|---|---:|---:|---:|---:|---:|
| 20d | 1103 | 55.85 | 0.92 | 1.00 | 3.33 |
| 60d | 1103 | 55.03 | 2.95 | 1.84 | 5.39 |
| 90d | 1105 | 52.40 | 3.38 | 0.84 | 1.11 |

## Verdict: entry vs WATCH

- Entry beats WATCH (avg): **False** (0/3 horizons)
- Entry thắng WATCH nếu hơn nửa horizon có avg_return cao hơn (min 8 samples/horizon).

## Per symbol

| Symbol | Trades | Notes |
|---|---:|---|
| ACB | 5 | AVOID:103, BUY:1, CONDITIONAL_BUY:18, HOLD:44, WATCH:53 |
| BCM | 2 | AVOID:81, BUY:1, CONDITIONAL_BUY:8, HOLD:63, WATCH:65 |
| BID | 2 | AVOID:98, BUY:1, CONDITIONAL_BUY:10, HOLD:39, WATCH:70 |
| BVH | 2 | AVOID:72, CONDITIONAL_BUY:14, HOLD:66, WATCH:66 |
| CTG | 1 | AVOID:140, CONDITIONAL_BUY:3, HOLD:26, WATCH:50 |
| FPT | 4 | AVOID:105, BUY:2, CONDITIONAL_BUY:10, HOLD:56, WATCH:46 |
| GAS | 7 | AVOID:48, BUY:1, CONDITIONAL_BUY:30, HOLD:86, WATCH:54 |
| GVR | 0 | AVOID:81, BUY:1, CONDITIONAL_BUY:10, HOLD:68, WATCH:58 |
| HDB | 0 | AVOID:137, BUY:1, CONDITIONAL_BUY:3, HOLD:39, WATCH:40 |
| HPG | 2 | AVOID:95, BUY:2, CONDITIONAL_BUY:4, HOLD:56, WATCH:62 |

---

Cách đọc: Hit% / Avg% sau phí round-trip; Excess = return mã − VNINDEX cùng cửa sổ. Nếu entry tốt hơn WATCH control và excess > 0 trên 60–90d → rule có tín hiệu sơ bộ.
