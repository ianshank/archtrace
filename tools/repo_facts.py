#!/usr/bin/env python3
"""The repository's own measurable facts, computed rather than typed.

Repository maintenance, not product: this sits beside `coverage_gate.py` in
`tools/` and is deliberately not part of the shipped `archtrace` package. A user
of the tool has no business counting archtrace's tests.

It exists because a hand-written count of anything in this repository has a
half-life of about two commits. The test count alone:

    a02eb09  226  CHANGELOG 0.5.0 written, claiming "183 -> 226"   <- true here
    badaec1  228  two commits later
    41d47ac  240  two commits after that

Nobody was careless. The number was correct the day it was typed and could not
stay correct, which is the argument for not typing it. `docs/architecture.svg`
drew "157 tests" for four releases, and `docs/code-quality-plan.md` records the
same failure a release earlier ("CHANGELOG.md's 0.3.0 entry said `cli.py`
reached 215 lines and 155 tests"). Three instances of one defect is a missing
mechanism, not three oversights.

Everything here is a pure function over the checked-out tree. No network, no
clock, no writes -- the diagram generators and the test suite both read from it,
so if it lied they would agree on the lie.
"""

from __future__ import annotations

import os
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOOLS = os.path.join(REPO, "tools")
TESTS = os.path.join(TOOLS, "tests")


def _flatten(suite) -> list:
    """Every leaf case in a suite tree, in discovery order."""
    if not isinstance(suite, unittest.TestSuite):
        return [suite]
    found: list = []
    for child in suite:
        found.extend(_flatten(child))
    return found


def test_cases() -> list:
    """Every test the suite would run, discovered exactly as `make test` does.

    Raises rather than returning a number when a test module fails to import.
    `unittest.discover` substitutes a `_FailedTest` placeholder for a module it
    cannot load, which still counts as one case -- so a broken import would
    quietly shrink the count by however many tests that module held and report a
    plausible smaller number. A fact that degrades into a plausible wrong answer
    is worse than one that refuses.
    """
    cases = _flatten(unittest.TestLoader().discover(TESTS, top_level_dir=TOOLS))
    broken = [c for c in cases if type(c).__name__ == "_FailedTest"]
    if broken:
        raise RuntimeError(
            "test discovery failed for: "
            + ", ".join(sorted(c.id() for c in broken))
            + ". Refusing to report a count that silently omits them.")
    return cases


def test_count() -> int:
    """How many tests `make test` runs."""
    return len(test_cases())


def rule_ids() -> list:
    """Every gate rule id, in registry order -- the order `check` runs them."""
    import sys
    if TOOLS not in sys.path:
        sys.path.insert(0, TOOLS)
    from archtrace import gate
    return [rid for rid, _severity, _fn in gate.RULES]


def renderer_version() -> str:
    """The version G6 stamps into `render/.manifest.json`."""
    import sys
    if TOOLS not in sys.path:
        sys.path.insert(0, TOOLS)
    from archtrace import model
    return model.RENDERER_VERSION


def coverage_floors() -> tuple:
    """`(total, per-module)` line-coverage floors this build enforces.

    The floor, not the measurement. A measured percentage is a snapshot that
    goes stale on the next commit; a floor is a claim the build keeps on every
    commit, which is the thing a diagram should be citing.
    """
    import sys
    if TOOLS not in sys.path:
        sys.path.insert(0, TOOLS)
    from archtrace import config
    policy = config.DEFAULT.coverage
    return policy.min_total_pct, policy.min_module_pct


def summary() -> dict:
    """Everything at once, for a caller that wants to print a strapline."""
    total, per_module = coverage_floors()
    return {
        "tests": test_count(),
        "rules": len(rule_ids()),
        "renderer": renderer_version(),
        "coverage_floor": total,
        "module_coverage_floor": per_module,
    }


if __name__ == "__main__":
    for key, value in summary().items():
        print(f"{key:24} {value}")
