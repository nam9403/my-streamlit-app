#!/usr/bin/env python3
"""
Unified quality gate for local and CI usage.

Default mode is advisory for static analysis and strict for tests.
Use --strict-static to make ruff/mypy blocking.
"""
from __future__ import annotations

import argparse
import importlib.util
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _run(cmd: list[str]) -> int:
    print(f"> {' '.join(cmd)}")
    result = subprocess.run(cmd, cwd=str(ROOT))
    return int(result.returncode)


def _has_pytest_cov() -> bool:
    return importlib.util.find_spec("pytest_cov") is not None


def _has_pytest_xdist() -> bool:
    return importlib.util.find_spec("xdist") is not None


def _expand_repo_globs(patterns: list[str]) -> list[str]:
    expanded: list[str] = []
    for pattern in patterns:
        if "*" in pattern or "?" in pattern:
            matches = sorted(ROOT.glob(pattern))
            expanded.extend([str(p.relative_to(ROOT)) for p in matches if p.is_file()])
        else:
            expanded.append(pattern)
    return expanded


def main() -> int:
    parser = argparse.ArgumentParser(
        epilog=(
            "Parallel tests: II_PYTEST_WORKERS=auto (pytest-xdist). "
            "Faster local: --skip-slow-tests / --skip-network-tests (pytest markers in conftest)."
        ),
    )
    parser.add_argument("--skip-tests", action="store_true", help="Skip pytest coverage gate.")
    parser.add_argument("--skip-static", action="store_true", help="Skip ruff and mypy checks.")
    parser.add_argument("--skip-performance", action="store_true", help="Skip performance dashboard and perf gate check.")
    parser.add_argument(
        "--strict-static",
        action="store_true",
        help="Treat static analysis failures as blocking.",
    )
    parser.add_argument(
        "--strict-performance",
        action="store_true",
        help="Treat performance HOLD as blocking (require PASS).",
    )
    parser.add_argument(
        "--skip-network-tests",
        action="store_true",
        help='Exclude tests marked "network" (pytest -m "not network").',
    )
    parser.add_argument(
        "--skip-slow-tests",
        action="store_true",
        help='Exclude tests marked "slow" (pytest -m "not slow").',
    )
    args = parser.parse_args()

    if not args.skip_static:
        architecture_cmd = [sys.executable, "scripts/architecture_gate.py"]
        if args.strict_static:
            architecture_cmd.append("--strict")
        ruff_targets = [
            "app.py",
            "core/app_*.py",
            "scripts/quality_gate.py",
            "scripts/preflight_check.py",
            "scripts/prod_readiness_check.py",
            "scripts/check_secrets.py",
            "scripts/architecture_gate.py",
            "scripts/check_architecture_boundaries.py",
            "scripts/generate_dependency_map.py",
            "scripts/compare_dependency_map.py",
            "scripts/generate_engineering_scorecard.py",
            "scripts/update_engineering_scorecard_history.py",
            "scripts/release_readiness_summary.py",
            "scripts/create_incident_report.py",
            "scripts/sanitize_runtime_artifacts.py",
            "scripts/stabilize_runtime_reliability.py",
        ]
        mypy_targets = [
            "app.py",
            "core/app_*.py",
            "scripts/quality_gate.py",
            "scripts/preflight_check.py",
            "scripts/prod_readiness_check.py",
            "scripts/check_secrets.py",
            "scripts/architecture_gate.py",
            "scripts/check_architecture_boundaries.py",
            "scripts/generate_dependency_map.py",
            "scripts/compare_dependency_map.py",
            "scripts/generate_engineering_scorecard.py",
            "scripts/update_engineering_scorecard_history.py",
            "scripts/release_readiness_summary.py",
            "scripts/create_incident_report.py",
            "scripts/sanitize_runtime_artifacts.py",
            "scripts/stabilize_runtime_reliability.py",
        ]
        strict_commands = [
            [sys.executable, "-m", "ruff", "check", *ruff_targets],
            architecture_cmd,
            [sys.executable, "scripts/generate_engineering_scorecard.py"],
            [sys.executable, "scripts/update_engineering_scorecard_history.py"],
        ]
        advisory_commands = [
            [sys.executable, "-m", "mypy", *_expand_repo_globs(mypy_targets)],
        ]
        for cmd in strict_commands:
            rc = _run(cmd)
            if rc != 0 and args.strict_static:
                print("[FAIL] Static analysis failed in strict mode.")
                return rc
            if rc != 0 and not args.strict_static:
                print("[WARN] Static analysis failed in advisory mode.")
        for cmd in advisory_commands:
            rc = _run(cmd)
            if rc != 0:
                print("[WARN] Static analysis failed in advisory mode.")

    if not args.skip_tests:
        test_cmd = [sys.executable, "-m", "pytest", "-q"]
        if _has_pytest_cov():
            test_cmd.extend(
                [
                    "--cov=core",
                    "--cov=app",
                    "--cov-report=term-missing",
                    "--cov-fail-under=40",
                ]
            )
        else:
            print("[WARN] pytest-cov is not installed; running tests without coverage gate locally.")
        workers = str(os.environ.get("II_PYTEST_WORKERS", "")).strip()
        if workers:
            if _has_pytest_xdist():
                test_cmd.extend(["-n", workers])
            else:
                print("[WARN] II_PYTEST_WORKERS is set but pytest-xdist is not installed; running tests serially.")
        marker_parts: list[str] = []
        if args.skip_network_tests:
            marker_parts.append("not network")
        if args.skip_slow_tests:
            marker_parts.append("not slow")
        if marker_parts:
            test_cmd.extend(["-m", " and ".join(marker_parts)])
        test_rc = _run(test_cmd)
        if test_rc != 0:
            print(f"[FAIL] Test quality gate failed with exit code {test_rc}.")
            return test_rc

    if not args.skip_performance:
        perf_commands = [
            [
                sys.executable,
                "scripts/build_timing_dashboard.py",
                "--required-min-samples",
                "30",
                "--window-hours",
                "2",
            ],
            [sys.executable, "scripts/perf_gate_check.py", "--profile", "dev"],
        ]
        if args.strict_performance:
            perf_commands[1].append("--require-pass")
        for cmd in perf_commands:
            rc = _run(cmd)
            if rc != 0 and args.strict_performance:
                print("[FAIL] Performance gate failed in strict mode.")
                return rc
            if rc != 0 and not args.strict_performance:
                print("[WARN] Performance gate failed in advisory mode.")

    print("[OK] Quality gate passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

