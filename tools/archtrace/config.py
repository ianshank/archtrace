"""Every tunable value in one place, overridable without editing code.

Three reasons this module exists rather than constants scattered across the
codebase:

1. **A threshold buried in a print statement is not a policy.** The SPEC §9a
   decision numbers lived inside `cmd_baseline`'s formatting, which meant the
   rule that decides whether the whole programme is worth running could only be
   changed by editing a function that prints things.
2. **Different organisations draw these lines differently.** A quote floor of
   eight words is a judgement, not a law. It should be arguable in a config file
   and visible in a review, not hidden in a diff of the gate.
3. **The gate must stay honest about what it enforces.** `archtrace config`
   prints the live values and where each came from, so nobody has to read source
   to learn what the build is actually checking.

Precedence, lowest to highest: defaults here, then `archtrace.toml` at the
repository root, then `ARCHTRACE_*` environment variables. Standard library
only; TOML is read with `tomllib`, which is 3.11+. On 3.9/3.10 a config file
that is *present* is refused rather than ignored -- silently dropping it meant
the same repository enforced different thresholds on different interpreters --
while its absence stays silent, because the file is optional. Use `ARCHTRACE_*`
variables on those versions.
"""

from __future__ import annotations

import os
import sys
from collections.abc import Mapping
from dataclasses import dataclass, field, fields
from typing import Any

from .log import ENV_LEVEL as LOG_ENV_VAR
from .log import get_logger

LOG = get_logger("config")

CONFIG_FILENAME = "archtrace.toml"
ENV_PREFIX = "ARCHTRACE_"

# `ARCHTRACE_*` names that are operational rather than policy, and so are not
# parsed as <SECTION>_<KEY>. Imported from their owning module rather than
# spelled again here: a copy would be free to drift, and the drift would brick
# the CLI, because an unmatched name is an error and `cli.main` refuses to run
# while any error is outstanding.
RESERVED_ENV = frozenset({LOG_ENV_VAR})


@dataclass(frozen=True)
class CitationPolicy:
    """G2 — what makes a quote substantial enough to support a requirement."""

    min_quote_words: int = 8
    min_quote_chars: int = 40
    generic_phrases: tuple = (
        "that makes sense", "i agree", "sounds good", "we need to", "let me",
        "as i said", "to be clear", "at the end of the day", "going forward",
    )


@dataclass(frozen=True)
class BaselinePolicy:
    """SPEC §9a — the numbers that decide whether to run this programme at all.

    `max_unexplained_pct` is the only stop condition. Raw traceability is
    reported and deliberately not gated: a healthy infrastructure-heavy
    architecture scores low on it, which is why v1's 60% bar was wrong.
    """

    max_unexplained_pct: int = 20
    min_citation_backed_pct: int = 100
    min_coverage_pct: int = 80


@dataclass(frozen=True)
class RenderPolicy:
    """Diagram geometry. Integers only — a computed float destabilises G6."""

    box_width: int = 220
    box_height: int = 104
    margin: int = 40
    chars_per_line: int = 26
    legend_height: int = 34
    title_chars: int = 20


@dataclass(frozen=True)
class MiningPolicy:
    """Phase 2 — driving an external miner as a subprocess."""

    command: str = "archmine index && archmine artifacts"
    facts_path: str = "docs/architecture/generated/architecture-facts.json"
    timeout_seconds: int = 900
    default_miner: str = "archmine"


@dataclass(frozen=True)
class CoveragePolicy:
    """Line coverage floors, enforced by the stdlib tracer."""

    # Actual is 94% total, worst module 85% (commands.evidence). The previous
    # floors -- 85 and 70 -- sat 9 and 15 points below that, which made them
    # decorative: shipping a 40-line untested feature in `gate` took it to 78%
    # and the total to 92%, and BOTH still passed. A floor that cannot fail on
    # a realistic regression is the same false green this repository keeps
    # finding elsewhere. 92/80 leaves ~2 points of total slack for refactor
    # noise and 5 on the worst module, and does catch that example.
    #
    # These are a ratchet. Raise them when the number rises; lowering one is a
    # decision that belongs in a commit message, which is why `coverage_gate`
    # says so when it fails.
    min_total_pct: int = 92
    min_module_pct: int = 80
    # __main__ runs the CLI on import and is never imported by tests.
    # __init__ modules are re-export shims of one to four lines, where a
    # percentage is noise rather than signal; they still count toward the total.
    exclude_modules: tuple = ("__main__", "__init__")


class ConfigError(ValueError):
    """A configuration override could not be honoured.

    Collected rather than raised at import time: the module-level `DEFAULT` is
    resolved when the package loads, and a traceback there would mean a typo in
    an environment variable produced a stack trace instead of a message. The CLI
    refuses to run while any error is outstanding, so nothing silently falls
    back to a default the operator did not choose.
    """


@dataclass(frozen=True)
class Config:
    citation: CitationPolicy = field(default_factory=CitationPolicy)
    baseline: BaselinePolicy = field(default_factory=BaselinePolicy)
    render: RenderPolicy = field(default_factory=RenderPolicy)
    mining: MiningPolicy = field(default_factory=MiningPolicy)
    coverage: CoveragePolicy = field(default_factory=CoveragePolicy)
    sources: tuple = ()
    errors: tuple = ()

    def describe(self) -> list:
        """Flatten to (section, key, value) for `archtrace config`."""
        skip = {"sources", "errors"}
        return [
            (section.name, item.name, getattr(getattr(self, section.name),
                                              item.name))
            for section in fields(self) if section.name not in skip
            for item in fields(getattr(self, section.name))
        ]


def _coerce(current: Any, raw: Any) -> Any:
    """Cast an override to the type the default already has.

    Refusing to guess is the rule everywhere else in this codebase, so a value
    that cannot be cast raises rather than silently falling back to the default
    — a config typo that is quietly ignored is worse than one that stops you.
    """
    if isinstance(current, bool):
        if isinstance(raw, bool):
            return raw
        return str(raw).strip().lower() in {"1", "true", "yes", "on"}
    if isinstance(current, int):
        return int(raw)
    if isinstance(current, tuple):
        if isinstance(raw, (list, tuple)):
            return tuple(raw)
        return tuple(part.strip() for part in str(raw).split(",") if part.strip())
    return type(current)(raw)


def _apply(block: Any, overrides: dict, section: str, seen: list,
           errors: list) -> Any:
    if not overrides:
        return block
    # A misspelled key was silently discarded: `_apply` iterated the block's
    # fields and simply never looked at anything else, so
    # ARCHTRACE_CITATION_MIN_QUOTE_WORDZ=99 changed nothing, reported nothing,
    # and left `sources` empty. A bad *value* was already refused loudly; a bad
    # *key* was not -- which is exactly the silent fallback this module's own
    # docstring says is worse than one that stops you.
    known = {item.name for item in fields(block)}
    errors.extend(
        f"{section}.{key}: no such setting "
        f"(known: {', '.join(sorted(known))})"
        for key in sorted(overrides) if key not in known)
    values = {}
    for item in fields(block):
        if item.name not in overrides:
            continue
        current = getattr(block, item.name)
        raw = overrides[item.name]
        try:
            values[item.name] = _coerce(current, raw)
        except (TypeError, ValueError):
            errors.append(
                f"{section}.{item.name}: cannot read {raw!r} as "
                f"{type(current).__name__} "
                f"(env {ENV_PREFIX}{section.upper()}_{item.name.upper()})")
            continue
        seen.append(f"{section}.{item.name}")
    return type(block)(**{**{f.name: getattr(block, f.name)
                            for f in fields(block)}, **values})


def _from_toml(path: str, errors: list) -> dict:
    """Read the optional config file, refusing an unreadable one loudly.

    `tomllib` is 3.11+. On 3.9/3.10 -- and 3.9 is the declared floor, tested in
    CI -- this used to return `{}` and say nothing, so a team's `archtrace.toml`
    was silently inert on the oldest interpreter they are told is supported.
    Two runners on two Python versions then enforced two different policies for
    the same repository, and `archtrace config` printed "Override with
    archtrace.toml" -- advice that could not work there.

    A *missing* file is still fine and silent: the file is optional. A file that
    is present and cannot be honoured is an error, which is the same rule the
    gate applies to an unknown schema version.
    """
    if not os.path.isfile(path):
        return {}
    try:
        import tomllib  # type: ignore[import-not-found]  # 3.11+ only
    except ModuleNotFoundError:
        errors.append(
            f"{os.path.basename(path)} is present but this interpreter has no "
            f"tomllib (Python {sys.version_info[0]}.{sys.version_info[1]}; "
            "needs 3.11+). Refusing to run with settings you wrote and this "
            f"build would ignore -- use {ENV_PREFIX}* variables instead, or "
            "run on 3.11+.")
        return {}
    try:
        with open(path, "rb") as handle:
            return tomllib.load(handle)
    except (OSError, ValueError) as exc:
        # tomllib raises TOMLDecodeError, a ValueError. Previously this escaped
        # as a traceback at *import* time, because DEFAULT is resolved on load.
        errors.append(f"{os.path.basename(path)} could not be read: {exc}")
        return {}


def _policy_sections() -> set:
    """The configurable sections. `sources` and `errors` are outputs of a load,
    not settings, so they are never overridable -- and the two places that
    filter them used to disagree, leaving `ARCHTRACE_ERRORS_*` parsed into a
    phantom section that `load` then silently dropped."""
    return {f.name for f in fields(Config) if f.name not in {"sources", "errors"}}


def _from_env(env: Mapping[str, str], errors: list) -> dict:
    """ARCHTRACE_CITATION_MIN_QUOTE_WORDS=10 -> {citation: {min_quote_words: 10}}.

    An `ARCHTRACE_`-prefixed name that matches no section is a typo, not a
    coincidence: nothing else in the environment wears this prefix. It used to
    be dropped here, before `load` could see it, so `ARCHTRACE_CITATON_…` (one
    letter) changed nothing and said nothing -- and the env layer is the one the
    missing-tomllib error explicitly tells 3.9/3.10 users to use instead.
    """
    sections = _policy_sections()
    out: dict = {}
    for key, value in sorted(env.items()):
        if not key.startswith(ENV_PREFIX) or key in RESERVED_ENV:
            continue
        remainder = key[len(ENV_PREFIX):].lower()
        # Policy variables are ARCHTRACE_<SECTION>_<KEY> and therefore always
        # have an underscore after the prefix. A single-token name is an
        # operational variable -- ARCHTRACE_LOG, ARCHTRACE_PYTHON -- and not
        # ours to judge. Deciding that by SHAPE rather than by an allowlist is
        # the difference between a rule and a game of whack-a-mole: the first
        # version of this check rejected ARCHTRACE_LOG and bricked the CLI, and
        # adding ARCHTRACE_PYTHON for the shim immediately hit the same trap.
        # A misspelled SECTION still has its key, so it still has an
        # underscore, so it is still caught.
        if "_" not in remainder:
            LOG.debug("ignoring operational variable %s", key)
            continue
        section = next((s for s in sections if remainder.startswith(s + "_")), None)
        if section is None:
            errors.append(
                f"{key}: no such configuration section "
                f"(expected {ENV_PREFIX}<SECTION>_<KEY> with SECTION one of "
                f"{', '.join(sorted(s.upper() for s in sections))})")
            continue
        out.setdefault(section, {})[remainder[len(section) + 1:]] = value
    return out


def load(root: str = ".", env: Mapping[str, str] | None = None) -> Config:
    """Resolve configuration: defaults, then file, then environment."""
    resolved_env: Mapping[str, str] = os.environ if env is None else env
    config = Config()
    seen: list = []
    errors: list = []
    layers = [_from_toml(os.path.join(root, CONFIG_FILENAME), errors),
              _from_env(resolved_env, errors)]
    known = _policy_sections()
    for layer in layers:
        # A misspelled SECTION was as silent as a misspelled key used to be:
        # `[citaton]` simply never matched and the whole block evaporated.
        # `_from_env` reports its own (it can only emit known section names),
        # so in practice this catches the TOML layer.
        errors.extend(
            f"{name}: no such configuration section "
            f"(known: {', '.join(sorted(known))})"
            for name in sorted(layer) if name not in known)
        updates = {}
        for section in fields(config):
            if section.name in {"sources", "errors"}:
                continue
            block = getattr(config, section.name)
            updates[section.name] = _apply(block, layer.get(section.name, {}),
                                           section.name, seen, errors)
        config = Config(**updates, sources=tuple(seen), errors=tuple(errors))
    return config


# Module-level default so callers that do not thread config through still get
# the documented values rather than a second, divergent set of literals.
DEFAULT = load()
