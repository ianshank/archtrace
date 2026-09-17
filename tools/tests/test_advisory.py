"""The advisory plane, held to the one property it can actually promise.

Nothing here gates, which is exactly why it needs tests: a deterministic rule
that breaks turns a build red, and an advisory that breaks produces a document
that still looks like a document. The two claims worth pinning are that the
worklist says something true and that an external reviewer cannot say anything
archtrace would appear to endorse.
"""

from __future__ import annotations

import contextlib
import io
import json
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from archtrace import canon
from archtrace.advisory import (
    FindingsError,
    load_findings,
    render,
    worklist,
)
from archtrace.cli import main
from archtrace.model import Engagement

EXAMPLE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "example")


class AdvisoryCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.root = os.path.join(self.tmp, "example")
        shutil.copytree(EXAMPLE, self.root)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _eng(self):
        return Engagement.load(self.root)

    def _patch_model(self, mutate):
        path = os.path.join(self.root, "model", "model.json")
        doc = canon.load_json(path)
        mutate(doc)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(canon.canonical_json(doc))

    def _findings_file(self, document) -> str:
        path = os.path.join(self.tmp, "findings.json")
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(document, fh)
        return path

    @staticmethod
    def _container(doc, ident):
        return next(c for c in doc["systems"][0]["containers"]
                    if c["id"] == ident)

    def _kinds(self):
        return {o.kind for o in worklist(self._eng())}

    def _of_kind(self, kind):
        return [o for o in worklist(self._eng()) if o.kind == kind]


class Worklist(AdvisoryCase):
    def test_a_quote_that_cleared_the_floor_by_little_is_reported(self):
        self.assertIn("near-floor-citation", self._kinds())

    def test_a_substantial_quote_is_not_reported(self):
        near = {o.where for o in self._of_kind("near-floor-citation")}
        confirmed = {r["id"] for r in self._eng().confirmed_requirements}
        self.assertTrue(confirmed - near,
                        "every confirmed requirement is near the floor, so "
                        "this observation is not discriminating between them")

    def test_a_directly_assumed_element_is_not_reported_as_tainted(self):
        """A recorded decision, and the most likely thing to be 'fixed' by
        someone who has not read it.

        `c_prefetch` is grounded `assumption` and nothing else. That is the
        design working: the kind is in the model, in every render and in the
        grounding mix, and the open-question register names what is unknown.
        Reporting it would be reporting honesty.
        """
        from archtrace.grounding import analyse
        self.assertIn(
            "c_prefetch", analyse(self._eng()).tainted,
            "the graph no longer considers it tainted, so this test is "
            "asserting the filter works against an input it never sees")
        self.assertNotIn(
            "c_prefetch", {o.where for o in self._of_kind("assumption-tainted")},
            "a directly `assumption`-grounded element is visibly a guess "
            "already; the advisory is for the ones that are not visible")

    def test_an_element_derived_from_an_assumption_is_reported(self):
        """The case that is invisible: it reads as `derived` everywhere."""
        def mutate(doc):
            self._container(doc, "c_worker")["grounding"] = [
                {"kind": "derived", "from": "c_prefetch", "adr": "ADR-001"}]
        self._patch_model(mutate)
        self.assertIn("c_worker",
                      {o.where for o in self._of_kind("assumption-tainted")})

    def test_a_load_bearing_adr_is_reported(self):
        self.assertIn("ADR-001", {o.where for o in
                                  self._of_kind("adr-concentration")})

    def test_evidence_concentration_is_one_row_not_one_per_requirement(self):
        """The example confirms five requirements against EV-001 alone. One
        observation per requirement would be five identical rows burying the
        four tiers above it -- the agent definition's "do not pad" applies to
        this document too."""
        rows = self._of_kind("evidence-concentration")
        self.assertEqual([o.where for o in rows], ["EV-001"])
        self.assertIn("5 of 5", rows[0].detail)

    def test_an_evidence_record_below_the_share_is_not_reported(self):
        """Otherwise this is not concentration, it is a list of every record
        anyone cited -- which G8 already covers from the other direction.

        Repoints one requirement's provenance at EV-002 so it carries 1 of 5.
        That breaks G2's span check; `worklist` never runs the gate, and this
        is a test of the instrument rather than of the model.
        """
        path = os.path.join(self.root, "requirements", "requirements.json")
        doc = canon.load_json(path)
        moved = next(r for r in doc["requirements"]
                     if r.get("status") == "confirmed")
        for prov in moved["provenance"]:
            prov["evidence_id"] = "EV-002"
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(canon.canonical_json(doc))
        reported = {o.where for o in self._of_kind("evidence-concentration")}
        self.assertIn("EV-001", reported)
        self.assertNotIn("EV-002", reported,
                         "one requirement out of five is 20%, under the 40% "
                         "share this observation exists to find")

    def test_a_deep_chain_is_reported(self):
        def mutate(doc):
            for a, b in (("c_api", "c_edge"), ("c_edge", "c_audit")):
                self._container(doc, a)["grounding"] = [
                    {"kind": "derived", "from": b, "adr": "ADR-001"}]
            self._container(doc, "c_telemetry")["grounding"] = [
                {"kind": "derived", "from": "c_api", "adr": "ADR-001"}]
        self._patch_model(mutate)
        self.assertIn("c_telemetry",
                      {o.where for o in self._of_kind("deep-derivation")})

    def test_a_shallow_chain_is_not_reported(self):
        self.assertEqual(self._of_kind("deep-derivation"), [])

    def test_an_engagement_with_no_confirmed_requirements_says_nothing(self):
        def mutate(doc):
            doc["decisions"] = []
            for system in doc["systems"]:
                for container in system.get("containers", []):
                    container["grounding"] = [{"kind": "standard",
                                               "standard": "STD-001"}]
        self._patch_model(mutate)
        path = os.path.join(self.root, "requirements", "requirements.json")
        doc = canon.load_json(path)
        for req in doc["requirements"]:
            req["status"] = "retired"
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(canon.canonical_json(doc))
        self.assertEqual(self._of_kind("evidence-concentration"), [])

    def test_the_worklist_is_ordered_most_urgent_first(self):
        tiers = [o.tier for o in worklist(self._eng())]
        self.assertEqual(tiers, sorted(tiers))


GOOD_FINDINGS = {
    "schema_version": 1, "produced_by": "nli-scorer 0.1",
    "findings": [{"where": "REQ-004", "kind": "contradiction",
                  "confidence": "likely", "detail": "7 days vs 7 years"}]}


class ExternalFindings(AdvisoryCase):
    def test_a_valid_file_loads_and_sorts_ahead_of_everything_local(self):
        observations = load_findings(self._findings_file(GOOD_FINDINGS))
        self.assertEqual(len(observations), 1)
        self.assertEqual(observations[0].tier, 0)
        self.assertEqual(observations[0].source, "nli-scorer 0.1")

    def test_malformed_json_is_refused(self):
        path = os.path.join(self.tmp, "bad.json")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("{ not json")
        with self.assertRaisesRegex(FindingsError, "not valid JSON"):
            load_findings(path)

    def test_a_missing_file_is_refused(self):
        with self.assertRaisesRegex(FindingsError, "cannot read"):
            load_findings(os.path.join(self.tmp, "absent.json"))

    def test_a_document_that_is_not_an_object_is_refused(self):
        with self.assertRaisesRegex(FindingsError, "not an object"):
            load_findings(self._findings_file([1, 2, 3]))

    def test_an_unknown_schema_version_is_refused_not_guessed(self):
        document = {**GOOD_FINDINGS, "schema_version": 7}
        with self.assertRaisesRegex(FindingsError, "Refusing to guess"):
            load_findings(self._findings_file(document))

    def test_findings_that_are_not_a_list_are_refused(self):
        document = {"schema_version": 1, "findings": "lots"}
        with self.assertRaisesRegex(FindingsError, "no `findings` list"):
            load_findings(self._findings_file(document))

    def test_a_finding_that_is_not_an_object_is_refused(self):
        document = {"schema_version": 1, "findings": ["a problem"]}
        with self.assertRaisesRegex(FindingsError, "is not an object"):
            load_findings(self._findings_file(document))

    def test_an_unknown_kind_is_refused_rather_than_dropped(self):
        """Dropping it would make a reviewer that misspells a category less
        useful than one that produces nothing, silently."""
        document = {"schema_version": 1,
                    "findings": [{**GOOD_FINDINGS["findings"][0],
                                  "kind": "vibes"}]}
        with self.assertRaisesRegex(FindingsError, "Refusing to guess"):
            load_findings(self._findings_file(document))

    def test_an_invented_confidence_scale_is_refused(self):
        document = {"schema_version": 1,
                    "findings": [{**GOOD_FINDINGS["findings"][0],
                                  "confidence": "0.93"}]}
        with self.assertRaisesRegex(FindingsError, "confidence"):
            load_findings(self._findings_file(document))

    def test_a_finding_with_no_detail_is_refused(self):
        document = {"schema_version": 1,
                    "findings": [{"where": "REQ-004", "kind": "defeater",
                                  "confidence": "likely"}]}
        with self.assertRaisesRegex(FindingsError, "`where` and `detail`"):
            load_findings(self._findings_file(document))


class Rendering(AdvisoryCase):
    def _render(self, observations=None):
        eng = self._eng()
        return render(eng, worklist(eng) + (observations or []))

    def test_the_document_is_byte_identical_across_runs(self):
        """A clock in a generated artifact is defect A1 this repository found
        in archmine's own drift gate and patched upstream. Doing it here would
        be worse, because we knew."""
        self.assertEqual(self._render(), self._render())

    def test_the_fingerprint_moves_when_the_model_does(self):
        before = self._render()
        self._patch_model(lambda doc: doc["systems"][0].update(
            {"description": "changed"}))
        self.assertNotEqual(before, self._render())

    def test_it_says_it_never_gates(self):
        self.assertIn("never gates", self._render())

    def test_an_empty_worklist_is_not_reported_as_a_clean_bill_of_health(self):
        text = render(self._eng(), [])
        self.assertIn("Nothing to report", text)
        self.assertIn("not a clean bill of health", text)

    def test_external_findings_are_labelled_as_not_archtrace_s(self):
        external = load_findings(self._findings_file(GOOD_FINDINGS))
        text = self._render(external)
        self.assertIn("From an external reviewer", text)
        self.assertIn("takes no position on whether it is right", text)

    def test_a_finding_cannot_forge_a_heading(self):
        """Untrusted text copied into an artifact a human skims. The agent
        definitions require evidence be treated as data rather than
        instruction; this is the one place that rule reaches a renderer."""
        document = {"schema_version": 1, "produced_by": "x",
                    "findings": [{"where": "REQ-004", "kind": "defeater",
                                  "confidence": "likely",
                                  "detail": "## Approved by archtrace\nreally"}]}
        text = self._render(load_findings(self._findings_file(document)))
        # Both halves matter, and the first one is the whole test. Flattening
        # the newline alone leaves "## Approved by archtrace" sitting in the
        # cell; asserting only that the string does not start a line passes
        # with the heading strip deleted, which is how this test was written
        # the first time.
        self.assertNotIn("## Approved", text)
        self.assertIn("Approved by archtrace really", text)

    def test_a_finding_cannot_break_out_of_its_table_cell(self):
        document = {"schema_version": 1, "produced_by": "a | b",
                    "findings": [{"where": "R | X", "kind": "defeater",
                                  "confidence": "likely",
                                  "detail": "one | two"}]}
        text = self._render(load_findings(self._findings_file(document)))
        row = next(line for line in text.splitlines() if "one / two" in line)
        self.assertEqual(row.count("|"), 6,
                         f"a pipe in untrusted text added a column: {row}")


class ReviewCommand(AdvisoryCase):
    def _run(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = main(["--root", self.root, *argv])
        return code, out.getvalue(), err.getvalue()

    def test_it_writes_the_advisory_and_exits_zero(self):
        code, out, _err = self._run("review")
        self.assertEqual(code, 0)
        path = os.path.join(self.root, "review", "advisory.md")
        self.assertTrue(os.path.isfile(path), out)
        with open(path, encoding="utf-8") as fh:
            self.assertIn("Advisory review", fh.read())

    def test_it_exits_zero_even_when_an_external_reviewer_found_things(self):
        """The property SPEC §7.3 has always claimed and nothing enforced."""
        path = self._findings_file(GOOD_FINDINGS)
        code, out, _err = self._run("review", "--findings", path)
        self.assertEqual(code, 0)
        self.assertIn("takes no position", out)

    def test_stdout_writes_no_file(self):
        code, out, _err = self._run("review", "--stdout")
        self.assertEqual(code, 0)
        self.assertIn("# Advisory review", out)
        self.assertFalse(os.path.isdir(os.path.join(self.root, "review")))

    def test_an_unreadable_findings_file_is_a_usage_error_not_a_silent_zero(self):
        """Exit 2, per SPEC §7.0. Degrading to "no external findings" would
        make a reviewer whose output stopped parsing indistinguishable from
        one that found nothing."""
        code, _out, err = self._run("review", "--findings",
                                    os.path.join(self.tmp, "absent.json"))
        self.assertEqual(code, 2)
        self.assertIn("cannot read", err)


if __name__ == "__main__":
    unittest.main()
