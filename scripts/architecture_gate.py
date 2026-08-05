#!/usr/bin/env python3
"""
Unified architecture gate:
1) check boundaries
2) generate dependency map
3) compare dependency drift
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _run(cmd: list[str]) -> int:
    print(f"> {' '.join(cmd)}")
    result = subprocess.run(cmd, cwd=str(ROOT))
    return int(result.returncode)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--strict", action="store_true", help="Fail on dependency drift warnings.")
    parser.add_argument("--write-baseline", action="store_true", help="Write/update dependency baseline and exit.")
    args = parser.parse_args()

    if args.write_baseline:
        rc_gen = _run([sys.executable, "scripts/generate_dependency_map.py"])
        if rc_gen != 0:
            return rc_gen
        rc_base = _run([sys.executable, "scripts/compare_dependency_map.py", "--write-baseline"])
        return rc_base

    steps: list[list[str]] = [
        [sys.executable, "scripts/check_architecture_boundaries.py"],
        [sys.executable, "scripts/generate_dependency_map.py"],
    ]
    for cmd in steps:
        rc = _run(cmd)
        if rc != 0:
            return rc

    drift_cmd = [sys.executable, "scripts/compare_dependency_map.py"]
    if args.strict:
        drift_cmd.append("--strict")
    return _run(drift_cmd)


if __name__ == "__main__":
    raise SystemExit(main())

