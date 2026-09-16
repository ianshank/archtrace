"""Deterministic build outputs and canonical formatting."""

from __future__ import annotations

import os

from .. import canon
from ..log import get_logger
from ..renders import render_all
from ._shared import EXIT_OK
from ._shared import engagement as _engagement

LOG = get_logger("build")

def cmd_render(args) -> int:
    eng = _engagement(args)
    out_dir = os.path.join(args.root, "render")
    os.makedirs(out_dir, exist_ok=True)
    outputs = render_all(eng)
    for name, data in sorted(outputs.items()):
        with open(os.path.join(out_dir, name), "wb") as fh:
            fh.write(data)
        if not getattr(args, "quiet", False):
            print(f"wrote render/{name} ({len(data)} b)")
    return EXIT_OK

def cmd_fmt(args) -> int:
    eng = _engagement(args)
    # Refresh derived fields before canonicalising: quote_cached is derived data
    # populated from the span, never authored by hand.
    refreshed = 0
    for req in eng.requirements:
        for prov in req.get("provenance", []):
            text = eng.evidence_text(prov.get("evidence_id", ""))
            if text is None:
                continue
            start, end = prov.get("start"), prov.get("end")
            if isinstance(start, int) and isinstance(end, int) \
                    and 0 <= start < end <= len(text):
                if prov.get("quote_cached") != text[start:end]:
                    refreshed += 1
                prov["quote_cached"] = text[start:end]
    writes = {
        os.path.join(args.root, "evidence", "index.json"):
            eng.evidence_index,
        os.path.join(args.root, "requirements", "requirements.json"):
            eng.requirements_doc,
        os.path.join(args.root, "model", "model.json"):
            eng.model,
    }
    for path, doc in writes.items():
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(canon.canonical_json(doc))
        print(f"formatted {os.path.relpath(path, args.root)}")
    print(f"refreshed {refreshed} cached quote(s) from their spans")
    return EXIT_OK
