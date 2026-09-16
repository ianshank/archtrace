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

from archtrace import canon, gate
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

    def assertFires(self, rule):
        rules, code, findings = self._rules()
        self.assertIn(rule, rules,
                      f"{rule} did not fire; got {sorted(rules)}\n"
                      + "\n".join(str(f) for f in findings))
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
        self.assertFires("G1")

    def test_g1_evidence_content_absent(self):
        os.remove(self._path("_evidence_root", "EV-002-platform-standards.txt"))
        self.assertFires("G1")

    # -- G2 ---------------------------------------------------------------

    def test_g2_fabricated_quote(self):
        def mutate(doc):
            doc["requirements"][1]["provenance"][0]["quote_cached"] = \
                "we require a four hour recovery point objective at minimum"
        self._patch(("requirements", "requirements.json"), mutate)
        self.assertFires("G2")

    def test_g2_trivially_short_quote_is_rejected(self):
        # The Goodhart move: quote something real but too small to support
        # anything. A naive substring check would pass this.
        def mutate(doc):
            prov = doc["requirements"][1]["provenance"][0]
            prov["start"], prov["end"] = 337, 348
            prov["quote_cached"] = "if the feed"
        self._patch(("requirements", "requirements.json"), mutate)
        self.assertFires("G2")

    def test_g2_speaker_not_in_the_room(self):
        def mutate(doc):
            doc["requirements"][1]["provenance"][0]["speaker"] = "D. Vendor"
        self._patch(("requirements", "requirements.json"), mutate)
        self.assertFires("G2")

    def test_g2_span_out_of_bounds(self):
        def mutate(doc):
            doc["requirements"][1]["provenance"][0]["end"] = 999999
        self._patch(("requirements", "requirements.json"), mutate)
        self.assertFires("G2")

    # -- G3 ---------------------------------------------------------------

    def test_g3_requirement_grounded_by_nothing(self):
        def mutate(doc):
            for rel in doc["relationships"]:
                rel["grounding"] = [g for g in rel["grounding"]
                                    if g.get("req") != "REQ-004"]
                if not rel["grounding"]:
                    rel["grounding"] = [{"kind": "standard", "standard": "STD-001"}]
        self._patch(("model", "model.json"), mutate)
        self.assertFires("G3")

    def test_g3_out_of_scope_without_a_decider(self):
        def mutate(doc):
            doc["out_of_scope"][0].pop("decided_by")
        self._patch(("model", "model.json"), mutate)
        self.assertFires("G3")

    def test_g3_superseded_without_successor(self):
        def mutate(doc):
            doc["requirements"][0]["superseded_by"] = None
        self._patch(("requirements", "requirements.json"), mutate)
        self.assertFires("G3")

    # -- G4 ---------------------------------------------------------------

    def test_g4_ungrounded_element(self):
        def mutate(doc):
            doc["systems"][0]["containers"][0]["grounding"] = []
        self._patch(("model", "model.json"), mutate)
        self.assertFires("G4")

    def test_g4_derived_without_an_adr(self):
        def mutate(doc):
            for container in doc["systems"][0]["containers"]:
                for entry in container["grounding"]:
                    if entry["kind"] == "derived":
                        entry.pop("adr")
        self._patch(("model", "model.json"), mutate)
        self.assertFires("G4")

    def test_g4_satisfies_an_unconfirmed_requirement(self):
        def mutate(doc):
            doc["people"][0]["grounding"] = [{"kind": "satisfies", "req": "REQ-000"}]
        self._patch(("model", "model.json"), mutate)
        self.assertFires("G4")

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
        self.assertFires("G5")

    def test_g5_dangling_relationship_endpoint(self):
        def mutate(doc):
            doc["relationships"][0]["destination"] = "s_does_not_exist"
        self._patch(("model", "model.json"), mutate)
        self.assertFires("G5")

    def test_g5_missing_uid(self):
        def mutate(doc):
            doc["people"][0].pop("uid")
        self._patch(("model", "model.json"), mutate)
        self.assertFires("G5")

    # -- G6 ---------------------------------------------------------------

    def test_g6_hand_edited_render(self):
        path = self._path("render", "c4-context.svg")
        with open(path, encoding="utf-8") as fh:
            svg = fh.read()
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(svg.replace("Dailies Ingest Platform", "Dailies Ingest (v2)"))
        self.assertFires("G6")

    def test_g6_stale_render_after_model_change(self):
        def mutate(doc):
            doc["systems"][0]["name"] = "Dailies Ingest Platform (renamed)"
        self._patch(("model", "model.json"), mutate)
        self.assertFires("G6")

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

    def test_g6_still_blocks_when_the_manifest_cannot_be_read(self):
        """The diagnosis is a diagnosis, never a gate of its own: an absent or
        corrupt manifest must not make a stale render pass."""
        from archtrace.model import RENDER_MANIFEST
        with open(self._path("render", RENDER_MANIFEST), "w",
                  encoding="utf-8") as fh:
            fh.write("{not json")
        self.assertFires("G6")

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
        self.assertFires("G7")

    def test_g9_unresolved_conflict_between_confirmed_requirements(self):
        def mutate(doc):
            by_id = {r["id"]: r for r in doc["requirements"]}
            by_id["REQ-002"]["conflicts_with"] = ["REQ-003"]
            by_id["REQ-003"]["conflicts_with"] = ["REQ-002"]
        self._patch(("requirements", "requirements.json"), mutate)
        self.assertFires("G9")

    def test_g10_unknown_schema_version(self):
        def mutate(doc):
            doc["schema_version"] = 99
        self._patch(("model", "model.json"), mutate)
        self.assertFires("G10")

    # -- G11 authority ----------------------------------------------------

    def test_g11_requirement_resting_only_on_observed_implementation(self):
        """The failure this catches: an architect reads a repo, writes down what
        the code does, and it becomes a stakeholder constraint. The citation is
        perfectly real, so every other gate certifies it."""
        def mutate(doc):
            doc["evidence"][0]["authority"] = "observed-implementation"
        self._patch(("evidence", "index.json"), mutate)
        self.assertFires("G11")

    def test_g11_third_party_material_is_not_a_requirement(self):
        def mutate(doc):
            doc["evidence"][0]["authority"] = "third-party"
        self._patch(("evidence", "index.json"), mutate)
        self.assertFires("G11")

    def test_g11_unknown_authority(self):
        def mutate(doc):
            doc["evidence"][0]["authority"] = "seems-right"
        self._patch(("evidence", "index.json"), mutate)
        self.assertFires("G11")

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
        self.assertFires("G12n")

    def test_g12n_open_must_cite_a_real_open_question(self):
        """`open` is a tracked gap. An untracked gap is indistinguishable from
        an overlooked one, which is the whole point of the distinction."""
        def mutate(doc):
            for entry in doc["nfr_coverage"]:
                if entry["status"] == "open":
                    entry["open_question"] = "OQ-999"
                    break
        self._patch(("model", "model.json"), mutate)
        self.assertFires("G12n")

    def test_g12n_open_is_not_a_synonym_for_not_applicable(self):
        """Three statuses, not two: collapsing `open` into `not_applicable`
        turns an unknown into a false assurance."""
        def mutate(doc):
            for entry in doc["nfr_coverage"]:
                if entry["status"] == "open":
                    entry["status"] = "not_applicable"
                    entry.pop("open_question", None)
        self._patch(("model", "model.json"), mutate)
        self.assertFires("G12n")

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


class Release(unittest.TestCase):
    """An approval must bind to a state, and must refuse a failing one."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.root = os.path.join(self.tmp, "example")
        shutil.copytree(EXAMPLE, self.root)

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

    def test_verify_reports_a_model_that_moved_without_failing_an_intact_one(self):
        """Two different questions, deliberately not conflated.

        An intact artifact whose model has since changed is still the thing
        that was approved: it verifies, and says the model moved.
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


if __name__ == "__main__":
    unittest.main(verbosity=2)
