# Process audit pack (P3)

Generated: 2026-08-02T09:27:31.309618+00:00

Gói audit quy trình mô tả kiểm soát vận hành và minh bạch dữ liệu. Không phải chứng nhận đầu tư, không cam kết lợi nhuận.

## 1. Data & nightly pipeline

- Nightly board OK: **False**
- Coverage: **100.0%**
- Fail rate: **0.0%**
- Board age (h): **67.6683403975**

## 2. Decision quality controls

- Completeness gate (CFO/NI/bank-aware): `core/decision_completeness.py`
- Unified action gate: `core/decision_action_gate.py`
- Decision playbook (Thesis/Setup/Trigger): `core/decision_playbook.py`
- CONDITIONAL_BUY in gate + board ranking
- Data integrity (OHLCV/MOS/RSI/paper allowlist): `core/data_integrity.py`
- Data trust score: `core/data_trust_score.py`
- Proprietary blend (flow+val+phase+WF+playbook nudge): `core/proprietary_signal.py`
- Live Autopilot ranking = nightly `score_rows`

## 3. Accountability artifacts

- Paper 30d samples: **0**
- Paper 30d hit-rate: **None%**
- Public trust page present: **True**

## 4. SLO / performance

- Autopilot p95: **—**
- Fail rate nightly scan: **—%**

## 5. Test suite

- Pytest: _not run (use `--with-pytest` to include)_

## 6. Production database & growth

- II_DB_URL set: **False**
- II_ENV: **dev**
- Universe mode default: **dynamic_liquid** (`II_AUTOPILOT_UNIVERSE_MODE`)

- Production profile ok: **True**

---

Audit này mô tả quy trình nội bộ; không thay thế tư vấn pháp lý/đầu tư.
