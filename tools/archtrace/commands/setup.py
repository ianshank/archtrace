"""Scaffolding an engagement and inspecting effective configuration."""

from __future__ import annotations

import argparse
import os
import sys

from .. import canon
from ..log import get_logger
from ..model import (
    SCHEMA_VERSION,
)
from ._shared import EXIT_OK, EXIT_USAGE
from .build import cmd_render

LOG = get_logger("setup")

def cmd_init(args) -> int:
    """Scaffold an engagement so the first thing you do is not hand-author JSON."""
    skeletons = {
        ("evidence", "index.json"): {"schema_version": SCHEMA_VERSION,
                                     "evidence": []},
        ("requirements", "proposed.json"): {"schema_version": SCHEMA_VERSION,
                                            "requirements": []},
        ("requirements", "requirements.json"): {"schema_version": SCHEMA_VERSION,
                                                "requirements": []},
        ("model", "model.json"): {
            "schema_version": SCHEMA_VERSION,
            "workspace": {"name": args.name, "client": args.client or ""},
            "standards": [], "open_questions": [], "nfr_coverage": [],
            "people": [], "systems": [], "relationships": [],
            "decisions": [], "out_of_scope": [],
        },
    }
    for parts, doc in skeletons.items():
        path = os.path.join(args.root, *parts)
        if os.path.exists(path) and not args.force:
            print(f"archtrace: {os.path.join(*parts)} already exists; "
                  "refusing to overwrite (use --force)", file=sys.stderr)
            return EXIT_USAGE
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(canon.canonical_json(doc))
        print(f"created {os.path.join(*parts)}")
    for directory in ("render", "review", "_evidence_root"):
        os.makedirs(os.path.join(args.root, directory), exist_ok=True)
    # An engagement is green from the first commit, so the gate is something you
    # keep green rather than something you eventually turn on.
    cmd_render(argparse.Namespace(**{**vars(args), "quiet": True}))
    print(f"\nengagement '{args.name}' ready. Evidence CONTENT goes under "
          f"{os.path.join(args.root, '_evidence_root')}, which is git-ignored: "
          "the repository holds claims about evidence, never the recordings.")
    print("Next: archtrace evidence add <transcript.txt> --authority "
          "stakeholder-confirmed ...")
    return EXIT_OK
