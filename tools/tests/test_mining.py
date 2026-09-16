"""Code-mining integration tests.

Two properties matter more than any individual rule here:

1. **Backwards compatibility.** An engagement with no code evidence must behave
   exactly as it did before this module existed, and a record with no
   `content_kind` must be treated as prose.
2. **The dependency boundary.** archtrace must never import the miner. The seam
   is a file, and `test_archtrace_imports_no_third_party_packages` is what stops
   that from quietly eroding.
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from archtrace import canon, gate, mining
from archtrace.model import Engagement

EXAMPLE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "example")

MINIMAL_FACTS = {
    "schema_version": "1.0.0",
    "root": "demo",
    "commit": "a" * 40,
    "symbols": [{"id": "sym:1", "name": "Widget", "kind": "class",
                 "language": "python", "path": "src/w.py",
                 "start_line": 1, "end_line": 9}],
    "relations": [],
    "warnings": [],
}


class ParseFacts(unittest.TestCase):
    def test_parses_a_supported_document(self):
        facts = mining.parse_facts(json.dumps(MINIMAL_FACTS))
        self.assertEqual(facts.commit, "a" * 40)
        self.assertIsNotNone(facts.symbol("sym:1"))
        self.assertIn("src/w.py:1", facts.locator("sym:1"))

    def test_refuses_an_unknown_schema_version(self):
        doc = dict(MINIMAL_FACTS, schema_version="2.0.0")
        with self.assertRaises(mining.FactsError) as ctx:
            mining.parse_facts(json.dumps(doc))
        self.assertIn("Refusing to guess", str(ctx.exception))

    def test_refuses_malformed_input(self):
        for bad in ("not json", "[]", json.dumps(
                dict(MINIMAL_FACTS, symbols=[{"name": "no id"}]))):
            with self.assertRaises(mining.FactsError):
                mining.parse_facts(bad)

    def test_tolerates_unknown_extra_fields(self):
        """A miner may grow fields; it may not omit the ones the gate reads."""
        doc = dict(MINIMAL_FACTS, future_field={"anything": True})
        self.assertEqual(len(mining.parse_facts(json.dumps(doc)).symbols), 1)

    def test_structured_evidence_is_hashed_raw_not_normalised(self):
        """Casefolding a symbol table would destroy the ids it exists to carry."""
        raw = json.dumps(MINIMAL_FACTS).encode()
        self.assertNotEqual(
            mining.sha256_bytes(raw),
            canon.sha256_text(canon.normalize(raw.decode())))


class StructuredEvidence(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.root = os.path.join(self.tmp, "example")
        shutil.copytree(EXAMPLE, self.root)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _rules(self):
        findings, code = gate.run(Engagement.load(self.root))
        return {f.rule for f in findings}, code, findings

    def _patch(self, rel, mutate):
        path = os.path.join(self.root, *rel)
        doc = canon.load_json(path)
        mutate(doc)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(canon.canonical_json(doc))

    def _rerender(self):
        from archtrace.renders import render_all
        for name, data in render_all(Engagement.load(self.root)).items():
            with open(os.path.join(self.root, "render", name), "wb") as fh:
                fh.write(data)

    def assertFires(self, rule, where=None, message=None):
        """Same contract as `test_gate.SeededDefect.assertFires`; see the note
        there for why `where` is the part that makes this an assertion about
        the seeded defect rather than about the example at large."""
        rules, code, findings = self._rules()
        self.assertIn(rule, rules, f"{rule} did not fire; got {sorted(rules)}\n"
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
        self.assertEqual(code, 1)

    # -- the example carries code evidence and stays green ----------------

    def test_example_with_code_evidence_passes(self):
        _rules, code, findings = self._rules()
        self.assertEqual(code, 0, "\n".join(str(f) for f in findings))
        record = Engagement.load(self.root).evidence_by_id("EV-003")
        self.assertEqual(record["content_kind"], "structured")
        self.assertEqual(record["authority"], "observed-implementation")

    # -- G1 on structured content -----------------------------------------

    def test_one_changed_byte_in_the_facts_file_blocks(self):
        path = os.path.join(self.root, "_evidence_root", "EV-003-mam-facts.json")
        with open(path, encoding="utf-8") as fh:
            doc = json.load(fh)
        doc["symbols"][0]["name"] += "X"
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(doc, fh, indent=2)
        self.assertFires("G1", "EV-003")

    def test_code_evidence_without_a_commit_blocks(self):
        def mutate(doc):
            for record in doc["evidence"]:
                if record["id"] == "EV-003":
                    record.pop("commit")
        self._patch(("evidence", "index.json"), mutate)
        path = os.path.join(self.root, "_evidence_root", "EV-003-mam-facts.json")
        with open(path, encoding="utf-8") as fh:
            doc = json.load(fh)
        doc["commit"] = None
        body = json.dumps(doc, indent=2) + "\n"
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(body)

        def rehash(index):
            for record in index["evidence"]:
                if record["id"] == "EV-003":
                    record["sha256_normalized"] = mining.sha256_bytes(body.encode())
        self._patch(("evidence", "index.json"), rehash)
        self.assertFires("G1", "EV-003")

    def test_unknown_content_kind_blocks(self):
        def mutate(doc):
            for record in doc["evidence"]:
                if record["id"] == "EV-003":
                    record["content_kind"] = "spreadsheet"
        self._patch(("evidence", "index.json"), mutate)
        self.assertFires("G1", "EV-003")

    # -- G13 symbol citation integrity ------------------------------------

    def test_a_symbol_that_was_never_mined_blocks(self):
        def mutate(doc):
            for system in doc["systems"]:
                if system["id"] == "s_mam":
                    system["grounding"][1]["symbol"] = "sym:deadbeefdeadbeef"
        self._patch(("model", "model.json"), mutate)
        self.assertFires("G13", "s_mam.grounding[1]")

    def test_a_symbol_citing_prose_evidence_blocks(self):
        def mutate(doc):
            for system in doc["systems"]:
                if system["id"] == "s_mam":
                    system["grounding"][1]["evidence_id"] = "EV-001"
        self._patch(("model", "model.json"), mutate)
        self.assertFires("G13", "s_mam.grounding[1]")

    def test_a_symbol_on_a_satisfies_grounding_blocks(self):
        """Code cannot satisfy a requirement, so a symbol there is a category
        error, not a typo."""
        def mutate(doc):
            doc["people"][0]["grounding"] = [
                {"kind": "satisfies", "req": "REQ-002", "symbol": "sym:1"}]
        self._patch(("model", "model.json"), mutate)
        self.assertFires("G13", "p_dit.grounding[0]")

    def test_a_symbol_without_an_evidence_id_blocks(self):
        def mutate(doc):
            for system in doc["systems"]:
                if system["id"] == "s_mam":
                    system["grounding"][1].pop("evidence_id")
        self._patch(("model", "model.json"), mutate)
        self.assertFires("G13", "s_mam.grounding[1]")

    # -- the authority boundary -------------------------------------------

    def test_a_requirement_citing_code_evidence_is_refused_twice(self):
        """Both G2 and G11 must independently refuse it. Defence in depth,
        because this is the boundary the whole grounding design rests on."""
        def mutate(doc):
            for req in doc["requirements"]:
                if req["id"] == "REQ-002":
                    req["provenance"] = [{
                        "evidence_id": "EV-003", "speaker": "archmine",
                        "start": 0, "end": 60,
                        "quote_cached": "class UserService"}]
        self._patch(("requirements", "requirements.json"), mutate)
        rules, code, _f = self._rules()
        self.assertEqual(code, 1)
        self.assertIn("G2", rules)
        self.assertIn("G11", rules)


class BackwardsCompatibility(unittest.TestCase):
    """An engagement that predates this module must be unaffected by it."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.root = os.path.join(self.tmp, "example")
        shutil.copytree(EXAMPLE, self.root)
        # Strip every trace of the mining integration.
        path = os.path.join(self.root, "evidence", "index.json")
        doc = canon.load_json(path)
        doc["evidence"] = [e for e in doc["evidence"]
                           if e.get("content_kind") != "structured"]
        for record in doc["evidence"]:
            record.pop("content_kind", None)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(canon.canonical_json(doc))
        model_path = os.path.join(self.root, "model", "model.json")
        model = canon.load_json(model_path)
        for system in model["systems"]:
            if system["id"] == "s_mam":
                system["grounding"] = [{"kind": "existing",
                                        "evidence_id": "EV-001"}]
        with open(model_path, "w", encoding="utf-8") as fh:
            fh.write(canon.canonical_json(model))
        from archtrace.renders import render_all
        for name, data in render_all(Engagement.load(self.root)).items():
            with open(os.path.join(self.root, "render", name), "wb") as fh:
                fh.write(data)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_an_engagement_with_no_code_evidence_still_passes(self):
        findings, code = gate.run(Engagement.load(self.root))
        self.assertEqual(code, 0, "\n".join(str(f) for f in findings))

    def test_records_without_content_kind_are_treated_as_prose(self):
        eng = Engagement.load(self.root)
        record = eng.evidence_by_id("EV-001")
        self.assertNotIn("content_kind", record)
        self.assertEqual(eng.content_kind("EV-001"), mining.CONTENT_PROSE)
        self.assertIsNotNone(eng.evidence_text("EV-001"))
        self.assertIsNone(eng.evidence_facts("EV-001"))

    def test_g13_is_inert_without_symbol_citations(self):
        findings = list(gate.g13_symbol_citations(Engagement.load(self.root)))
        self.assertEqual(findings, [])


FAKE_MINER = """import json, os, sys
out = os.path.join("docs", "architecture", "generated")
os.makedirs(out, exist_ok=True)
doc = {"schema_version": "1.0.0", "root": "fake", "commit": COMMIT,
       "symbols": [{"id": "sym:fake1", "name": "Thing", "kind": "class",
                    "language": "python", "path": "src/t.py",
                    "start_line": 3, "end_line": 9}],
       "relations": [], "warnings": []}
with open(os.path.join(out, "architecture-facts.json"), "w") as fh:
    json.dump(doc, fh, indent=2)
sys.exit(EXIT)
"""


class Mine(unittest.TestCase):
    """`mine` drives a miner as a subprocess. A fake one keeps these tests
    runnable on a machine where no miner is installed — which is the same
    property the gate itself has to have."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.root = os.path.join(self.tmp, "example")
        shutil.copytree(EXAMPLE, self.root)
        self.repo = os.path.join(self.tmp, "repo")
        os.makedirs(self.repo)
        with open(os.path.join(self.repo, "src.py"), "w") as fh:
            fh.write("x = 1\n")
        self._git("init", "-q", ".")
        self._git("add", "-A")
        self._git("-c", "user.email=a@b", "-c", "user.name=t",
                  "commit", "-qm", "initial")
        self.commit = self._git("rev-parse", "HEAD").stdout.strip()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _git(self, *argv):
        import subprocess
        return subprocess.run(["git", "-C", self.repo, *argv],
                              capture_output=True, text=True, check=False)

    def _miner(self, commit="None", exit_code=0):
        path = os.path.join(self.tmp, "fake_miner.py")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(FAKE_MINER.replace("COMMIT", commit)
                     .replace("EXIT", str(exit_code)))
        return f"{sys.executable} {path}"

    def _run(self, *extra, command=None):
        import contextlib
        import io as _io

        from archtrace.cli import main
        argv = ["--root", self.root, "mine", "--repo", self.repo,
                "--command", command if command is not None else self._miner(),
                "--source-uri", "https://example.invalid/repo",
                "--date", "2026-09-16", "--classification", "internal",
                "--retention-until", "2029-09-16", *extra]
        out, err = _io.StringIO(), _io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = main(argv)
        return code, out.getvalue() + err.getvalue()

    def _index(self):
        return canon.load_json(os.path.join(self.root, "evidence", "index.json"))

    # -- refusals ---------------------------------------------------------

    def test_dry_run_writes_nothing(self):
        before = json.dumps(self._index(), sort_keys=True)
        code, out = self._run("--dry-run")
        self.assertEqual(code, 0)
        self.assertIn("would run", out)
        self.assertEqual(before, json.dumps(self._index(), sort_keys=True))

    def test_a_dirty_tree_is_refused(self):
        with open(os.path.join(self.repo, "src.py"), "a") as fh:
            fh.write("y = 2\n")
        code, out = self._run("--id", "EV-009")
        self.assertNotEqual(code, 0)
        self.assertIn("uncommitted changes", out)

    def test_a_dirty_tree_is_allowed_when_you_say_so(self):
        with open(os.path.join(self.repo, "src.py"), "a") as fh:
            fh.write("y = 2\n")
        code, _out = self._run("--id", "EV-009", "--allow-dirty")
        self.assertEqual(code, 0)

    def test_a_non_repository_without_a_commit_is_refused(self):
        shutil.rmtree(os.path.join(self.repo, ".git"))
        code, out = self._run("--id", "EV-009")
        self.assertNotEqual(code, 0)
        self.assertIn("not evidence", out)

    def test_a_failing_miner_is_refused(self):
        code, out = self._run("--id", "EV-009",
                              command=self._miner(exit_code=3))
        self.assertNotEqual(code, 0)
        self.assertIn("exited 3", out)

    def test_a_miner_that_produces_nothing_is_refused(self):
        code, out = self._run("--id", "EV-009", command=f"{sys.executable} -c pass")
        self.assertNotEqual(code, 0)
        self.assertIn("produced no", out)

    def test_malformed_facts_are_refused(self):
        bad = os.path.join(self.tmp, "bad.py")
        with open(bad, "w") as fh:
            fh.write("import os\n"
                     "os.makedirs('docs/architecture/generated', exist_ok=True)\n"
                     "open('docs/architecture/generated/architecture-facts.json',"
                     "'w').write('{\"schema_version\": \"9.9.9\"}')\n")
        code, out = self._run("--id", "EV-009",
                              command=f"{sys.executable} {bad}")
        self.assertNotEqual(code, 0)
        self.assertIn("Refusing to guess", out)

    # -- the happy path ---------------------------------------------------

    def test_registers_code_evidence_with_the_right_shape(self):
        code, _out = self._run("--id", "EV-009",
                               "--local-name", "EV-009-facts.json")
        self.assertEqual(code, 0)
        record = next(r for r in self._index()["evidence"] if r["id"] == "EV-009")
        self.assertEqual(record["content_kind"], "structured")
        self.assertEqual(record["authority"], "observed-implementation")
        self.assertEqual(record["source"], "code-mining")
        self.assertEqual(record["commit"], self.commit)
        copied = os.path.join(self.root, "_evidence_root", "EV-009-facts.json")
        self.assertTrue(os.path.isfile(copied))
        with open(copied, "rb") as fh:
            self.assertEqual(record["sha256_normalized"],
                             mining.sha256_bytes(fh.read()))

    def test_a_missing_commit_is_stamped_into_the_copy_not_the_source(self):
        """archmine 0.1.0 declares `commit` and never sets it, so without this
        every facts file it produces is unusable as evidence."""
        code, out = self._run("--id", "EV-009",
                              "--local-name", "EV-009-facts.json")
        self.assertEqual(code, 0)
        self.assertIn("stamped commit", out)
        copied = os.path.join(self.root, "_evidence_root", "EV-009-facts.json")
        with open(copied, encoding="utf-8") as fh:
            self.assertEqual(json.load(fh)["commit"], self.commit)
        source = os.path.join(self.repo, "docs", "architecture", "generated",
                              "architecture-facts.json")
        with open(source, encoding="utf-8") as fh:
            self.assertIsNone(json.load(fh)["commit"],
                              "the miner's own output must not be modified")

    def test_a_commit_the_miner_supplies_is_left_alone(self):
        code, out = self._run("--id", "EV-009", "--local-name", "EV-009-facts.json",
                              command=self._miner(commit='"deadbeef"'))
        self.assertEqual(code, 0)
        self.assertNotIn("stamped commit", out)
        record = next(r for r in self._index()["evidence"] if r["id"] == "EV-009")
        self.assertEqual(record["commit"], self.commit)

    def test_mined_evidence_passes_the_gate_once_it_is_cited(self):
        self._run("--id", "EV-009", "--local-name", "EV-009-facts.json")
        path = os.path.join(self.root, "model", "model.json")
        doc = canon.load_json(path)
        for system in doc["systems"]:
            if system["id"] == "s_mam":
                system["grounding"].append(
                    {"kind": "existing", "evidence_id": "EV-009",
                     "symbol": "sym:fake1"})
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(canon.canonical_json(doc))
        from archtrace.renders import render_all
        for name, data in render_all(Engagement.load(self.root)).items():
            with open(os.path.join(self.root, "render", name), "wb") as fh:
                fh.write(data)
        findings, code = gate.run(Engagement.load(self.root))
        self.assertEqual(code, 0, "\n".join(str(f) for f in findings))


class SourceLocators(unittest.TestCase):
    def test_traceability_resolves_a_symbol_to_a_file_and_line(self):
        from archtrace.renders import render_all
        outputs = render_all(Engagement.load(EXAMPLE))
        markdown = outputs["traceability.md"].decode()
        self.assertIn("src/service.py:1 (class UserService)", markdown)
        self.assertIn("## Code evidence", markdown)
        rows = outputs["traceability.csv"].decode()
        self.assertIn("source_locator", rows)
        self.assertIn("sym:9d3c379feee242b7", rows)

    def test_an_unresolvable_symbol_degrades_to_the_id(self):
        from archtrace.renders import _source_locator
        eng = Engagement.load(EXAMPLE)
        self.assertEqual(
            _source_locator(eng, {"evidence_id": "EV-003", "symbol": "sym:nope"}),
            "sym:nope")


class DependencyBoundary(unittest.TestCase):
    def test_archtrace_imports_no_third_party_packages(self):
        """The load-bearing invariant. archtrace runs on a bare CI runner with
        no setup step, whether or not a miner is installed anywhere."""
        import importlib
        import pathlib
        import sysconfig

        stdlib = pathlib.Path(sysconfig.get_paths()["stdlib"]).resolve()
        package = pathlib.Path(__file__).resolve().parents[1] / "archtrace"
        # __main__ runs the CLI on import by design; every other module is
        # library code and must import cleanly and cheaply.
        modules = [f"archtrace.{p.stem}" for p in sorted(package.glob("*.py"))
                   if p.stem not in ("__init__", "__main__")]
        before = set(sys.modules)
        for name in modules:
            importlib.import_module(name)
        offenders = []
        for name, module in sys.modules.items():
            if name in before or name.startswith(("archtrace", "test")):
                continue
            origin = getattr(getattr(module, "__spec__", None), "origin", None)
            if not origin or origin in ("built-in", "frozen"):
                continue
            resolved = pathlib.Path(origin).resolve()
            if stdlib not in resolved.parents and package not in resolved.parents:
                offenders.append(f"{name} <- {resolved}")
        self.assertEqual(offenders, [],
                         "archtrace pulled in non-stdlib modules: "
                         + ", ".join(offenders))

    def test_mining_module_does_not_import_archmine(self):
        source = (os.path.join(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__))), "archtrace", "mining.py"))
        with open(source, encoding="utf-8") as fh:
            text = fh.read()
        for forbidden in ("import archmine", "from archmine",
                          "import networkx", "import pydantic",
                          "import tree_sitter", "import yaml"):
            self.assertNotIn(forbidden, text)


if __name__ == "__main__":
    unittest.main(verbosity=2)
