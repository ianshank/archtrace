"""Engagement loading and traversal.

An Engagement is the three source-of-truth documents plus the evidence root.
Evidence *content* lives outside the repository (see SPEC §0.4); the repository
holds only claims about it, so the content root is supplied at call time.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from dataclasses import dataclass, field

from . import canon

SCHEMA_VERSION = 1
SUPPORTED_SCHEMA_VERSIONS = frozenset({1})
RENDERER_VERSION = "1.3.0"
# The renderer stamps this file with the version that produced the artifacts
# beside it. Named here, next to the version it carries, so the gate can ask
# "which renderer wrote these?" without the renderer and the gate each
# spelling the filename their own way.
RENDER_MANIFEST = ".manifest.json"

REQUIREMENT_TYPES = frozenset({"functional", "nfr", "constraint", "assumption"})
REQUIREMENT_STATUSES = frozenset({"proposed", "confirmed", "superseded", "retired"})
PRIORITIES = frozenset({"must", "should", "could", "wont"})

# What kind of authority an evidence record carries. The distinction that
# matters: observed implementation is evidence of what *is*, never of what is
# *required*. Without this tier, "the code already does X" silently becomes a
# stakeholder constraint, which is the commonest way an inference is promoted
# to a fact.
EVIDENCE_AUTHORITY = frozenset({
    "stakeholder-confirmed",     # a person with standing said it
    "authoritative-document",    # SOW, contract, signed standard
    "observed-implementation",   # the code or infrastructure does this today
    "third-party",               # vendor claim, analyst note, someone else's deck
})
REQUIREMENT_AUTHORITY = frozenset({"stakeholder-confirmed", "authoritative-document"})

# Evidence comes in two shapes and they are cited differently. Prose is
# normalised and cited by byte span; structured evidence (a code-mining facts
# file) is hashed raw and cited by symbol id, because casefolding a symbol table
# would destroy the identifiers it exists to carry. Records with no
# `content_kind` are prose, which is what every record written before this
# existed already was.
EVIDENCE_SOURCES = frozenset({
    "teams-transcript", "email", "sharepoint", "interview", "document",
    "code-mining",
})

# Categories a solution architect is expected to have considered. Three honest
# positions, not two: covered, genuinely not applicable, or open and tracked.
# Collapsing "open" into "not_applicable" is how a gate turns an unknown into a
# false assurance. Silence about a category warns; a declared position does not.
NFR_STATUSES = frozenset({"covered", "not_applicable", "open"})
NFR_CATEGORIES = (
    "security", "privacy", "reliability", "performance", "observability",
    "accessibility", "cost", "data-retention", "operability",
)

# Each grounding kind names the field that must resolve, and where it resolves.
GROUNDING_KINDS = {
    "satisfies": ("req", "requirements"),
    "derived": ("from", "elements"),
    "standard": ("standard", "standards"),
    "existing": ("evidence_id", "evidence"),
    "assumption": ("open_question", "open_questions"),
}

LEVELS = ("person", "system", "container", "component")


@dataclass(frozen=True)
class Element:
    """A C4 element flattened out of the model's nesting."""
    level: str
    parent: str | None
    data: dict

    @property
    def id(self) -> str:
        return self.data["id"]

    @property
    def uid(self) -> str:
        return self.data.get("uid", "")

    @property
    def name(self) -> str:
        return self.data.get("name", self.id)

    @property
    def grounding(self) -> list:
        return self.data.get("grounding", [])

    @property
    def layout(self) -> dict:
        return self.data.get("layout", {})


@dataclass
class Engagement:
    root: str
    evidence_root: str
    evidence_index: dict = field(default_factory=dict)
    requirements_doc: dict = field(default_factory=dict)
    model: dict = field(default_factory=dict)

    # --- construction ------------------------------------------------------

    @classmethod
    def load(cls, root: str, evidence_root: str | None = None) -> Engagement:
        def read(*parts) -> dict:
            # Tolerant on purpose: bootstrapping an engagement means registering
            # evidence and resolving quotes before requirements or a model
            # exist. A missing document is reported by G10, not by a traceback.
            path = os.path.join(root, *parts)
            return canon.load_json(path) if os.path.isfile(path) else {}

        return cls(
            root=root,
            evidence_root=evidence_root or os.path.join(root, "_evidence_root"),
            evidence_index=read("evidence", "index.json"),
            requirements_doc=read("requirements", "requirements.json"),
            model=read("model", "model.json"),
        )

    # --- evidence ----------------------------------------------------------

    @property
    def evidence(self) -> list:
        return self.evidence_index.get("evidence", [])

    def evidence_by_id(self, eid: str) -> dict | None:
        return next((e for e in self.evidence if e["id"] == eid), None)

    def evidence_bytes(self, eid: str) -> bytes | None:
        """Raw content for an evidence record, read from the content root.

        Returns None when the content is not present locally, which is the
        normal state on a machine that has the repository but not the
        classified material.
        """
        rec = self.evidence_by_id(eid)
        if rec is None:
            return None
        path = os.path.join(self.evidence_root, rec["local_path"])
        if not os.path.isfile(path):
            return None
        with open(path, "rb") as fh:
            return fh.read()

    def content_kind(self, eid: str) -> str:
        from .mining import CONTENT_PROSE
        rec = self.evidence_by_id(eid) or {}
        return rec.get("content_kind", CONTENT_PROSE)

    def evidence_text(self, eid: str) -> str | None:
        """Normalised prose for an evidence record.

        Returns None for structured evidence: a facts file has no byte spans to
        cite, and normalising it would corrupt the symbol ids that are the point
        of citing it at all.
        """
        from .mining import CONTENT_PROSE
        if self.content_kind(eid) != CONTENT_PROSE:
            return None
        raw = self.evidence_bytes(eid)
        if raw is None:
            return None
        return canon.normalize(raw.decode("utf-8", errors="replace"))

    def evidence_facts(self, eid: str):
        """Parsed code facts for a structured evidence record, or None."""
        from .mining import CONTENT_STRUCTURED, FactsError, parse_facts
        if self.content_kind(eid) != CONTENT_STRUCTURED:
            return None
        raw = self.evidence_bytes(eid)
        if raw is None:
            return None
        try:
            return parse_facts(raw)
        except FactsError:
            return None

    # --- requirements ------------------------------------------------------

    @property
    def requirements(self) -> list:
        return self.requirements_doc.get("requirements", [])

    def requirement_by_id(self, rid: str) -> dict | None:
        return next((r for r in self.requirements if r["id"] == rid), None)

    @property
    def confirmed_requirements(self) -> list:
        return [r for r in self.requirements if r.get("status") == "confirmed"]

    # --- model -------------------------------------------------------------

    def elements(self) -> Iterator[Element]:
        for person in self.model.get("people", []):
            yield Element("person", None, person)
        for system in self.model.get("systems", []):
            yield Element("system", None, system)
            for container in system.get("containers", []):
                yield Element("container", system["id"], container)
                for component in container.get("components", []):
                    yield Element("component", container["id"], component)

    def element_by_id(self, eid: str) -> Element | None:
        return next((e for e in self.elements() if e.id == eid), None)

    @property
    def relationships(self) -> list:
        return self.model.get("relationships", [])

    @property
    def decisions(self) -> list:
        return self.model.get("decisions", [])

    @property
    def standards(self) -> list:
        return self.model.get("standards", [])

    @property
    def open_questions(self) -> list:
        return self.model.get("open_questions", [])

    @property
    def out_of_scope(self) -> list:
        return self.model.get("out_of_scope", [])

    @property
    def nfr_coverage(self) -> dict:
        """Declared position on each NFR category, keyed by category."""
        return {entry["category"]: entry
                for entry in self.model.get("nfr_coverage", [])}

    def requirement_authorities(self, req: dict) -> set:
        """Authority tiers behind a requirement's citations."""
        tiers = set()
        for prov in req.get("provenance", []):
            record = self.evidence_by_id(prov.get("evidence_id", ""))
            if record:
                tiers.add(record.get("authority"))
        return tiers

    # --- grounding ---------------------------------------------------------

    def grounding_mix(self) -> dict:
        """Distribution of grounding kinds across elements and relationships.

        This is the quality signal, not a pass/fail. A model that is 100%
        `satisfies` is the suspicious one: real architectures contain elements
        nobody asked for, and a gate that refuses to admit that teaches people
        to invent requirements.
        """
        mix: dict = {}
        total = 0
        carriers = [e.grounding for e in self.elements()]
        carriers += [r.get("grounding", []) for r in self.relationships]
        for grounding in carriers:
            for entry in grounding:
                mix[entry.get("kind", "?")] = mix.get(entry.get("kind", "?"), 0) + 1
                total += 1
        return {"total": total, "by_kind": mix}

    def requirements_grounded(self) -> set:
        """REQ ids referenced by at least one element or relationship."""
        found = set()
        carriers = [e.grounding for e in self.elements()]
        carriers += [r.get("grounding", []) for r in self.relationships]
        for grounding in carriers:
            for entry in grounding:
                if entry.get("kind") == "satisfies" and entry.get("req"):
                    found.add(entry["req"])
        return found
