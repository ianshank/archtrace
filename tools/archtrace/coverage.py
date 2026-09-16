"""Line-coverage measurement and enforcement using the standard library.

`coverage.py` is the better tool and this is not trying to replace it. It exists
because the coverage *gate* has to run wherever the rest of the gate runs — a
bare CI runner with no setup step — and a quality bar that only holds when an
optional package happens to be installed is not a bar.

Executable lines come from the AST rather than from `trace`'s private helpers:
statement nodes are what can be executed, and deriving them ourselves keeps this
working across Python versions that move those internals around.

Known and deliberate limits, stated because a coverage number that hides its own
method is worse than no number:

- Line coverage only. No branch coverage; a half-tested `if` counts as covered.
- Multi-line statements count at their first line, matching `trace`'s events.
- `...`/docstring-only bodies are excluded as non-executable.
- Nested measurement is supported, but the inner run's lines are attributed to
  the inner report only.
"""

from __future__ import annotations

import ast
import os
import sys
import trace as _trace
from dataclasses import dataclass

from .config import DEFAULT as CONFIG
from .log import get_logger

LOG = get_logger("coverage")

# Statement nodes whose line is reported by the tracer but which never execute
# as a distinct event worth counting.
_NON_EXECUTABLE = (ast.Pass,)


@dataclass(frozen=True)
class ModuleCoverage:
    module: str
    path: str
    executable: int
    covered: int

    @property
    def percent(self) -> int:
        if not self.executable:
            return 100
        return 100 * self.covered // self.executable

    @property
    def missing(self) -> int:
        return self.executable - self.covered


@dataclass(frozen=True)
class Report:
    modules: tuple
    min_total_pct: int
    min_module_pct: int

    @property
    def executable(self) -> int:
        return sum(m.executable for m in self.modules)

    @property
    def covered(self) -> int:
        return sum(m.covered for m in self.modules)

    @property
    def percent(self) -> int:
        if not self.executable:
            return 100
        return 100 * self.covered // self.executable

    def failures(self) -> list:
        """Every floor this report breaches, most severe first."""
        out = []
        if self.percent < self.min_total_pct:
            out.append(f"total {self.percent}% < {self.min_total_pct}%")
        out.extend(
            f"{module.module} {module.percent}% < {self.min_module_pct}% "
            f"({module.missing} line(s) never executed)"
            for module in sorted(self.modules, key=lambda m: m.percent)
            if module.percent < self.min_module_pct)
        return out


def executable_lines(path: str) -> set:
    """Line numbers in `path` that can actually run."""
    try:
        with open(path, encoding="utf-8") as handle:
            tree = ast.parse(handle.read(), filename=path)
    except (OSError, SyntaxError):
        LOG.debug("cannot parse %s for coverage", path)
        return set()
    lines = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.stmt) or isinstance(node, _NON_EXECUTABLE):
            continue
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant) \
                and isinstance(node.value.value, str):
            continue  # docstring
        lines.add(node.lineno)
    return lines


def measure(run, package_dir: str, exclude: tuple = ()) -> Report:
    """Execute `run()` under the tracer and report coverage of `package_dir`.

    `run` is a zero-argument callable rather than a command string so the caller
    decides what "the suite" means without this module shelling out.
    """
    package_dir = os.path.abspath(package_dir)
    excluded = set(exclude) | set(CONFIG.coverage.exclude_modules)

    # Modules already imported ran their module-level code before the tracer
    # existed, so their constants and class bodies would read as 0% covered --
    # an artefact of measurement, not a gap in the tests. Dropping them forces
    # a fresh import inside the trace so the number means what it says.
    package = os.path.basename(package_dir)
    for name in [n for n in list(sys.modules)
                 if n == package or n.startswith(package + ".")]:
        del sys.modules[name]
    tracer = _trace.Trace(count=1, trace=0, ignoredirs=[sys.prefix,
                                                       sys.exec_prefix])
    LOG.debug("tracing %s (excluding %s)", package_dir, sorted(excluded))
    # `trace.Trace.runfunc` calls `sys.settrace(None)` in its finally block,
    # which silently disarms an OUTER tracer when measurement is nested -- as it
    # is when this module's own tests run under the coverage gate. Saving and
    # restoring makes nesting safe instead of quietly reporting everything after
    # the inner run as uncovered.
    outer = sys.gettrace()
    try:
        tracer.runfunc(run)
    finally:
        sys.settrace(outer)
    counts = tracer.results().counts

    hit: dict = {}
    for (filename, lineno), count in counts.items():
        if count:
            hit.setdefault(os.path.abspath(filename), set()).add(lineno)

    def _module(directory: str, entry: str, prefix: str = "") -> ModuleCoverage:
        path = os.path.join(directory, entry)
        runnable = executable_lines(path)
        covered = runnable & hit.get(path, set())
        return ModuleCoverage(f"{prefix}{entry[:-3]}", path,
                              len(runnable), len(covered))

    modules = [_module(package_dir, entry)
               for entry in sorted(os.listdir(package_dir))
               if entry.endswith(".py") and entry[:-3] not in excluded]

    sub = os.path.join(package_dir, "commands")
    if os.path.isdir(sub):
        modules.extend(_module(sub, entry, prefix="commands.")
                       for entry in sorted(os.listdir(sub))
                       if entry.endswith(".py") and entry[:-3] not in excluded)

    return Report(tuple(modules), CONFIG.coverage.min_total_pct,
                  CONFIG.coverage.min_module_pct)


def render(report: Report) -> str:
    """Human-readable table, stable enough to diff between runs."""
    width = max((len(m.module) for m in report.modules), default=10)
    rows = [f"{'module'.ljust(width)}   lines  covered   pct",
            f"{'-' * width}   -----  -------  ----"]
    rows.extend(
        f"{m.module.ljust(width)}   {m.executable:>5}  {m.covered:>7}  "
        f"{m.percent:>3}%"
        for m in sorted(report.modules, key=lambda mod: mod.module))
    rows.append(f"{'TOTAL'.ljust(width)}   {report.executable:>5}  "
                f"{report.covered:>7}  {report.percent:>3}%")
    return "\n".join(rows)
