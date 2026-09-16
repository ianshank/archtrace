"""Optional code-mining evidence adapter. Standard library only.

**The seam is a file, not a library import.** archtrace never imports archmine,
networkx, pydantic or tree-sitter. It reads the `architecture-facts.json` that
archmine — or anything else emitting the same shape — produces. Three
consequences, all deliberate:

1. The zero-dependency invariant survives. `archtrace check` runs on a bare CI
   runner with no setup step whether or not a miner is installed.
2. The miner is swappable. Replace archmine with a compiler-grade extractor and
   nothing downstream changes as long as the file shape holds.
3. Mining can run on a different machine, at a different time, under a different
   Python. Only the artifact crosses.

Code facts are `observed-implementation` authority. They are evidence of what
exists, never of what is required (SPEC §4, G11), so they ground *elements* via
the `existing` and `derived` kinds and can never carry a requirement.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any

# Shapes this adapter understands. An unknown version is refused rather than
# guessed, for the same reason the gate refuses an unknown schema_version.
SUPPORTED_FACTS_VERSIONS = frozenset({"1.0.0"})

# Evidence whose content is prose gets normalised and cited by byte span.
# Evidence whose content is structured gets hashed raw and cited by symbol id:
# casefolding a symbol table would destroy the identifiers it exists to carry.
CONTENT_PROSE = "prose"
CONTENT_STRUCTURED = "structured"
CONTENT_KINDS = frozenset({CONTENT_PROSE, CONTENT_STRUCTURED})


class FactsError(ValueError):
    """The facts file is not a shape this adapter can vouch for."""


@dataclass(frozen=True)
class CodeFacts:
    """A normalised view of one mining run."""

    schema_version: str
    root: str
    commit: str | None
    symbols: dict[str, dict] = field(default_factory=dict)
    relations: list[dict] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def symbol(self, symbol_id: str) -> dict | None:
        return self.symbols.get(symbol_id)

    def locator(self, symbol_id: str) -> str:
        """Human-readable source location, for the traceability render."""
        symbol = self.symbols.get(symbol_id)
        if symbol is None:
            return symbol_id
        return (f"{symbol.get('path', '?')}:{symbol.get('start_line', '?')}"
                f" ({symbol.get('kind', '?')} {symbol.get('name', '?')})")


def parse_facts(data: bytes | str) -> CodeFacts:
    """Validate and normalise a facts document.

    Deliberately tolerant about extra keys and strict about the ones that carry
    meaning: a miner is allowed to grow fields, but it may not omit the ones the
    gate reasons over.
    """
    if isinstance(data, bytes):
        try:
            data = data.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise FactsError(f"facts file is not UTF-8: {exc}") from exc
    try:
        raw: Any = json.loads(data)
    except json.JSONDecodeError as exc:
        raise FactsError(f"facts file is not valid JSON: {exc}") from exc
    if not isinstance(raw, dict):
        raise FactsError("facts file must be a JSON object")

    version = raw.get("schema_version")
    if version not in SUPPORTED_FACTS_VERSIONS:
        raise FactsError(
            f"facts schema_version {version!r} is not supported "
            f"(known: {sorted(SUPPORTED_FACTS_VERSIONS)}). Refusing to guess.")

    symbols: dict[str, dict] = {}
    for entry in raw.get("symbols", []):
        if not isinstance(entry, dict) or "id" not in entry:
            raise FactsError("every symbol needs an 'id'")
        symbols[entry["id"]] = entry

    relations = [r for r in raw.get("relations", []) if isinstance(r, dict)]
    warnings = [str(w) for w in raw.get("warnings", [])]

    return CodeFacts(
        schema_version=str(version),
        root=str(raw.get("root", "")),
        commit=raw.get("commit") or None,
        symbols=symbols,
        relations=relations,
        warnings=warnings,
    )


def sha256_bytes(data: bytes) -> str:
    """Hash structured evidence exactly as it sits on disk.

    Prose evidence is hashed after normalisation so that a re-export with
    different line wrapping still verifies. Structured evidence gets no such
    tolerance: a facts file that changed by one byte describes a different
    codebase, and that is precisely what we want the gate to notice.
    """
    return hashlib.sha256(data).hexdigest()


def summarise(facts: CodeFacts) -> dict:
    """Counts for the report, not for the gate."""
    kinds: dict[str, int] = {}
    languages: dict[str, int] = {}
    for symbol in facts.symbols.values():
        kind = symbol.get("kind", "?")
        kinds[kind] = kinds.get(kind, 0) + 1
        if kind == "file":
            language = symbol.get("language", "?")
            languages[language] = languages.get(language, 0) + 1
    confidence: dict[str, int] = {}
    for relation in facts.relations:
        tier = relation.get("confidence", "?")
        confidence[tier] = confidence.get(tier, 0) + 1
    return {
        "symbols": len(facts.symbols),
        "relations": len(facts.relations),
        "by_kind": kinds,
        "by_language": languages,
        "relation_confidence": confidence,
        "warnings": len(facts.warnings),
    }
