# Walk-forward playbook OOS (Wave 1)

Generated: `2026-08-02T12:41:46.026997+00:00`

Walk-forward học tập — không cam kết lợi nhuận tương lai. Embargo tách train/test; train_select không được xem test.

- Mode: **locked**
- Date range: `2022-01-17` → `2026-03-30`
- Folds: **3/3** pass (total 6)
- Gate PASS: **True**
- PASS nếu ≥ nửa fold test (≥8 samples @ 60d) thắng WATCH avg hoặc excess@60d > 0.
- OOS pooled entry trades: **62**

## OOS pooled entry

| Horizon | Samples | Hit% | Avg% | Excess% |
|---|---:|---:|---:|---:|
| 20d | 62 | 53.23 | 1.581 | 5.01 |
| 40d | 60 | 55.0 | 3.045 | 2.906 |
| 60d | 62 | 56.45 | 5.494 | 7.967 |
| 90d | 62 | 56.45 | 7.566 | 0.813 |

- OOS entry beats WATCH: **True** (4/4)

## Per fold (test)

| Fold | Test window | n | Avg60 | Ex60 | vsWATCH | PASS | Selected |
|---:|---|---:|---:|---:|---|---|---|
| 0 | 2023-07-28→2024-01-27 | 7 | 1.579 | 13.318 | False | False | `locked:pit_quality` |
| 1 | 2024-02-07→2024-08-06 | 15 | 3.296 | 15.035 | True | True | `locked:pit_quality` |
| 2 | 2024-08-17→2025-02-16 | 23 | 0.261 | 10.05 | True | True | `locked:pit_quality` |
| 3 | 2025-02-27→2025-08-26 | 16 | 17.297 | -4.109 | True | True | `locked:pit_quality` |
| 4 | 2025-09-06→2026-03-05 | 1 | -2.626 | 9.762 | False | False | `locked:pit_quality` |
| 5 | 2026-03-16→2026-03-30 | 0 | None | None | False | False | `locked:pit_quality` |
