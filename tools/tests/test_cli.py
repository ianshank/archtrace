"""End-to-end CLI behaviour — the regression suite for the verbs themselves.

Every test drives `main()` the way a user or CI would, and asserts on the exit
code and on stdout. Exit codes are the contract with CI, so they are asserted
explicitly rather than inferred from output text.

One invariant runs through all of it: **stdout stays machine-readable.**
`archtrace quote` emits JSON that an agent pastes into a file, so anything that
leaks onto stdout is a correctness bug, not a cosmetic one.
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

from archtrace import log
from archtrace.cli import main

EXAMPLE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "example")


class CliCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.root = os.path.join(self.tmp, "example")
        shutil.copytree(EXAMPLE, self.root)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)
        log.configure("silent")

    def run_cli(self, *argv, root=None):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = main(["--root", root or self.root, *argv])
        return code, out.getvalue(), err.getvalue()


class Verbs(CliCase):
    def test_check_passes_on_the_worked_example(self):
        code, out, _err = self.run_cli("check")
        self.assertEqual(code, 0)
        self.assertIn("0 blocking", out)
        self.assertIn("Correctness is still yours", out)

    def test_check_strict_promotes_warnings(self):
        path = os.path.join(self.root, "model", "model.json")
        with open(path, encoding="utf-8") as fh:
            doc = json.load(fh)
        doc["nfr_coverage"] = [e for e in doc["nfr_coverage"]
                               if e["category"] != "cost"]
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(doc, fh)
        self.run_cli("render")
        self.assertEqual(self.run_cli("check")[0], 0)
        self.assertEqual(self.run_cli("check", "--strict")[0], 1)

    def test_render_writes_every_output(self):
        shutil.rmtree(os.path.join(self.root, "render"))
        code, out, _err = self.run_cli("render")
        self.assertEqual(code, 0)
        self.assertIn("c4-context.svg", out)
        self.assertTrue(os.path.isfile(
            os.path.join(self.root, "render", "architecture.docx")))

    def test_fmt_is_idempotent(self):
        first = self.run_cli("fmt")
        self.assertEqual(first[0], 0)
        before = open(os.path.join(self.root, "model", "model.json"), "rb").read()
        self.run_cli("fmt")
        after = open(os.path.join(self.root, "model", "model.json"), "rb").read()
        self.assertEqual(before, after, "fmt must reach a fixed point")

    def test_report_prints_the_grounding_mix_and_nfr_stance(self):
        code, out, _err = self.run_cli("report")
        self.assertEqual(code, 0)
        self.assertIn("grounding mix", out)
        self.assertIn("non-functional coverage", out)
        self.assertIn("open questions", out)

    def test_config_prints_effective_values(self):
        code, out, _err = self.run_cli("config")
        self.assertEqual(code, 0)
        self.assertIn("[citation]", out)
        self.assertIn("min_quote_words", out)
        self.assertIn("All defaults", out)

    def test_baseline_reports_and_writes_a_worksheet(self):
        target = os.path.join(self.tmp, "ws.csv")
        code, out, _err = self.run_cli("baseline", "--worksheet", target)
        self.assertEqual(code, 0)
        self.assertIn("UNEXPLAINED", out)
        self.assertIn("verdict: proceed", out)
        with open(target, encoding="utf-8") as fh:
            self.assertIn("quotable_statement", fh.readline())

    def test_baseline_blank_worksheet_needs_no_model(self):
        listing = os.path.join(self.tmp, "elements.txt")
        with open(listing, "w", encoding="utf-8") as fh:
            fh.write("API Gateway\nLegacy CRM\n")
        target = os.path.join(self.tmp, "blank.csv")
        code, out, _err = self.run_cli("baseline", "--elements", listing,
                                       "--worksheet", target)
        self.assertEqual(code, 0)
        self.assertIn("2 elements", out)
        self.assertIn("UNEXPLAINED", open(target, encoding="utf-8").read())

    def test_init_scaffolds_a_green_engagement(self):
        fresh = os.path.join(self.tmp, "fresh")
        os.makedirs(fresh)
        code, out, _err = self.run_cli("init", "New Engagement", root=fresh)
        self.assertEqual(code, 0)
        self.assertIn("ready", out)
        self.assertEqual(self.run_cli("check", root=fresh)[0], 0)

    def test_init_refuses_to_clobber(self):
        code, _out, err = self.run_cli("init", "Second")
        self.assertEqual(code, 2)
        self.assertIn("refusing to overwrite", err)


class EvidenceVerbs(CliCase):
    def test_quote_emits_parseable_json_on_stdout(self):
        """The output contract: an agent pastes this straight into a file."""
        code, out, _err = self.run_cli(
            "quote", "EV-001", "the operator does not touch a console")
        self.assertEqual(code, 0)
        payload = json.loads(out)
        self.assertEqual(payload["provenance"][0]["evidence_id"], "EV-001")
        self.assertIsInstance(payload["provenance"][0]["start"], int)

    def test_quote_with_logging_keeps_stdout_clean(self):
        code, out, err = self.run_cli(
            "--log", "debug", "quote", "EV-001",
            "the operator does not touch a console")
        self.assertEqual(code, 0)
        json.loads(out)          # would raise if a log line leaked to stdout
        self.assertIn("archtrace", err)

    def test_quote_reports_a_fragment_it_cannot_find(self):
        code, _out, err = self.run_cli("quote", "EV-001", "never said this")
        self.assertEqual(code, 1)
        self.assertIn("not found", err)

    def test_quote_against_unknown_evidence(self):
        code, _out, err = self.run_cli("quote", "EV-999", "anything")
        self.assertEqual(code, 2)
        self.assertIn("no content", err)

    def test_symbols_finds_and_suggests_a_grounding(self):
        code, out, _err = self.run_cli("symbols", "EV-003", "UserService")
        self.assertEqual(code, 0)
        self.assertIn("sym:", out)
        self.assertIn('"kind": "existing"', out)

    def test_symbols_reports_no_match(self):
        code, _out, err = self.run_cli("symbols", "EV-003", "NoSuchThing")
        self.assertEqual(code, 1)
        self.assertIn("nothing matching", err)

    def test_symbols_against_prose_evidence_is_refused(self):
        code, _out, err = self.run_cli("symbols", "EV-001", "anything")
        self.assertEqual(code, 2)
        self.assertIn("not readable structured", err)

    def test_evidence_add_registers_prose_and_hashes_it(self):
        source = os.path.join(self.root, "_evidence_root", "EV-005-notes.txt")
        with open(source, "w", encoding="utf-8") as fh:
            fh.write("00:01  M. Sponsor: we need month end to close cleanly.\n")
        code, out, _err = self.run_cli(
            "evidence", "add", source, "--id", "EV-005",
            "--source", "interview", "--authority", "stakeholder-confirmed",
            "--source-uri", "https://example.invalid/notes",
            "--date", "2026-09-16", "--participants", "M. Sponsor",
            "--classification", "internal", "--retention-until", "2029-09-16")
        self.assertEqual(code, 0)
        self.assertIn("registered EV-005", out)
        with open(os.path.join(self.root, "evidence", "index.json"),
                  encoding="utf-8") as fh:
            record = next(r for r in json.load(fh)["evidence"]
                          if r["id"] == "EV-005")
        self.assertEqual(len(record["sha256_normalized"]), 64)
        self.assertNotIn("content_kind", record,
                         "prose records stay shaped as they always were")


class ReleaseVerbs(CliCase):
    def test_release_requires_an_approver(self):
        code, _out, err = self.run_cli("release")
        self.assertEqual(code, 2)
        self.assertIn("--approved-by", err)

    def test_release_then_verify_matches(self):
        code, _out, _err = self.run_cli(
            "release", "--approved-by", "Ian Cruickshank",
            "--role", "solution-architect")
        self.assertEqual(code, 0)
        code, out, _err = self.run_cli("release", "--verify")
        self.assertEqual(code, 0)
        self.assertIn("MATCH", out)

    def test_verify_without_a_manifest(self):
        os.remove(os.path.join(self.root, "release.json"))
        code, _out, err = self.run_cli("release", "--verify")
        self.assertEqual(code, 2)
        self.assertIn("no release.json", err)


class GlobalBehaviour(CliCase):
    def test_no_arguments_is_a_usage_error_not_a_traceback(self):
        with self.assertRaises(SystemExit) as ctx, \
                contextlib.redirect_stderr(io.StringIO()):
            main([])
        self.assertEqual(ctx.exception.code, 2)

    def test_evidence_root_defaults_under_the_engagement(self):
        code, _out, _err = self.run_cli("check")
        self.assertEqual(code, 0, "the default evidence root must resolve")

    def test_a_bad_configuration_override_refuses_to_run(self):
        """A typo in an environment variable must produce a message and exit 2,
        never a traceback out of module import."""
        import subprocess
        env = dict(os.environ,
                   ARCHTRACE_CITATION_MIN_QUOTE_WORDS="eight",
                   PYTHONPATH=os.path.dirname(
                       os.path.dirname(os.path.abspath(__file__))))
        result = subprocess.run(
            [sys.executable, "-m", "archtrace.cli", "--root", self.root, "check"],
            capture_output=True, text=True, env=env, check=False)
        self.assertEqual(result.returncode, 2)
        self.assertIn("bad configuration", result.stderr)
        self.assertNotIn("Traceback", result.stderr)

    def test_log_level_is_accepted_for_every_verb(self):
        for level in ("debug", "info", "warning", "error", "silent"):
            code, _out, _err = self.run_cli("--log", level, "report")
            self.assertEqual(code, 0, level)


if __name__ == "__main__":
    unittest.main(verbosity=2)
