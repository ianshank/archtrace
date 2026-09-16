"""Tests for the cross-cutting modules: config, logging, and the coverage gate.

These three exist to make the rest of the system auditable, so leaving them
untested would be the sharpest kind of irony. The coverage gate itself found
this gap, which is the argument for having it.
"""

from __future__ import annotations

import dataclasses
import io
import logging
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from archtrace import config, coverage, log


class ConfigDefaults(unittest.TestCase):
    def test_defaults_are_the_documented_policy(self):
        cfg = config.load(root=tempfile.mkdtemp(), env={})
        self.assertEqual(cfg.citation.min_quote_words, 8)
        self.assertEqual(cfg.citation.min_quote_chars, 40)
        self.assertEqual(cfg.baseline.max_unexplained_pct, 20)
        self.assertEqual(cfg.baseline.min_citation_backed_pct, 100)
        self.assertEqual(cfg.baseline.min_coverage_pct, 80)
        self.assertEqual(cfg.sources, ())

    def test_describe_covers_every_section(self):
        rows = config.load(root=tempfile.mkdtemp(), env={}).describe()
        sections = {section for section, _key, _value in rows}
        self.assertEqual(sections, {"citation", "baseline", "render", "mining",
                                    "coverage"})
        self.assertTrue(all(isinstance(key, str) for _s, key, _v in rows))

    def test_config_is_frozen(self):
        cfg = config.load(root=tempfile.mkdtemp(), env={})
        with self.assertRaises(dataclasses.FrozenInstanceError):
            cfg.baseline.max_unexplained_pct = 99


class ConfigOverrides(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

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

    def _module(self, name, body):
        path = os.path.join(self.tmp, f"{name}.py")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(body)
        return path

    def test_executable_lines_excludes_docstrings_and_pass(self):
        path = self._module("sample", '"""Doc."""\n\n\ndef f():\n'
                                      '    """Inner."""\n    pass\n\n\nX = 1\n')
        self.assertEqual(coverage.executable_lines(path), {4, 9})

    def test_a_file_that_cannot_be_parsed_yields_no_lines(self):
        path = self._module("broken", "def (:\n")
        self.assertEqual(coverage.executable_lines(path), set())
        self.assertEqual(coverage.executable_lines(
            os.path.join(self.tmp, "absent.py")), set())

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


if __name__ == "__main__":
    unittest.main(verbosity=2)
