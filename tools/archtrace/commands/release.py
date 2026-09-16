"""Binding an approval to exact content hashes, and verifying it."""

from __future__ import annotations

import hashlib
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

RENDER_DIRNAME = "render"


def digest_bytes(data: bytes) -> str:
    """The one hash format the manifest speaks, so nothing can spell it twice."""
    return "sha256:" + hashlib.sha256(data).hexdigest()


def digest_file(path: str) -> str | None:
    """Hash a file **on disk**, or None when it is not readable.

    Publication integrity is a question about the bytes in someone's hand, never
    about bytes a renderer could produce. Hashing a fresh render instead answers
    a different and much weaker question -- "could the model reproduce this?" --
    and reports MATCH on a deliverable that was edited after it was approved.

    Returning None rather than raising keeps a missing output a reportable
    finding instead of a traceback, which is the rule the gate rules follow too.
    """
    try:
        with open(path, "rb") as handle:
            return digest_bytes(handle.read())
    except OSError as exc:
        LOG.debug("cannot hash %s: %s", path, exc)
        return None


def published_outputs(root: str) -> set:
    """Every direct entry in render/ -- files AND directories, dotfiles included.

    Used to spot something on disk that no approval covers. Directories are
    listed because filtering to regular files let a hand-added `render/appendix/`
    hold unapproved content that `--verify` reported as MATCH while G6 blocked
    it as a stray: two controls disagreeing about one tree is the failure this
    whole area is about.

    Dotfiles are listed because `.manifest.json` is a real approved output and a
    listing that skipped it would let it be swapped without notice; callers
    decide what to do with the *other* dotfiles, and `_verify_release` follows
    G6 in ignoring them. Not recursive, matching G6's own stray check -- the
    top-level entry is enough to report, whatever is beneath it.
    """
    render_dir = os.path.join(root, RENDER_DIRNAME)
    if not os.path.isdir(render_dir):
        return set()
    return set(os.listdir(render_dir))


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

    path = os.path.join(args.root, "release.json")
    if args.verify:
        # Deliberately BEFORE the engagement is loaded. Verification compares
        # bytes on disk against the manifest and needs neither the model nor a
        # renderer, so `--verify` still answers when the model will not load --
        # which is exactly when someone most needs to know whether the artifact
        # in their hand is the approved one.
        return _verify_release(args, path)
    eng = _engagement(args)
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
        value = digest_file(os.path.join(args.root, *parts))
        if value is None:
            raise OSError(f"cannot read {os.path.join(*parts)} to hash it")
        return value

    # The approved SET is the renderer's contract; the approved BYTES come from
    # disk. Taking the set from disk too meant a stray dotfile -- .DS_Store, an
    # editor swap file -- was signed into an audit manifest as an approved
    # deliverable, and then deleting that junk reported DRIFT and blocked
    # publication of an intact deliverable set. G6 deliberately exempts dotfiles
    # from its stray rule, so release must not disagree with it.
    approved_outputs = {}
    for name in sorted(render_all(eng)):
        value = digest_file(os.path.join(args.root, RENDER_DIRNAME, name))
        if value is None:
            # G6 has already passed, so every output exists. If one has become
            # unreadable since, say so rather than silently shrinking the set
            # an approval covers.
            print(f"archtrace: cannot read render/{name} to hash it; refusing "
                  "to sign an approval that silently omits it", file=sys.stderr)
            return EXIT_BLOCKED
        approved_outputs[name] = value

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
        "outputs": approved_outputs,
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

def _verify_release(args, path: str) -> int:
    """Does what is on disk still match what was approved?

    This is the control that matters at publication time. A commit id says a
    state was approved once; only recomputing the hashes says the artifact in
    your hand is that state. Binding a stakeholder deliverable to a commit
    rather than to content is how an unapproved revision gets published with an
    approved-looking provenance trail.

    The hashes are recomputed from the files in `render/`, not from a fresh
    render of the model: the question is whether the artifact about to be sent
    is the approved one, and only the bytes on disk can answer it.
    """
    if not os.path.isfile(path):
        print("archtrace: no release.json to verify", file=sys.stderr)
        return EXIT_USAGE
    manifest = canon.load_json(path)
    drift = []
    for name, expected in manifest.get("sources", {}).items():
        actual = digest_file(os.path.join(args.root, name))
        if actual is None:
            drift.append(("source", f"{name} (missing)"))
        elif actual != expected:
            drift.append(("source", name))

    # Outputs are hashed FROM DISK, exactly as sources already were. Hashing a
    # fresh `render_all` here was the defect: it verified that the model could
    # still produce the approved bytes, never that the file about to be sent
    # actually was them, so an edited deliverable verified clean.
    approved = manifest.get("outputs", {})
    render_dir = os.path.join(args.root, RENDER_DIRNAME)
    for name, expected in sorted(approved.items()):
        actual = digest_file(os.path.join(render_dir, name))
        if actual is None:
            drift.append(("output", f"{name} (missing from {RENDER_DIRNAME}/)"))
        elif actual != expected:
            drift.append(("output", name))
    drift.extend(("output", f"{extra} (not in the approved set)")
                 for extra in sorted(published_outputs(args.root) - set(approved))
                 # G6 exempts dotfiles from its stray rule; release must agree
                 # with it, or a .DS_Store blocks publication of an intact set.
                 if not extra.startswith("."))
    LOG.debug("verified %d source(s) and %d output(s) against %s; %d drifted",
              len(manifest.get("sources", {})), len(approved), path, len(drift))

    print(f"release.json  approved by {manifest.get('approved_by')} "
          f"({manifest.get('authority_role')}) at {manifest.get('approved_at')}")
    print(f"              commit {manifest.get('model_commit') or '(none)'}")
    if not drift:
        print(f"\nMATCH — every source and output in {RENDER_DIRNAME}/ is "
              "byte-identical to what was approved. Safe to publish.")
        return EXIT_OK
    print(f"\nDRIFT — {len(drift)} item(s) differ from the approved state:")
    for kind, name in drift:
        print(f"  {kind:<7} {name}")
    print("\nDo NOT publish these as approved. Either re-run the approval, or "
          "publish the state the manifest actually describes.")
    return EXIT_BLOCKED
