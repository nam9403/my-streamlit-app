# Project 1 - Weaknesses, Gaps, and Full Upgrade Plan

## Current Assessment

The project is in a strong Late-MVP/Early-Growth state, with meaningful product depth, broad test coverage by feature, and release/readiness scripts.  
The biggest risks are not feature gaps, but architecture concentration, production scalability, and engineering governance maturity.

## Critical Weaknesses

1. Monolithic orchestration risk
- `app.py` contains UI, orchestration, and domain integration in one large runtime flow.
- Blast radius is high when changing one area.

2. Centralized "god layer" risk
- `core/product_layer.py` still aggregates many responsibilities, even after service/repository refactors.
- Long-term maintainability and onboarding speed will degrade as scope grows.

3. Limited production platform baseline
- Missing containerized deployment standard and environment promotion model.
- Operational reproducibility and rollback confidence are limited.

4. Quality gate maturity gap
- Test quantity is good, but previously no minimum coverage gate in CI.
- Static analysis baseline was not codified in pipeline.

5. Dependency reproducibility gap
- Runtime dependencies use open ranges (`>=`), increasing drift risk across environments.

## Missing Components for Scale

1. Platform
- Docker image build pipeline, staging/prod parity, and release promotion strategy.

2. Observability
- Centralized metrics/tracing/alerting stack with production SLO dashboards.

3. Data layer evolution
- Planned migration path from SQLite-bound growth limits to managed database for concurrency and reliability.

4. Security governance
- Secret rotation policy automation, access controls, and operational audit trail hardening.

5. Engineering governance
- Enforced architecture boundaries, ownership map, and quality scorecard per release.

## Solution Strategy (Phased)

## Phase 1 (Completed in this upgrade pass)
- Add coverage tooling and enforce minimum project coverage in test execution.
- Add static analysis tooling (`ruff`, `mypy`) and wire advisory checks into CI.
- Create this consolidated master upgrade plan for execution tracking.

## Phase 2 (Next 1-2 sprints)
- Split `app.py` into feature entry modules and reduce import fan-in.
- Continue extraction from `core/product_layer.py` into dedicated domain services.
- Add architecture tests for import boundaries between UI/orchestration/domain/persistence.

## Phase 3 (2-4 sprints)
- Introduce container build and environment-specific deployment templates.
- Add release promotion gates (staging -> production) and rollback checklist automation.
- Add reliability checks for latency/error budgets in CI/CD reporting.

## Phase 4 (4-8 sprints)
- Introduce managed database migration strategy with compatibility layer.
- Add full observability (metrics + tracing + alerts + dashboards).
- Add security/compliance runbooks and rotation workflows.

## Execution KPIs

- Coverage floor: >= 45% now, then raise progressively to 55% and 65%.
- Static analysis trend: advisory in CI now, then switch to blocking gates by scope.
- File-size and dependency graph KPIs:
  - reduce direct domain imports in `app.py`
  - reduce public API surface in `core/product_layer.py`
- Release stability:
  - preflight/prod-readiness pass rate
  - regression incident count after release

## Delivery Rule

Do upgrades in small, reversible increments:
- one architecture slice at a time
- tests before/alongside extraction
- no broad rewrites without migration wrappers
