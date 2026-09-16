"""The human gate: promoting a proposal to a confirmed requirement."""

from __future__ import annotations

import os
import sys
from typing import Any

from .. import canon
from ..log import get_logger
from ..model import (
    REQUIREMENT_AUTHORITY,
    SCHEMA_VERSION,
)
from ._shared import EXIT_OK, EXIT_USAGE
from ._shared import engagement as _engagement

LOG = get_logger("requirements")

def cmd_promote(args) -> int:
    """The human gate, made deliberate.

    Promotion from proposed to confirmed is the ONLY control that catches a
    plausible-but-wrong requirement carrying a real, substantial, correctly
    attributed quote. No deterministic rule reaches it. So this command shows
    you exactly what you are attesting to and does nothing until you say so.
    """
    proposed_path = os.path.join(args.root, "requirements", "proposed.json")
    confirmed_path = os.path.join(args.root, "requirements", "requirements.json")
    if not os.path.isfile(proposed_path):
        print(f"archtrace: no {proposed_path}", file=sys.stderr)
        return EXIT_USAGE
    proposed = canon.load_json(proposed_path)
    record = next((r for r in proposed.get("requirements", [])
                   if r["id"] == args.requirement_id), None)
    if record is None:
        print(f"archtrace: {args.requirement_id} is not in proposed.json",
              file=sys.stderr)
        return EXIT_USAGE

    eng = _engagement(args)
    print(f"{record['id']}  [{record.get('type')}/{record.get('priority')}]")
    print(f"  {record.get('statement', '')}\n")
    weak = True
    for prov in record.get("provenance", []):
        evidence = eng.evidence_by_id(prov.get("evidence_id", "")) or {}
        authority = evidence.get("authority", "UNKNOWN")
        if authority in REQUIREMENT_AUTHORITY:
            weak = False
        text = eng.evidence_text(prov.get("evidence_id", ""))
        start, end = prov.get("start"), prov.get("end")
        if text is not None and isinstance(start, int) and isinstance(end, int) \
                and 0 <= start < end <= len(text):
            # Read the span from the evidence, never the cached string: the
            # cache is what you would be trusting, and the point is not to.
            prov["quote_cached"] = text[start:end]
        print(f"  {prov.get('evidence_id')} [{authority}] "
              f"{prov.get('speaker', '?')}:")
        print(f'    "{prov.get("quote_cached", "")}"')
    if weak:
        print("\n  WARNING: no stakeholder-confirmed or authoritative-document "
              "citation. Observed implementation is evidence of what exists, "
              "not of what is required (G11 will block this).")
    print("\nConfirming this asserts that the quote above SUPPORTS the "
          "statement above.\nNo gate can check that; it is the one judgement "
          "that is only yours.")
    if not args.yes:
        print(f"\nDry run. Re-run with --yes to promote {record['id']}.")
        return EXIT_OK

    record["status"] = "confirmed"
    record.setdefault("uid", canon.stable_uid("r", record["id"],
                                              record.get("statement", "")))
    record.setdefault("conflicts_with", [])
    confirmed: dict[str, Any] = (
        canon.load_json(confirmed_path) if os.path.isfile(confirmed_path)
        else {"schema_version": SCHEMA_VERSION, "requirements": []})
    confirmed["requirements"] = [r for r in confirmed["requirements"]
                                 if r["id"] != record["id"]] + [record]
    confirmed["requirements"].sort(key=lambda r: r["id"])
    proposed["requirements"] = [r for r in proposed["requirements"]
                                if r["id"] != record["id"]]
    for path, doc in ((confirmed_path, confirmed), (proposed_path, proposed)):
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(canon.canonical_json(doc))
    print(f"\npromoted {record['id']}. Commit it — the commit is the audit "
          "record of who confirmed it and when.")
    return EXIT_OK
