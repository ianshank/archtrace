"""Canonicalisation primitives.

Everything in archtrace that must be deterministic goes through this module:
text normalisation (so citation integrity survives real transcripts), canonical
JSON serialisation (so diffs are stable and readable), and canonical comparison
of generated artifacts (so the render-freshness gate reports toolchain drift as
toolchain drift rather than as an architecture defect).

Standard library only.
"""

from __future__ import annotations

import hashlib
import io
import json
import re
import unicodedata
import xml.etree.ElementTree as ET
import zipfile
from collections.abc import Iterable, Mapping
from typing import Any

# --- text normalisation ----------------------------------------------------

# Every Teams/Word/SharePoint export contains these and every LLM emits the
# ASCII form, so without folding them the citation gate blocks nearly every
# requirement.
#
# Eleven of the thirteen are invisible to NFKC -- the quotes and dashes, which
# is the whole reason `test_nfkc_alone_is_insufficient` exists. The last two are
# NOT: NFKC already folds the ellipsis to three dots and NBSP to a space. This
# comment used to claim NFKC folded none of them, which was simply false, and a
# comment nobody can trust is worse than no comment. They are kept rather than
# removed so the table stands on its own: deleting them would make the result
# depend on NFKC having run first, which is a coupling not worth introducing to
# save two dict entries.
PUNCTUATION_FOLD = {
    # ORDER MATTERS. NFKC runs first and decomposes ″ (DOUBLE PRIME) into two
    # PRIME characters, so by the time this table is applied there is no ″ left
    # to match -- the entry for it was unreachable, and `6″` normalised to `6''`
    # while `6"` normalised to `6"`, which is exactly the citation mismatch this
    # table exists to prevent. The two-character sequence is folded BEFORE the
    # single PRIME, or the single rule would consume both halves first.
    "′′": '"',
    "‘": "'", "’": "'", "‛": "'", "′": "'",
    "“": '"', "”": '"', "‟": '"',
    "–": "-", "—": "-", "−": "-",
    "…": "...",
    " ": " ",
}

# NFKC does not remove these either.
ZERO_WIDTH = re.compile("[\u200b‌‍⁠﻿]")
WHITESPACE = re.compile(r"\s+")


def normalize(text: str) -> str:
    """Canonical text form. Applied at evidence intake; the hash is taken of the
    result, so the gate and the stored evidence agree by construction."""
    text = unicodedata.normalize("NFKC", text)
    for src, dst in PUNCTUATION_FOLD.items():
        text = text.replace(src, dst)
    text = ZERO_WIDTH.sub("", text)
    text = WHITESPACE.sub(" ", text)
    return text.strip().casefold()


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def stable_uid(prefix: str, *parts: str) -> str:
    """Deterministic identity for a newly created object. Generated once and
    never re-derived from a renameable field."""
    digest = hashlib.sha256("\x1f".join(parts).encode("utf-8")).hexdigest()
    return f"{prefix}_{digest[:12]}"


# --- canonical JSON --------------------------------------------------------

# Explicit key order per object type rather than a global sort_keys, which would
# alphabetise requirement fields into an unreadable order while still producing
# stable diffs. This gets both properties.
KEY_ORDER: Mapping[str, tuple] = {
    "evidence": ("id", "source", "content_kind", "authority",
                 "commit", "facts_schema_version", "document_owner",
                 "effective_date", "document_version",
                 "source_uri", "local_path", "date",
                 "participants", "classification", "retention_until",
                 "sha256_normalized"),
    "requirement": ("id", "uid", "statement", "type", "nfr_categories",
                    "priority", "status",
                    "supersedes", "superseded_by", "conflicts_with",
                    "provenance"),
    "provenance": ("evidence_id", "speaker", "start", "end", "quote_cached"),
    "grounding": ("kind", "req", "from", "adr", "standard", "evidence_id",
                  "symbol", "open_question", "note"),
    "element": ("id", "uid", "name", "technology", "description", "external",
                "layout", "grounding", "containers", "components"),
    "relationship": ("source", "destination", "description", "technology",
                     "grounding"),
    "decision": ("id", "title", "status", "drivers", "decision",
                 "consequences"),
    "nfr_coverage": ("category", "status", "open_question", "rationale",
                     "decided_by", "date"),
}


def _order(obj: Any, kind: str | None) -> Any:
    if isinstance(obj, dict):
        order = KEY_ORDER.get(kind or "", ())
        keys = [k for k in order if k in obj] + sorted(
            k for k in obj if k not in order)
        return {k: _order(obj[k], _child_kind(kind, k)) for k in keys}
    if isinstance(obj, list):
        return [_order(v, kind) for v in obj]
    return obj


_CHILD = {
    ("requirement", "provenance"): "provenance",
    ("element", "grounding"): "grounding",
    ("element", "containers"): "element",
    ("element", "components"): "element",
    ("relationship", "grounding"): "grounding",
}


def _child_kind(parent: str | None, key: str) -> str | None:
    return _CHILD.get((parent or "", key))


ROOT_KINDS = {
    "evidence": "evidence",
    "requirements": "requirement",
    "proposed": "requirement",
    "people": "element",
    "systems": "element",
    "relationships": "relationship",
    "decisions": "decision",
    "nfr_coverage": "nfr_coverage",
    "provenance": "provenance",
}


def canonical_json(doc: Mapping[str, Any]) -> str:
    out = {}
    for key in sorted(doc, key=lambda k: (k != "schema_version", k)):
        out[key] = _order(doc[key], ROOT_KINDS.get(key))
    return json.dumps(out, indent=2, ensure_ascii=False) + "\n"


def load_json(path: Any) -> dict[str, Any]:
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


# --- canonical comparison of generated artifacts ---------------------------

def canonical_bytes(name: str, data: bytes) -> bytes:
    """Comparison form for a generated file.

    XML is C14N-canonicalised so that attribute ordering and insignificant
    whitespace cannot fail the render-freshness gate. A .docx is unzipped and
    each part canonicalised, which removes zip entry timestamps and any
    compression-level difference between a laptop and a CI runner.
    """
    lower = name.lower()
    if lower.endswith(".docx"):
        parts = []
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            for entry in sorted(zf.namelist()):
                parts.append(entry.encode("utf-8"))
                parts.append(canonical_bytes(entry, zf.read(entry)))
        return b"\x00".join(parts)
    if lower.endswith((".xml", ".drawio", ".svg")):
        try:
            root = ET.fromstring(data.decode("utf-8"))  # noqa: S314
        except ET.ParseError:
            return data
        # Conventional but non-deterministic; excluded rather than emitted.
        root.attrib.pop("modified", None)
        return ET.canonicalize(
            ET.tostring(root, encoding="unicode"),
            strip_text=True).encode("utf-8")
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return data
    return "\n".join(line.rstrip() for line in text.splitlines()).encode("utf-8")


def deterministic_zip(parts: Iterable[tuple[str, bytes]]) -> bytes:
    """Byte-stable zip container.

    ZIP_STORED rather than ZIP_DEFLATED: zlib output is not guaranteed stable
    across builds, so a compressed .docx can differ between a laptop and
    ubuntu-latest for reasons nobody can diagnose. These documents are a few KB
    of XML; compression buys nothing and costs determinism.
    """
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_STORED) as zf:
        for name, data in parts:
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            # Set on the ZipInfo, not only on the ZipFile. `writestr` with a
            # ZipInfo reads compression from the INFO and ignores the archive
            # default, so the constructor argument above -- which reads like the
            # thing enforcing this -- enforces nothing here. It held only
            # because a fresh ZipInfo happens to default to ZIP_STORED, which
            # nothing stated and no test could have caught.
            info.compress_type = zipfile.ZIP_STORED
            info.external_attr = 0o600 << 16
            info.create_system = 0
            zf.writestr(info, data)
    return buf.getvalue()
