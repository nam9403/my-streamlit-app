# Playbook exit rules bake-off (Wave 2)

Generated: `2026-08-02T13:15:12.857184+00:00`

Exit bake-off học tập trên entry pit_quality — path sim no look-ahead trong cửa sổ giữ. Không cam kết lợi nhuận tương lai.

- Symbols OK: **30/30**
- Entry trades: **101**
- Entry style: `pit_quality`
- Best: **time90** — {'samples': 101, 'hit_rate_pct': 55.45, 'avg_return_pct': 4.377, 'median_return_pct': 1.007, 'avg_hold_days': 90.0, 'exit_reasons': {'time_stop': 101}}

| Rank | Variant | n | Hit% | Avg% | Median% | Avg hold | Reasons |
|---:|---|---:|---:|---:|---:|---:|---|
| 1 | `time90` | 101 | 55.45 | 4.377 | 1.007 | 90.0 | time_stop:101 |
| 2 | `time40_atr2` | 101 | 53.47 | 4.323 | 1.033 | 29.53 | atr_stop:42, time_stop:59 |
| 3 | `time60_atr2` | 101 | 43.56 | 3.788 | -3.033 | 40.3 | atr_stop:52, time_stop:49 |
| 4 | `time40` | 101 | 58.42 | 3.475 | 1.724 | 40.0 | time_stop:101 |
| 5 | `time60` | 101 | 55.45 | 3.426 | 1.725 | 60.0 | time_stop:101 |
| 6 | `time40_atr2_gb` | 101 | 55.45 | 2.313 | 2.581 | 25.17 | atr_stop:40, giveback:28, time_stop:33 |
| 7 | `time60_atr2_gb` | 101 | 53.47 | 2.052 | 2.581 | 29.68 | atr_stop:46, giveback:41, time_stop:14 |
| 8 | `time60_gb` | 101 | 62.38 | 1.614 | 4.032 | 48.02 | giveback:41, time_stop:60 |
| 9 | `time40_gb` | 101 | 58.42 | 1.359 | 2.795 | 35.13 | giveback:28, time_stop:73 |
| 10 | `time20` | 101 | 55.45 | 1.0 | 0.588 | 20.0 | time_stop:101 |

## Recommendation

Khuyến nghị paper/nightly horizon **90d** theo variant `time90` (n=101, hit=55.45%, avg=4.377%). Cần paper live để xác nhận; không cam kết lợi nhuận tương lai.

## Operational lock

- Variant: `time40_atr2`
- Horizon: **40d**
- Van hanh (paper/nightly): horizon **40d** theo `time40_atr2` (hit=53.47%, avg=4.323%, median=1.033%). Raw-avg leader `time90` khong dung mac dinh.
