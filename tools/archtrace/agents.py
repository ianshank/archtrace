"""Deterministic validation of agent and skill definitions.

Agent files are prose, which is exactly why they drift. `--deny-tool=write,shell`
appears in a markdown code fence, so nothing stops someone relaxing it to
`--deny-tool=write` in a hurry; the evidence-is-not-instruction rule is a
section heading, so nothing notices when a new agent ships without one. A
control that lives only in prose is a control nobody is enforcing.

This module makes those properties checkable, and `archtrace agents` fails the
build when one is broken. It parses only the restricted frontmatter subset the
files actually use (scalars and inline lists) rather than pulling in a YAML
dependency the gate cannot have.

Checks are declared, not hard-coded into one function, so adding a house rule is
a new entry in `CHECKS` rather than an edit to control flow.
"""

from __future__ import annotations

import os
import re
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Callable

from .log import get_logger

LOG = get_logger("agents")

FRONTMATTER = re.compile(r"\A---\r?\n(.*?)\r?\n---\r?\n", re.DOTALL)
INLINE_LIST = re.compile(r"\A\[(.*)\]\Z")

# An agent in this system proposes; it never writes and never gates. Both tool
# kinds must be denied: an agent denied `write` but granted `shell` writes files
# with `sh -c 'cat > file'`.
ALLOWED_TOOLS = frozenset({"read", "search"})
REQUIRED_DENY = "--deny-tool=write,shell"
MAX_DESCRIPTION = 300

# Phrases that would mean an agent is claiming authority it must not have.
FORBIDDEN_CLAIMS = (
    "i approve", "you may merge", "auto-merge", "sets the exit code",
    "blocks the build",
)


class AgentError(ValueError):
    """The definition is not a shape this validator can vouch for."""


@dataclass(frozen=True)
class AgentDefinition:
    path: str
    slug: str
    frontmatter: dict
    body: str

    @property
    def name(self) -> str:
        return str(self.frontmatter.get("name", ""))

    @property
    def tools(self) -> list:
        value = self.frontmatter.get("tools", [])
        return value if isinstance(value, list) else [value]


@dataclass(frozen=True)
class Finding:
    check: str
    agent: str
    message: str

    def __str__(self) -> str:
        return f"FAIL {self.check}  {self.agent}\n        {self.message}"


def _scalar(raw: str):
    raw = raw.strip()
    if len(raw) >= 2 and raw[0] == raw[-1] and raw[0] in "\"'":
        return raw[1:-1]
    return raw


def parse_frontmatter(text: str) -> dict:
    """Parse the restricted subset these files use: scalars and inline lists."""
    match = FRONTMATTER.match(text)
    if not match:
        raise AgentError("no YAML frontmatter delimited by --- lines")
    data: dict = {}
    for line in match.group(1).splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if ":" not in line:
            raise AgentError(f"frontmatter line is not key: value -> {line!r}")
        key, _, value = line.partition(":")
        value = value.strip()
        listed = INLINE_LIST.match(value)
        if listed:
            data[key.strip()] = [_scalar(p) for p in listed.group(1).split(",")
                                 if p.strip()]
        else:
            data[key.strip()] = _scalar(value)
    return data


def load(path: str) -> AgentDefinition:
    with open(path, encoding="utf-8") as handle:
        text = handle.read()
    frontmatter = parse_frontmatter(text)
    body = FRONTMATTER.sub("", text, count=1)
    slug = os.path.basename(path).split(".")[0]
    return AgentDefinition(path=path, slug=slug, frontmatter=frontmatter,
                           body=body)


def discover(directory: str) -> list:
    """Every `*.agent.md` in a directory, sorted for stable output."""
    if not os.path.isdir(directory):
        return []
    return [os.path.join(directory, name)
            for name in sorted(os.listdir(directory))
            if name.endswith(".agent.md")]


# --- checks ----------------------------------------------------------------

CHECKS: list = []


def check(name: str):
    def wrap(fn: Callable) -> Callable:
        CHECKS.append((name, fn))
        return fn
    return wrap


@check("A1-name-matches-file")
def _name_matches_file(agents: list) -> Iterator[Finding]:
    for agent in agents:
        if agent.name != agent.slug:
            yield Finding("A1-name-matches-file", agent.slug,
                          f"frontmatter name {agent.name!r} does not match the "
                          f"filename. Copilot resolves agents by name, so a "
                          "mismatch invokes something other than what you edited")


@check("A2-name-unique")
def _name_unique(agents: list) -> Iterator[Finding]:
    """The archmine-kit collision (A4 in the integration review) in rule form.

    A user-level agent silently shadows a repo-level one of the same name, so a
    duplicate is resolved by load order with no error anywhere.
    """
    seen: dict = {}
    for agent in agents:
        if agent.name in seen:
            yield Finding("A2-name-unique", agent.slug,
                          f"name {agent.name!r} is already defined by "
                          f"{os.path.basename(seen[agent.name])}; whichever "
                          "loads last wins and nothing reports it")
        seen[agent.name] = agent.path


@check("A3-description")
def _description(agents: list) -> Iterator[Finding]:
    for agent in agents:
        description = str(agent.frontmatter.get("description", "")).strip()
        if not description:
            yield Finding("A3-description", agent.slug,
                          "no description; the description is what decides when "
                          "the agent is selected")
        elif len(description) > MAX_DESCRIPTION:
            yield Finding("A3-description", agent.slug,
                          f"description is {len(description)} chars, over the "
                          f"{MAX_DESCRIPTION} limit")


@check("A4-tools-allowlisted")
def _tools(agents: list) -> Iterator[Finding]:
    for agent in agents:
        if not agent.tools:
            yield Finding("A4-tools-allowlisted", agent.slug,
                          "no tools declared; declare the read-only set "
                          "explicitly rather than inheriting a default")
            continue
        for tool in agent.tools:
            if tool not in ALLOWED_TOOLS:
                yield Finding("A4-tools-allowlisted", agent.slug,
                              f"tool {tool!r} is not in the read-only allowlist "
                              f"{sorted(ALLOWED_TOOLS)}. These agents propose; "
                              "they never write")


@check("A5-read-only-invocation")
def _read_only(agents: list) -> Iterator[Finding]:
    """The frontmatter `tools` key is advisory; the CLI flags are what hold."""
    for agent in agents:
        if REQUIRED_DENY not in agent.body:
            yield Finding("A5-read-only-invocation", agent.slug,
                          f"the body never shows {REQUIRED_DENY}. Denying "
                          "`write` alone does not make an agent read-only -- it "
                          "writes with `sh -c 'cat > file'`")


@check("A6-evidence-is-not-instruction")
def _injection(agents: list) -> Iterator[Finding]:
    for agent in agents:
        lowered = agent.body.lower()
        if "evidence is data" not in lowered and \
                "never instructions" not in lowered:
            yield Finding("A6-evidence-is-not-instruction", agent.slug,
                          "no evidence-is-not-instruction section. Every agent "
                          "that reads retrieved documents needs one")


@check("A7-no-authority-claims")
def _authority(agents: list) -> Iterator[Finding]:
    for agent in agents:
        lowered = agent.body.lower()
        for phrase in FORBIDDEN_CLAIMS:
            if phrase in lowered:
                yield Finding("A7-no-authority-claims", agent.slug,
                              f"claims authority it does not have ({phrase!r}). "
                              "Agents are advisory; the deterministic gate and a "
                              "human decide")


def _safe_load(path: str) -> tuple:
    """Load one definition, returning (definition, error) rather than raising.

    One unparseable file must not hide the findings in every other file.
    """
    try:
        return load(path), None
    except (AgentError, OSError) as exc:
        return None, str(exc)


def validate(directory: str) -> list:
    """Every finding across every agent definition in `directory`."""
    paths = discover(directory)
    agents, findings = [], []
    for path in paths:
        loaded, error = _safe_load(path)
        if error is None:
            agents.append(loaded)
        else:
            findings.append(Finding("A0-parse", os.path.basename(path), error))
    LOG.debug("validating %d agent definition(s) in %s", len(agents), directory)
    for name, fn in CHECKS:
        produced = list(fn(agents))
        LOG.debug("check %s produced %d finding(s)", name, len(produced))
        findings.extend(produced)
    return findings
