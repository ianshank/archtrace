#!/usr/bin/env python3
"""Run the test suite under the stdlib tracer and enforce the coverage floors.

Exits non-zero when a floor is breached, so it can sit in `make pre-pr` beside
the other deterministic gates. Thresholds come from `archtrace.config`, not from
literals here — see `archtrace config`.
"""

from __future__ import annotations

import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from archtrace import coverage  # noqa: E402  (after sys.path bootstrap)
from archtrace.log import configure  # noqa: E402


def _run_suite() -> None:
    loader = unittest.TestLoader()
    suite = loader.discover(os.path.join(HERE, "tests"), top_level_dir=HERE)
    with open(os.devnull, "w", encoding="utf-8") as sink:
        result = unittest.TextTestRunner(verbosity=0, stream=sink).run(suite)
    if not result.wasSuccessful():
        raise SystemExit("coverage gate: the test suite failed; fix that first")


def main() -> int:
    configure(os.environ.get("ARCHTRACE_LOG"))
    report = coverage.measure(_run_suite, os.path.join(HERE, "archtrace"))
    print(coverage.render(report))
    failures = report.failures()
    if failures:
        print("\ncoverage gate FAILED:")
        for failure in failures:
            print(f"  {failure}")
        print("\nRaise the tests, or lower the floor in archtrace.toml and say "
              "why in the commit.")
        return 1
    print(f"\ncoverage gate passed: total {report.percent}% "
          f"(floor {report.min_total_pct}%), "
          f"per-module floor {report.min_module_pct}%")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
