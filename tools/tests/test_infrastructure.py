"""Tests for the cross-cutting modules: config, logging, and the coverage gate.

These three exist to make the rest of the system auditable, so leaving them
untested would be the sharpest kind of irony. The coverage gate itself found
this gap, which is the argument for having it.
"""

from __future__ import annotations

import builtins
import contextlib
import dataclasses
import io
import logging
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from archtrace import config, coverage, log

EXAMPLE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "example")


class ConfigDefaults(unittest.TestCase):
    def setUp(self):
        # A directory with no archtrace.toml in it, so these assert the
        # DEFAULTS rather than whatever the developer's CWD happens to hold.
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def test_defaults_are_the_documented_policy(self):
        cfg = config.load(root=self.tmp, env={})
        self.assertEqual(cfg.citation.min_quote_words, 8)
        self.assertEqual(cfg.citation.min_quote_chars, 40)
        self.assertEqual(cfg.baseline.max_unexplained_pct, 20)
        self.assertEqual(cfg.baseline.min_citation_backed_pct, 100)
        self.assertEqual(cfg.baseline.min_coverage_pct, 80)
        self.assertEqual(cfg.sources, ())

    def test_describe_covers_every_section(self):
        rows = config.load(root=self.tmp, env={}).describe()
        sections = {section for section, _key, _value in rows}
        self.assertEqual(sections, {"citation", "baseline", "render", "mining",
                                    "coverage"})
        self.assertTrue(all(isinstance(key, str) for _s, key, _v in rows))

    def test_config_is_frozen(self):
        cfg = config.load(root=self.tmp, env={})
        with self.assertRaises(dataclasses.FrozenInstanceError):
            cfg.baseline.max_unexplained_pct = 99


class ConfigOverrides(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def _toml(self, body: str) -> None:
        with open(os.path.join(self.tmp, config.CONFIG_FILENAME), "w",
                  encoding="utf-8") as fh:
            fh.write(body)

    def test_a_misspelled_setting_is_refused_not_ignored(self):
        """A bad value already stopped the run; a bad key did not.

        `_apply` only ever looked at names it recognised, so a typo changed
        nothing, recorded nothing in `sources`, and reported nothing -- the
        silent fallback this module's docstring calls worse than a hard stop.
        """
        cfg = config.load(root=self.tmp,
                          env={"ARCHTRACE_CITATION_MIN_QUOTE_WORDZ": "99"})
        self.assertTrue(cfg.errors, "a misspelled setting must be refused")
        self.assertIn("min_quote_wordz", cfg.errors[0])
        self.assertIn("min_quote_words", cfg.errors[0],
                      "the message should name the settings that do exist")
        self.assertEqual(cfg.citation.min_quote_words, 8)

    def test_a_config_file_this_interpreter_cannot_read_is_refused(self):
        """3.9 is the declared floor and tomllib is 3.11+.

        Returning {} meant an adopter's archtrace.toml was inert on the oldest
        interpreter they are told is supported, with no warning -- so two CI
        runners enforced two different policies for the same repository.
        """
        self._toml("[citation]\nmin_quote_words = 99\n")
        real_import = builtins.__import__

        def no_tomllib(name, *args, **kwargs):
            if name == "tomllib":
                raise ModuleNotFoundError("No module named 'tomllib'")
            return real_import(name, *args, **kwargs)

        with mock.patch.object(builtins, "__import__", no_tomllib):
            cfg = config.load(root=self.tmp, env={})
        self.assertTrue(cfg.errors, "an unreadable config file must be refused")
        self.assertIn("tomllib", cfg.errors[0])
        self.assertEqual(cfg.citation.min_quote_words, 8)

    def test_an_absent_config_file_stays_silent_on_any_interpreter(self):
        """The file is optional. Only a file that is present and cannot be
        honoured is an error."""
        real_import = builtins.__import__

        def no_tomllib(name, *args, **kwargs):
            if name == "tomllib":
                raise ModuleNotFoundError("No module named 'tomllib'")
            return real_import(name, *args, **kwargs)

        with mock.patch.object(builtins, "__import__", no_tomllib):
            cfg = config.load(root=self.tmp, env={})
        self.assertEqual(cfg.errors, ())

    @unittest.skipIf(sys.version_info < (3, 11), "tomllib is 3.11+")
    def test_a_malformed_config_file_is_an_error_not_a_traceback(self):
        """`DEFAULT` resolves at import, so this used to be a traceback raised
        while the package was still loading."""
        self._toml("[citation\nmin_quote_words = ")
        cfg = config.load(root=self.tmp, env={})
        self.assertTrue(cfg.errors)
        self.assertIn("could not be read", cfg.errors[0])

    @unittest.skipIf(sys.version_info < (3, 11), "tomllib is 3.11+")
    def test_a_misspelled_section_is_refused_too(self):
        """Caught reviewing the misspelled-key fix: it left an asymmetry.

        A typo'd key stopped the run, but a typo'd SECTION name still
        evaporated in silence -- `[citaton]` matched nothing and the whole
        block was dropped, which is the same defect one level up.
        """
        self._toml("[citaton]\nmin_quote_words = 99\n")
        cfg = config.load(root=self.tmp, env={})
        self.assertTrue(cfg.errors)
        self.assertIn("citaton", cfg.errors[0])
        self.assertIn("no such configuration section", cfg.errors[0])

    @unittest.skipIf(sys.version_info < (3, 11), "tomllib is 3.11+")
    def test_a_valid_config_file_still_loads_without_errors(self):
        """The regression guard for both refusals above."""
        self._toml("[citation]\nmin_quote_words = 10\n"
                   "[baseline]\nmax_unexplained_pct = 15\n")
        cfg = config.load(root=self.tmp, env={})
        self.assertEqual(cfg.errors, ())
        self.assertEqual(cfg.citation.min_quote_words, 10)
        self.assertEqual(cfg.baseline.max_unexplained_pct, 15)

    def test_sources_and_errors_are_not_configurable_sections(self):
        """They are outputs of a load, not settings.

        Two places filtered them and disagreed, so ARCHTRACE_ERRORS_* parsed
        into a phantom section that `load` then silently dropped. They are now
        refused like any other name that is not a section -- which is the point:
        there is no such setting, so pretending to accept one is the failure.
        """
        cfg = config.load(root=self.tmp, env={"ARCHTRACE_ERRORS_FOO": "1",
                                              "ARCHTRACE_SOURCES_BAR": "2"})
        self.assertEqual(len(cfg.errors), 2, cfg.errors)
        self.assertTrue(all("no such configuration section" in e
                            for e in cfg.errors))
        self.assertEqual(cfg.sources, ())

    def test_a_misspelled_environment_section_is_refused(self):
        """The layer the missing-tomllib error tells 3.9/3.10 users to use.

        `_from_env` dropped anything whose prefix matched no section before
        `load` could see it, so ARCHTRACE_CITATON_… (one letter) changed
        nothing and said nothing. Nothing else in the environment wears this
        prefix, so an unmatched one is a typo, not a coincidence.
        """
        cfg = config.load(root=self.tmp,
                          env={"ARCHTRACE_CITATON_MIN_QUOTE_WORDS": "99"})
        self.assertTrue(cfg.errors)
        self.assertIn("ARCHTRACE_CITATON_MIN_QUOTE_WORDS", cfg.errors[0])
        self.assertEqual(cfg.citation.min_quote_words, 8)

    def test_unprefixed_environment_variables_are_never_touched(self):
        """The regression guard for the check above: only ARCHTRACE_* is ours."""
        cfg = config.load(root=self.tmp,
                          env={"PATH": "/usr/bin", "HOME": "/root",
                               "ARCHTRACE_CITATION_MIN_QUOTE_WORDS": "12"})
        self.assertEqual(cfg.errors, ())
        self.assertEqual(cfg.citation.min_quote_words, 12)

    def test_the_logging_variable_is_reserved_not_a_policy_section(self):
        """ARCHTRACE_LOG is operational, not policy, and refusing it bricked
        the CLI.

        `DEFAULT = load()` runs at import and `cli.main` refuses to dispatch
        while any configuration error stands, so treating ARCHTRACE_LOG as an
        unknown section made every command exit 2 for anyone who set it -- and
        the Dockerfile sets it, so the shipped container was bricked for any
        real command (`--help` survived only because argparse exits first).
        """
        cfg = config.load(root=self.tmp, env={"ARCHTRACE_LOG": "debug"})
        self.assertEqual(cfg.errors, ())
        self.assertEqual(cfg.sources, ())

    def test_the_reserved_name_is_taken_from_the_module_that_owns_it(self):
        """A second spelling of it here would be free to drift, and the drift
        would brick the CLI rather than merely being untidy."""
        self.assertIn(log.ENV_LEVEL, config.RESERVED_ENV)

    def test_environment_overrides_and_is_recorded(self):
        cfg = config.load(root=self.tmp, env={
            "ARCHTRACE_CITATION_MIN_QUOTE_WORDS": "12",
            "ARCHTRACE_BASELINE_MAX_UNEXPLAINED_PCT": "5",
        })
        self.assertEqual(cfg.citation.min_quote_words, 12)
        self.assertEqual(cfg.baseline.max_unexplained_pct, 5)
        self.assertIn("citation.min_quote_words", cfg.sources)
        self.assertIn("baseline.max_unexplained_pct", cfg.sources)

    def test_unrelated_environment_variables_are_ignored(self):
        cfg = config.load(root=self.tmp, env={"PATH": "/usr/bin",
                                              "ARCHTRACE_NOT_A_SECTION": "1"})
        self.assertEqual(cfg.sources, ())

    def test_a_bad_value_is_recorded_not_silently_ignored(self):
        """Refusing to guess is the rule everywhere else, but the module-level
        DEFAULT resolves at import, so raising here would turn a typo in an
        environment variable into a stack trace. The error is collected and the
        CLI refuses to run while one is outstanding."""
        cfg = config.load(root=self.tmp,
                          env={"ARCHTRACE_CITATION_MIN_QUOTE_WORDS": "eight"})
        self.assertEqual(len(cfg.errors), 1)
        self.assertIn("cannot read 'eight' as int", cfg.errors[0])
        self.assertIn("ARCHTRACE_CITATION_MIN_QUOTE_WORDS", cfg.errors[0])
        self.assertEqual(cfg.citation.min_quote_words, 8,
                         "the default stands, but the CLI must not proceed")
        self.assertNotIn("citation.min_quote_words", cfg.sources)

    def test_a_clean_load_records_no_errors(self):
        self.assertEqual(config.load(root=self.tmp, env={}).errors, ())

    def test_tuple_values_accept_a_comma_separated_string(self):
        cfg = config.load(root=self.tmp,
                          env={"ARCHTRACE_CITATION_GENERIC_PHRASES": "a, b ,c"})
        self.assertEqual(cfg.citation.generic_phrases, ("a", "b", "c"))

    @unittest.skipIf(sys.version_info < (3, 11), "tomllib is 3.11+")
    def test_a_config_file_overrides_defaults_and_env_overrides_the_file(self):
        with open(os.path.join(self.tmp, config.CONFIG_FILENAME), "w") as fh:
            fh.write("[citation]\nmin_quote_words = 10\n"
                     "[baseline]\nmax_unexplained_pct = 15\n")
        cfg = config.load(root=self.tmp, env={})
        self.assertEqual(cfg.citation.min_quote_words, 10)
        self.assertEqual(cfg.baseline.max_unexplained_pct, 15)
        cfg = config.load(root=self.tmp,
                          env={"ARCHTRACE_CITATION_MIN_QUOTE_WORDS": "20"})
        self.assertEqual(cfg.citation.min_quote_words, 20)
        self.assertEqual(cfg.baseline.max_unexplained_pct, 15)

    def test_a_missing_config_file_is_not_an_error(self):
        self.assertEqual(config.load(root=self.tmp, env={}).citation
                         .min_quote_words, 8)

    def test_boolean_coercion_accepts_the_usual_spellings(self):
        for raw, expected in (("true", True), ("1", True), ("on", True),
                              ("false", False), ("no", False), ("", False)):
            self.assertEqual(config._coerce(False, raw), expected, raw)


class Logging(unittest.TestCase):
    def tearDown(self):
        log.configure("silent")

    def test_logging_goes_to_the_supplied_stream_never_stdout(self):
        """stdout carries machine-readable output — `archtrace quote` emits JSON
        an agent pastes into a file. A log line there would corrupt it."""
        stream = io.StringIO()
        logger = log.configure("debug", stream=stream)
        logger.debug("diagnostic %s", "detail")
        self.assertIn("diagnostic detail", stream.getvalue())

    def test_silent_is_the_default(self):
        stream = io.StringIO()
        logger = log.configure(None, stream=stream)
        logger.info("should not appear")
        logger.error("nor this")
        self.assertEqual(stream.getvalue(), "")

    def test_an_unknown_level_falls_back_to_silent(self):
        stream = io.StringIO()
        logger = log.configure("chatty", stream=stream)
        logger.error("quiet")
        self.assertEqual(stream.getvalue(), "")

    def test_configure_is_idempotent(self):
        stream = io.StringIO()
        for _ in range(3):
            logger = log.configure("info", stream=stream)
        logger.info("once")
        self.assertEqual(stream.getvalue().count("once"), 1)

    def test_child_loggers_sit_under_one_namespace(self):
        self.assertEqual(log.get_logger("gate").name, "archtrace.gate")
        self.assertEqual(log.get_logger().name, "archtrace")

    def test_timed_reports_success_and_failure_without_raising_its_own(self):
        stream = io.StringIO()
        logger = log.configure("debug", stream=stream)
        with log.timed("step", logger):
            pass
        self.assertIn("step: ok", stream.getvalue())
        with self.assertRaises(ValueError), log.timed("boom", logger):
            raise ValueError("expected")
        self.assertIn("boom: failed", stream.getvalue())

    def test_logging_does_not_propagate_to_the_root_logger(self):
        root = io.StringIO()
        handler = logging.StreamHandler(root)
        logging.getLogger().addHandler(handler)
        try:
            log.configure("debug", stream=io.StringIO()).debug("private")
            self.assertEqual(root.getvalue(), "")
        finally:
            logging.getLogger().removeHandler(handler)


class Coverage(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def _module(self, name, body):
        path = os.path.join(self.tmp, f"{name}.py")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(body)
        return path

    def test_every_subpackage_is_measured_not_one_hardcoded_name(self):
        """An unmeasured module shrinks the DENOMINATOR.

        The walker spelled out `commands` by name, so a new subpackage was
        invisible -- and invisible in the dangerous direction: the headline
        percentage stays flat or improves while coverage falls. Splitting a
        large module into a package would have silently removed it from the
        gate.
        """
        pkg = os.path.join(self.tmp, "pkg")
        os.makedirs(os.path.join(pkg, "deep", "deeper"))
        for part in (pkg, os.path.join(pkg, "deep"),
                     os.path.join(pkg, "deep", "deeper")):
            with open(os.path.join(part, "__init__.py"), "w") as fh:
                fh.write("")
        for rel, body in (("top.py", "X = 1\n"),
                          (os.path.join("deep", "mid.py"), "Y = 2\n"),
                          (os.path.join("deep", "deeper", "low.py"), "Z = 3\n")):
            with open(os.path.join(pkg, rel), "w") as fh:
                fh.write(body)
        report = coverage.measure(lambda: None, pkg)
        self.assertEqual(sorted(m.module for m in report.modules),
                         ["deep.deeper.low", "deep.mid", "top"])

    def test_executable_lines_excludes_docstrings_and_pass(self):
        path = self._module("sample", '"""Doc."""\n\n\ndef f():\n'
                                      '    """Inner."""\n    pass\n\n\nX = 1\n')
        self.assertEqual(coverage.executable_lines(path), {4, 9})

    def test_a_file_that_cannot_be_parsed_is_unmeasurable_not_empty(self):
        """None, not an empty set.

        An empty set is the right answer for a module with no statements, so
        returning it for an unparseable one made the two indistinguishable --
        and `percent` scores an empty module 100%. This previously asserted
        `== set()`, which locked the defect in: it checked the mechanism and
        never asked what the mechanism meant for the gate.
        """
        path = self._module("broken", "def (:\n")
        self.assertIsNone(coverage.executable_lines(path))
        self.assertIsNone(coverage.executable_lines(
            os.path.join(self.tmp, "absent.py")))
        self.assertEqual(coverage.executable_lines(
            self._module("empty", '"""Only a docstring."""\n')), set(),
            "a genuinely empty module still reports an empty set")

    def test_an_unmeasurable_module_fails_the_gate_rather_than_scoring_100(self):
        """The whole point of the distinction above."""
        broken = coverage.ModuleCoverage("broken", "/x", 0, 0,
                                         unreadable="could not be parsed")
        self.assertEqual(broken.percent, 0,
                         "an unmeasurable module must not read as fully covered")
        report = coverage.Report(modules=(broken,), min_total_pct=85,
                                 min_module_pct=70)
        failures = report.failures()
        self.assertTrue(failures, "an unmeasurable module must fail the gate")
        self.assertIn("broken", failures[0])
        self.assertIn("could not be parsed", failures[0])

    def test_percentages_and_missing_counts(self):
        module = coverage.ModuleCoverage("m", "/x", executable=10, covered=7)
        self.assertEqual(module.percent, 70)
        self.assertEqual(module.missing, 3)
        empty = coverage.ModuleCoverage("e", "/y", executable=0, covered=0)
        self.assertEqual(empty.percent, 100, "an empty module is not 0%")

    def test_failures_name_every_breached_floor(self):
        report = coverage.Report(
            modules=(coverage.ModuleCoverage("low", "/a", 10, 1),
                     coverage.ModuleCoverage("high", "/b", 10, 10)),
            min_total_pct=90, min_module_pct=70)
        failures = report.failures()
        self.assertTrue(any("total 55%" in f for f in failures))
        self.assertTrue(any(f.startswith("low ") for f in failures))
        self.assertFalse(any(f.startswith("high ") for f in failures))

    def test_a_clean_report_has_no_failures(self):
        report = coverage.Report(
            modules=(coverage.ModuleCoverage("ok", "/a", 10, 10),),
            min_total_pct=90, min_module_pct=70)
        self.assertEqual(report.failures(), [])
        self.assertIn("TOTAL", coverage.render(report))
        self.assertIn("100%", coverage.render(report))

    def test_measure_traces_a_real_package(self):
        package = os.path.join(self.tmp, "pkg")
        os.makedirs(package)
        self._module(os.path.join("pkg", "__init__"), "")
        self._module(os.path.join("pkg", "used"),
                     "def hit():\n    return 1\n\n\ndef missed():\n    return 2\n")
        sys.path.insert(0, self.tmp)
        try:
            def run():
                import pkg.used
                pkg.used.hit()
            report = coverage.measure(run, package)
        finally:
            sys.path.remove(self.tmp)
            for name in [n for n in list(sys.modules) if n.startswith("pkg")]:
                del sys.modules[name]
        used = next(m for m in report.modules if m.module == "used")
        self.assertGreater(used.covered, 0)
        self.assertLess(used.percent, 100, "the unused function must show")


class MakefileGates(unittest.TestCase):
    """The gates that guard the other gates.

    `make lint`, `types` and `secrets` once used `tool && run || echo`, where
    `||` fires when the tool is ABSENT *or* when it ran and found violations —
    the `echo` then exited 0. All three reported green on findings they had just
    printed, so `ci / quality` could not go red on lint or types at all.

    Nothing caught it because nothing tested the Makefile. These tests drive the
    real recipes with a stubbed tool, so the three states stay distinguishable:
    violations fail, a clean run passes, an absent tool skips.

    Deliberately free of ruff/mypy/gitleaks: the `gate` CI job runs `make test`
    with nothing installed, and a test that needed the dev extras would silently
    stop running exactly where this defect lived.
    """

    REPO = os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))))
    # (target, the executable its recipe looks for)
    RECIPES = (("lint", "ruff"), ("types", "mypy"), ("secrets", "gitleaks"))

    def _make(self, target: str, stub: str | None, exit_code: int = 0):
        """Run `make <target>` with `stub` first on PATH, or with no stub."""
        import shutil
        import subprocess

        bindir = tempfile.mkdtemp()
        if stub is not None:
            path = os.path.join(bindir, stub)
            with open(path, "w", encoding="utf-8") as handle:
                handle.write(f"#!/bin/sh\nexit {exit_code}\n")
            os.chmod(path, 0o755)  # noqa: S103
        # PATH is ONLY the scratch bindir -- no /usr/bin, no /bin. A real
        # ruff/mypy/gitleaks living in either (a normal outcome of a
        # system-wide "pip install -e .[dev]") would otherwise get discovered
        # for the "absent tool" cases below, silently defeating the isolation
        # those tests exist to guarantee. `make` itself is resolved to an
        # absolute path above, so it needs no PATH lookup to launch.
        env = dict(os.environ, PATH=bindir)
        try:
            return subprocess.run([shutil.which("make") or "make", "-C",
                                   self.REPO, target], env=env,
                                  capture_output=True, text=True, check=False)
        finally:
            shutil.rmtree(bindir, ignore_errors=True)

    def test_a_tool_that_reports_violations_fails_the_build(self):
        for target, tool in self.RECIPES:
            with self.subTest(target=target):
                result = self._make(target, stub=tool, exit_code=1)
                self.assertNotEqual(
                    result.returncode, 0,
                    f"`make {target}` exited 0 while {tool} reported "
                    "violations. A gate that cannot go red is not a gate.")

    def test_a_failing_tool_is_not_reported_as_a_missing_one(self):
        for target, tool in self.RECIPES:
            with self.subTest(target=target):
                result = self._make(target, stub=tool, exit_code=1)
                self.assertNotIn(
                    "SKIP", result.stdout,
                    f"`make {target}` called a failing {tool} 'not installed'. "
                    "That message sent people looking for the wrong problem.")

    def test_an_absent_tool_skips_without_failing(self):
        for target, tool in self.RECIPES:
            with self.subTest(target=target):
                result = self._make(target, stub=None)
                self.assertEqual(result.returncode, 0,
                                 f"`make {target}` must tolerate a missing "
                                 f"{tool}; the gate runs without dev extras")
                self.assertIn("SKIP", result.stdout)

    def test_a_clean_tool_run_passes(self):
        for target, tool in self.RECIPES:
            with self.subTest(target=target):
                result = self._make(target, stub=tool, exit_code=0)
                self.assertEqual(result.returncode, 0)
                self.assertNotIn("SKIP", result.stdout)


class FreshnessTarget(unittest.TestCase):
    """`make freshness` and `--only`, which shipped with no tests at all.

    The same argument `MakefileGates` makes: nothing caught the lint recipe's
    defect because nothing tested the Makefile. This target was added to close
    a gate that could not fail, and its first two versions each reintroduced
    one -- re-rendering over the evidence before diffing, then reporting
    success when discovery found nothing. Both were found by hand.
    """

    REPO = os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))))

    def _make(self, target: str, *overrides: str):
        return subprocess.run(
            ["make", "-C", self.REPO, "--no-print-directory", target,
             *overrides],
            capture_output=True, text=True, check=False)

    def test_freshness_passes_on_the_committed_tree(self):
        done = self._make("freshness")
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertIn("renders are fresh", done.stdout)

    def test_freshness_does_not_write_to_the_tree(self):
        """It must not re-render.

        An earlier version did, which overwrote an uncommitted hand edit before
        the check could see it -- and, where the evidence content is not on this
        machine, rewrote committed deliverables with degraded placeholders and
        left them there.

        Asserted on mtimes rather than on `git status`, because re-rendering an
        up-to-date engagement writes byte-identical content: a content check
        passes while the target is still writing, and would only fail in the
        very case (evidence absent) this test cannot arrange.
        """
        rendered = [os.path.join(dirpath, name)
                    for engagement in ("example", "engagements/archtrace-self")
                    for dirpath, _dirs, files in
                    os.walk(os.path.join(self.REPO, engagement, "render"))
                    for name in files]
        self.assertTrue(rendered, "expected committed renders to assert on")
        before = {path: os.stat(path).st_mtime_ns for path in rendered}
        self._make("freshness")
        after = {path: os.stat(path).st_mtime_ns for path in rendered}
        rewritten = sorted(os.path.relpath(p, self.REPO)
                           for p in before if before[p] != after[p])
        self.assertEqual(rewritten, [],
                         "freshness wrote to render/; it must only read")

    def test_freshness_fails_when_it_discovers_no_engagements(self):
        """Checking nothing is a failure, not a pass."""
        done = self._make("freshness", "ENGAGEMENT_GLOBS=no/such/place")
        self.assertNotEqual(done.returncode, 0)
        self.assertIn("no engagements found", done.stdout)

    def test_evidence_guard_passes_on_this_repository(self):
        done = self._make("evidence-guard")
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertIn("no recording content is committed", done.stdout)

    def test_evidence_guard_refuses_when_it_cannot_check(self):
        """A guard that passes when it cannot look is the false green it was
        added to close.

        The first version piped `git ls-files` through `|| true`, so outside a
        git repository the command failed, the failure was swallowed, and the
        target reported success. Verified by running the real recipe against a
        directory that is not a repository.
        """
        outside = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, outside, ignore_errors=True)
        shutil.copy(os.path.join(self.REPO, "Makefile"), outside)
        done = subprocess.run(
            ["make", "-C", outside, "--no-print-directory", "evidence-guard"],
            capture_output=True, text=True, check=False)
        self.assertNotEqual(done.returncode, 0,
                            "reported a pass for a check that did not run")
        self.assertIn("did not run", done.stdout)

    def test_engagements_lists_what_freshness_would_check(self):
        done = self._make("engagements")
        self.assertEqual(done.returncode, 0)
        found = done.stdout.split()
        self.assertIn("example", found)
        for path in found:
            self.assertTrue(
                os.path.isfile(os.path.join(self.REPO, path, "model",
                                            "model.json")),
                f"{path} was listed but holds no model/model.json")


class RuleSubset(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.root = os.path.join(self.tmp, "example")
        shutil.copytree(EXAMPLE, self.root)

    def _check(self, *extra):
        from archtrace.cli import main
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
            code = main(["--root", self.root, "check", *extra])
        return code, out.getvalue()

    def test_only_runs_the_named_rule_and_still_blocks_on_it(self):
        path = os.path.join(self.root, "render", "traceability.md")
        with open(path, encoding="utf-8") as fh:
            body = fh.read()
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(body.replace("Dailies", "Substituted"))
        code, out = self._check("--only", "G6")
        self.assertEqual(code, 1, out)
        self.assertIn("G6", out)

    def test_only_does_not_run_the_rules_it_was_not_given(self):
        os.remove(os.path.join(self.root, "_evidence_root",
                               "EV-001-kickoff.txt"))
        full_code, full_out = self._check()
        self.assertEqual(full_code, 1, "G1 should block on missing evidence")
        self.assertIn("G1", full_out)
        code, out = self._check("--only", "G6")
        self.assertEqual(code, 0, out)
        self.assertNotIn("G1", out)

    def test_a_subset_pass_never_claims_the_whole_gate_passed(self):
        """'Grounded and internally consistent' is a statement about every
        rule. Printing it after `--only G6` would be the same false green in a
        smaller costume."""
        code, out = self._check("--only", "G6")
        self.assertEqual(code, 0, out)
        self.assertIn("SUBSET", out)
        self.assertNotIn("grounded and internally consistent", out)

    def test_an_unknown_rule_id_is_refused_and_names_the_known_ones(self):
        code, out = self._check("--only", "G99")
        self.assertEqual(code, 2)
        self.assertIn("G99", out)
        self.assertIn("G6", out, "the message should list the real rule ids")


class DocumentedContract(unittest.TestCase):
    """The documents that promise a contract must match the code that keeps it.

    SPEC.md's rule table stopped at G10 while the registry shipped fifteen ids.
    That was untidy until `check --only RULE...` made those ids something a
    user has to type, at which point an undocumented id is a usability defect.
    Asserting it here is the only version of this that stays true: the last
    three releases each added a rule and none updated the table.
    """

    REPO = os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))))

    def test_spec_documents_every_registered_rule(self):
        from archtrace import gate
        with open(os.path.join(self.REPO, "SPEC.md"), encoding="utf-8") as fh:
            spec = fh.read()
        documented = set(re.findall(r"\*\*(G\d+[a-z]?)\*\*", spec))
        registered = {rid for rid, _severity, _fn in gate.RULES}
        self.assertEqual(
            registered - documented, set(),
            "these rule ids exist in the registry and appear in no SPEC.md "
            "table row; `check --only` makes them user-facing")

    def test_spec_does_not_document_rules_that_do_not_exist(self):
        """The other direction: a removed rule leaves a promise behind."""
        from archtrace import gate
        with open(os.path.join(self.REPO, "SPEC.md"), encoding="utf-8") as fh:
            spec = fh.read()
        documented = set(re.findall(r"\*\*(G\d+[a-z]?)\*\*", spec))
        registered = {rid for rid, _severity, _fn in gate.RULES}
        self.assertEqual(documented - registered, set(),
                         "SPEC.md documents rule ids the gate does not run")

    def test_the_changelog_and_the_package_agree_on_the_version(self):
        """They disagreed for a whole release (0.3.0 vs 0.4.0) with nothing
        to notice. Regex both -- tomllib is 3.11+ and 3.9 is the floor."""
        with open(os.path.join(self.REPO, "pyproject.toml"), encoding="utf-8") as fh:
            packaged = re.search(r'(?m)^version\s*=\s*"([^"]+)"', fh.read())
        with open(os.path.join(self.REPO, "CHANGELOG.md"), encoding="utf-8") as fh:
            released = re.search(r"(?m)^## \[([^\]]+)\]", fh.read())
        self.assertIsNotNone(packaged, "no version in pyproject.toml")
        self.assertIsNotNone(released, "no release heading in CHANGELOG.md")
        self.assertEqual(packaged.group(1), released.group(1),
                         "pyproject.toml and the newest CHANGELOG heading "
                         "disagree about what version this is")


class DocsFreshness(unittest.TestCase):
    """`make docs-fresh`, held to what `make freshness` had to learn.

    That target shipped three times before it was right: it re-rendered before
    diffing, it passed when it discovered nothing, and it overwrote committed
    deliverables. A check that writes to what it is checking has destroyed its
    own evidence, so the non-mutating property is asserted here rather than
    assumed from reading the recipe.
    """

    REPO = os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))))
    # Enough of the repository for the generators to import and for
    # `repo_facts` to discover the same suite. `example/` and `engagements/`
    # are the bulk of the tree and none of these targets read them.
    NEEDED = ("Makefile", "pyproject.toml", "docs", "tools")

    def setUp(self):
        """Every negative case here edits a diagram, and the diagrams are
        tracked files. Working on a copy keeps a killed test run from leaving
        the real tree dirty -- no other test in this suite mutates it, and this
        one should not be the exception that teaches people to expect it."""
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.repo = os.path.join(self.tmp, "repo")
        os.makedirs(self.repo)
        for name in self.NEEDED:
            source = os.path.join(self.REPO, name)
            target = os.path.join(self.repo, name)
            if os.path.isdir(source):
                shutil.copytree(source, target,
                                ignore=shutil.ignore_patterns("__pycache__"))
            else:
                shutil.copy(source, target)
        self.docs = os.path.join(self.repo, "docs")

    def _make(self, target: str):
        return subprocess.run(
            ["make", "-C", self.repo, "--no-print-directory", target],
            capture_output=True, text=True, check=False)

    def _stamps(self) -> dict:
        return {name: os.stat(os.path.join(self.docs, name)).st_mtime_ns
                for name in sorted(os.listdir(self.docs))
                if name.endswith(".svg")}

    def test_docs_fresh_passes_on_the_committed_tree(self):
        done = self._make("docs-fresh")
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertIn("match their generators", done.stdout)

    def test_docs_fresh_writes_nothing(self):
        """Compared by mtime, not by content. A re-render that happens to
        produce identical bytes leaves `git status` clean, so a content
        comparison would pass on precisely the mutation that matters -- which is
        how the first version of the equivalent freshness test missed it."""
        before = self._stamps()
        self.assertTrue(before, "no diagrams found to check")
        self._make("docs-fresh")
        self.assertEqual(self._stamps(), before,
                         "docs-fresh wrote into the directory it checks")
        strays = [n for n in os.listdir(self.docs) if n.endswith(".expected")]
        self.assertEqual(strays, [], "docs-fresh left scratch files behind")

    def test_docs_fresh_fails_on_a_hand_edited_diagram(self):
        """The whole point. A target that cannot go red is not a check."""
        with open(os.path.join(self.docs, "architecture.svg"), "ab") as fh:
            fh.write(b"<!-- an edit nobody generated -->\n")
        done = self._make("docs-fresh")
        self.assertNotEqual(done.returncode, 0,
                            "docs-fresh passed on an edited diagram")
        self.assertIn("STALE", done.stdout)
        self.assertIn("make docs", done.stdout)

    def test_docs_fresh_fails_when_a_generator_crashes(self):
        """A generator that cannot run must stop the build, not be read as
        "no drift found". `make freshness` shipped a version that reported a
        pass for a check it had not managed to perform."""
        with open(os.path.join(self.docs, "gen_sequence.py"), "a",
                  encoding="utf-8") as fh:
            fh.write("\nraise SystemExit('deliberate failure')\n")
        done = self._make("docs-fresh")
        self.assertNotEqual(done.returncode, 0,
                            "a crashing generator was read as a clean check")
        self.assertIn("generator failed", done.stdout)

    def test_every_generated_diagram_is_well_formed_xml(self):
        """An SVG that does not parse renders as nothing at all. Three
        rendering defects in these generators were caught by rasterising the
        output and looking at it, which is not a process."""
        import xml.etree.ElementTree as ET
        for name in sorted(os.listdir(self.docs)):
            if not name.endswith(".svg"):
                continue
            with self.subTest(diagram=name), \
                    open(os.path.join(self.docs, name), encoding="utf-8") as fh:
                ET.fromstring(fh.read())

    def test_no_diagram_text_runs_off_its_own_canvas(self):
        """Text that overflows the viewBox is invisible in a browser and
        clipped in a deck, and neither shows up in a byte comparison. The width
        estimate is deliberately generous (0.55em per character against the
        ~0.5 of a real Helvetica run) so this fires on a genuine overflow
        rather than on a long-but-fitting line."""
        import re
        for name in sorted(os.listdir(self.docs)):
            if not name.endswith(".svg"):
                continue
            with self.subTest(diagram=name):
                with open(os.path.join(self.docs, name), encoding="utf-8") as fh:
                    svg = fh.read()
                width = int(re.search(r'width="(\d+)"', svg).group(1))
                height = int(re.search(r'height="(\d+)"', svg).group(1))
                spilled = []
                for element in re.finditer(
                        r'<text x="([-\d.]+)" y="([-\d.]+)"[^>]*'
                        r'font-size="([\d.]+)"[^>]*?>(.*?)</text>', svg):
                    x, y = float(element.group(1)), float(element.group(2))
                    size, body = float(element.group(3)), element.group(4)
                    anchor = re.search(r'text-anchor="(\w+)"', element.group(0))
                    run = len(body) * size * 0.55
                    left = {"end": x - run, "middle": x - run / 2}.get(
                        anchor.group(1) if anchor else "start", x)
                    if left < -2 or left + run > width + 2 or y > height:
                        spilled.append(body[:60])
                self.assertEqual(spilled, [], f"{name}: text outside the canvas")

    def test_a_rule_without_a_diagram_label_stops_generation(self):
        """A rule added to the registry must not quietly vanish from the
        picture. That is exactly how the sequence diagram came to show eleven
        of fifteen: nothing failed, the rule simply was not drawn."""
        sys.path.insert(0, os.path.join(self.REPO, "docs"))
        import gen_sequence
        with mock.patch("repo_facts.rule_ids",
                        return_value=[*gen_sequence.RULE_LABELS, "G99"]), \
                self.assertRaises(SystemExit) as caught:
            gen_sequence._gate_lines()
        self.assertIn("G99", str(caught.exception))

    def test_a_label_for_a_rule_that_no_longer_runs_stops_generation(self):
        """The other direction: a diagram drawing a gate step the gate does not
        take is a different lie, told just as confidently."""
        sys.path.insert(0, os.path.join(self.REPO, "docs"))
        import gen_sequence
        keep = list(gen_sequence.RULE_LABELS)[:-1]
        with mock.patch("repo_facts.rule_ids", return_value=keep), \
                self.assertRaises(SystemExit) as caught:
            gen_sequence._gate_lines()
        self.assertIn(list(gen_sequence.RULE_LABELS)[-1], str(caught.exception))


class ConfigurationRoot(unittest.TestCase):
    """`archtrace.toml` governs the repository, not the current directory.

    Reproduced before the fix, both of these: `cd engagements/aurora &&
    archtrace check` read no configuration at all, and `cd ~ && archtrace --root
    /work/proj check` enforced whatever `~/archtrace.toml` said. The policy came
    from where the operator was standing rather than from the project being
    gated, and nothing said so.
    """

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.repo = os.path.join(self.tmp, "proj")
        os.makedirs(os.path.join(self.repo, ".git"))
        os.makedirs(os.path.join(self.repo, "engagements", "aurora"))
        with open(os.path.join(self.repo, "archtrace.toml"), "w",
                  encoding="utf-8") as fh:
            fh.write("[citation]\nmin_quote_words = 42\n")
        # A marker with NO config file, for the assertions driven through the
        # environment layer. `self.repo` carries a toml, and on 3.9/3.10 a
        # PRESENT config file is refused by design -- so pointing an env-driven
        # test at it fails there for a reason that has nothing to do with what
        # the test is about.
        self.plain = os.path.join(self.tmp, "plain")
        os.makedirs(os.path.join(self.plain, ".git"))

    # Two mechanisms, and only one of them needs `tomllib`. Resolving WHICH
    # directory governs is pure path handling and must be exercised on 3.9, the
    # declared floor; reading a value out of the file cannot be, because this
    # tool deliberately REFUSES a present-but-unreadable config there rather
    # than ignoring it. Splitting them keeps 3.9 covering the new logic instead
    # of skipping the whole class -- which is what a blanket skip would have
    # done, and what CI caught me doing.

    def test_a_subdirectory_resolves_to_the_repository_root(self):
        deep = os.path.join(self.repo, "engagements", "aurora")
        self.assertEqual(config.find_config_root(deep), self.repo)

    def test_the_repository_root_is_governed_by_itself(self):
        self.assertEqual(config.find_config_root(self.repo), self.repo)

    def test_a_directory_with_no_marker_above_it_governs_itself(self):
        """The fallback must be the starting directory, not a walk to `/`.
        Walking past a non-repository into someone's home directory is how the
        second defect above happened; finding nothing is the safer answer."""
        bare = os.path.join(self.tmp, "bare")
        os.makedirs(bare)
        self.assertEqual(config.find_config_root(bare), os.path.abspath(bare))

    def test_where_the_operator_stands_does_not_change_the_resolution(self):
        """The sharp one, in the half that runs on every interpreter. `--root`
        names the project being gated, so its root wins over the directory the
        operator happens to be in -- even when that directory is itself a
        repository with its own configuration."""
        elsewhere = os.path.join(self.tmp, "elsewhere")
        os.makedirs(os.path.join(elsewhere, ".git"))
        with open(os.path.join(elsewhere, "archtrace.toml"), "w",
                  encoding="utf-8") as fh:
            fh.write("[citation]\nmin_quote_words = 99\n")
        cwd = os.getcwd()
        os.chdir(elsewhere)
        self.addCleanup(os.chdir, cwd)
        deep = os.path.join(self.repo, "engagements", "aurora")
        self.assertEqual(config.find_config_root(deep), self.repo)
        self.assertNotEqual(config.find_config_root(deep), elsewhere)

    def test_the_gate_enforces_the_policy_the_cli_resolved(self):
        """`apply_config` is what makes resolution reach the rules rather than
        only the printout. A tool that reports one threshold and enforces
        another is the failure `archtrace config` exists to prevent.

        Driven through the environment layer rather than the file, so this runs
        on 3.9 too -- `ARCHTRACE_*` is exactly what `config.py` tells 3.9 and
        3.10 users to use instead of a TOML file.
        """
        from archtrace import gate
        self.addCleanup(gate.apply_config, config.Config())
        resolved = config.load(
            self.plain, env={"ARCHTRACE_CITATION_MIN_QUOTE_WORDS": "42"})
        self.assertFalse(resolved.errors, resolved.errors)
        gate.apply_config(resolved)
        self.assertEqual(gate.MIN_QUOTE_WORDS, 42)
        self.assertNotEqual(gate.MIN_QUOTE_WORDS,
                            config.CitationPolicy().min_quote_words,
                            "the fixture must differ from the default, or this "
                            "asserts nothing")

    @unittest.skipIf(sys.version_info < (3, 11), "tomllib is 3.11+")
    def test_the_value_at_the_repository_root_is_the_one_applied(self):
        """The other half: the file at the resolved root is actually read.
        Needs `tomllib`, so 3.9 and 3.10 skip it -- there a present config file
        is refused by design, which `ConfigDefaults` asserts separately."""
        deep = os.path.join(self.repo, "engagements", "aurora")
        self.assertEqual(config.load(deep, env={}).citation.min_quote_words, 42)

    @unittest.skipIf(sys.version_info < (3, 11), "tomllib is 3.11+")
    def test_an_unrelated_config_where_the_operator_stands_is_not_read(self):
        elsewhere = os.path.join(self.tmp, "elsewhere")
        os.makedirs(os.path.join(elsewhere, ".git"))
        with open(os.path.join(elsewhere, "archtrace.toml"), "w",
                  encoding="utf-8") as fh:
            fh.write("[citation]\nmin_quote_words = 99\n")
        cwd = os.getcwd()
        os.chdir(elsewhere)
        self.addCleanup(os.chdir, cwd)
        deep = os.path.join(self.repo, "engagements", "aurora")
        self.assertEqual(
            config.load(deep, env={}).citation.min_quote_words, 42,
            "the policy came from where the operator stood, not from the "
            "project named by --root")

    def test_the_suite_asserts_against_the_default_policy_not_the_repo_s(self):
        """A repository may legitimately configure its own gate. When archtrace
        does that to itself, its own suite must still pass -- these tests assert
        what the DEFAULT policy does, so they pin it rather than inheriting it.

        Before the tests pinned it, a plausible `archtrace.toml` at this repo's
        root turned 26 of its own tests red, which made those assertions
        statements about the developer's working directory rather than about
        the gate.
        """
        from archtrace import gate
        self.assertEqual(
            (gate.MIN_QUOTE_WORDS, gate.MIN_QUOTE_CHARS),
            (config.CitationPolicy().min_quote_words,
             config.CitationPolicy().min_quote_chars),
            "a gate test ran without pinning the policy it asserts against")


class CountedClaims(unittest.TestCase):
    """Numbers the documents state about this repository, checked against it.

    Every one of these was typed correctly and went stale anyway. The test count
    in CHANGELOG 0.5.0 was right the day it was written and wrong two commits
    later; `docs/architecture.svg` drew "157 tests" across four releases; the
    gate rule list in two diagrams named eleven of fifteen ids. Nobody was
    careless -- a hand-written measurement of a repository that changes every
    day simply cannot stay true, so the fix is a check rather than a correction.
    """

    REPO = os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))))

    @staticmethod
    def _facts():
        sys.path.insert(0, os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
        import repo_facts
        return repo_facts

    def _read(self, *parts):
        with open(os.path.join(self.REPO, *parts), encoding="utf-8") as fh:
            return fh.read()

    def test_the_facts_module_counts_what_the_suite_runs(self):
        """The count this whole mechanism rests on. Discovery must find the
        same cases `make test` runs, or every claim below is checked against a
        number that is itself wrong."""
        facts = self._facts()
        loaded = unittest.TestLoader().discover(
            os.path.dirname(os.path.abspath(__file__)),
            top_level_dir=os.path.dirname(
                os.path.dirname(os.path.abspath(__file__))))

        def leaves(suite):
            return (sum(leaves(child) for child in suite)
                    if isinstance(suite, unittest.TestSuite) else 1)

        self.assertEqual(facts.test_count(), leaves(loaded))

    def test_a_module_that_fails_to_import_refuses_rather_than_undercounts(self):
        """`unittest.discover` substitutes a `_FailedTest` placeholder for a
        module it cannot load. That still counts as one case, so a broken import
        would quietly shrink the count by however many tests the module held and
        report a smaller number that looks entirely plausible."""
        facts = self._facts()
        broken = unittest.TestSuite([unittest.TestSuite(
            [unittest.loader._FailedTest("test_thing", ImportError("boom"))])])
        with mock.patch.object(unittest.TestLoader, "discover",
                               return_value=broken), \
                self.assertRaises(RuntimeError) as caught:
            facts.test_cases()
        self.assertIn("test discovery failed", str(caught.exception))

    # `**43 tests** (183 → 226)` — a delta and the range it came from. Both
    # halves are checked: the new total against the suite, and the delta
    # against the range, because a hand-updated total with an untouched delta
    # is a document that contradicts itself in the same sentence.
    DELTA_CLAIM = re.compile(r"\*\*(\d+) tests\*\*\s*\((\d+)\s*(?:→|->)\s*(\d+)\)")
    TOTAL_CLAIM = re.compile(r"\*\*(\d+) tests\*\*(?!\s*\()")

    def test_every_stated_test_count_matches_the_suite(self):
        """Only the CURRENT release section of the changelog, and the readme.
        Older entries record what was true when they were written; rewriting
        them would be falsifying history, not fixing a stale number."""
        facts = self._facts()
        actual = facts.test_count()
        wrong = []
        for name in ("CHANGELOG.md", "README.md"):
            text = self._read(name)
            current = text.split("\n## ")[1] if name == "CHANGELOG.md" else text
            for delta, before, after in self.DELTA_CLAIM.findall(current):
                if int(after) != actual:
                    wrong.append(f"{name}: '({before} → {after})' vs {actual}")
                if int(after) - int(before) != int(delta):
                    wrong.append(f"{name}: '**{delta} tests** ({before} → "
                                 f"{after})' does not add up")
            for claimed in self.TOTAL_CLAIM.findall(current):
                if int(claimed) != actual:
                    wrong.append(f"{name}: '**{claimed} tests**' vs {actual}")
        self.assertEqual(
            wrong, [],
            "`make facts` prints the real numbers; `make docs` fixes the "
            "diagrams. Only the newest CHANGELOG section is checked, so this "
            "is the section you are already editing.")

    def test_the_readme_states_the_real_number_of_pre_pr_steps(self):
        """This one has now gone stale twice: the readme said nine when the
        Makefile ran ten, and ten when it ran eleven. Both were correct when
        typed. The recipe's own `N/M` labels are the source of truth, and they
        are checked for internal consistency first -- a recipe whose steps are
        numbered 1/10, 2/11, 3/11 would otherwise let this pass on a typo."""
        recipe = self._read("Makefile").split("\npre-pr:")[1].split("\n\n")[0]
        steps = re.findall(r'== (\d+)/(\d+) ', recipe)
        self.assertTrue(steps, "no numbered steps found in the pre-pr recipe")
        totals = {total for _n, total in steps}
        self.assertEqual(len(totals), 1,
                         f"the pre-pr steps disagree on the total: {totals}")
        total = int(totals.pop())
        self.assertEqual(
            [int(n) for n, _t in steps], list(range(1, len(steps) + 1)),
            "the pre-pr steps are not numbered 1..N in order")
        self.assertEqual(len(steps), total,
                         f"the recipe has {len(steps)} steps labelled /{total}")
        claimed = re.search(r"make pre-pr\s+#[^\n]*?\((\d+) steps\)",
                            self._read("README.md"))
        self.assertIsNotNone(
            claimed, "README.md no longer states a pre-pr step count in the "
                     "form '(N steps)'; this test cannot check what it cannot "
                     "find, so restore the form or delete the claim")
        self.assertEqual(int(claimed.group(1)), total,
                         "README.md and the Makefile disagree about how many "
                         "steps `make pre-pr` runs")

    def test_the_sequence_diagram_names_every_gate_rule(self):
        """`docs/workflow-sequence.mmd` is hand-authored on purpose -- it is the
        editable source GitHub renders -- so a generator cannot keep it honest
        and this does. It listed eleven of fifteen ids while claiming to show
        what the gate runs."""
        facts = self._facts()
        mermaid = self._read("docs", "workflow-sequence.mmd")
        drawn = set(re.findall(r"\b(G\d+[a-z]?)\b", mermaid))
        self.assertEqual(
            set(facts.rule_ids()) - drawn, set(),
            "these rules run and do not appear in workflow-sequence.mmd")
        self.assertEqual(
            drawn - set(facts.rule_ids()), set(),
            "workflow-sequence.mmd draws rules the gate does not run")

    def test_the_generated_diagrams_match_their_generators(self):
        """G6 asks this of `render/`; nothing asked it of `docs/`. A committed
        SVG whose generator has moved on is a diagram nobody can trust, and the
        only way to notice was to run the generator and look at `git status`."""
        for script, svg in (("gen_architecture.py", "architecture.svg"),
                            ("gen_sequence.py", "workflow-sequence.svg")):
            with self.subTest(diagram=svg):
                committed = self._read("docs", svg)
                proc = subprocess.run(
                    [sys.executable,
                     os.path.join(self.REPO, "docs", script), "--stdout"],
                    capture_output=True, text=True, cwd=self.REPO, check=False)
                self.assertEqual(proc.returncode, 0, proc.stderr)
                self.assertEqual(
                    proc.stdout, committed,
                    f"docs/{svg} is not what docs/{script} produces; "
                    f"run `make docs`")


if __name__ == "__main__":
    unittest.main(verbosity=2)
