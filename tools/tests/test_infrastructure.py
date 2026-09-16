"""Tests for the cross-cutting modules: config, logging, and the coverage gate.

These three exist to make the rest of the system auditable, so leaving them
untested would be the sharpest kind of irony. The coverage gate itself found
this gap, which is the argument for having it.
"""

from __future__ import annotations

import builtins
import dataclasses
import io
import logging
import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from archtrace import config, coverage, log


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


if __name__ == "__main__":
    unittest.main(verbosity=2)
