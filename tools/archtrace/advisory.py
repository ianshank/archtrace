"""The advisory plane: a ranked worklist, and a seam for a neural reviewer.

SPEC §7.3 has promised `archtrace review` since v2 and nothing implemented it.
`review/advisory.md` was a path named in three diagrams, a heading in the
RUNBOOK and a prompt an operator pasted into `copilot` by hand; no command
wrote it, no schema described it, and no test asserted anything about it. So
the half of this design that is allowed to be wrong had nowhere to put its
output, which is a strange gap in a repository this careful about the half that
is not.

Two things arrive here, and keeping them apart is the whole design.

**The worklist is deterministic.** Every observation below is computed from the
model and the evidence manifest by the same code that would run on a machine
with no network. It is the ranked adversarial reading the gate cannot express
as a pass/fail: citations that cleared G2 by a word, elements that present as
`derived` while resting on a guess, one ADR holding up a third of the model.
None of it blocks, because none of it is wrong often enough to be a rule --
that is exactly the distinction G12 draws between a warning and a block, one
level up.

**The neural half arrives as a file.** `--findings` reads observations produced
by something else entirely: an NLI model scoring whether an evidence span
actually entails the requirement drawn from it, a defeater generator reading an
ADR for the reasons it might not hold, a human with a text editor. archtrace
validates the shape, refuses a version it does not know, and renders it beside
its own. It never imports the producer and never runs it. That is the same seam
`archmine` uses -- `docs/archmine-integration.md` §3 calls it "a file, not an
import" -- and it is what lets the producer be a 400 MB transformer stack while
the gate stays standard-library-only on a bare runner.

**What this must never do is adjudicate.** A finding that an LLM produced is a
question for a person, not a verdict: `.github/agents/architecture-reviewer.agent.md`
says the judgement has never been benchmarked against a human baseline on this
corpus, and the exit code says so too. `archtrace review` returns 0 no matter
what it finds. A findings file the operator pointed at and that cannot be read
is a different thing -- a usage error, exit 2, the same answer `check` gives an
unknown `--only` id -- because refusing to guess is not the same as refusing to
pass.

No timestamp in the output. Writing `datetime.now()` into a generated artifact
is defect A1 this repository found in `archmine` and patched upstream; doing it
here would be worse, because we knew.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass

from . import canon
from .config import DEFAULT as CONFIG
from .grounding import analyse
from .log import get_logger
from .model import Engagement

LOG = get_logger("advisory")

ADVISORY_DIR = "review"
ADVISORY_FILE = "advisory.md"

FINDINGS_SCHEMA_VERSIONS = frozenset({1})

# What an external reviewer is allowed to claim. A closed set because an
# advisory whose categories are free text cannot be read at a glance, ranked,
# or compared between runs -- and because the point of naming them is to say
# which jobs the neural half is being invited to do.
FINDING_KINDS = {
    # The support gap SPEC §7.1 states plainly: the quote is real, substantial
    # and correctly attributed, and still does not support the requirement.
    # This is textually the NLI task.
    "unsupported-inference": "Quote does not support the requirement",
    # The span says the opposite of the requirement drawn from it.
    "contradiction": "Evidence contradicts the requirement",
    # A reason a documented decision might not hold. Generated from an ADR.
    "defeater": "A reason this decision may not hold",
    # The axis a single extraction agent is weakest on, per SPEC §4.
    "missing-requirement": "Plausibly absent from the requirement set",
    # In the room, but not the person whose statement becomes a constraint.
    "authority": "Speaker authority is doubtful",
    # Text in the corpus addressed to a reader rather than said between
    # people. The agent definition requires this be reported, never obeyed.
    "anomaly": "Evidence text aimed at the reader, not at the room",
}

# The repository's own confidence vocabulary, used in SPEC, REVIEW and
# docs/tech-debt. A reviewer that invents its own scale cannot be compared
# with the prose it sits beside.
CONFIDENCE = ("certain", "likely", "guessing")


class FindingsError(ValueError):
    """An external findings file could not be honoured.

    Raised rather than degraded. Every other reader in this codebase refuses an
    unknown `schema_version` instead of guessing -- `parse_facts`, the config
    loader, G10 -- and a reviewer's output is the last place to start.
    """


@dataclass(frozen=True)
class Observation:
    """One line of the worklist.

    `tier` orders the document. It is not a severity in the gate's sense --
    nothing here blocks -- it is an answer to "if you read three of these,
    read which three?".
    """

    tier: int
    kind: str
    where: str
    detail: str
    confidence: str
    source: str

    @property
    def sort_key(self) -> tuple:
        return (self.tier, self.kind, self.where, self.detail)


def _quote_words(req: dict) -> int:
    """Words in the shortest quote supporting a requirement."""
    return min((len(prov.get("quote_cached", "").split())
                for prov in req.get("provenance", [])), default=0)


def _evidence_concentration(eng: Engagement) -> list:
    """Evidence records carrying a disproportionate share of the requirements.

    Every citation is verbatim, in bounds and correctly attributed, and the
    whole requirement set can still turn on one recording being complete and
    correctly transcribed. G8 asks the opposite question -- evidence nobody
    cited -- and nothing asked this one.
    """
    confirmed = eng.confirmed_requirements
    if not confirmed:
        return []
    carried: dict = {}
    for req in confirmed:
        for record in {prov.get("evidence_id")
                       for prov in req.get("provenance", []) if prov.get(
                           "evidence_id")}:
            carried[record] = carried.get(record, 0) + 1
    share = CONFIG.advisory.evidence_share_pct
    return [
        Observation(
            5, "evidence-concentration", record,
            f"Supports {count} of {len(confirmed)} confirmed requirement(s). "
            "Every citation into it is verbatim and in bounds; that says "
            "nothing about whether the recording was complete, whether the "
            "speaker was corrected later in the same meeting, or whether the "
            "transcript dropped a clause.",
            "likely", "archtrace")
        for record, count in sorted(carried.items())
        if 100 * count // len(confirmed) >= share]


def worklist(eng: Engagement) -> list:
    """Everything archtrace can say about this model without an LLM.

    Ordered by how likely the record is to not mean what it claims, which is a
    different ordering from how badly it breaks a rule -- the rule breakages
    are already `archtrace check`'s job and it has said them.
    """
    found: list = []
    analysis = analyse(eng)

    # Tier 1 -- it passed, and the margin is the whole story.
    floor = CONFIG.citation.min_quote_words
    margin = CONFIG.advisory.near_floor_margin_words
    for req in eng.confirmed_requirements:
        words = _quote_words(req)
        if not words or words >= floor + margin:
            continue
        found.append(Observation(
            1, "near-floor-citation", req["id"],
            f"Supported by a {words}-word quote against a {floor}-word floor. "
            "G2 raises the cost of quoting short, high-frequency fragments; it "
            "does not eliminate the strategy (SPEC §7.1). Read this one "
            "against its span.",
            "certain", "archtrace"))

    # Tier 2 -- presents as a consequence of a decision, rests on a guess.
    # Only the TRANSITIVE case. An element grounded directly on an
    # `assumption` is already honest: the kind is right there in the model, in
    # every render and in the grounding mix, and the open-question register
    # names what is unknown. Listing it here would be reporting the design
    # working. The finding is the element two hops down that reads as
    # `derived` -- a consequence of a documented decision -- while everything
    # underneath it is somebody's guess.
    for element in analysis.tainted:
        hops = analysis.depth.get(element, 0)
        if not hops:
            continue
        found.append(Observation(
            2, "assumption-tainted", element,
            f"Grounded `derived`, and every route from it to a real reason "
            f"passes through an `assumption` {hops} hop(s) down. It reads in "
            "the model, the diagrams and the grounding mix as a consequence "
            "of a documented decision. Nothing under it is.",
            "certain", "archtrace"))

    # Tier 3 -- one decision holding up a disproportionate share of the model.
    total_derived = sum(analysis.adr_load.values())
    share = CONFIG.advisory.adr_load_share_pct
    for adr, count in sorted(analysis.adr_load.items()):
        if total_derived and 100 * count // total_derived < share:
            continue
        found.append(Observation(
            3, "adr-concentration", adr,
            f"Holds up {count} of {total_derived} derived grounding(s). If "
            "this decision was wrong, everything hanging off it is wrong, and "
            "no gate can tell you that because each citation is valid.",
            "likely", "archtrace"))

    # Tier 4 -- architecture justified by other architecture.
    hops = CONFIG.advisory.deep_derivation_hops
    for element, depth in sorted(analysis.depth.items()):
        if depth < hops:
            continue
        found.append(Observation(
            4, "deep-derivation", element,
            f"{depth} hops from a reason anyone stated. Each link is valid "
            "(G14 passes); the chain is still a long way from anything a "
            "stakeholder, a standard or an incumbent system would recognise.",
            "guessing", "archtrace"))

    # Tier 5 -- how much of the requirement set rests on one recording.
    # Deliberately NOT one observation per singly-sourced requirement. Most
    # requirements are said once, so that version fires on nearly everything
    # and buries the four tiers above it in identical rows; the agent
    # definition's "do not pad" applies to this document too. Concentration is
    # the same instrument as ADR load and says the thing worth knowing.
    found.extend(_evidence_concentration(eng))

    LOG.debug("deterministic worklist: %d observation(s)", len(found))
    return sorted(found, key=lambda o: o.sort_key)


# A heading, a rule, or a list bullet at the start of an untrusted line can
# forge structure in the rendered document -- "## Approved" reads as a section
# this tool wrote. The agent definitions already require that evidence be
# treated as data rather than instruction; this applies the same rule to the
# one place evidence-derived text is copied into an artifact a human skims.
_MARKDOWN_LEAD = re.compile(r"^\s*(#{1,6}\s|[-*+]\s|>\s|\d+\.\s|-{3,}|={3,})")


def _neutralise(text: str) -> str:
    """Flatten untrusted text to one line that cannot forge document structure."""
    flat = " ".join(str(text).split())
    return _MARKDOWN_LEAD.sub("", flat).strip() or "(empty)"


def load_findings(path: str) -> list:
    """Read an external reviewer's output, refusing anything unrecognised.

    Every rejection here is a refusal rather than a degradation, and each one
    names the thing it could not accept. The alternative -- dropping a finding
    whose `kind` is unknown -- would make a reviewer that misspells a category
    silently less useful than one that produces nothing, which is the worst
    possible failure mode for a component nobody is watching.
    """
    try:
        with open(path, "rb") as handle:
            document = json.load(handle)
    except OSError as exc:
        raise FindingsError(f"cannot read {path}: {exc}") from exc
    except ValueError as exc:
        raise FindingsError(f"{path} is not valid JSON: {exc}") from exc
    if not isinstance(document, dict):
        raise FindingsError(
            f"{path} is a {type(document).__name__}, not an object")
    version = document.get("schema_version")
    if version not in FINDINGS_SCHEMA_VERSIONS:
        raise FindingsError(
            f"{path} declares schema_version {version!r} "
            f"(known: {sorted(FINDINGS_SCHEMA_VERSIONS)}). Refusing to guess.")
    producer = _neutralise(document.get("produced_by") or "an unnamed reviewer")
    entries = document.get("findings")
    if not isinstance(entries, list):
        raise FindingsError(f"{path} has no `findings` list")

    out: list = []
    for index, entry in enumerate(entries):
        spot = f"{path} findings[{index}]"
        if not isinstance(entry, dict):
            raise FindingsError(f"{spot} is not an object")
        kind = entry.get("kind")
        if kind not in FINDING_KINDS:
            raise FindingsError(
                f"{spot} has kind {kind!r} "
                f"(known: {sorted(FINDING_KINDS)}). Refusing to guess.")
        confidence = entry.get("confidence")
        if confidence not in CONFIDENCE:
            raise FindingsError(
                f"{spot} has confidence {confidence!r} "
                f"(expected one of {list(CONFIDENCE)})")
        where, detail = entry.get("where"), entry.get("detail")
        if not where or not detail:
            raise FindingsError(f"{spot} needs both `where` and `detail`")
        # Tier 0: an external reviewer is looking at the semantic gap, which is
        # the thing no deterministic observation here can reach. It reads
        # first, and it is labelled every time so nobody mistakes it for one
        # of ours.
        out.append(Observation(0, kind, _neutralise(where),
                               _neutralise(detail), confidence, producer))
    LOG.debug("loaded %d external finding(s) from %s", len(out), path)
    return sorted(out, key=lambda o: o.sort_key)


def render(eng: Engagement, observations: list) -> str:
    """The advisory document. Deterministic, and it says what it is not."""
    fingerprint = canon.sha256_text(canon.canonical_json(eng.model))[:12]
    name = eng.model.get("workspace", {}).get("name", "")
    lines = [
        "# Advisory review",
        "",
        ("**This document never gates.** `archtrace review` exits 0 whatever "
         "it finds, and nothing here has been checked against a human "
         "baseline on this corpus. It is a reading order for a person, not a "
         "verdict."),
        "",
        ("The deterministic gate has already run and said its piece; "
         "everything below is the part `archtrace check` cannot express as a "
         "pass or a fail. Correctness is still yours."),
        "",
        f"- engagement: {name or '(unnamed)'}",
        f"- model fingerprint: `{fingerprint}`",
        f"- observations: {len(observations)}",
        "",
        ("No timestamp, deliberately: this file is regenerated, and a clock "
         "in a generated artifact is the drift defect "
         "`docs/archmine-integration.md` §2 found in someone else's gate. The "
         "fingerprint above tells you whether it still describes the model in "
         "your tree."),
        "",
    ]
    if not observations:
        lines += ["## Nothing to report", "",
                  ("No near-floor citations, no assumption-tainted elements, "
                   "no concentrated decisions, and no external findings were "
                   "supplied. That is a statement about this model, not a "
                   "clean bill of health: the support gap in SPEC §7.1 is "
                   "closed by a human reading quotes against requirements, "
                   "and nothing here did that."), ""]
        return "\n".join(lines)

    external = [o for o in observations if o.tier == 0]
    if external:
        lines += [
            "## From an external reviewer",
            "",
            ("Produced outside archtrace and validated for shape only. "
             "archtrace did not run this, cannot reproduce it, and takes no "
             "position on whether it is right."),
            "",
        ]
        lines += _table(external, source=True)
        lines.append("")

    ours = [o for o in observations if o.tier > 0]
    if ours:
        lines += [
            "## From the model itself",
            "",
            ("Computed deterministically from `model.json` and the evidence "
             "manifest, in reading order -- most likely to not mean what it "
             "claims, first."),
            "",
        ]
        lines += _table(ours, source=False)
        lines.append("")

    lines += [
        "## What this does not cover",
        "",
        ("The support gap. Whether a real, substantial, correctly-attributed "
         "quote actually supports the requirement drawn from it is not "
         "decidable here, and SPEC §7.1 says so at length. Supply "
         "`--findings` from a reviewer that reads text, or read them "
         "yourself. Promotion from `proposed` to `confirmed` stays a human "
         "commit either way."),
        "",
    ]
    return "\n".join(lines)


def _table(observations: list, source: bool) -> list:
    header = ["| where | kind | confidence | observation |",
              "|---|---|---|---|"]
    if source:
        header = ["| where | kind | confidence | by | observation |",
                  "|---|---|---|---|---|"]
    rows = []
    for obs in observations:
        # Pipes inside a cell end the cell. An external `detail` is untrusted
        # text and `where` may be an arbitrary string, so neither can be
        # interpolated raw into a markdown table.
        cells = [f"`{obs.where.replace('|', '/')}`", obs.kind, obs.confidence]
        if source:
            cells.append(obs.source.replace("|", "/"))
        cells.append(obs.detail.replace("|", "/"))
        rows.append("| " + " | ".join(cells) + " |")
    return header + rows


def write(eng: Engagement, text: str) -> str:
    """Write the advisory under the engagement root, returning its path."""
    directory = os.path.join(eng.root, ADVISORY_DIR)
    os.makedirs(directory, exist_ok=True)
    path = os.path.join(directory, ADVISORY_FILE)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(text)
    return path
