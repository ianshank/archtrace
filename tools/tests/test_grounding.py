"""The derivation graph, measured rather than assumed.

G14's own tests in `test_gate.py` prove the rule fires. These prove the numbers
underneath it -- depth, assumption taint, ADR load -- because those reach the
operator through `archtrace report` and `archtrace review`, where nothing exits
non-zero and a wrong number is therefore silent.
"""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from archtrace import canon
from archtrace.grounding import analyse
from archtrace.model import Engagement

EXAMPLE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "example")


class DerivationGraph(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.root = os.path.join(self.tmp, "example")
        shutil.copytree(EXAMPLE, self.root)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _patch(self, mutate):
        path = os.path.join(self.root, "model", "model.json")
        doc = canon.load_json(path)
        mutate(doc)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(canon.canonical_json(doc))

    def _analyse(self):
        return analyse(Engagement.load(self.root))

    @staticmethod
    def _container(doc, ident):
        return next(c for c in doc["systems"][0]["containers"]
                    if c["id"] == ident)

    # -- foundedness ------------------------------------------------------

    def test_the_shipped_example_is_entirely_founded(self):
        analysis = self._analyse()
        self.assertEqual(analysis.unfounded, ())
        self.assertEqual(analysis.cycles, ())

    def test_a_dangling_derivation_target_is_unfounded_not_a_crash(self):
        """G4 reports the unknown id. G14 must still produce an answer rather
        than a KeyError, because a rule that crashes loses every other rule's
        findings along with its own."""
        def mutate(doc):
            self._container(doc, "c_worker")["grounding"] = [
                {"kind": "derived", "from": "c_nope", "adr": "ADR-001"}]
        self._patch(mutate)
        self.assertEqual(self._analyse().unfounded, ("c_worker",))

    # -- depth ------------------------------------------------------------

    def test_depth_counts_hops_to_the_nearest_real_reason(self):
        analysis = self._analyse()
        self.assertEqual(analysis.depth["c_queue"], 0)
        self.assertEqual(analysis.depth["c_worker"], 1)
        self.assertEqual(analysis.max_depth, 1)

    def test_depth_follows_the_shortest_route_not_the_longest(self):
        """An element with a good reason and a long one is as well founded as
        its best reason. Scoring it by the worst route would penalise an
        architect for recording more than the minimum."""
        def mutate(doc):
            self._container(doc, "c_worker")["grounding"] = [
                {"kind": "derived", "from": "c_prefetch", "adr": "ADR-001"},
                {"kind": "derived", "from": "c_queue", "adr": "ADR-001"}]
            self._container(doc, "c_prefetch")["grounding"] = [
                {"kind": "derived", "from": "c_audit", "adr": "ADR-001"}]
        self._patch(mutate)
        analysis = self._analyse()
        self.assertEqual(analysis.depth["c_prefetch"], 1)
        self.assertEqual(analysis.depth["c_worker"], 1)

    # -- assumption taint -------------------------------------------------

    def test_an_assumption_grounded_element_is_tainted(self):
        """`c_prefetch` ships grounded on OQ-001 and nothing else."""
        self.assertIn("c_prefetch", self._analyse().tainted)

    def test_taint_propagates_through_derivation(self):
        """This is the reading that matters. An element derived from a guess
        presents in every render as `derived` -- a consequence of a documented
        decision -- while resting on an open question two hops down."""
        def mutate(doc):
            self._container(doc, "c_worker")["grounding"] = [
                {"kind": "derived", "from": "c_prefetch", "adr": "ADR-001"}]
        self._patch(mutate)
        analysis = self._analyse()
        self.assertIn("c_worker", analysis.tainted)
        self.assertEqual(analysis.unfounded, ())

    def test_a_second_firm_route_clears_the_taint(self):
        """Taint means EVERY route passes through a guess, not that one does."""
        def mutate(doc):
            self._container(doc, "c_worker")["grounding"] = [
                {"kind": "derived", "from": "c_prefetch", "adr": "ADR-001"},
                {"kind": "derived", "from": "c_queue", "adr": "ADR-001"}]
        self._patch(mutate)
        self.assertNotIn("c_worker", self._analyse().tainted)

    def test_a_requirement_backed_element_is_never_tainted(self):
        self.assertNotIn("c_queue", self._analyse().tainted)

    # -- cycles -----------------------------------------------------------

    def test_a_two_element_cycle_is_reported_as_one_component(self):
        def mutate(doc):
            for a, b in (("c_api", "c_edge"), ("c_edge", "c_api")):
                self._container(doc, a)["grounding"] = [
                    {"kind": "derived", "from": b, "adr": "ADR-001"}]
        self._patch(mutate)
        analysis = self._analyse()
        self.assertEqual(analysis.cycles, (("c_api", "c_edge"),))
        self.assertEqual(analysis.cycle_containing("c_api"),
                         ("c_api", "c_edge"))
        self.assertIsNone(analysis.cycle_containing("c_queue"))

    def test_a_self_derivation_is_a_cycle(self):
        def mutate(doc):
            self._container(doc, "c_worker")["grounding"] = [
                {"kind": "derived", "from": "c_worker", "adr": "ADR-001"}]
        self._patch(mutate)
        self.assertEqual(self._analyse().cycles, (("c_worker",),))

    def test_a_three_element_cycle_is_one_component(self):
        def mutate(doc):
            for a, b in (("c_api", "c_edge"), ("c_edge", "c_worker"),
                         ("c_worker", "c_api")):
                self._container(doc, a)["grounding"] = [
                    {"kind": "derived", "from": b, "adr": "ADR-001"}]
        self._patch(mutate)
        self.assertEqual(self._analyse().cycles,
                         (("c_api", "c_edge", "c_worker"),))

    def test_a_long_chain_is_not_mistaken_for_a_cycle(self):
        def mutate(doc):
            for a, b in (("c_api", "c_edge"), ("c_edge", "c_queue")):
                self._container(doc, a)["grounding"] = [
                    {"kind": "derived", "from": b, "adr": "ADR-001"}]
        self._patch(mutate)
        analysis = self._analyse()
        self.assertEqual(analysis.cycles, ())
        self.assertEqual(analysis.depth["c_api"], 2)
        self.assertEqual(analysis.max_depth, 2)

    # -- ADR load ---------------------------------------------------------

    def test_adr_load_counts_what_one_decision_holds_up(self):
        """G4 already forces every `derived` entry to cite an ADR, so "ADR
        coverage" is 100% on any model that passes and measures nothing. What
        is worth knowing is concentration: if one decision is load-bearing for
        half the model and it was wrong, half the model is wrong.

        Asserted as a delta. The example's own ADR-001 load is part of the
        fixture, not part of this claim, and a test that hardcodes it breaks
        the next time someone adds a `derived` element to the example.
        """
        before = self._analyse().adr_load.get("ADR-001", 0)

        def mutate(doc):
            for ident in ("c_api", "c_edge"):
                self._container(doc, ident)["grounding"] = [
                    {"kind": "derived", "from": "c_queue", "adr": "ADR-001"}]
        self._patch(mutate)
        self.assertEqual(self._analyse().adr_load["ADR-001"], before + 2)

    def test_adr_load_counts_relationships_as_well_as_elements(self):
        """The example grounds `c_queue->c_worker` as `derived`, so dropping
        relationships from the traversal would lose a real citation. That loop
        is exactly the one `docs/tech-debt.md` §2a found untested twice."""
        before = self._analyse().adr_load.get("ADR-001", 0)
        self.assertGreater(before, 1,
                           "the example no longer grounds a relationship as "
                           "`derived`, so this test proves nothing")

        def mutate(doc):
            for rel in doc["relationships"]:
                if any(g.get("kind") == "derived"
                       for g in rel.get("grounding", [])):
                    rel["grounding"] = [{"kind": "standard",
                                         "standard": "STD-001"}]
        self._patch(mutate)
        self.assertEqual(self._analyse().adr_load.get("ADR-001"), before - 1)

    def test_adr_load_is_empty_when_nothing_is_derived(self):
        def mutate(doc):
            firm = [{"kind": "standard", "standard": "STD-001"}]
            self._container(doc, "c_worker")["grounding"] = list(firm)
            for rel in doc["relationships"]:
                if any(g.get("kind") == "derived"
                       for g in rel.get("grounding", [])):
                    rel["grounding"] = list(firm)
        self._patch(mutate)
        self.assertEqual(self._analyse().adr_load, {})

    # -- totality ---------------------------------------------------------

    def test_a_malformed_grounding_entry_does_not_crash_the_analysis(self):
        """Gate rules stay total over malformed input; so must the analysis
        they call, or one bad field costs every finding in the run."""
        def mutate(doc):
            self._container(doc, "c_worker")["grounding"] = [
                "not-an-object", {}, {"kind": "derived"}]
        self._patch(mutate)
        self.assertEqual(self._analyse().unfounded, ("c_worker",))


if __name__ == "__main__":
    unittest.main()
