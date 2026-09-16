"""Deterministic gates. No network, no LLM, no clock.

Every rule here is blocking or warning by declaration, and `archtrace check`
exits non-zero if any blocking rule fires. LLM judgement never reaches this
module; advisory output lives in review/ and cannot affect the exit code.
"""

from __future__ import annotations

import json
import os
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from typing import Callable

from . import canon
from .config import DEFAULT as CONFIG
from .log import get_logger
from .mining import (
    CONTENT_KINDS,
    CONTENT_PROSE,
    CONTENT_STRUCTURED,
    FactsError,
    parse_facts,
    sha256_bytes,
)
from .model import (
    EVIDENCE_AUTHORITY,
    GROUNDING_KINDS,
    NFR_CATEGORIES,
    NFR_STATUSES,
    PRIORITIES,
    RENDER_MANIFEST,
    RENDERER_VERSION,
    REQUIREMENT_AUTHORITY,
    REQUIREMENT_STATUSES,
    REQUIREMENT_TYPES,
    SUPPORTED_SCHEMA_VERSIONS,
    Engagement,
)

LOG = get_logger("gate")

BLOCK = "block"
WARN = "warn"

# G2 thresholds live in config, not here. A citation-integrity check with no
# floor is trivially gamed by quoting short high-frequency fragments; the floor
# raises the cost of that strategy without pretending to eliminate it (SPEC
# §7.1). Where the line sits is a judgement an organisation should be able to
# argue about in a config file rather than a patch to the gate.
MIN_QUOTE_WORDS = CONFIG.citation.min_quote_words
MIN_QUOTE_CHARS = CONFIG.citation.min_quote_chars
GENERIC_PHRASES = frozenset(CONFIG.citation.generic_phrases)


@dataclass(frozen=True)
class Finding:
    rule: str
    severity: str
    where: str
    message: str

    def __str__(self) -> str:
        mark = "BLOCK" if self.severity == BLOCK else " WARN"
        return f"{mark} {self.rule}  {self.where}\n        {self.message}"


Rule = Callable[[Engagement], Iterator[Finding]]
RULES: list[tuple[str, str, Rule]] = []


def rule(rid: str, severity: str):
    def wrap(fn: Rule) -> Rule:
        RULES.append((rid, severity, fn))
        return fn
    return wrap


# --- G10 schema ------------------------------------------------------------

@rule("G10", BLOCK)
def g10_schema_version(eng: Engagement) -> Iterator[Finding]:
    for label, doc in (("evidence/index.json", eng.evidence_index),
                       ("requirements/requirements.json", eng.requirements_doc),
                       ("model/model.json", eng.model)):
        version = doc.get("schema_version")
        if version not in SUPPORTED_SCHEMA_VERSIONS:
            yield Finding("G10", BLOCK, label,
                          f"schema_version {version!r} is not supported "
                          f"(known: {sorted(SUPPORTED_SCHEMA_VERSIONS)}). "
                          "Refusing to guess.")


# --- G1 evidence integrity -------------------------------------------------

@rule("G1", BLOCK)
def g1_evidence_integrity(eng: Engagement) -> Iterator[Finding]:
    seen = set()
    for rec in eng.evidence:
        if rec["id"] in seen:
            yield Finding("G1", BLOCK, rec["id"], "duplicate evidence id")
        seen.add(rec["id"])
        for required in ("source_uri", "local_path", "sha256_normalized",
                         "participants", "retention_until", "classification"):
            if not rec.get(required):
                yield Finding("G1", BLOCK, rec["id"],
                              f"evidence record is missing {required!r}")
        kind = rec.get("content_kind", CONTENT_PROSE)
        if kind not in CONTENT_KINDS:
            yield Finding("G1", BLOCK, rec["id"],
                          f"unknown content_kind {kind!r} "
                          f"(expected one of {sorted(CONTENT_KINDS)})")
            continue
        raw = eng.evidence_bytes(rec["id"])
        if raw is None:
            yield Finding("G1", BLOCK, rec["id"],
                          "evidence content not present under --evidence-root; "
                          "citation integrity cannot be verified")
            continue
        if kind == CONTENT_PROSE:
            # Prose is hashed AFTER normalisation, so a re-export with different
            # line wrapping still verifies.
            actual = canon.sha256_text(
                canon.normalize(raw.decode("utf-8", errors="replace")))
        else:
            # Structured evidence gets no such tolerance: a facts file that
            # changed by one byte describes a different codebase, and that is
            # exactly what the gate should notice.
            actual = sha256_bytes(raw)
        if actual != rec["sha256_normalized"]:
            yield Finding("G1", BLOCK, rec["id"],
                          "content hash changed "
                          f"({rec['sha256_normalized'][:12]} -> {actual[:12]}); "
                          "everything citing it must be re-confirmed")
        if kind == CONTENT_STRUCTURED:
            try:
                facts = parse_facts(raw)
            except FactsError as exc:
                yield Finding("G1", BLOCK, rec["id"], str(exc))
                continue
            if not rec.get("commit") and not facts.commit:
                yield Finding("G1", BLOCK, rec["id"],
                              "code-mining evidence with no commit. A fact about "
                              "a codebase that does not say WHICH codebase state "
                              "cannot be re-verified, so it is not evidence")


# --- G2 citation integrity -------------------------------------------------

@rule("G2", BLOCK)
def g2_citation_integrity(eng: Engagement) -> Iterator[Finding]:
    for req in eng.confirmed_requirements:
        provenance = req.get("provenance", [])
        if not provenance:
            yield Finding("G2", BLOCK, req["id"],
                          "confirmed requirement has no provenance")
            continue
        for idx, prov in enumerate(provenance):
            where = f"{req['id']}.provenance[{idx}]"
            rec = eng.evidence_by_id(prov.get("evidence_id", ""))
            if rec is None:
                yield Finding("G2", BLOCK, where,
                              f"unknown evidence_id {prov.get('evidence_id')!r}")
                continue
            if rec.get("content_kind", CONTENT_PROSE) == CONTENT_STRUCTURED:
                yield Finding("G2", BLOCK, where,
                              f"{rec['id']} is structured evidence and has no "
                              "byte spans to quote. Code facts ground an ELEMENT "
                              "via `existing`/`derived` grounding with a symbol "
                              "id; they never carry a requirement")
                continue
            speaker = prov.get("speaker")
            if speaker not in rec.get("participants", []):
                yield Finding("G2", BLOCK, where,
                              f"speaker {speaker!r} is not a participant of "
                              f"{rec['id']}; a quote attributed to someone who "
                              "was not in the room is not evidence")
            text = eng.evidence_text(rec["id"])
            if text is None:
                continue
            start, end = prov.get("start"), prov.get("end")
            if not isinstance(start, int) or not isinstance(end, int):
                yield Finding("G2", BLOCK, where,
                              "provenance span must be integer byte offsets")
                continue
            if not (0 <= start < end <= len(text)):
                yield Finding("G2", BLOCK, where,
                              f"span [{start}:{end}] out of bounds for "
                              f"{rec['id']} (length {len(text)})")
                continue
            actual = text[start:end]
            cached = prov.get("quote_cached", "")
            if actual != cached:
                yield Finding("G2", BLOCK, where,
                              "quote_cached does not match the span; run "
                              "`archtrace fmt` rather than editing it by hand\n"
                              f"        span says: {actual!r}\n"
                              f"        cache says: {cached!r}")
                continue
            words = actual.split()
            if len(words) < MIN_QUOTE_WORDS or len(actual) < MIN_QUOTE_CHARS:
                yield Finding("G2", BLOCK, where,
                              f"quote is {len(words)} words / {len(actual)} chars; "
                              f"minimum is {MIN_QUOTE_WORDS} / {MIN_QUOTE_CHARS}. "
                              "Short fragments pass a substring check without "
                              "supporting anything")
            if actual.strip() in GENERIC_PHRASES:
                yield Finding("G2", BLOCK, where,
                              "quote is a generic conversational phrase")


# --- G3 requirement coverage ----------------------------------------------

@rule("G3", BLOCK)
def g3_requirement_coverage(eng: Engagement) -> Iterator[Finding]:
    grounded = eng.requirements_grounded()
    excluded = {o["req"] for o in eng.out_of_scope}
    for entry in eng.out_of_scope:
        for required in ("rationale", "decided_by", "date"):
            if not entry.get(required):
                yield Finding("G3", BLOCK, entry.get("req", "out_of_scope"),
                              f"out-of-scope entry is missing {required!r}; "
                              "a requirement is not dropped, it is declined by "
                              "someone on a date for a reason")
    for req in eng.requirements:
        status = req.get("status")
        if status not in REQUIREMENT_STATUSES:
            yield Finding("G3", BLOCK, req["id"], f"unknown status {status!r}")
        if req.get("type") not in REQUIREMENT_TYPES:
            yield Finding("G3", BLOCK, req["id"],
                          f"unknown type {req.get('type')!r}")
        if req.get("priority") not in PRIORITIES:
            yield Finding("G3", BLOCK, req["id"],
                          f"unknown priority {req.get('priority')!r}")
        if status == "superseded" and not req.get("superseded_by"):
            yield Finding("G3", BLOCK, req["id"],
                          "superseded requirement must name its successor")
        if status == "superseded" and req.get("superseded_by") and \
                eng.requirement_by_id(req["superseded_by"]) is None:
            yield Finding("G3", BLOCK, req["id"],
                          f"superseded_by {req['superseded_by']!r} does not exist")
        if status != "confirmed":
            continue
        if req["id"] not in grounded and req["id"] not in excluded:
            yield Finding("G3", BLOCK, req["id"],
                          "confirmed requirement is neither grounded by any "
                          "model element nor explicitly out of scope")


# --- G4 element grounding --------------------------------------------------

def _check_grounding(eng: Engagement, where: str, grounding: list) -> Iterator[Finding]:
    if not grounding:
        yield Finding("G4", BLOCK, where,
                      "no grounding. Every element needs a stated reason to "
                      "exist, but that reason need not be a requirement: use "
                      f"one of {sorted(GROUNDING_KINDS)}")
        return
    confirmed = {r["id"] for r in eng.confirmed_requirements}
    for idx, entry in enumerate(grounding):
        spot = f"{where}.grounding[{idx}]"
        kind = entry.get("kind")
        if kind not in GROUNDING_KINDS:
            yield Finding("G4", BLOCK, spot, f"unknown grounding kind {kind!r}")
            continue
        field_name, domain = GROUNDING_KINDS[kind]
        ref = entry.get(field_name)
        if not ref:
            yield Finding("G4", BLOCK, spot,
                          f"grounding kind {kind!r} requires {field_name!r}")
            continue
        if domain == "requirements" and ref not in confirmed:
            yield Finding("G4", BLOCK, spot,
                          f"{ref!r} is not a confirmed requirement")
        elif domain == "elements" and eng.element_by_id(ref) is None:
            yield Finding("G4", BLOCK, spot, f"derived from unknown element {ref!r}")
        elif domain == "standards" and ref not in {s["id"] for s in eng.standards}:
            yield Finding("G4", BLOCK, spot, f"unknown standard {ref!r}")
        elif domain == "evidence" and eng.evidence_by_id(ref) is None:
            yield Finding("G4", BLOCK, spot, f"unknown evidence record {ref!r}")
        elif domain == "open_questions" and \
                ref not in {q["id"] for q in eng.open_questions}:
            yield Finding("G4", BLOCK, spot, f"unknown open question {ref!r}")
        if kind == "derived" and not entry.get("adr"):
            yield Finding("G4", BLOCK, spot,
                          "a derived element must cite the ADR it follows from")
        if kind == "derived" and entry.get("adr") and \
                entry["adr"] not in {d["id"] for d in eng.decisions}:
            yield Finding("G4", BLOCK, spot, f"unknown ADR {entry['adr']!r}")


@rule("G4", BLOCK)
def g4_element_grounding(eng: Engagement) -> Iterator[Finding]:
    for element in eng.elements():
        yield from _check_grounding(eng, element.id, element.grounding)
    for rel in eng.relationships:
        where = f"{rel.get('source')}->{rel.get('destination')}"
        yield from _check_grounding(eng, where, rel.get("grounding", []))


# --- G5 C4 well-formedness -------------------------------------------------

@rule("G5", BLOCK)
def g5_wellformed(eng: Engagement) -> Iterator[Finding]:
    ids, uids = set(), set()
    for element in eng.elements():
        if element.id in ids:
            yield Finding("G5", BLOCK, element.id, "duplicate element id")
        ids.add(element.id)
        if not element.uid:
            yield Finding("G5", BLOCK, element.id,
                          "missing uid; Jira linkage breaks silently on rename "
                          "without an immutable identity")
        elif element.uid in uids:
            yield Finding("G5", BLOCK, element.id, "duplicate element uid")
        uids.add(element.uid)
        for axis in ("x", "y"):
            value = element.layout.get(axis)
            if not isinstance(value, int) or isinstance(value, bool):
                yield Finding("G5", BLOCK, element.id,
                              f"layout.{axis} must be an integer (got "
                              f"{value!r}); computed floats destabilise the "
                              "render-freshness gate")
    for rel in eng.relationships:
        for endpoint in ("source", "destination"):
            if rel.get(endpoint) not in ids:
                yield Finding("G5", BLOCK,
                              f"{rel.get('source')}->{rel.get('destination')}",
                              f"{endpoint} {rel.get(endpoint)!r} is not an element")


@rule("G5e", WARN)
def g5e_external_containers(eng: Engagement) -> Iterator[Finding]:
    for system in eng.model.get("systems", []):
        if system.get("external") and system.get("containers"):
            yield Finding("G5e", WARN, system["id"],
                          "external system declares containers; legitimate when "
                          "you integrate at that level, worth a second look "
                          "otherwise")


# --- G6 render freshness ---------------------------------------------------

def _committed_renderer(render_dir: str):
    """Which renderer wrote the artifacts sitting in render/, if it said.

    The manifest has recorded `renderer_version` all along; G6 just never read
    it, so a toolchain upgrade and a hand edit produced the same message and
    the operator was left to guess which had happened. Returns None when the
    manifest is absent or unreadable, which is itself reported by the ordinary
    byte comparison -- this is a diagnosis, never a gate of its own.
    """
    try:
        with open(os.path.join(render_dir, RENDER_MANIFEST),
                  encoding="utf-8") as handle:
            document = json.load(handle)
    except (OSError, ValueError) as exc:
        LOG.debug("no readable render manifest in %s: %s", render_dir, exc)
        return None
    # `null`, `[]` and `"text"` are all valid JSON and none of them has .get.
    # Catching only OSError/ValueError let those raise an AttributeError out of
    # a helper whose whole contract is that it degrades to None.
    if not isinstance(document, dict):
        LOG.debug("render manifest in %s is %s, not an object",
                  render_dir, type(document).__name__)
        return None
    recorded = document.get("renderer_version")
    return recorded if isinstance(recorded, str) else None


@rule("G6", BLOCK)
def g6_render_freshness(eng: Engagement) -> Iterator[Finding]:
    from .renders import render_all  # local import avoids a cycle

    render_dir = os.path.join(eng.root, "render")
    try:
        fresh = render_all(eng)
    except Exception as exc:  # a renderer crash is a finding, not a traceback
        yield Finding("G6", BLOCK, "render/",
                      f"renderer failed on this model: {type(exc).__name__}: {exc}")
        return
    written_by = _committed_renderer(render_dir)
    stale_toolchain = written_by is not None and written_by != RENDERER_VERSION
    if stale_toolchain:
        LOG.debug("render/ was written by renderer %s; this build is %s",
                  written_by, RENDERER_VERSION)
    for name, data in sorted(fresh.items()):
        path = os.path.join(render_dir, name)
        if not os.path.isfile(path):
            yield Finding("G6", BLOCK, f"render/{name}",
                          "render is missing; run `archtrace render`")
            continue
        with open(path, "rb") as fh:
            committed = fh.read()
        # Raw equality first: a == b implies canonical(a) == canonical(b), and
        # in the passing case -- which is every run on a healthy repository --
        # all twelve outputs are raw-identical. Canonicalising both sides
        # unconditionally meant parsing the SVG, drawio and docx XML twice per
        # output on every single check. Profiled at 91% of the gate's total
        # time; `make pre-pr` pays it three times over (check, freshness, gate)
        # and `make freshness` once per engagement.
        if committed == data:
            continue
        if canon.canonical_bytes(name, committed) != canon.canonical_bytes(name, data):
            if stale_toolchain:
                yield Finding(
                    "G6", BLOCK, f"render/{name}",
                    f"generated by renderer {written_by}, but this build is "
                    f"{RENDERER_VERSION}. This is toolchain drift, not "
                    "something you edited: run `archtrace render` and commit "
                    "the result.")
            elif written_by is None:
                # No manifest, or one that records no version. Which of those
                # two it is cannot be known from here, so naming either would
                # be a guess -- and guessing "the same renderer" points the
                # operator at the model when the renderer may well have moved.
                yield Finding(
                    "G6", BLOCK, f"render/{name}",
                    "committed render differs from a fresh regeneration, and "
                    f"render/{RENDER_MANIFEST} records no renderer version, so "
                    "a hand edit and toolchain drift cannot be told apart here. "
                    "Run `archtrace render`: if the diff disappears it was "
                    "drift, and if it persists the model and the artifact "
                    "disagree.")
            else:
                yield Finding(
                    "G6", BLOCK, f"render/{name}",
                    "committed render differs from a fresh regeneration, and "
                    f"the renderer that wrote it was {written_by} -- the same "
                    "one running now. Renders are build outputs: edit the "
                    "model, not the artifact.")
    for stray in sorted(os.listdir(render_dir)) if os.path.isdir(render_dir) else []:
        if stray not in fresh and not stray.startswith("."):
            yield Finding("G6", BLOCK, f"render/{stray}",
                          "file in render/ that the renderer does not produce")


# --- G7 ADR linkage --------------------------------------------------------

@rule("G7", BLOCK)
def g7_adr_linkage(eng: Engagement) -> Iterator[Finding]:
    confirmed = {r["id"] for r in eng.confirmed_requirements}
    for decision in eng.decisions:
        if not decision.get("drivers"):
            yield Finding("G7", BLOCK, decision["id"],
                          "ADR has no drivers; a decision with no driver is a "
                          "preference")
        for driver in decision.get("drivers", []):
            if driver not in confirmed:
                yield Finding("G7", BLOCK, decision["id"],
                              f"driver {driver!r} is not a confirmed requirement")


# --- G8 orphan evidence ----------------------------------------------------

@rule("G8", WARN)
def g8_orphan_evidence(eng: Engagement) -> Iterator[Finding]:
    cited = {p.get("evidence_id") for r in eng.requirements
             for p in r.get("provenance", [])}
    # Gate rules stay total over malformed input: a missing field is another
    # rule's finding to report, not a traceback that hides every other one.
    cited |= {g.get("evidence_id") for e in eng.elements() for g in e.grounding
              if g.get("kind") == "existing"}
    cited |= {g.get("evidence_id") for r in eng.relationships
              for g in r.get("grounding", []) if g.get("kind") == "existing"}
    cited |= {s.get("evidence_id") for s in eng.standards}
    cited.discard(None)
    for rec in eng.evidence:
        if rec["id"] not in cited:
            yield Finding("G8", WARN, rec["id"],
                          "evidence gathered but never cited")


# --- G9 unresolved conflicts ----------------------------------------------

@rule("G9", BLOCK)
def g9_conflicts(eng: Engagement) -> Iterator[Finding]:
    resolved = {d for decision in eng.decisions for d in decision.get("drivers", [])}
    for req in eng.confirmed_requirements:
        for other in req.get("conflicts_with", []):
            counterpart = eng.requirement_by_id(other)
            if counterpart is None:
                yield Finding("G9", BLOCK, req["id"],
                              f"conflicts_with unknown requirement {other!r}")
                continue
            if counterpart.get("status") != "confirmed":
                continue
            if not (req["id"] in resolved and other in resolved):
                yield Finding("G9", BLOCK, f"{req['id']}~{other}",
                              "two confirmed requirements declare a conflict "
                              "with no ADR resolving it; both quotes are "
                              "verbatim and the architecture cannot satisfy both")


# --- G11 authority ---------------------------------------------------------

@rule("G11", BLOCK)
def g11_requirement_authority(eng: Engagement) -> Iterator[Finding]:
    """A requirement may not rest solely on observed implementation.

    "The code already does this" is evidence of what is, not of what is
    required. Without this rule an architect's own reading of a repository
    becomes a stakeholder constraint, which is the commonest route by which an
    inference is promoted to a fact — and every other gate would certify it,
    because the citation is perfectly real.
    """
    for record in eng.evidence:
        if record.get("authority") not in EVIDENCE_AUTHORITY:
            yield Finding("G11", BLOCK, record["id"],
                          f"unknown authority {record.get('authority')!r} "
                          f"(expected one of {sorted(EVIDENCE_AUTHORITY)})")
        # A document carries authority only as a specific version owned by
        # someone and in force on a date. "The security policy says so" is not
        # citable; "PLAT-STD-014 v3, C. Platform, effective 2026-04-01" is.
        if record.get("authority") == "authoritative-document":
            for required in ("document_owner", "effective_date"):
                if not record.get(required):
                    yield Finding("G11", BLOCK, record["id"],
                                  f"authoritative-document is missing "
                                  f"{required!r} — an unowned, undated document "
                                  "cannot settle a requirement")
    for req in eng.confirmed_requirements:
        tiers = eng.requirement_authorities(req)
        if not tiers or (tiers & REQUIREMENT_AUTHORITY):
            continue
        yield Finding("G11", BLOCK, req["id"],
                      f"confirmed requirement rests only on {sorted(tiers)}. "
                      "Observed implementation and third-party material are "
                      "evidence of what exists, not of what is required — "
                      "ground the element as `existing` instead, or get a "
                      "stakeholder to confirm it")


# --- G12 NFR coverage ------------------------------------------------------

@rule("G12", WARN)
def g12_nfr_silence(eng: Engagement) -> Iterator[Finding]:
    """Silence about an NFR category warns; it does not block.

    A nine-category hard block on day one is the kind of rule that gets the
    whole gate switched off, and an unconsidered category is a prompt for a
    conversation rather than proof of a defect.
    """
    coverage = eng.nfr_coverage
    declared = set(coverage)
    for req in eng.confirmed_requirements:
        declared |= set(req.get("nfr_categories", []))
    for category in NFR_CATEGORIES:
        if category in declared:
            continue
        yield Finding("G12", WARN, category,
                      "no confirmed NFR and no declared position; say it is "
                      "covered or say it does not apply, but do not leave it "
                      "silent")


@rule("G12n", BLOCK)
def g12n_nfr_not_applicable_needs_a_reason(eng: Engagement) -> Iterator[Finding]:
    """Declaring a category inapplicable is an assertion, and assertions have
    owners. Same shape as the out-of-scope rule: a requirement is not dropped,
    it is declined by someone on a date for a reason."""
    for category, entry in eng.nfr_coverage.items():
        if category not in NFR_CATEGORIES:
            yield Finding("G12n", BLOCK, category,
                          f"unknown NFR category (expected one of "
                          f"{list(NFR_CATEGORIES)})")
            continue
        status = entry.get("status")
        if status not in NFR_STATUSES:
            yield Finding("G12n", BLOCK, category,
                          f"status must be one of {sorted(NFR_STATUSES)}, "
                          f"got {status!r}")
            continue
        if status == "open":
            question = entry.get("open_question")
            if question not in {q["id"] for q in eng.open_questions}:
                yield Finding("G12n", BLOCK, category,
                              "an open NFR category must cite an open question "
                              f"that exists (got {question!r}); an untracked "
                              "gap is indistinguishable from an overlooked one")
            continue
        if status != "not_applicable":
            continue
        for required in ("rationale", "decided_by", "date"):
            if not entry.get(required):
                yield Finding("G12n", BLOCK, category,
                              f"'not_applicable' is an assertion, and it is "
                              f"missing {required!r}")


# --- G13 code-fact citation integrity --------------------------------------

@rule("G13", BLOCK)
def g13_symbol_citations(eng: Engagement) -> Iterator[Finding]:
    """A cited symbol must exist in the facts file it claims to come from.

    This is G2 for code evidence. Without it, "grounded in the repository" is an
    assertion rather than a claim anyone can check, and the mining step buys you
    nothing a hand-written note would not.
    """
    def check(where: str, grounding: list) -> Iterator[Finding]:
        for index, entry in enumerate(grounding):
            symbol = entry.get("symbol")
            if not symbol:
                continue
            spot = f"{where}.grounding[{index}]"
            if entry.get("kind") not in ("existing", "derived"):
                yield Finding("G13", BLOCK, spot,
                              f"a symbol citation is only meaningful on an "
                              f"`existing` or `derived` grounding, not "
                              f"{entry.get('kind')!r}")
                continue
            evidence_id = entry.get("evidence_id")
            if not evidence_id:
                yield Finding("G13", BLOCK, spot,
                              "a symbol citation must name the evidence_id of "
                              "the facts file it came from")
                continue
            record = eng.evidence_by_id(evidence_id)
            if record is None:
                yield Finding("G13", BLOCK, spot,
                              f"unknown evidence record {evidence_id!r}")
                continue
            if record.get("content_kind", CONTENT_PROSE) != CONTENT_STRUCTURED:
                yield Finding("G13", BLOCK, spot,
                              f"{evidence_id} is prose evidence; a symbol id "
                              "cannot resolve against it")
                continue
            facts = eng.evidence_facts(evidence_id)
            if facts is None:
                continue  # G1 already reported the unreadable facts file
            if facts.symbol(symbol) is None:
                yield Finding("G13", BLOCK, spot,
                              f"symbol {symbol!r} does not appear in "
                              f"{evidence_id}. Either the model cites a symbol "
                              "that was never mined, or the code moved and the "
                              "facts were not re-indexed")

    for element in eng.elements():
        yield from check(element.id, element.grounding)
    for rel in eng.relationships:
        yield from check(f"{rel.get('source')}->{rel.get('destination')}",
                         rel.get("grounding", []))


# --- runner ----------------------------------------------------------------

def run(eng: Engagement, strict: bool = False,
        only: Iterable[str] | None = None) -> tuple[list[Finding], int]:
    """Run the registered rules, optionally only the ones named in `only`.

    `only` takes rule ids from the registry rather than a hardcoded list, so
    selecting a subset needs no change here when a rule is added. It exists for
    callers that can answer one question but not another -- checking render
    freshness across engagements whose evidence content is not on this machine,
    where G1 and G2 legitimately cannot verify and would drown the answer.

    Selecting a subset never turns a blocking rule into a passing one: the
    findings a selected rule produces are graded exactly as they always were.
    """
    selected = None if only is None else set(only)
    if selected is not None:
        unknown = selected - {rid for rid, _s, _f in RULES}
        if unknown:
            raise ValueError(
                f"unknown rule id(s): {sorted(unknown)} "
                f"(known: {sorted({rid for rid, _s, _f in RULES})})")
    findings: list[Finding] = []
    for rid, _sev, fn in RULES:
        if selected is not None and rid not in selected:
            continue
        try:
            produced = list(fn(eng))
        except Exception as exc:
            # A rule crash is a finding, not a traceback. Several rules index
            # with `[]` where the document may legitimately be malformed --
            # `o["req"]` on an out_of_scope entry, `rec["id"]` on an evidence
            # record -- and the module docstring for those rules already claims
            # "a missing field is another rule's finding to report, not a
            # traceback". It was not true: removing one `req` key produced a
            # raw KeyError out of `archtrace check`, which loses every other
            # rule's findings along with it. G6 has wrapped its renderer call
            # this way since it was written; this extends the same treatment to
            # every rule, so one malformed field costs one finding rather than
            # the whole report.
            LOG.debug("rule %s crashed", rid, exc_info=True)
            produced = [Finding(rid, BLOCK, "<rule crashed>",
                                f"{type(exc).__name__}: {exc}. This is a defect "
                                "in the rule or a document shape it does not "
                                "handle; the other rules still ran.")]
        LOG.debug("rule %s produced %d finding(s)", rid, len(produced))
        findings.extend(produced)
    blocking = [f for f in findings
                if f.severity == BLOCK or (strict and f.severity == WARN)]
    return findings, (1 if blocking else 0)
