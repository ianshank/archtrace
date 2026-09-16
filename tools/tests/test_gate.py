"""Seeded-defect tests.

A gate that has only ever been observed passing is not evidence of anything.
Each case copies the worked example, seeds exactly one defect, and asserts that
the intended rule fires. Standard library only; run with `python3 -m unittest`.
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

from archtrace import canon, config, gate
from archtrace.model import NFR_CATEGORIES, Engagement
from archtrace.renders import render_all

EXAMPLE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "example")


class SeededDefect(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.root = os.path.join(self.tmp, "example")
        shutil.copytree(EXAMPLE, self.root)
        # Pin the citation policy to the DEFAULTS these assertions describe.
        # Two things otherwise decide it: an `archtrace.toml` at the repository
        # root (legitimate -- a repo may configure its own gate, and then its
        # own suite fails, which is a test defect not a config one), and test
        # ordering, because `cli.main` rebinds these module constants from
        # `--root` and any test that drives the CLI leaves them rebound. A test
        # asserting "this quote is too short" must say which floor it means.
        gate.apply_config(config.Config())

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    # -- helpers ----------------------------------------------------------

    def _path(self, *parts):
        return os.path.join(self.root, *parts)

    def _patch(self, rel, mutate):
        path = self._path(*rel)
        doc = canon.load_json(path)
        mutate(doc)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(canon.canonical_json(doc))

    def _rerender(self):
        """Simulate the real workflow: edit the model, then `archtrace render`.

        A mutation that legitimately changes a render must be followed by a
        regeneration, or G6 fires correctly and masks the rule under test.
        """
        eng = Engagement.load(self.root)
        for name, data in render_all(eng).items():
            with open(self._path("render", name), "wb") as fh:
                fh.write(data)

    def _rules(self):
        eng = Engagement.load(self.root)
        findings, code = gate.run(eng)
        return {f.rule for f in findings}, code, findings

    @staticmethod
    def _find(items, ident):
        """An element of the example by id, never by position.

        `doc["requirements"][0]` is REQ-000, not REQ-001, and five tests
        written against that assumption failed on the `where` assertion rather
        than passing for the wrong reason. Ordering is not part of the
        example's contract; ids are.
        """
        match = next((i for i in items if i.get("id") == ident), None)
        if match is None:
            raise AssertionError(
                f"{ident} is not in the example any more; this test is "
                f"asserting on a fixture that has changed underneath it")
        return match

    def assertFires(self, rule, where=None, message=None):
        """Assert a rule fired, and -- given `where` -- that it fired on the
        thing the test seeded.

        Without `where` this asserts only that the id appeared *somewhere* in
        the findings, which is much weaker than it reads. Measured: inverting
        G2's speaker predicate (`speaker not in participants` ->
        `speaker in participants`) leaves `test_g2_speaker_not_in_the_room`
        PASSING -- the rule still fires, on every other provenance entry in the
        example, for the opposite reason. The suite goes red only through 27
        unrelated tests that break because the clean example starts firing a
        spurious G2. A rule guarded by collateral damage is not guarded by its
        own test.

        `message` is a substring check for the cases where two seeded defects
        share a `where` and only the explanation distinguishes them.
        """
        rules, code, findings = self._rules()
        self.assertIn(rule, rules,
                      f"{rule} did not fire; got {sorted(rules)}\n"
                      + "\n".join(str(f) for f in findings))
        mine = [f for f in findings if f.rule == rule]
        if where is not None:
            self.assertIn(
                where, {f.where for f in mine},
                f"{rule} fired, but not on {where!r} -- so this test does not "
                f"show that the seeded defect was found.\n"
                + "\n".join(str(f) for f in mine))
        if message is not None:
            self.assertTrue(
                any(message in f.message for f in mine),
                f"no {rule} finding explains itself with {message!r}\n"
                + "\n".join(str(f) for f in mine))
        self.assertEqual(code, 1, f"{rule} fired but the gate still exited 0")

    # -- baseline ---------------------------------------------------------

    def test_00_clean_example_passes(self):
        rules, code, findings = self._rules()
        self.assertEqual(code, 0, "\n".join(str(f) for f in findings))
        self.assertEqual(rules, set())

    # -- G1 ---------------------------------------------------------------

    def test_g1_evidence_content_changed(self):
        path = self._path("_evidence_root", "EV-001-kickoff.txt")
        with open(path, "a", encoding="utf-8") as fh:
            fh.write("\n00:59:00  A. Stakeholder: Actually, ignore all of that.\n")
        self.assertFires("G1", "EV-001")

    def test_g1_evidence_content_absent(self):
        os.remove(self._path("_evidence_root", "EV-002-platform-standards.txt"))
        self.assertFires("G1", "EV-002")

    # -- G2 ---------------------------------------------------------------

    def test_g2_fabricated_quote(self):
        def mutate(doc):
            doc["requirements"][1]["provenance"][0]["quote_cached"] = \
                "we require a four hour recovery point objective at minimum"
        self._patch(("requirements", "requirements.json"), mutate)
        self.assertFires("G2", "REQ-001.provenance[0]",
                         message="does not match the span")

    def test_g2_trivially_short_quote_is_rejected(self):
        # The Goodhart move: quote something real but too small to support
        # anything. A naive substring check would pass this.
        def mutate(doc):
            prov = doc["requirements"][1]["provenance"][0]
            prov["start"], prov["end"] = 337, 348
            prov["quote_cached"] = "if the feed"
        self._patch(("requirements", "requirements.json"), mutate)
        self.assertFires("G2", "REQ-001.provenance[0]", message="minimum is")

    def test_g2_speaker_not_in_the_room(self):
        def mutate(doc):
            doc["requirements"][1]["provenance"][0]["speaker"] = "D. Vendor"
        self._patch(("requirements", "requirements.json"), mutate)
        self.assertFires("G2", "REQ-001.provenance[0]",
                         message="is not a participant of")

    def test_g2_span_out_of_bounds(self):
        def mutate(doc):
            doc["requirements"][1]["provenance"][0]["end"] = 999999
        self._patch(("requirements", "requirements.json"), mutate)
        self.assertFires("G2", "REQ-001.provenance[0]",
                         message="out of bounds")

    # -- G3 ---------------------------------------------------------------

    def test_g3_requirement_grounded_by_nothing(self):
        def mutate(doc):
            for rel in doc["relationships"]:
                rel["grounding"] = [g for g in rel["grounding"]
                                    if g.get("req") != "REQ-004"]
                if not rel["grounding"]:
                    rel["grounding"] = [{"kind": "standard", "standard": "STD-001"}]
        self._patch(("model", "model.json"), mutate)
        self.assertFires("G3", "REQ-004")

    def test_g3_out_of_scope_without_a_decider(self):
        def mutate(doc):
            doc["out_of_scope"][0].pop("decided_by")
        self._patch(("model", "model.json"), mutate)
        self.assertFires("G3", "REQ-005")

    def test_g3_superseded_without_successor(self):
        def mutate(doc):
            doc["requirements"][0]["superseded_by"] = None
        self._patch(("requirements", "requirements.json"), mutate)
        self.assertFires("G3", "REQ-000")

    # -- G4 ---------------------------------------------------------------

    def test_g4_ungrounded_element(self):
        def mutate(doc):
            doc["systems"][0]["containers"][0]["grounding"] = []
        self._patch(("model", "model.json"), mutate)
        self.assertFires("G4", "c_edge")

    def test_g4_derived_without_an_adr(self):
        def mutate(doc):
            for container in doc["systems"][0]["containers"]:
                for entry in container["grounding"]:
                    if entry["kind"] == "derived":
                        entry.pop("adr")
        self._patch(("model", "model.json"), mutate)
        self.assertFires("G4", "c_worker.grounding[0]")

    def test_g4_satisfies_an_unconfirmed_requirement(self):
        def mutate(doc):
            doc["people"][0]["grounding"] = [{"kind": "satisfies", "req": "REQ-000"}]
        self._patch(("model", "model.json"), mutate)
        self.assertFires("G4", "p_dit.grounding[0]")

    def test_g4_infrastructure_does_not_need_a_requirement(self):
        """The defect the v1 design would have had: a load balancer nobody asked
        for must be expressible without inventing a requirement."""
        eng = Engagement.load(self.root)
        edge = eng.element_by_id("c_edge")
        self.assertEqual([g["kind"] for g in edge.grounding], ["standard"])
        _rules, code, _f = self._rules()
        self.assertEqual(code, 0)

    # -- G5 ---------------------------------------------------------------

    def test_g5_float_layout_coordinate(self):
        def mutate(doc):
            doc["systems"][0]["layout"]["x"] = 320.5
        self._patch(("model", "model.json"), mutate)
        self.assertFires("G5", "s_ingest")

    def test_g5_dangling_relationship_endpoint(self):
        def mutate(doc):
            doc["relationships"][0]["destination"] = "s_does_not_exist"
        self._patch(("model", "model.json"), mutate)
        self.assertFires("G5", "p_dit->s_does_not_exist")

    def test_g5_missing_uid(self):
        def mutate(doc):
            doc["people"][0].pop("uid")
        self._patch(("model", "model.json"), mutate)
        self.assertFires("G5", "p_dit")

    # -- G6 ---------------------------------------------------------------

    def test_g6_hand_edited_render(self):
        path = self._path("render", "c4-context.svg")
        with open(path, encoding="utf-8") as fh:
            svg = fh.read()
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(svg.replace("Dailies Ingest Platform", "Dailies Ingest (v2)"))
        self.assertFires("G6", "render/c4-context.svg")

    def test_g6_stale_render_after_model_change(self):
        def mutate(doc):
            doc["systems"][0]["name"] = "Dailies Ingest Platform (renamed)"
        self._patch(("model", "model.json"), mutate)
        self.assertFires("G6", "render/c4-context.svg")

    def test_a_rule_that_crashes_becomes_a_finding_not_a_traceback(self):
        """The invariant gate.py claims for its rules, now actually enforced.

        Several rules index with `[]` where a document may legitimately be
        malformed. Removing one `req` key from out_of_scope produced a raw
        KeyError out of `archtrace check` -- which loses every OTHER rule's
        findings along with it, so one missing field hid the whole report.
        G6 has wrapped its renderer call this way since it was written.
        """
        def mutate(doc):
            doc["out_of_scope"][0].pop("req")
        self._patch(("model", "model.json"), mutate)
        _rules, code, findings = self._rules()
        self.assertEqual(code, 1)
        crashed = [f for f in findings if f.where == "<rule crashed>"]
        self.assertTrue(crashed, "expected the crash to surface as a finding")
        self.assertIn("KeyError", crashed[0].message)
        self.assertEqual(crashed[0].rule, "G3", "the finding must name the rule")

    def test_one_crashing_rule_does_not_suppress_the_others(self):
        """The whole point: a traceback costs the entire report."""
        def mutate(doc):
            doc["out_of_scope"][0].pop("req")
            doc["systems"][0]["containers"][0]["grounding"] = []
        self._patch(("model", "model.json"), mutate)
        _rules, _code, findings = self._rules()
        rules = {f.rule for f in findings}
        self.assertIn("G3", rules, "the crashing rule reports")
        self.assertIn("G4", rules, "and an unrelated rule still ran")

    def test_g6_short_circuit_keeps_canonical_tolerance(self):
        """Raw equality is only a fast path: a == b implies canon(a) == canon(b).

        Bytes that differ but are canonically equal must still pass, or the
        optimisation has changed the rule rather than speeding it up.
        """
        path = self._path("render", "model.drawio")
        with open(path, encoding="utf-8") as fh:
            xml = fh.read()
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(xml.replace("\n", "\n  "))
        _rules, code, findings = self._rules()
        self.assertEqual(code, 0,
                         "reformatted but canonically equal XML must pass\n"
                         + "\n".join(str(f) for f in findings))

    def _g6_messages(self):
        _rules, _code, findings = self._rules()
        return [f.message for f in findings if f.rule == "G6"]

    def test_g6_names_toolchain_drift_as_toolchain_drift(self):
        """The manifest has always recorded which renderer wrote these bytes.

        G6 never read it, so a toolchain upgrade and a hand edit produced the
        same message and the operator had to guess. That is not hypothetical:
        engagements/archtrace-self sat in the tree with renders from renderer
        1.1.0 after the renderer moved to 1.2.0.
        """
        from archtrace.model import RENDER_MANIFEST
        path = self._path("render", RENDER_MANIFEST)
        manifest = canon.load_json(path)
        manifest["renderer_version"] = "0.0.1-ancient"
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
        messages = self._g6_messages()
        self.assertTrue(messages, "a renderer version change must still block")
        self.assertTrue(any("toolchain drift" in m for m in messages), messages)
        self.assertTrue(any("0.0.1-ancient" in m for m in messages),
                        "the message should name the renderer that wrote it")
        self.assertFalse(any("edit the model, not the artifact" in m
                             for m in messages),
                         "toolchain drift must not be reported as a hand edit")

    def test_g6_names_a_hand_edit_as_a_hand_edit(self):
        """The other half: same renderer, different bytes, so it WAS an edit."""
        path = self._path("render", "traceability.md")
        with open(path, encoding="utf-8") as fh:
            body = fh.read()
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(body.replace("Dailies", "Substituted"))
        messages = self._g6_messages()
        self.assertTrue(any("edit the model, not the artifact" in m
                            for m in messages), messages)
        self.assertFalse(any("toolchain drift" in m for m in messages),
                         "the renderer did not move, so this is not drift")

    def test_g6_survives_a_manifest_that_is_valid_json_but_not_an_object(self):
        """`null`, `[]` and `"text"` are all valid JSON and none has .get.

        The helper caught only OSError/ValueError, so these raised an
        AttributeError out of a function whose whole contract is that it
        degrades to None and lets the byte comparison speak.
        """
        from archtrace.model import RENDER_MANIFEST
        for payload in ("null", "[]", '"a string"', "42"):
            with self.subTest(payload=payload):
                with open(self._path("render", RENDER_MANIFEST), "w",
                          encoding="utf-8") as fh:
                    fh.write(payload)
                # Must be a finding, not a traceback.
                self.assertFires("G6", "render/.manifest.json")

    def test_g6_does_not_claim_a_renderer_it_cannot_know(self):
        """With no recorded version, a hand edit and drift are indistinguishable.

        Saying "the same one running now" there points the operator at the
        model when the renderer may well have moved.
        """
        from archtrace.model import RENDER_MANIFEST
        path = self._path("render", RENDER_MANIFEST)
        manifest = canon.load_json(path)
        manifest.pop("renderer_version", None)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
        messages = self._g6_messages()
        self.assertTrue(messages)
        self.assertTrue(any("records no renderer version" in m
                            for m in messages), messages)
        self.assertFalse(any("the same one running now" in m
                             for m in messages),
                         "it cannot know that, so it must not say it")

    def test_g6_still_blocks_when_the_manifest_cannot_be_read(self):
        """The diagnosis is a diagnosis, never a gate of its own: an absent or
        corrupt manifest must not make a stale render pass."""
        from archtrace.model import RENDER_MANIFEST
        with open(self._path("render", RENDER_MANIFEST), "w",
                  encoding="utf-8") as fh:
            fh.write("{not json")
        self.assertFires("G6", "render/.manifest.json")

    def test_g6_tolerates_insignificant_xml_whitespace(self):
        """Canonical comparison, not byte comparison: a reformatted but
        equivalent XML render must not fail the build."""
        path = self._path("render", "model.drawio")
        with open(path, encoding="utf-8") as fh:
            xml = fh.read()
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(xml.replace("\n", "\n  "))
        _rules, code, findings = self._rules()
        self.assertEqual(code, 0, "\n".join(str(f) for f in findings))

    # -- G7 / G9 / G10 ----------------------------------------------------

    def test_g7_adr_driver_is_not_a_confirmed_requirement(self):
        def mutate(doc):
            doc["decisions"][0]["drivers"] = ["REQ-000"]
        self._patch(("model", "model.json"), mutate)
        self.assertFires("G7", "ADR-001")

    def test_g9_unresolved_conflict_between_confirmed_requirements(self):
        def mutate(doc):
            by_id = {r["id"]: r for r in doc["requirements"]}
            by_id["REQ-002"]["conflicts_with"] = ["REQ-003"]
            by_id["REQ-003"]["conflicts_with"] = ["REQ-002"]
        self._patch(("requirements", "requirements.json"), mutate)
        self.assertFires("G9", "REQ-002~REQ-003")

    def test_g10_unknown_schema_version(self):
        def mutate(doc):
            doc["schema_version"] = 99
        self._patch(("model", "model.json"), mutate)
        self.assertFires("G10", "model/model.json")

    # -- G11 authority ----------------------------------------------------

    def test_g11_requirement_resting_only_on_observed_implementation(self):
        """The failure this catches: an architect reads a repo, writes down what
        the code does, and it becomes a stakeholder constraint. The citation is
        perfectly real, so every other gate certifies it."""
        def mutate(doc):
            doc["evidence"][0]["authority"] = "observed-implementation"
        self._patch(("evidence", "index.json"), mutate)
        self.assertFires("G11", "REQ-001", message="observed-implementation")

    def test_g11_third_party_material_is_not_a_requirement(self):
        def mutate(doc):
            doc["evidence"][0]["authority"] = "third-party"
        self._patch(("evidence", "index.json"), mutate)
        self.assertFires("G11", "REQ-001", message="third-party")

    def test_g11_unknown_authority(self):
        def mutate(doc):
            doc["evidence"][0]["authority"] = "seems-right"
        self._patch(("evidence", "index.json"), mutate)
        self.assertFires("G11", "EV-001", message="unknown authority")

    def test_g11_authoritative_document_is_sufficient(self):
        def mutate(doc):
            for record in doc["evidence"]:
                record["authority"] = "authoritative-document"
                record.setdefault("document_owner", "C. Platform")
                record.setdefault("effective_date", "2026-04-01")
        self._patch(("evidence", "index.json"), mutate)
        self._rerender()
        _rules, code, findings = self._rules()
        self.assertEqual(code, 0, "\n".join(str(f) for f in findings))

    # -- G12 NFR coverage -------------------------------------------------

    def test_g12_undeclared_category_warns_but_does_not_block(self):
        def mutate(doc):
            doc["nfr_coverage"] = [e for e in doc["nfr_coverage"]
                                   if e["category"] != "privacy"]
        self._patch(("model", "model.json"), mutate)
        self._rerender()
        rules, code, _f = self._rules()
        self.assertIn("G12", rules)
        self.assertEqual(code, 0, "a nine-category hard block gets the gate "
                                  "switched off in week two")

    def test_g12n_not_applicable_without_a_decider_blocks(self):
        def mutate(doc):
            for entry in doc["nfr_coverage"]:
                if entry["status"] == "not_applicable":
                    entry.pop("decided_by")
        self._patch(("model", "model.json"), mutate)
        self.assertFires("G12n", "accessibility", message="decided_by")

    def test_g12n_open_must_cite_a_real_open_question(self):
        """`open` is a tracked gap. An untracked gap is indistinguishable from
        an overlooked one, which is the whole point of the distinction."""
        def mutate(doc):
            for entry in doc["nfr_coverage"]:
                if entry["status"] == "open":
                    entry["open_question"] = "OQ-999"
                    break
        self._patch(("model", "model.json"), mutate)
        self.assertFires("G12n", "privacy",
                         message="an open question that exists")

    def test_g12n_open_is_not_a_synonym_for_not_applicable(self):
        """Three statuses, not two: collapsing `open` into `not_applicable`
        turns an unknown into a false assurance."""
        def mutate(doc):
            for entry in doc["nfr_coverage"]:
                if entry["status"] == "open":
                    entry["status"] = "not_applicable"
                    entry.pop("open_question", None)
        self._patch(("model", "model.json"), mutate)
        self.assertFires("G12n", message="'not_applicable' is an assertion")

    # -- branches that had never fired ------------------------------------
    #
    # A mutation audit found 29 blocking branches whose `Finding` had never
    # been produced by any test run: each could be replaced with `if False:`
    # and the suite stayed green. Three were sampled and confirmed before these
    # were written. They are cheap tests, and their absence is the difference
    # between a rule that is enforced and a rule that is merely present.
    #
    # These could not usefully have been written before `assertFires` learned
    # `where` -- several of these rules also fire elsewhere in the example when
    # provoked, so "G4 appeared somewhere" would have proved nothing.

    def test_g1_duplicate_evidence_id(self):
        """Two records under one id: `evidence_by_id` returns the first, so a
        citation resolves to a record whose hash belongs to the other."""
        def mutate(doc):
            doc["evidence"].append(dict(doc["evidence"][0]))
        self._patch(("evidence", "index.json"), mutate)
        self.assertFires("G1", "EV-001", message="duplicate evidence id")

    def test_g1_evidence_missing_its_retention_date(self):
        """SPEC §0.4 is the whole reason the manifest exists; a record with no
        retention date records nothing about retention."""
        def mutate(doc):
            doc["evidence"][0].pop("retention_until")
        self._patch(("evidence", "index.json"), mutate)
        self.assertFires("G1", "EV-001", message="'retention_until'")

    def test_g3_unknown_requirement_status(self):
        def mutate(doc):
            self._find(doc["requirements"], "REQ-001")["status"] = "probably-fine"
        self._patch(("requirements", "requirements.json"), mutate)
        self.assertFires("G3", "REQ-001", message="unknown status")

    def test_g3_unknown_requirement_type(self):
        def mutate(doc):
            self._find(doc["requirements"], "REQ-001")["type"] = "vibes"
        self._patch(("requirements", "requirements.json"), mutate)
        self.assertFires("G3", "REQ-001", message="unknown type")

    def test_g3_unknown_requirement_priority(self):
        def mutate(doc):
            self._find(doc["requirements"], "REQ-001")["priority"] = "urgent-ish"
        self._patch(("requirements", "requirements.json"), mutate)
        self.assertFires("G3", "REQ-001", message="unknown priority")

    def test_g3_superseded_by_a_requirement_that_does_not_exist(self):
        """Distinct from `superseded` with no successor at all: this one names
        a successor, so it reads as handled right up until someone follows it."""
        def mutate(doc):
            req = self._find(doc["requirements"], "REQ-001")
            req["status"] = "superseded"
            req["superseded_by"] = "REQ-999"
        self._patch(("requirements", "requirements.json"), mutate)
        self.assertFires("G3", "REQ-001", message="does not exist")

    def test_g4_unknown_grounding_kind(self):
        """The kind is what decides which domain the reference is checked
        against, so an unrecognised one is not a typo -- it is an element that
        skips grounding entirely."""
        def mutate(doc):
            doc["people"][0]["grounding"][0]["kind"] = "seems-reasonable"
        self._patch(("model", "model.json"), mutate)
        self.assertFires("G4", "p_dit.grounding[0]",
                         message="unknown grounding kind")

    def test_g4_derived_from_an_element_that_does_not_exist(self):
        def mutate(doc):
            containers = doc["systems"][0]["containers"]
            self._find(containers, "c_worker")["grounding"][0][
                "from"] = "c_does_not_exist"
        self._patch(("model", "model.json"), mutate)
        self.assertFires("G4", "c_worker.grounding[0]",
                         message="derived from unknown element")

    def test_g4_citing_an_adr_that_does_not_exist(self):
        def mutate(doc):
            containers = doc["systems"][0]["containers"]
            self._find(containers, "c_worker")["grounding"][0][
                "adr"] = "ADR-999"
        self._patch(("model", "model.json"), mutate)
        self.assertFires("G4", "c_worker.grounding[0]", message="unknown ADR")

    def test_g4_citing_a_standard_that_does_not_exist(self):
        def mutate(doc):
            containers = doc["systems"][0]["containers"]
            self._find(containers, "c_edge")["grounding"][0][
                "standard"] = "STD-999"
        self._patch(("model", "model.json"), mutate)
        self.assertFires("G4", "c_edge.grounding[0]",
                         message="unknown standard")

    def test_g4_citing_an_open_question_that_does_not_exist(self):
        """An assumption whose open question is fictional is an assumption
        nobody is tracking, which is the state `assumption` exists to prevent."""
        def mutate(doc):
            containers = doc["systems"][0]["containers"]
            self._find(containers, "c_prefetch")["grounding"][0][
                "open_question"] = "OQ-999"
        self._patch(("model", "model.json"), mutate)
        self.assertFires("G4", "c_prefetch.grounding[0]",
                         message="unknown open question")

    def test_g4_citing_an_evidence_record_that_does_not_exist(self):
        def mutate(doc):
            self._find(doc["systems"], "s_mam")["grounding"][0][
                "evidence_id"] = "EV-999"
        self._patch(("model", "model.json"), mutate)
        self.assertFires("G4", "s_mam.grounding[0]",
                         message="unknown evidence record")

    def test_g5_duplicate_element_id(self):
        """Two elements under one id: every reference to it resolves to
        whichever the lookup reached first."""
        def mutate(doc):
            doc["people"].append(dict(doc["people"][0]))
        self._patch(("model", "model.json"), mutate)
        self.assertFires("G5", "p_dit", message="duplicate element id")

    def test_g5_duplicate_element_uid(self):
        """The uid is the Jira linkage. Two elements sharing one means two
        model elements silently become one ticket."""
        def mutate(doc):
            containers = doc["systems"][0]["containers"]
            self._find(containers, "c_api")["uid"] = \
                self._find(containers, "c_edge")["uid"]
        self._patch(("model", "model.json"), mutate)
        self.assertFires("G5", "c_api", message="duplicate element uid")

    def test_g6_a_render_that_is_missing_from_disk(self):
        """Distinct from a stale one: nothing to compare is not a pass."""
        os.remove(self._path("render", "c4-context.svg"))
        self.assertFires("G6", "render/c4-context.svg",
                         message="render is missing")

    def test_g6_a_stray_file_in_render(self):
        """`render/` is the renderer's output and nothing else. A file the
        renderer does not produce is either an edit or a leftover, and
        `release` would otherwise be asked to sign it."""
        with open(self._path("render", "appendix.md"), "w",
                  encoding="utf-8") as fh:
            fh.write("something the renderer never wrote\n")
        self.assertFires("G6", "render/appendix.md",
                         message="the renderer does not produce")

    def test_g7_an_adr_with_no_drivers(self):
        def mutate(doc):
            doc["decisions"][0].pop("drivers")
        self._patch(("model", "model.json"), mutate)
        self.assertFires("G7", "ADR-001", message="no drivers")

    def test_g9_conflicts_with_a_requirement_that_does_not_exist(self):
        """Distinct from an unresolved conflict: this one cannot be resolved,
        because the counterpart is not there to resolve it against."""
        def mutate(doc):
            self._find(doc["requirements"], "REQ-001")["conflicts_with"] = ["REQ-999"]
        self._patch(("requirements", "requirements.json"), mutate)
        self.assertFires("G9", "REQ-001",
                         message="conflicts_with unknown requirement")

    def test_g12n_unknown_nfr_category(self):
        def mutate(doc):
            doc["nfr_coverage"][0]["category"] = "vibes"
        self._patch(("model", "model.json"), mutate)
        self.assertFires("G12n", "vibes", message="unknown NFR category")

    def test_g12n_unknown_nfr_status(self):
        def mutate(doc):
            doc["nfr_coverage"][0]["status"] = "probably-ok"
        self._patch(("model", "model.json"), mutate)
        self.assertFires("G12n", "security", message="status must be one of")

    def test_g4_checks_relationship_grounding_not_only_elements(self):
        """Both G4 and G13 end with `for rel in eng.relationships`, and both
        loops could be replaced with `for rel in []` while all 277 tests passed.
        Relationships carry grounding exactly as elements do -- the example has
        ten of them, every one grounded -- so an unchecked loop means half the
        model's claims were never gated.
        """
        def mutate(doc):
            doc["relationships"][0]["grounding"][0]["kind"] = "seems-reasonable"
        self._patch(("model", "model.json"), mutate)
        self._rerender()
        self.assertFires("G4", "p_dit->s_ingest.grounding[0]",
                         message="unknown grounding kind")

    def test_g4_relationship_satisfying_an_unconfirmed_requirement(self):
        """The same loop, reached through the reference check rather than the
        kind check, so a partial restoration of it does not pass."""
        def mutate(doc):
            doc["relationships"][0]["grounding"][0]["req"] = "REQ-999"
        self._patch(("model", "model.json"), mutate)
        self._rerender()
        self.assertFires("G4", "p_dit->s_ingest.grounding[0]",
                         message="not a confirmed requirement")

    def test_g2_a_generic_conversational_phrase_is_not_a_quote(self):
        """The stoplist branch, which had never fired.

        `GENERIC_PHRASES` is an exact-match set, not a substring scan, so the
        quote must BE one of its phrases. Writing this turned up that **every
        phrase in the stoplist is below both default floors** (the longest, "at
        the end of the day", is 6 words / 21 chars against 8 / 40), and the
        floor check does not `continue`. So at default configuration the
        stoplist can never be the only reason a quote is refused -- it is
        strictly redundant, and only becomes load-bearing for an organisation
        that lowers `min_quote_words` and `min_quote_chars` in `archtrace.toml`.

        The floors are lowered here for exactly that reason: testing the branch
        at defaults would assert nothing the floor check does not already cover.
        Recorded in NEXT-STEPS rather than changed, because whether the stoplist
        should carry phrases long enough to clear the floors is a policy
        question, not a defect.
        """
        from archtrace import mining
        phrase = "at the end of the day"
        path = self._path("_evidence_root", "EV-001-kickoff.txt")
        with open(path, encoding="utf-8") as fh:
            text = fh.read()
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(f"{text}\n00:59:00  A. Stakeholder: {phrase}\n")
        normalised = canon.normalize(open(path, encoding="utf-8").read())

        def rehash(doc):
            self._find(doc["evidence"], "EV-001")["sha256_normalized"] = \
                mining.sha256_bytes(normalised.encode("utf-8"))
        self._patch(("evidence", "index.json"), rehash)

        start = normalised.rindex(phrase)

        def seed(doc):
            prov = self._find(doc["requirements"], "REQ-001")["provenance"][0]
            prov["start"], prov["end"] = start, start + len(phrase)
            prov["quote_cached"] = phrase
        self._patch(("requirements", "requirements.json"), seed)
        self._rerender()

        original = (gate.MIN_QUOTE_WORDS, gate.MIN_QUOTE_CHARS)
        gate.MIN_QUOTE_WORDS, gate.MIN_QUOTE_CHARS = 1, 1
        self.addCleanup(setattr, gate, "MIN_QUOTE_WORDS", original[0])
        self.addCleanup(setattr, gate, "MIN_QUOTE_CHARS", original[1])
        self.assertFires("G2", "REQ-001.provenance[0]",
                         message="generic conversational phrase")

    def test_every_stoplist_phrase_is_shorter_than_the_floors(self):
        """Not a defect, but it must not change without somebody noticing.

        While the floors sit above every stoplist phrase, the stoplist adds
        nothing at default configuration -- the floor refuses those quotes
        first, with a different message. If a longer phrase is ever added, or
        the floors are lowered in the shipped defaults, this fails and the
        person making that change learns that the stoplist has just become
        load-bearing.
        """
        clears = [p for p in gate.GENERIC_PHRASES
                  if len(p.split()) >= gate.MIN_QUOTE_WORDS
                  and len(p) >= gate.MIN_QUOTE_CHARS]
        self.assertEqual(
            clears, [],
            "these stoplist phrases now clear the quote floors, so the "
            "stoplist has become the only thing refusing them; that is a "
            "policy change worth making deliberately")

    def test_g5e_external_system_with_containers_warns_without_blocking(self):
        """G5e's only finding, and it had never been produced. It is a WARN, so
        `assertFires` does not apply -- that helper asserts exit 1, and the
        whole point of this rule is that it does not block."""
        def mutate(doc):
            self._find(doc["systems"], "s_mam")["containers"] = [{
                "id": "c_mam_api", "uid": "e_ffffffffffff", "name": "MAM API",
                "description": "Theirs, not ours.",
                "layout": {"x": 0, "y": 0},
                "grounding": [{"kind": "existing", "evidence_id": "EV-001"}],
            }]
        self._patch(("model", "model.json"), mutate)
        self._rerender()
        findings, code = gate.run(Engagement.load(self.root))
        warned = [f for f in findings if f.rule == "G5e"]
        self.assertEqual([f.where for f in warned], ["s_mam"],
                         "\n".join(str(f) for f in findings))
        self.assertEqual(warned[0].severity, gate.WARN)
        self.assertEqual(code, 0, "G5e must not block; it is a second look")

    # -- G8 warns, does not block -----------------------------------------

    def test_g8_orphan_evidence_warns_only(self):
        def mutate(doc):
            for standard in doc["standards"]:
                standard.pop("evidence_id", None)
        self._patch(("model", "model.json"), mutate)
        self._rerender()
        rules, code, _f = self._rules()
        self.assertIn("G8", rules)
        self.assertEqual(code, 0, "an orphan-evidence warning must not block")

    def test_strict_promotes_warnings(self):
        def mutate(doc):
            for standard in doc["standards"]:
                standard.pop("evidence_id", None)
        self._patch(("model", "model.json"), mutate)
        self._rerender()
        _findings, code = gate.run(Engagement.load(self.root), strict=True)
        self.assertEqual(code, 1)


class ColdStart(unittest.TestCase):
    """A scaffolded engagement must reach the gate without hand-authored JSON."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _run(self, *argv):
        from archtrace.cli import main
        return main(["--root", self.tmp, *argv])

    def test_init_produces_an_engagement_that_passes(self):
        self.assertEqual(self._run("init", "Cold Start", "--client", "Acme"), 0)
        findings, code = gate.run(Engagement.load(self.tmp))
        self.assertEqual(code, 0, "\n".join(str(f) for f in findings))

    def test_init_warns_about_every_undeclared_nfr_category(self):
        self._run("init", "Cold Start")
        findings, _code = gate.run(Engagement.load(self.tmp))
        self.assertEqual({f.where for f in findings if f.rule == "G12"},
                         set(NFR_CATEGORIES))

    def test_init_refuses_to_overwrite(self):
        self._run("init", "Cold Start")
        self.assertNotEqual(self._run("init", "Something Else"), 0)

    def test_promote_dry_run_writes_nothing(self):
        self._run("init", "Cold Start")
        self._seed_proposal()
        self.assertEqual(self._run("promote", "REQ-001"), 0)
        confirmed = canon.load_json(
            os.path.join(self.tmp, "requirements", "requirements.json"))
        self.assertEqual(confirmed["requirements"], [],
                         "a dry run must not confirm anything")

    def test_promote_moves_the_record_and_stamps_a_uid(self):
        self._run("init", "Cold Start")
        self._seed_proposal()
        self.assertEqual(self._run("promote", "REQ-001", "--yes"), 0)
        confirmed = canon.load_json(
            os.path.join(self.tmp, "requirements", "requirements.json"))
        proposed = canon.load_json(
            os.path.join(self.tmp, "requirements", "proposed.json"))
        self.assertEqual(len(confirmed["requirements"]), 1)
        self.assertEqual(proposed["requirements"], [])
        record = confirmed["requirements"][0]
        self.assertEqual(record["status"], "confirmed")
        self.assertTrue(record["uid"])

    def test_promote_of_an_unmodelled_requirement_then_blocks(self):
        """Confirming a requirement you have not modelled is exactly the state
        the coverage gate exists to catch."""
        self._run("init", "Cold Start")
        self._seed_proposal()
        self._run("promote", "REQ-001", "--yes")
        self._run("render")
        findings, code = gate.run(Engagement.load(self.tmp))
        self.assertEqual(code, 1)
        self.assertIn("G3", {f.rule for f in findings})

    def _seed_proposal(self):
        text = ("00:08:14  M. Sponsor: the number that matters is that finance "
                "can close the month without hand-reconciling three systems.")
        path = os.path.join(self.tmp, "_evidence_root", "kickoff.txt")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)
        self._run("evidence", "add", path, "--id", "EV-001",
                  "--source", "teams-transcript",
                  "--authority", "stakeholder-confirmed",
                  "--source-uri", "https://example.invalid/x",
                  "--date", "2026-09-12",
                  "--participants", "M. Sponsor", "I. Cruickshank",
                  "--classification", "internal", "--retention-until", "2027-09-12")
        normalised = canon.normalize(text)
        needle = "finance can close the month without hand-reconciling three systems"
        start = normalised.find(needle)
        doc = {"schema_version": 1, "requirements": [{
            "id": "REQ-001", "type": "functional", "priority": "must",
            "status": "proposed", "conflicts_with": [],
            "statement": "Month-end close completes without manual reconciliation.",
            "provenance": [{"evidence_id": "EV-001", "speaker": "M. Sponsor",
                            "start": start, "end": start + len(needle),
                            "quote_cached": needle}]}]}
        with open(os.path.join(self.tmp, "requirements", "proposed.json"),
                  "w", encoding="utf-8") as fh:
            fh.write(canon.canonical_json(doc))


class FullLifecycle(unittest.TestCase):
    """One engagement, `init` to MATCH, driven only through the CLI.

    Everything else in this file starts from the worked example, which is a
    fixture somebody already got right. `ColdStart` scaffolds a real one but
    stops at a *blocked* gate -- no test anywhere took a scaffolded engagement
    all the way to a green check and a verified release, so the path an adopter
    actually walks was never walked.

    It also uses `quote`. Every other test that needs a byte span computes it
    with `canon.normalize` plus `str.find`, which is the mistake `quote` exists
    to remove -- so the one command written to stop a class of error was never
    the input to anything. Here its stdout is parsed and spliced into
    `proposed.json` exactly as an agent or an analyst would.
    """

    APPROVER = ("--approved-by", "I. Cruickshank",
                "--role", "solution-architect")
    TRANSCRIPT = (
        "00:08:14  M. Sponsor: the number that matters is that finance can "
        "close the month without hand-reconciling three separate systems.\n"
        "00:09:02  M. Sponsor: and we cannot lose an event when the upstream "
        "feed drops for half a day, that is the part that hurts us.\n"
        "00:14:31  M. Sponsor: to say it once more, finance can close the "
        "month without hand-reconciling three separate systems.\n")
    # Deliberately said TWICE, at 08:14 and 14:31. `quote` promises the FIRST
    # occurrence and warns about the rest; with a single occurrence that promise
    # is unfalsifiable, and `text.find` could be `text.rfind` forever.
    FRAGMENT = "finance can close the month without hand-reconciling three separate systems"

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        gate.apply_config(config.Config())

    def _run(self, *argv):
        """Drive `main` and capture stdout, because stdout is the contract:
        `quote` emits JSON an agent pastes into a file."""
        from archtrace.cli import main
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = main(["--root", self.tmp, *argv])
        return code, out.getvalue(), err.getvalue()

    def _path(self, *parts):
        return os.path.join(self.tmp, *parts)

    def _model(self):
        """A two-element model satisfying REQ-001, with every NFR category
        declared so the run reaches a clean gate rather than a warning one."""
        return {
            "schema_version": 1,
            "workspace": {"name": "Lifecycle", "client": "Acme"},
            "people": [{
                "id": "p_finance", "uid": "e_a00000000001",
                "name": "Finance", "description": "Closes the month.",
                "layout": {"x": 0, "y": 0},
                "grounding": [{"kind": "satisfies", "req": "REQ-001"}],
            }],
            "systems": [{
                "id": "s_close", "uid": "e_a00000000002",
                "name": "Close Platform", "description": "Reconciles.",
                "external": False, "layout": {"x": 320, "y": 0},
                # Two grounding kinds, not one. `existing` also cites EV-002,
                # which otherwise sits in the manifest uncited and G8 warns --
                # and a warn verdict prints different wording, so the clean
                # claim below would be asserting the wrong sentence.
                "grounding": [
                    {"kind": "satisfies", "req": "REQ-001"},
                    {"kind": "existing", "evidence_id": "EV-002"},
                ],
                "containers": [],
            }],
            "relationships": [{
                "source": "p_finance", "destination": "s_close",
                "description": "closes the month in",
                "technology": "web",
                "grounding": [{"kind": "satisfies", "req": "REQ-001"}],
            }],
            "decisions": [], "standards": [], "out_of_scope": [],
            "open_questions": [],
            "nfr_coverage": [
                {"category": category, "status": "not_applicable",
                 "decided_by": "I. Cruickshank", "date": "2026-09-16",
                 "rationale": "Out of scope for this worked lifecycle."}
                for category in NFR_CATEGORIES
            ],
        }

    def test_init_to_match_without_touching_a_fixture(self):
        code, _out, err = self._run("init", "Lifecycle", "--client", "Acme")
        self.assertEqual(code, 0, err)

        # --- evidence intake -------------------------------------------
        source = self._path("_evidence_root", "kickoff.txt")
        with open(source, "w", encoding="utf-8") as fh:
            fh.write(self.TRANSCRIPT)
        code, _out, err = self._run(
            "evidence", "add", source, "--id", "EV-001",
            "--source", "teams-transcript",
            "--authority", "stakeholder-confirmed",
            "--source-uri", "https://example.invalid/kickoff",
            "--date", "2026-09-16",
            "--participants", "M. Sponsor", "I. Cruickshank",
            "--classification", "internal", "--retention-until", "2029-01-01")
        self.assertEqual(code, 0, err)

        # A second record with NO --id, so the auto-numbering path runs. With
        # one hand-numbered record it never does, and the id could be derived
        # any way at all.
        second = self._path("_evidence_root", "standards.txt")
        with open(second, "w", encoding="utf-8") as fh:
            fh.write("Retention for finance records is seven years.\n")
        code, _out, err = self._run(
            "evidence", "add", second,
            "--source", "document", "--authority", "authoritative-document",
            "--source-uri", "https://example.invalid/standards",
            "--date", "2026-09-16", "--participants", "I. Cruickshank",
            "--classification", "internal", "--retention-until", "2029-01-01",
            # G11 refuses an authoritative document with no owner and no
            # effective date -- "the policy says so" is not a citation. Supplied
            # here because the happy path is what this test is for; the refusal
            # has its own test.
            "--document-owner", "Group Finance",
            "--effective-date", "2026-01-01")
        self.assertEqual(code, 0, err)
        index = canon.load_json(self._path("evidence", "index.json"))
        self.assertEqual([r["id"] for r in index["evidence"]],
                         ["EV-001", "EV-002"],
                         "the second record must be EV-002")

        # --- quote: its stdout is the input, not a hand-computed span ----
        code, out, err = self._run("quote", "EV-001", self.FRAGMENT,
                                   "--speaker", "M. Sponsor")
        self.assertEqual(code, 0, err)
        quoted = json.loads(out)["provenance"][0]
        self.assertEqual(quoted["speaker"], "M. Sponsor")
        self.assertGreater(quoted["end"], quoted["start"])
        self.assertIn("occurs more than once", err,
                      "a fragment said twice must be flagged, not silently "
                      "resolved to one of them")
        normalised = canon.normalize(self.TRANSCRIPT)
        self.assertEqual(
            quoted["start"], normalised.find(canon.normalize(self.FRAGMENT)),
            "quote promises the FIRST occurrence; this is the assertion that "
            "makes `find` distinguishable from `rfind`")
        self.assertEqual(out, canon.canonical_json({"provenance": [quoted]})
                         + "\n", "stdout must stay machine-readable JSON")

        proposed = {"schema_version": 1, "requirements": [{
            "id": "REQ-001", "type": "functional", "priority": "must",
            "status": "proposed", "conflicts_with": [],
            "statement": "Month-end close completes without manual "
                         "reconciliation.",
            "provenance": [quoted],
        }]}
        with open(self._path("requirements", "proposed.json"), "w",
                  encoding="utf-8") as fh:
            fh.write(canon.canonical_json(proposed))

        # --- the human gate ---------------------------------------------
        self.assertEqual(self._run("promote", "REQ-001")[0], 0)
        self.assertEqual(
            canon.load_json(self._path("requirements",
                                       "requirements.json"))["requirements"],
            [], "the dry run must confirm nothing")
        self.assertEqual(self._run("promote", "REQ-001", "--yes")[0], 0)

        # --- model, format, render --------------------------------------
        with open(self._path("model", "model.json"), "w",
                  encoding="utf-8") as fh:
            fh.write(canon.canonical_json(self._model()))
        self.assertEqual(self._run("fmt")[0], 0)
        with open(self._path("model", "model.json"), "rb") as fh:
            before = fh.read()
        self.assertEqual(self._run("fmt")[0], 0)
        with open(self._path("model", "model.json"), "rb") as fh:
            self.assertEqual(fh.read(), before,
                             "fmt must reach a fixed point")
        code, out, err = self._run("render")
        self.assertEqual(code, 0, err)

        # --- the gate, green on an engagement nobody pre-built ----------
        code, out, err = self._run("check")
        self.assertEqual(code, 0, out + err)
        self.assertIn("grounded and internally consistent", out)

        # --- approval and verification ----------------------------------
        code, out, err = self._run("release", *self.APPROVER)
        self.assertEqual(code, 0, err)
        manifest = canon.load_json(self._path("release.json"))
        self.assertEqual(manifest["confirmed_requirements"], ["REQ-001"])
        self.assertEqual(manifest["approved_by"], "I. Cruickshank")
        self.assertIn("traceability.md", manifest["outputs"])

        code, out, _err = self._run("release", "--verify")
        self.assertEqual(code, 0, out)
        self.assertIn("MATCH", out)

        # --- and it can still refuse ------------------------------------
        victim = self._path("render", "traceability.md")
        with open(victim, "ab") as fh:
            fh.write(b"\n<!-- edited after approval -->\n")
        code, out, _err = self._run("release", "--verify")
        self.assertNotEqual(code, 0, out)
        self.assertIn("DRIFT", out)
        self.assertIn("traceability.md", out)
        self.assertNotEqual(self._run("check")[0], 0,
                            "G6 must also refuse the edited render")


class Release(unittest.TestCase):
    """An approval must bind to a state, and must refuse a failing one."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.root = os.path.join(self.tmp, "example")
        shutil.copytree(EXAMPLE, self.root)
        # Pin the citation policy to the DEFAULTS these assertions describe.
        # Two things otherwise decide it: an `archtrace.toml` at the repository
        # root (legitimate -- a repo may configure its own gate, and then its
        # own suite fails, which is a test defect not a config one), and test
        # ordering, because `cli.main` rebinds these module constants from
        # `--root` and any test that drives the CLI leaves them rebound. A test
        # asserting "this quote is too short" must say which floor it means.
        gate.apply_config(config.Config())

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _release(self, *extra):
        from archtrace.cli import main
        return main(["--root", self.root, "release",
                     "--approved-by", "Ian Cruickshank",
                     "--role", "solution-architect", *extra])

    def test_release_refuses_when_the_gate_blocks(self):
        path = os.path.join(self.root, "model", "model.json")
        doc = canon.load_json(path)
        doc["people"][0]["grounding"] = []
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(canon.canonical_json(doc))
        manifest_path = os.path.join(self.root, "release.json")
        before = (open(manifest_path, "rb").read()
                  if os.path.exists(manifest_path) else None)
        self.assertNotEqual(self._release(), 0)
        after = (open(manifest_path, "rb").read()
                 if os.path.exists(manifest_path) else None)
        self.assertEqual(before, after,
                         "a refused release must not write or alter a manifest")

    def test_verify_detects_drift_from_the_approved_state(self):
        self.assertEqual(self._release(), 0)
        from archtrace.cli import main
        self.assertEqual(main(["--root", self.root, "release", "--verify"]), 0)
        path = os.path.join(self.root, "model", "model.json")
        doc = canon.load_json(path)
        doc["systems"][0]["name"] = "Renamed After Approval"
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(canon.canonical_json(doc))
        self.assertNotEqual(main(["--root", self.root, "release", "--verify"]), 0,
                            "publishing a post-approval edit as approved is the "
                            "failure this exists to catch")

    def _verify(self):
        from archtrace.cli import main
        return main(["--root", self.root, "release", "--verify"])

    def _output(self, name: str) -> str:
        return os.path.join(self.root, "render", name)

    def test_verify_detects_a_hand_edited_text_deliverable(self):
        """The publication control must read the bytes being published.

        Verifying a *fresh render* instead answers a weaker question -- could
        the model still produce this? -- and reports "Safe to publish" on a
        deliverable someone edited after it was approved. The pre-existing
        drift test mutated model.json, a source, which was always hashed from
        disk; nothing exercised an edit to render/ itself.
        """
        self.assertEqual(self._release(), 0)
        self.assertEqual(self._verify(), 0, "a clean release must verify")
        path = self._output("traceability.md")
        with open(path, encoding="utf-8") as fh:
            edited = fh.read().replace("Dailies", "Substituted")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(edited)
        self.assertNotEqual(self._verify(), 0,
                            "an edited deliverable must not verify as approved")

    def test_verify_detects_a_hand_edited_binary_deliverable(self):
        """The Word document is the artifact that actually reaches a
        stakeholder, and it is the one a byte comparison is easiest to skip."""
        self.assertEqual(self._release(), 0)
        path = self._output("architecture.docx")
        with open(path, "rb") as fh:
            data = fh.read()
        with open(path, "wb") as fh:
            fh.write(data + b"\x00")
        self.assertNotEqual(self._verify(), 0)

    def test_verify_detects_a_deleted_deliverable(self):
        self.assertEqual(self._release(), 0)
        os.remove(self._output("c4-context.svg"))
        self.assertNotEqual(self._verify(), 0,
                            "an approved output that is gone is not a match")

    def test_verify_detects_an_unapproved_file_added_to_render(self):
        self.assertEqual(self._release(), 0)
        with open(self._output("extra-appendix.md"), "w",
                  encoding="utf-8") as fh:
            fh.write("an appendix nobody approved\n")
        self.assertNotEqual(self._verify(), 0)

    def test_verify_detects_an_unapproved_directory_added_to_render(self):
        """G6 blocks a stray directory; --verify reported MATCH on the same
        tree because it listed only regular files. Two controls disagreeing
        about one tree is the failure this whole area is about."""
        self.assertEqual(self._release(), 0)
        os.makedirs(self._output("appendix"))
        with open(os.path.join(self._output("appendix"), "extra.md"), "w",
                  encoding="utf-8") as fh:
            fh.write("content nobody approved\n")
        self.assertNotEqual(self._verify(), 0)

    def test_verify_judges_render_on_its_own_bytes_not_a_re_render(self):
        """The name, docstring and assertion here used to disagree.

        It described `--verify` reporting that the model had moved while still
        verifying -- behaviour that was removed when `--verify` stopped loading
        the engagement. What it actually exercises: model.json is a SOURCE, and
        sources have always been hashed from disk, so editing one is drift by
        the source rule. The point of the assertion is that render/ reached
        that verdict WITHOUT being re-rendered. "Has the model moved?" is G6's
        question now, asked by `archtrace check`.
        """
        self.assertEqual(self._release(), 0)
        path = os.path.join(self.root, "model", "model.json")
        doc = canon.load_json(path)
        doc["systems"][0]["description"] = "Edited after the approval."
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(canon.canonical_json(doc))
        # model.json is a *source*, so this correctly drifts. The point of the
        # assertion is that render/ is judged on its own bytes, not re-rendered.
        self.assertNotEqual(self._verify(), 0)

    def test_release_signs_the_bytes_on_disk_not_a_fresh_render(self):
        """T1's other half, and nothing was watching it.

        `--verify` was fixed to read `render/` from disk. `release` is what
        writes the hashes it verifies against, and every other test in this
        class signs from a clean tree -- where the bytes on disk and a fresh
        render are identical by construction, so the two questions cannot be
        told apart. Re-seeding the original defect on the signing side leaves
        all 252 tests green; that was measured, not assumed.

        G6 compares CANONICALLY, so trailing whitespace on a Markdown line is
        invisible to the gate while changing the file's bytes. That narrow gap
        is the only place the two questions differ, and it is exactly the state
        an approval has to describe honestly: the bytes in the operator's hand,
        not the ones the renderer would produce from the model.
        """
        import hashlib
        name = "traceability.md"
        path = self._output(name)
        with open(path, "rb") as fh:
            as_rendered = fh.read()
        on_disk = as_rendered.replace(b"\n", b"   \n", 1)
        self.assertNotEqual(on_disk, as_rendered, "the fixture changed nothing")
        self.assertEqual(
            canon.canonical_bytes(name, on_disk),
            canon.canonical_bytes(name, as_rendered),
            "this edit must be canonically invisible, or G6 blocks the release "
            "and the test proves nothing about signing")
        with open(path, "wb") as fh:
            fh.write(on_disk)

        self.assertEqual(self._release(), 0, "G6 should not have blocked this")
        manifest = canon.load_json(os.path.join(self.root, "release.json"))
        self.assertEqual(
            manifest["outputs"][name],
            "sha256:" + hashlib.sha256(on_disk).hexdigest(),
            "the approval recorded a hash of bytes that are not the ones on "
            "disk; it describes a render nobody is holding")
        self.assertEqual(self._verify(), 0,
                         "the bytes signed must be the bytes that verify")

    def test_release_binds_every_output_and_source_by_hash(self):
        self.assertEqual(self._release(), 0)
        manifest = canon.load_json(os.path.join(self.root, "release.json"))
        self.assertEqual(manifest["approved_by"], "Ian Cruickshank")
        self.assertEqual(set(manifest["sources"]),
                         {"evidence/index.json", "requirements/requirements.json",
                          "model/model.json"})
        for value in list(manifest["outputs"].values()) + \
                list(manifest["sources"].values()):
            self.assertTrue(value.startswith("sha256:"))
        self.assertIn("REQ-001", manifest["confirmed_requirements"])

    def test_release_records_outstanding_warnings_rather_than_hiding_them(self):
        path = os.path.join(self.root, "model", "model.json")
        doc = canon.load_json(path)
        doc["nfr_coverage"] = [e for e in doc["nfr_coverage"]
                               if e["category"] != "cost"]
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(canon.canonical_json(doc))
        from archtrace.cli import main
        main(["--root", self.root, "render"])
        self.assertEqual(self._release(), 0)
        manifest = canon.load_json(os.path.join(self.root, "release.json"))
        self.assertIn("G12:cost", manifest["warnings_outstanding"])

    def test_release_manifest_is_not_a_gated_render(self):
        """A commit id changes on every commit, so binding it inside the
        render-freshness gate would fail the build permanently."""
        self._release()
        self.assertFalse(
            os.path.exists(os.path.join(self.root, "render", "release.json")))
        findings, code = gate.run(Engagement.load(self.root))
        self.assertEqual(code, 0, "\n".join(str(f) for f in findings))


class AuthoritativeDocument(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.root = os.path.join(self.tmp, "example")
        shutil.copytree(EXAMPLE, self.root)
        # Pin the citation policy to the DEFAULTS these assertions describe.
        # Two things otherwise decide it: an `archtrace.toml` at the repository
        # root (legitimate -- a repo may configure its own gate, and then its
        # own suite fails, which is a test defect not a config one), and test
        # ordering, because `cli.main` rebinds these module constants from
        # `--root` and any test that drives the CLI leaves them rebound. A test
        # asserting "this quote is too short" must say which floor it means.
        gate.apply_config(config.Config())

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_an_unowned_undated_document_cannot_settle_a_requirement(self):
        path = os.path.join(self.root, "evidence", "index.json")
        doc = canon.load_json(path)
        for record in doc["evidence"]:
            if record["authority"] == "authoritative-document":
                record.pop("document_owner")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(canon.canonical_json(doc))
        findings, code = gate.run(Engagement.load(self.root))
        self.assertEqual(code, 1)
        self.assertIn("G11", {f.rule for f in findings})


class Baseline(unittest.TestCase):
    """The §9a instrument must not flatter an ungrounded architecture."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.root = os.path.join(self.tmp, "example")
        shutil.copytree(EXAMPLE, self.root)
        # Pin the citation policy to the DEFAULTS these assertions describe.
        # Two things otherwise decide it: an `archtrace.toml` at the repository
        # root (legitimate -- a repo may configure its own gate, and then its
        # own suite fails, which is a test defect not a config one), and test
        # ordering, because `cli.main` rebinds these module constants from
        # `--root` and any test that drives the CLI leaves them rebound. A test
        # asserting "this quote is too short" must say which floor it means.
        gate.apply_config(config.Config())

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _run(self, *extra):
        import contextlib
        import io as _io

        from archtrace.cli import main
        buf = _io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = main(["--root", self.root, "baseline", *extra])
        return code, buf.getvalue()

    def test_worked_example_passes_on_unexplained_not_on_traceability(self):
        _code, out = self._run()
        self.assertIn("UNEXPLAINED", out)
        self.assertIn("[PASS]  unexplained 0%", out)
        # Raw traceability is 50% and must NOT be a stop condition: half this
        # architecture is infrastructure nobody asked for, which is healthy.
        self.assertIn("Raw traceability is 50%", out)
        self.assertIn("INFORMATIONAL, not a bar", out)
        self.assertIn("verdict: proceed", out)

    def test_ungrounded_elements_trigger_a_stop(self):
        path = os.path.join(self.root, "model", "model.json")
        doc = canon.load_json(path)
        for container in doc["systems"][0]["containers"][:4]:
            container["grounding"] = []
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(canon.canonical_json(doc))
        _code, out = self._run()
        self.assertIn("[STOP]  unexplained 40%", out)
        self.assertIn("verdict: do not proceed", out)

    def test_a_requirement_link_with_no_citation_behind_it_is_flagged(self):
        reqs = os.path.join(self.root, "requirements", "requirements.json")
        doc = canon.load_json(reqs)
        for req in doc["requirements"]:
            if req["id"] == "REQ-002":
                req["provenance"] = []
        with open(reqs, "w", encoding="utf-8") as fh:
            fh.write(canon.canonical_json(doc))
        _code, out = self._run()
        self.assertIn("[FIX]", out)
        self.assertIn("verdict: do not proceed", out)

    def test_blank_worksheet_from_a_past_engagement(self):
        listing = os.path.join(self.tmp, "elements.txt")
        with open(listing, "w", encoding="utf-8") as fh:
            fh.write("API Gateway\nOrder Service\nLegacy CRM\n")
        target = os.path.join(self.tmp, "ws.csv")
        code, out = self._run("--elements", listing, "--worksheet", target)
        self.assertEqual(code, 0)
        with open(target, encoding="utf-8") as fh:
            content = fh.read()
        self.assertIn("UNEXPLAINED", content)
        self.assertIn("Legacy CRM", content)
        self.assertIn("that column, not the quote column, is the decision", out)


class HostileModelText(unittest.TestCase):
    """Ordinary punctuation in a model field must not corrupt an artifact.

    A quote, a pipe and an ampersand are all things that appear in real system
    names. Three of the text renderers emitted them raw: PlantUML and Mermaid
    produced a C4 macro whose quoted argument was terminated early, and the
    Markdown table gained an extra column. None of it was tested, so a mutation
    that deletes SVG escaping entirely left the suite green.
    """

    HOSTILE = 'Dailies "Ingest" | Platform & <Co>'

    def _rendered(self):
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        root = os.path.join(tmp, "example")
        shutil.copytree(EXAMPLE, root)
        path = os.path.join(root, "model", "model.json")
        doc = canon.load_json(path)
        doc["systems"][0]["name"] = self.HOSTILE
        doc["systems"][0]["description"] = 'a & b <c> "d"'
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(canon.canonical_json(doc))
        return render_all(Engagement.load(root))

    def test_svg_and_drawio_stay_well_formed_xml(self):
        """Closes a surviving mutation: replacing `escape` with the identity
        function left every test passing."""
        import xml.etree.ElementTree as ET
        rendered = self._rendered()

        def parses(name: str) -> str:
            try:
                ET.fromstring(rendered[name].decode("utf-8"))
            except ET.ParseError as exc:
                return f"{name} is not well-formed XML: {exc}"
            return ""

        broken = [p for p in map(parses, ("c4-context.svg", "c4-container.svg",
                                          "model.drawio")) if p]
        self.assertEqual(broken, [])
        # A bare `"` is legal in XML *text content* and is deliberately not
        # escaped there; `&` and `<` are the ones that must be.
        svg = rendered["c4-context.svg"].decode("utf-8")
        self.assertIn("&amp;", svg)
        self.assertIn("&lt;Co&gt;", svg)
        self.assertNotIn("<Co>", svg)

    def test_docx_stays_a_readable_zip_with_well_formed_parts(self):
        import io
        import xml.etree.ElementTree as ET
        import zipfile
        with zipfile.ZipFile(io.BytesIO(self._rendered()["architecture.docx"])) as zf:
            self.assertIsNone(zf.testzip())
            ET.fromstring(zf.read("word/document.xml").decode("utf-8"))

    def test_c4_text_renders_do_not_terminate_their_own_arguments(self):
        """A bare `"` inside a quoted C4 macro argument ends it early, and the
        whole diagram stops parsing. Both formats have an entity for it, and
        they spell it differently."""
        rendered = self._rendered()
        puml = rendered["c4-context.puml"].decode("utf-8")
        line = next(ln for ln in puml.splitlines() if ln.startswith("System("))
        self.assertEqual(line.count('"'), 4,
                         f"a C4 macro argument was terminated early: {line}")
        self.assertIn("&quot;", line)

        mmd = rendered["c4-context.mmd"].decode("utf-8")
        line = next(ln for ln in mmd.splitlines() if ln.strip().startswith("System("))
        self.assertEqual(line.count('"'), 4,
                         f"a C4 macro argument was terminated early: {line}")
        self.assertIn("#quot;", line)

    def test_markdown_tables_keep_their_column_count(self):
        """An unescaped pipe adds a column and silently shifts every cell
        after it, so a grounding column starts reading as a name."""
        import re
        body = rendered = self._rendered()["traceability.md"].decode("utf-8")
        rows = [ln for ln in body.splitlines()
                if ln.startswith("|") and "s_ingest" in ln]
        self.assertTrue(rows, "expected the element row to be present")
        for row in rows:
            cells = len(re.split(r"(?<!\\)\|", row)) - 2
            self.assertEqual(cells, 5, f"row has {cells} cells, not 5: {row}")
        self.assertIn(r"\|", rendered)

    def test_hostile_text_still_passes_the_gate(self):
        """Escaping must not make the model unrenderable or the gate unhappy:
        a rendered-then-checked engagement with hostile text is still clean."""
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        root = os.path.join(tmp, "example")
        shutil.copytree(EXAMPLE, root)
        path = os.path.join(root, "model", "model.json")
        doc = canon.load_json(path)
        doc["systems"][0]["name"] = self.HOSTILE
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(canon.canonical_json(doc))
        from archtrace.cli import main
        # Captured: `render` prints a line per output, and an uncaptured
        # main() here spews into the suite's own output.
        with contextlib.redirect_stdout(io.StringIO()):
            main(["--root", root, "render"])
        _findings, code = gate.run(Engagement.load(root))
        self.assertEqual(code, 0)


class Determinism(unittest.TestCase):
    def test_renders_are_byte_stable_across_runs(self):
        eng = Engagement.load(EXAMPLE)
        first, second = render_all(eng), render_all(eng)
        for name in first:
            self.assertEqual(first[name], second[name], f"{name} is not stable")

    def test_docx_is_a_readable_zip_with_the_required_parts(self):
        import io
        import zipfile
        data = render_all(Engagement.load(EXAMPLE))["architecture.docx"]
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            self.assertIsNone(zf.testzip())
            names = set(zf.namelist())
            for required in ("[Content_Types].xml", "_rels/.rels",
                             "word/document.xml", "word/styles.xml",
                             "word/_rels/document.xml.rels"):
                self.assertIn(required, names)
            for info in zf.infolist():
                self.assertEqual(info.date_time, (1980, 1, 1, 0, 0, 0),
                                 "zip entry carries a wall-clock timestamp")
                self.assertEqual(info.compress_type, zipfile.ZIP_STORED,
                                 "deflate output is not stable across zlib builds")

    def test_generated_xml_parses(self):
        import xml.etree.ElementTree as ET
        outputs = render_all(Engagement.load(EXAMPLE))
        for name in ("model.drawio", "c4-context.svg", "c4-container.svg"):
            ET.fromstring(outputs[name].decode("utf-8"))

    def test_jira_external_id_survives_an_element_rename(self):
        """Hashing the renameable id instead of the uid is how a rename silently
        orphans a ticket and creates a duplicate."""
        eng = Engagement.load(EXAMPLE)
        before = json.loads(render_all(eng)["jira-tickets.json"])
        eng.model["systems"][0]["containers"][1]["id"] = "c_ingest_api"
        for rel in eng.relationships:
            for end in ("source", "destination"):
                if rel[end] == "c_api":
                    rel[end] = "c_ingest_api"
        after = json.loads(render_all(eng)["jira-tickets.json"])
        self.assertEqual({t["external_id"] for t in before["tickets"]},
                         {t["external_id"] for t in after["tickets"]})


class Normalisation(unittest.TestCase):
    def test_curly_punctuation_and_line_wrapping_fold(self):
        wrapped = "if the feed drops for half a day we cannot\nlose those events"
        straight = "If the feed drops for half a day we cannot lose those events"
        self.assertEqual(canon.normalize(wrapped), canon.normalize(straight))

    def test_nfkc_alone_is_insufficient(self):
        import unicodedata
        curly, straight = "we can’t", "we can't"
        self.assertNotEqual(unicodedata.normalize("NFKC", curly),
                            unicodedata.normalize("NFKC", straight))
        self.assertEqual(canon.normalize(curly), canon.normalize(straight))

    def test_zero_width_characters_are_stripped(self):
        self.assertEqual(canon.normalize("audit\u200brecord"), "auditrecord")

    # -- what each step of normalize() is FOR ------------------------------
    #
    # `test_nfkc_alone_is_insufficient` proves NFKC is not sufficient. Nothing
    # proved it was necessary: deleting the call entirely left the suite green,
    # as did dropping the ellipsis fold. Every step below is a documented reason
    # the citation gate does not block a legitimate quote, so each is asserted
    # against the export shape it exists to survive.

    def test_nfkc_is_necessary_not_only_insufficient(self):
        """Ligatures and compatibility forms come out of PDF and Word exports.
        Without NFKC a requirement quoting "workflow" from a PDF that rendered
        it with an fi-ligature fails G2 against the same words typed by hand."""
        self.assertEqual(canon.normalize("the \ufb01nal \ufb02ow"),
                         canon.normalize("the final flow"))
        self.assertEqual(canon.normalize("\u2460 ingest"),
                         canon.normalize("1 ingest"))
        self.assertEqual(canon.normalize("\uff26\uff29\uff38"),
                         canon.normalize("FIX"))

    def test_the_ellipsis_folds_to_three_dots(self):
        """Word autocorrects "..." to a single ellipsis character as you type,
        so the transcript and the analyst's paraphrase disagree by one
        codepoint that nobody can see.

        Deleting this entry from `PUNCTUATION_FOLD` does NOT fail this test,
        and that is correct rather than a gap: NFKC already folds the ellipsis,
        so the entry is belt-and-braces. What matters is the property, which
        holds either way. The table's own comment used to claim NFKC folded
        none of its entries; it folds this one and NBSP.
        """
        self.assertEqual(canon.normalize("we need\u2026 eventually"),
                         canon.normalize("we need... eventually"))
        self.assertEqual(canon.normalize("a\u00a0b"), canon.normalize("a b"))

    def test_the_fold_table_matches_its_own_comment(self):
        """The comment explains which entries NFKC cannot handle. If someone
        adds an entry NFKC already folds, or NFKC's tables change under us, the
        explanation stops being true -- and this is a module whose comments are
        the only record of why each fold exists."""
        import unicodedata
        redundant = {src for src, dst in canon.PUNCTUATION_FOLD.items()
                     if unicodedata.normalize("NFKC", src) == dst}
        self.assertEqual(
            redundant, {"\u2026", "\u00a0"},
            "the set of entries NFKC already folds has changed; the comment "
            "above PUNCTUATION_FOLD names exactly these two and must be "
            "updated with them")

    def test_no_fold_key_is_destroyed_by_nfkc_before_the_table_sees_it(self):
        """How the double-prime entry was found. NFKC runs first, so a key it
        DECOMPOSES can never match -- the entry sits in the table looking
        correct and does nothing. `″` decomposed to `′′`, so `6″` normalised to
        `6\'\'` while `6"` normalised to `6"`, and a citation using one form
        never matched a quote using the other.

        A key NFKC merely *folds to its own target* is fine (redundant, checked
        above). A key NFKC turns into something ELSE is dead."""
        import unicodedata
        dead = {src for src, dst in canon.PUNCTUATION_FOLD.items()
                if len(src) == 1
                and unicodedata.normalize("NFKC", src) not in (src, dst)}
        self.assertEqual(
            dead, set(),
            "these fold keys are decomposed by NFKC before the table runs, so "
            "they never match anything and the character they were meant to "
            "handle is silently normalised to something else")

    def test_a_double_prime_quote_matches_an_ascii_one(self):
        """The defect the check above found, asserted on the behaviour an
        analyst would actually hit: a transcript written with ″ and a
        requirement quoting it with a plain double quote."""
        self.assertEqual(canon.normalize("a 6\u2033 clearance"),
                         canon.normalize('a 6" clearance'))
        self.assertEqual(canon.normalize("6\u2032"), canon.normalize("6'"),
                         "a lone prime must still fold to an apostrophe")

    def test_curly_double_quotes_fold_like_single_ones(self):
        """The single-quote case is covered above. Doubles are what a
        transcript uses to quote a system name, and they are a different
        codepoint range."""
        self.assertEqual(canon.normalize("the \u201cgolden\u201d path"),
                         canon.normalize('the "golden" path'))

    def test_every_dash_folds_to_a_hyphen(self):
        """Three separate codepoints, all rendered by Word as it decides what
        you meant: en dash, em dash, and the true minus sign that appears when
        a requirement quotes a number. A quote containing any of them would
        otherwise never match the same words typed with a hyphen."""
        for dash in ("\u2013", "\u2014", "\u2212"):
            with self.subTest(dash=dash):
                self.assertEqual(canon.normalize(f"four{dash}hour window"),
                                 canon.normalize("four-hour window"))

    def test_every_fold_table_entry_actually_folds(self):
        """The table is the control; a typo'd key would sit there looking
        correct forever. Asserting the whole table covers the entries no
        individual test names, and fails when one stops working."""
        for src, dst in canon.PUNCTUATION_FOLD.items():
            with self.subTest(char=src):
                self.assertEqual(canon.normalize(f"x{src}y"),
                                 canon.normalize(f"x{dst}y"))

    def test_stable_uid_separates_its_parts_unambiguously(self):
        """The `\\x1f` separator is a real control, not decoration. With an
        ordinary `-` the parts run together, so two different identities
        collapse to one hash -- and a uid whose whole job is immutable identity
        would silently alias two elements into one Jira ticket."""
        self.assertNotEqual(canon.stable_uid("e", "a", "b-c"),
                            canon.stable_uid("e", "a-b", "c"))
        self.assertEqual(canon.stable_uid("e", "a", "b"),
                         canon.stable_uid("e", "a", "b"),
                         "the same parts must always give the same uid")


class CanonicalBytes(unittest.TestCase):
    """The G6 false-positive guards, each asserted against what it is for.

    G6 compares a committed render with a fresh one. These three mechanisms are
    the only reason that comparison does not fail on a machine that happens to
    zip in a different order or stamp a timestamp. All three could be deleted
    with the suite green: the renders are byte-identical on one machine, so the
    tolerance is never exercised by comparing a render to itself.
    """

    def test_a_modified_timestamp_is_not_a_difference(self):
        """draw.io writes `modified="..."` on every save. Two exports of one
        unchanged diagram differ only there, and G6 must not call that a hand
        edit."""
        stamped = b'<mxfile modified="2026-01-01T00:00:00Z"><x/></mxfile>'
        plain = b'<mxfile><x/></mxfile>'
        self.assertEqual(canon.canonical_bytes("model.drawio", stamped),
                         canon.canonical_bytes("model.drawio", plain))

    def test_zip_entry_order_is_not_a_difference(self):
        """A .docx is a zip. Entry order is not part of the document, and it is
        not guaranteed stable between a laptop and a CI runner."""
        parts = [("word/document.xml", b"<a/>"), ("[Content_Types].xml", b"<b/>")]
        one = canon.deterministic_zip(parts)
        other = canon.deterministic_zip(list(reversed(parts)))
        self.assertEqual(canon.canonical_bytes("architecture.docx", one),
                         canon.canonical_bytes("architecture.docx", other))

    def test_deterministic_zip_stores_rather_than_deflates(self):
        """zlib output is not guaranteed stable across builds, so a compressed
        .docx can differ between machines for reasons nobody can diagnose.
        These documents are a few KB of XML; compression buys nothing and costs
        the determinism G6 depends on."""
        import io
        import zipfile
        data = canon.deterministic_zip([("word/document.xml", b"<a/>" * 500)])
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            for info in zf.infolist():
                self.assertEqual(info.compress_type, zipfile.ZIP_STORED,
                                 f"{info.filename} is compressed")


if __name__ == "__main__":
    unittest.main(verbosity=2)
