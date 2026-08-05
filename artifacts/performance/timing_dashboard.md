# Timing Dashboard Mini

- Generated at (UTC): `2026-05-02T04:54:47.058157+00:00`
- Source: `E:/Du an 1/data/reports/logs/timing_metrics.jsonl`
- Total parsed timing events: `82`
- Minimum samples per metric: `1`

## Percentiles by flow

| Flow | Samples | Min | p50 | p90 | p95 | p99 | Avg | Std | Max |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `scanner.scan_potential_stocks` | 8 | 3.90 | 13.35 | 1079.89 | 1215.54 | 1324.06 | 300.62 | 504.23 | 1351.19 |
| `product_layer.get_admin_kpi` | 22 | 3.00 | 9.01 | 13.01 | 14.43 | 70.62 | 11.73 | 16.50 | 85.53 |
| `product_layer.process_notification_queue` | 8 | 10.01 | 12.01 | 14.01 | 14.01 | 14.01 | 12.20 | 1.32 | 14.01 |
| `scanner.load_autopilot_board` | 6 | 1.44 | 7.32 | 12.21 | 12.56 | 12.83 | 7.24 | 4.34 | 12.90 |
| `product_layer.get_kpi_dashboard` | 34 | 1.00 | 2.00 | 7.21 | 12.36 | 13.68 | 2.96 | 3.43 | 14.01 |
| `product_layer.get_notification_queue_diagnostics` | 2 | 11.01 | 11.01 | 11.01 | 11.01 | 11.01 | 11.01 | 0.00 | 11.01 |
| `product_layer.retry_failed_notifications` | 2 | 1.00 | 1.50 | 1.90 | 1.95 | 1.99 | 1.50 | 0.50 | 2.00 |

## Required flow sample coverage

- Required flows covered: `1/5`
- Coverage ratio: `0.2`
- All required flows covered: `False`

| Flow | Samples | Required min samples | Meets target |
|---|---:|---:|:---:|
| `product_layer.get_admin_kpi` | 22 | 30 | no |
| `product_layer.process_notification_queue` | 8 | 30 | no |
| `product_layer.get_notification_queue_diagnostics` | 2 | 30 | no |
| `product_layer.retry_failed_notifications` | 2 | 30 | no |
| `product_layer.get_kpi_dashboard` | 34 | 30 | yes |

## Optimization targets

- Slowest p95 flow: `scanner.scan_potential_stocks` (1215.54 ms)
- Prioritize reducing p95 first, then avg.
