# Decision playbook historical backtest

Generated: `2026-08-02T12:22:33.162443+00:00`

Backtest học tập — valuation proxy + fundamentals cache, không cam kết lợi nhuận tương lai. So sánh excess vs VNINDEX/ETF (nếu có). Paper live vẫn cần để xác nhận.

- Symbols OK: **30/30**
- Pooled entry trades (BUY/CONDITIONAL_BUY): **101**
- ARMED+READY pool (pre-style): **102**
- Method: `Replay playbook P1 tuned; entry_style=pit_quality; ARMED+READY+filters; cost=0.3% round-trip; stride=5.`

## Entry signals (BUY / CONDITIONAL_BUY)

| Horizon | Samples | Hit% | Avg% | Median% | Excess vs bench% |
|---|---:|---:|---:|---:|---:|
| 20d | 101 | 55.45 | 0.99 | 0.59 | 4.79 |
| 40d | 99 | 57.58 | 2.31 | 1.72 | 3.41 |
| 60d | 101 | 55.45 | 3.48 | 1.73 | 7.87 |
| 90d | 101 | 55.45 | 4.37 | 1.01 | 1.66 |

## Control: nếu mua khi WATCH/HOLD

| Horizon | Samples | Hit% | Avg% | Median% | Excess vs bench% |
|---|---:|---:|---:|---:|---:|
| 20d | 5057 | 50.43 | 0.17 | 0.10 | 3.55 |
| 40d | 5056 | 51.23 | 0.78 | 0.34 | 1.98 |
| 60d | 5066 | 50.34 | 1.53 | 0.16 | 5.92 |
| 90d | 5058 | 50.61 | 2.28 | 0.24 | 1.38 |

## Control: nếu mua khi AVOID (đo bảo vệ)

| Horizon | Samples | Hit% | Avg% | Median% | Excess vs bench% |
|---|---:|---:|---:|---:|---:|
| 20d | 1103 | 44.42 | -0.24 | -1.03 | 2.58 |
| 40d | 1103 | 40.71 | -0.97 | -2.50 | -0.47 |
| 60d | 1105 | 38.64 | -1.11 | -3.98 | 1.62 |
| 90d | 1104 | 38.50 | -0.65 | -5.13 | -3.58 |

## Verdict: entry vs WATCH

- Entry beats WATCH (avg): **True** (4/4 horizons)
- Entry thắng WATCH nếu hơn nửa horizon có avg_return cao hơn (min 8 samples/horizon).

## Verdict: AVOID vs WATCH (protective gate)

- AVOID is protective: **True** (4/4 horizons)
- AVOID bảo vệ nếu avg_return thấp hơn WATCH trên ≥ nửa horizon (min 8 samples).

## Filter sweep (offline trên ARMED+READY pool)

- Variants tested: **15**
- Any variant beats WATCH: **True**
- Best: `style=pit_quality;buy_only=False;pit_ok=True;both_g=True;rsi≤72.0;mos≥8.0;rev≥None;ni≥None;rs≥None;block_roff=False` — trades=101, avg60=3.48, ex20=4.79, beats=True

| Rank | Label | Trades | Avg60% | Ex20% | Ex60% | Beats WATCH | Wins |
|---:|---|---:|---:|---:|---:|---|---:|
| 1 | `style=pit_quality;buy_only=False;pit_ok=True;both_g=True;rsi≤72.0;mos≥8.0;rev≥None;ni≥None;rs≥None;block_roff=False` | 101 | 3.48 | 4.79 | 7.87 | True | 4 |
| 2 | `style=both;buy_only=False;pit_ok=False;both_g=False;rsi≤72.0;mos≥8.0;rev≥None;ni≥None;rs≥None;block_roff=False` | 101 | 3.48 | 4.79 | 7.87 | True | 4 |
| 3 | `style=value_accum;buy_only=False;pit_ok=False;both_g=False;rsi≤72.0;mos≥8.0;rev≥None;ni≥None;rs≥None;block_roff=False` | 62 | 3.36 | 4.56 | 6.70 | True | 4 |
| 4 | `style=breakout;buy_only=False;pit_ok=False;both_g=False;rsi≤72.0;mos≥8.0;rev≥None;ni≥None;rs≥None;block_roff=False` | 24 | 3.70 | 4.39 | 8.43 | True | 3 |
| 5 | `style=pit_strict;buy_only=False;pit_ok=True;both_g=True;rsi≤72.0;mos≥8.0;rev≥None;ni≥None;rs≥None;block_roff=False` | 54 | 2.05 | 4.92 | 4.58 | True | 3 |

## Per symbol

| Symbol | Trades | Notes |
|---|---:|---|
| ACB | 5 | AVOID:43, CONDITIONAL_BUY:6, HOLD:72, WATCH:98 |
| BCM | 1 | AVOID:65, BUY:1, HOLD:72, WATCH:80 |
| BID | 2 | AVOID:21, CONDITIONAL_BUY:3, HOLD:52, WATCH:142 |
| BVH | 0 | AVOID:72, HOLD:78, WATCH:68 |
| CTG | 0 | HOLD:36, WATCH:183 |
| FPT | 4 | BUY:4, CONDITIONAL_BUY:2, HOLD:72, WATCH:141 |
| GAS | 2 | AVOID:10, BUY:1, CONDITIONAL_BUY:6, HOLD:111, WATCH:91 |
| GVR | 2 | AVOID:71, BUY:2, CONDITIONAL_BUY:2, HOLD:76, WATCH:67 |
| HDB | 0 | BUY:1, HOLD:51, WATCH:168 |
| HPG | 3 | AVOID:83, BUY:3, CONDITIONAL_BUY:1, HOLD:55, WATCH:77 |
| MBB | 3 | AVOID:28, BUY:3, HOLD:47, WATCH:141 |
| MSN | 3 | AVOID:45, BUY:1, CONDITIONAL_BUY:6, HOLD:90, WATCH:76 |
| MWG | 1 | AVOID:50, BUY:1, HOLD:47, WATCH:120 |
| PLX | 5 | AVOID:46, CONDITIONAL_BUY:5, HOLD:85, WATCH:82 |
| POW | 6 | AVOID:39, BUY:6, HOLD:51, WATCH:123 |
| SAB | 0 | AVOID:26, CONDITIONAL_BUY:4, HOLD:114, WATCH:74 |
| SHB | 4 | AVOID:22, BUY:1, CONDITIONAL_BUY:6, HOLD:64, WATCH:126 |
| SSB | 10 | AVOID:11, BUY:5, CONDITIONAL_BUY:9, HOLD:97, WATCH:97 |
| SSI | 8 | AVOID:72, BUY:8, CONDITIONAL_BUY:4, HOLD:53, WATCH:81 |
| STB | 2 | AVOID:53, BUY:2, HOLD:40, WATCH:116 |
| TCB | 5 | AVOID:47, BUY:3, CONDITIONAL_BUY:9, HOLD:55, WATCH:103 |
| TPB | 2 | AVOID:25, BUY:2, HOLD:70, WATCH:122 |
| VCB | 2 | AVOID:17, CONDITIONAL_BUY:7, HOLD:66, WATCH:128 |
| VHM | 3 | AVOID:34, BUY:2, CONDITIONAL_BUY:3, HOLD:88, WATCH:88 |
| VIB | 2 | AVOID:38, BUY:2, HOLD:61, WATCH:119 |
| VIC | 0 | WATCH:13 |
| VJC | 8 | AVOID:52, BUY:7, CONDITIONAL_BUY:4, HOLD:105, WATCH:52 |
| VNM | 12 | AVOID:29, BUY:2, CONDITIONAL_BUY:18, HOLD:116, WATCH:53 |
| VPB | 3 | AVOID:51, BUY:2, CONDITIONAL_BUY:4, HOLD:73, WATCH:88 |
| VRE | 3 | AVOID:55, BUY:3, CONDITIONAL_BUY:2, HOLD:91, WATCH:67 |

---

Cách đọc: Hit% / Avg% sau phí round-trip; Excess = return mã − VNINDEX cùng cửa sổ. Nếu entry tốt hơn WATCH control và excess > 0 trên 60–90d → rule có tín hiệu sơ bộ.
