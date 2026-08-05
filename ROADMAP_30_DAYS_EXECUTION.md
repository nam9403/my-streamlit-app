# Project 1 - 30 Day Execution Roadmap

Goal: move from "technically healthy MVP" to "scalable, sellable product foundation" with measurable reliability, security, and growth metrics.

## North-Star Outcomes (Day 30)

- Runtime/data stack supports scale migration path (SQLite -> PostgreSQL-ready).
- Notification delivery architecture is queue-based and observable.
- Engineering quality gates are stricter with reduced false positives/flakes.
- Product analytics can answer activation, retention, and conversion questions.
- Production hardening has clearer security controls and operational playbooks.

---

## Week 1 (Days 1-7) - Scale Foundation

### 1) Data Layer Migration Plan (SQLite -> PostgreSQL-ready)
- Inventory all DB access points in `core/product_layer.py`, repositories, and scripts.
- Introduce DB config abstraction (driver/url/env-based), keep SQLite default.
- Define migration checklist (schema parity, indexes, transaction behavior).

Done when:
- A single DB configuration module is used by all repositories.
- App runs unchanged on SQLite after refactor.
- PostgreSQL migration checklist documented with risk notes.

### 2) Queue Architecture Hardening
- Formalize queue contract (`pending`, `done`, `failed`, retries/backoff).
- Move retry policy to centralized strategy.
- Add structured queue metrics export (processed/sent/retried/failed).

Done when:
- Queue behavior is deterministic and test-covered.
- `prod_readiness_check.py` can report queue health from consistent metrics.

### 3) CI Stability Baseline
- Investigate and patch Windows lock-file flake around `.pytest_tmp`.
- Ensure tests can run sequentially in gate steps where needed.

Done when:
- No intermittent `WinError 32` in repeated local CI simulation.

---

## Week 2 (Days 8-14) - Reliability + Test Depth

### 1) Coverage Expansion (target >= 45% -> 50%)
- Prioritize low-coverage but high-risk modules:
  - `core/ai_logic.py`
  - `core/scanner_service.py`
  - `core/app_*` panels/orchestration
  - `core/opportunity_3m_service.py`

Done when:
- Coverage gate increased to >= 45% first, then >= 50% if stable.
- New tests focus on behavior and regressions, not only happy paths.

### 2) Mypy Hardening Strategy
- Current scoped mypy is clean; expand scope gradually:
  - Step A: `core/analysis_*`
  - Step B: service/repository modules
  - Step C: full `core` (minus temporary excludes with TODO owners)

Done when:
- A planned list of temporary excludes exists with deadlines.
- At least one scope expansion is blocking in CI.

### 3) Runtime SLO Signals
- Add explicit SLO report artifact (latency/error budget/queue-fail ratios).
- Ensure `scale_gate_check.py` and `slo_gate_check.py` can be trended over time.

Done when:
- SLO artifacts are versioned per run and comparable over time.

---

## Week 3 (Days 15-21) - Security + Production Hardening

### 1) Secret Management Maturity
- Add key rotation playbook for `II_APP_SECRET_KEY`.
- Add explicit "rotation required by date" metadata/check.
- Tighten behavior when secret format invalid in prod mode.

Done when:
- Rotation workflow tested with fallback and rollback notes.
- `preflight_check.py --prod` enforces stricter secret hygiene.

### 2) Supply Chain & Dependency Controls
- Keep `pip-audit` in readiness flow; define policy by severity.
- Add dependency update cadence (weekly triage, monthly lock refresh).

Done when:
- Vulnerability policy is explicit (block/warn by severity).
- Dependency drift has owner and review cadence.

### 3) Access & Operational Safety
- Define operator-only actions (queue retry, migration tasks, admin tools).
- Add safe-guard rails for destructive or mass operations.

Done when:
- Critical operations require explicit confirm flags and are logged.

---

## Week 4 (Days 22-30) - Product Growth Instrumentation

### 1) Funnel Analytics You Can Sell
- Standardize events for:
  - onboarding complete
  - first analysis success
  - notification channel activated
  - upgrade intent / upgrade success
- Build KPI snapshots per day/week.

Done when:
- You can answer: activation rate, retention proxy, upgrade conversion by variant.

### 2) A/B Experiment Framework (lightweight)
- Persist variant assignment by user.
- Track variant performance in upgrade funnel automatically.
- Add winner selection logic with minimum sample threshold.

Done when:
- A/B report includes sample size, CTR, CVR, and confidence notes.

### 3) Sellability Pack
- Prepare concise technical due-diligence bundle:
  - architecture map
  - quality gate proofs
  - prod readiness artifacts
  - KPI trend snapshots

Done when:
- A buyer/investor can review project maturity in < 30 minutes.

---

## Weekly Operating Ritual (mandatory)

- Monday: choose 3 highest-impact tasks for the week.
- Daily: run `python scripts/quality_gate.py --strict-static`.
- Wednesday/Friday: run `python scripts/prod_readiness_check.py --require-go`.
- Friday: publish one-page weekly score:
  - quality status
  - reliability status
  - growth metrics status
  - next week risks.

---

## Suggested Command Pack

- Full quality:
  - `python scripts/quality_gate.py --strict-static`
- Production readiness:
  - `python scripts/prod_readiness_check.py --require-go`
- Architecture drift:
  - `python scripts/architecture_gate.py --strict`
- Test-only fast check:
  - `python -m pytest -q`

---

## Risk Register (Top 5)

- SQLite write contention under higher throughput.
- External data provider instability (portal/scraper dependencies).
- Queue reliability degradation if notification channels are misconfigured.
- Low coverage in orchestration-heavy modules may hide regression risk.
- Env/secret misconfiguration across staging/prod causing false readiness.

---

## Day-30 Exit Criteria (Go/No-Go)

- GO only if all true:
  - `quality_gate --strict-static` passes consistently.
  - `prod_readiness_check --require-go` passes consistently.
  - Coverage >= 45% minimum (target >= 50%).
  - No P0 security issues open.
  - Growth telemetry dashboard has at least 2 weeks of stable data.

