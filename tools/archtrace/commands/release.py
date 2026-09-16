"""Binding an approval to exact content hashes, and verifying it."""

from __future__ import annotations

import os
import sys

from .. import canon, gate
from ..log import get_logger
from ..model import (
    RENDERER_VERSION,
)
from ..renders import render_all
from ._shared import EXIT_BLOCKED, EXIT_OK, EXIT_USAGE, git
from ._shared import engagement as _engagement

LOG = get_logger("release")


def cmd_release(args) -> int:
    """Bind an approval to an exact state, outside the gated render set.

    A commit says who and when. It does not say *what artifact* was approved,
    and it cannot, because the renders are regenerated. This writes a manifest
    that names the commit, the three source documents, the evidence manifest and
    every output by hash — so a published Word document or Jira import can be
    tied back to a reviewed state rather than to a hopeful assumption.

    It lives outside render/ deliberately: a commit id changes on every commit,
    so putting it in a render-freshness-gated file would fail the build forever.
    """
    import datetime
    import hashlib

    eng = _engagement(args)
    path = os.path.join(args.root, "release.json")
    if args.verify:
        return _verify_release(args, eng, path)
    if not (args.approved_by and args.role):
        print("archtrace: --approved-by and --role are required to create a "
              "release", file=sys.stderr)
        return EXIT_USAGE
    findings, code = gate.run(eng, strict=args.strict)
    if code != EXIT_OK:
        for finding in findings:
            if finding.severity == gate.BLOCK:
                print(finding)
        print("\narchtrace: refusing to release — the gate blocks. An approval "
              "that binds a failing state is worse than no approval.",
              file=sys.stderr)
        if os.path.isfile(path):
            # Not deleted: it is an audit record of a real past approval, and
            # its hashes already prove it no longer describes this state.
            # `--verify` is how anyone confirms that.
            print("archtrace: note — release.json still describes an EARLIER "
                  "approved state. It is deliberately not deleted; run "
                  "`archtrace release --verify` to see the drift.",
                  file=sys.stderr)
        return EXIT_BLOCKED

    dirty = git(args.root, "status", "--porcelain")
    commit = git(args.root, "rev-parse", "HEAD")
    if commit is None:
        print("archtrace: not a git repository; releasing without a commit id. "
              "The manifest binds hashes but not history.", file=sys.stderr)
    elif dirty and not args.allow_dirty:
        print("archtrace: working tree is dirty, so no commit describes what "
              "you are releasing. Commit first, or pass --allow-dirty and "
              "accept that the commit id in the manifest is a lie.",
              file=sys.stderr)
        return EXIT_USAGE

    def digest(*parts: str) -> str:
        with open(os.path.join(args.root, *parts), "rb") as fh:
            return "sha256:" + hashlib.sha256(fh.read()).hexdigest()

    manifest = {
        "engagement": eng.model.get("workspace", {}).get("name", ""),
        "approved_by": args.approved_by,
        "approved_at": datetime.datetime.now(
            datetime.timezone.utc).replace(microsecond=0).isoformat(),
        "authority_role": args.role,
        "model_commit": commit,
        "working_tree_clean": not dirty,
        "renderer_version": RENDERER_VERSION,
        "schema_version": eng.model.get("schema_version"),
        "sources": {
            "evidence/index.json": digest("evidence", "index.json"),
            "requirements/requirements.json": digest("requirements",
                                                     "requirements.json"),
            "model/model.json": digest("model", "model.json"),
        },
        "outputs": {name: "sha256:" + hashlib.sha256(data).hexdigest()
                    for name, data in sorted(render_all(eng).items())},
        "confirmed_requirements": sorted(r["id"] for r in
                                         eng.confirmed_requirements),
        "warnings_outstanding": [f"{f.rule}:{f.where}" for f in findings
                                 if f.severity == gate.WARN],
    }
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(canon.canonical_json(manifest))
    print(f"wrote {os.path.relpath(path, args.root)}")
    print(f"  approver   {args.approved_by} ({args.role})")
    print(f"  commit     {commit or '(none)'}")
    print(f"  outputs    {len(manifest['outputs'])} hashed")
    if manifest["warnings_outstanding"]:
        print(f"  WARNING    releasing with {len(manifest['warnings_outstanding'])} "
              "outstanding warning(s); they are recorded in the manifest")
    print("\nPublish against these hashes. If an output you are about to send "
          "does not match, it was not the thing that was approved.")
    return EXIT_OK

def _verify_release(args, eng, path: str) -> int:
    """Does what is on disk still match what was approved?

    This is the control that matters at publication time. A commit id says a
    state was approved once; only recomputing the hashes says the artifact in
    your hand is that state. Binding a stakeholder deliverable to a commit
    rather than to content is how an unapproved revision gets published with an
    approved-looking provenance trail.
    """
    import hashlib

    if not os.path.isfile(path):
        print("archtrace: no release.json to verify", file=sys.stderr)
        return EXIT_USAGE
    manifest = canon.load_json(path)
    drift = []
    for name, expected in manifest.get("sources", {}).items():
        with open(os.path.join(args.root, name), "rb") as fh:
            actual = "sha256:" + hashlib.sha256(fh.read()).hexdigest()
        if actual != expected:
            drift.append(("source", name))
    outputs = render_all(eng)
    for name, expected in manifest.get("outputs", {}).items():
        data = outputs.get(name)
        if data is None:
            # An approved output the renderer no longer produces is drift, not a
            # missing hash: the approved state cannot be reproduced.
            drift.append(("output", f"{name} (no longer rendered)"))
            continue
        if "sha256:" + hashlib.sha256(data).hexdigest() != expected:
            drift.append(("output", name))
    drift.extend(("output", f"{missing} (not in the approved set)")
                 for missing in sorted(set(outputs)
                                       - set(manifest.get("outputs", {}))))

    print(f"release.json  approved by {manifest.get('approved_by')} "
          f"({manifest.get('authority_role')}) at {manifest.get('approved_at')}")
    print(f"              commit {manifest.get('model_commit') or '(none)'}")
    if not drift:
        print("\nMATCH — every source and output is byte-identical to what was "
              "approved. Safe to publish.")
        return EXIT_OK
    print(f"\nDRIFT — {len(drift)} item(s) differ from the approved state:")
    for kind, name in drift:
        print(f"  {kind:<7} {name}")
    print("\nDo NOT publish these as approved. Either re-run the approval, or "
          "publish the state the manifest actually describes.")
    return EXIT_BLOCKED
