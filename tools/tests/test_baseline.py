"""The SPEC §9a instrument, tested on its numbers rather than its prose.

`cmd_baseline` was 156 lines interleaving the arithmetic with 54 `print` calls,
so the only way to assert what §9a computed was to capture stdout and parse it
back. §9a is the measurement NEXT-STEPS calls blocking -- the one that decides
whether the whole programme is worth running -- which made it the worst thing
in the codebase to have been unable to test directly.
"""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from archtrace import baseline, canon
from archtrace.config import BaselinePolicy
from archtrace.model import Engagement

EXAMPLE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "example")


class Percent(unittest.TestCase):
    """Three call sites want three different empty-denominator answers, and
    getting that wrong silently is how a measurement reports 100% of nothing."""

    def test_ordinary_integer_percent(self):
        self.assertEqual(baseline._pct(1, 2), 50)
        self.assertEqual(baseline._pct(1, 3), 33, "floor, never round")
        self.assertEqual(baseline._pct(2, 3), 66)

    def test_the_caller_states_the_empty_answer(self):
        self.assertEqual(baseline._pct(0, 0), 0)
        self.assertEqual(baseline._pct(0, 0, empty=100), 100)


class Measure(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.root = os.path.join(self.tmp, "example")
        shutil.copytree(EXAMPLE, self.root)

    def _patch(self, mutate):
        path = os.path.join(self.root, "model", "model.json")
        doc = canon.load_json(path)
        mutate(doc)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(canon.canonical_json(doc))

    def _measure(self):
        return baseline.measure(Engagement.load(self.root))

    def test_the_worked_example_scores_as_documented(self):
        """README states these numbers as the argument for grounding kinds:
        50% traceability is healthy, and 0% unexplained is what decides."""
        scored = self._measure()
        self.assertEqual(scored.total, 10)
        self.assertEqual(scored.traceability, 50)
        self.assertEqual(scored.unexplained, 0)
        self.assertEqual(scored.unexplained_pct, 0)
        self.assertEqual(scored.coverage, 100)
        self.assertEqual(scored.backed, 100)

    def test_the_kind_breakdown_sums_to_its_own_subtotal(self):
        """The defect that shipped once: per-kind rows counted grounding
        ENTRIES while the subtotal counted ELEMENTS, so an element citing two
        pieces of evidence for one kind was counted twice and the column did
        not add up."""
        scored = self._measure()
        self.assertEqual(sum(scored.by_kind.values()), scored.otherwise)

    def test_an_ungrounded_element_is_unexplained_not_otherwise(self):
        self._patch(lambda d: d["people"][0].update(grounding=[]))
        scored = self._measure()
        self.assertEqual(scored.unexplained, 1)
        self.assertEqual(scored.unexplained_pct, 10)

    def test_a_satisfies_without_a_quote_is_not_counted_as_backed(self):
        """An element claiming to satisfy a requirement that has no citation is
        the exact fabrication the gate exists to stop, so it must not be
        counted as quotable."""
        path = os.path.join(self.root, "requirements", "requirements.json")
        doc = canon.load_json(path)
        for req in doc["requirements"]:
            req["provenance"] = []
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(canon.canonical_json(doc))
        scored = self._measure()
        self.assertEqual(scored.quotable, 0)
        self.assertLess(scored.backed, 100)

    def test_an_out_of_scope_entry_missing_req_does_not_crash_the_instrument(self):
        """G3's finding to report, not a KeyError out of the measurement."""
        self._patch(lambda d: d["out_of_scope"][0].pop("req"))
        scored = self._measure()
        self.assertEqual(scored.total, 10)


class Decide(unittest.TestCase):
    """The decision rules, without capturing stdout."""

    POLICY = BaselinePolicy()

    def _baseline(self, **over):
        fields = {"rows": [], "by_kind": {}, "total": 10, "quotable": 10,
                  "claims_req": 10, "otherwise": 0, "unexplained": 0,
                  "confirmed": 5, "accounted": 5}
        fields.update(over)
        return baseline.Baseline(**fields)

    def test_a_clean_engagement_proceeds(self):
        verdict = baseline.decide(self._baseline(), self.POLICY)
        self.assertTrue(verdict.passed)
        self.assertTrue(all("[PASS]" in line for line in verdict.lines))

    def test_too_much_unexplained_stops_the_programme(self):
        """The one stop condition. 3 of 10 is 30% against a 20% bar."""
        verdict = baseline.decide(
            self._baseline(unexplained=3, quotable=7, claims_req=7),
            self.POLICY)
        self.assertFalse(verdict.passed)
        self.assertTrue(any("[STOP]" in line for line in verdict.lines))

    def test_exactly_at_the_bar_passes(self):
        """`>` not `>=`: 20% against max_unexplained_pct=20 is a pass. An
        off-by-one here changes the answer for the whole programme."""
        verdict = baseline.decide(
            self._baseline(unexplained=2, quotable=8, claims_req=8),
            self.POLICY)
        self.assertTrue(verdict.passed, verdict.lines)

    def test_an_unbacked_citation_claim_is_a_fix_not_a_stop(self):
        verdict = baseline.decide(
            self._baseline(quotable=5, claims_req=10), self.POLICY)
        self.assertFalse(verdict.passed)
        self.assertTrue(any("[FIX]" in line for line in verdict.lines))

    def test_the_policy_is_honoured_not_hardcoded(self):
        """The thresholds are configuration; a stricter policy must bite."""
        strict = BaselinePolicy(max_unexplained_pct=0)
        scored = self._baseline(unexplained=1, quotable=9, claims_req=9)
        self.assertFalse(baseline.decide(scored, strict).passed)
        self.assertTrue(baseline.decide(scored, self.POLICY).passed)


if __name__ == "__main__":
    unittest.main(verbosity=2)
