"""archtrace command line.

    archtrace init NAME              scaffold an engagement
    archtrace evidence add FILE      register evidence (hashes normalised text)
    archtrace quote EV-ID "text"     resolve a quote to a verifiable byte span
    archtrace evidence add-facts     register code-mining facts (optional)
    archtrace symbols EV-ID PATTERN  find a symbol to cite in code evidence
    archtrace mine --repo PATH       drive a miner, register its facts (optional)
    archtrace promote REQ-ID         the human gate: confirm a proposed requirement
    archtrace render                 regenerate every build output
    archtrace check [--strict]       deterministic gates; exit 1 on any block
    archtrace fmt                    canonicalise JSON, refresh derived fields
    archtrace report                 grounding mix and NFR coverage summary
    archtrace release --approved-by  bind an approval to exact content hashes
    archtrace baseline               SPEC §9a — run this BEFORE anything else

All commands accept --root (engagement directory) and --evidence-root (where the
evidence *content* lives; it is deliberately not in the repository).
"""

from __future__ import annotations

import argparse
import os
import sys

from . import canon, gate
from .model import (NFR_CATEGORIES, REQUIREMENT_AUTHORITY, RENDERER_VERSION,
                    SCHEMA_VERSION, Engagement)
from .renders import render_all

EXIT_OK, EXIT_BLOCKED, EXIT_USAGE = 0, 1, 2


def _engagement(args) -> Engagement:
    return Engagement.load(args.root, args.evidence_root)


# --- commands --------------------------------------------------------------

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
    confirmed = canon.load_json(confirmed_path) if os.path.isfile(confirmed_path) \
        else {"schema_version": SCHEMA_VERSION, "requirements": []}
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


def _git(root: str, *argv) -> str | None:
    import subprocess
    try:
        out = subprocess.run(["git", "-C", root, *argv], capture_output=True,
                             text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return None
    return out.stdout.strip() if out.returncode == 0 else None


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

    dirty = _git(args.root, "status", "--porcelain")
    commit = _git(args.root, "rev-parse", "HEAD")
    if commit is None:
        print("archtrace: not a git repository; releasing without a commit id. "
              "The manifest binds hashes but not history.", file=sys.stderr)
    elif dirty and not args.allow_dirty:
        print("archtrace: working tree is dirty, so no commit describes what "
              "you are releasing. Commit first, or pass --allow-dirty and "
              "accept that the commit id in the manifest is a lie.",
              file=sys.stderr)
        return EXIT_USAGE

    def digest(*parts) -> str:
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
        actual = ("sha256:" + hashlib.sha256(data).hexdigest()
                  if data is not None else None)
        if actual != expected:
            drift.append(("output", name))
    for missing in set(outputs) - set(manifest.get("outputs", {})):
        drift.append(("output", f"{missing} (not in the approved set)"))

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


def cmd_baseline(args) -> int:
    """The SPEC §9a measurement, as an instrument rather than prose.

    Two numbers decide whether this program is worth running at all:

      traceability — what share of your architecture can be tied to something a
                     stakeholder actually said. Under 60%, the problem was never
                     automation.
      naive-reject — what share a satisfies-only rule would have thrown out.
                     This is the direct measurement of whether grounding kinds
                     were the right call.

    A caveat the output repeats, because it matters more than the number: this
    only means something if the model PREDATES the measurement. Score a model
    and an evidence set that were authored together and you are measuring your
    own consistency, not your grounding.
    """
    import csv as _csv

    if args.elements:
        return _blank_worksheet(args)

    eng = _engagement(args)
    elements = list(eng.elements())
    if not elements:
        print("archtrace: no elements to measure", file=sys.stderr)
        return EXIT_USAGE

    confirmed = {r["id"]: r for r in eng.confirmed_requirements}
    rows, quotable, by_kind = [], 0, {}
    for element in elements:
        kinds = [g.get("kind") for g in element.grounding]
        for kind in kinds:
            by_kind[kind] = by_kind.get(kind, 0) + 1
        quote = speaker = evidence_id = req_id = ""
        for entry in element.grounding:
            if entry.get("kind") != "satisfies":
                continue
            req = confirmed.get(entry.get("req", ""))
            if not req or not req.get("provenance"):
                continue
            prov = req["provenance"][0]
            req_id, quote = req["id"], prov.get("quote_cached", "")
            speaker, evidence_id = prov.get("speaker", ""), prov["evidence_id"]
            break
        if quote:
            quotable += 1
        rows.append({
            "element_id": element.id, "level": element.level,
            "name": element.name, "grounding_kinds": "|".join(kinds),
            "traces_to_requirement": req_id,
            "quotable_statement": "yes" if quote else "no",
            "quote": quote, "speaker": speaker, "evidence_id": evidence_id,
        })

    total = len(elements)
    claims_req = sum(1 for r in rows if "satisfies" in r["grounding_kinds"])
    otherwise = sum(1 for r in rows
                    if r["grounding_kinds"] and "satisfies" not in r["grounding_kinds"])
    unexplained = sum(1 for r in rows if not r["grounding_kinds"])
    traceability = 100 * quotable // total
    unexplained_pct = 100 * unexplained // total
    backed = 100 * quotable // claims_req if claims_req else 100

    modelled = eng.requirements_grounded()
    excluded = {o["req"] for o in eng.out_of_scope}
    accounted = len([r for r in confirmed if r in modelled or r in excluded])
    coverage = 100 * accounted // len(confirmed) if confirmed else 0

    name = eng.model.get("workspace", {}).get("name", "")
    print(f"§9a baseline — {name}\n")
    print(f"elements                              {total:>4}")
    print(f"  trace to a quotable statement       {quotable:>4}   "
          f"{traceability:>3}%")
    print(f"  legitimately grounded otherwise     {otherwise:>4}   "
          f"{100 * otherwise // total:>3}%")
    for kind in sorted(k for k in by_kind if k != "satisfies"):
        print(f"      {kind:<14}                 {by_kind[kind]:>4}")
    print(f"  UNEXPLAINED                         {unexplained:>4}   "
          f"{unexplained_pct:>3}%   <- the decision number")
    print(f"\nconfirmed requirements                {len(confirmed):>4}")
    print(f"  modelled or explicitly out of scope {accounted:>4}   {coverage:>3}%")

    print("\nDECISION RULES (SPEC §9a, corrected)")
    ok = True
    if unexplained_pct > 20:
        ok = False
        print(f"  [STOP]  unexplained {unexplained_pct}% vs <= 20%")
        print("          Elements you can neither quote nor justify. The problem "
              "was never\n          automation — this pipeline would "
              "industrialise that gap at speed.")
    else:
        print(f"  [PASS]  unexplained {unexplained_pct}% vs <= 20%")
    if backed < 100:
        ok = False
        print(f"  [FIX]   {backed}% of requirement-linked elements have a real "
              "quote behind them")
        print("          An element claiming to satisfy a requirement that has "
              "no citation is\n          the exact fabrication this gate exists "
              "to stop.")
    else:
        print(f"  [PASS]  every requirement-linked element has a real quote "
              f"({claims_req}/{claims_req})")
    if coverage < 80:
        ok = False
        print(f"  [FIX SCHEMA] coverage {coverage}% vs >= 80%")
    else:
        print(f"  [PASS]  coverage {coverage}%")

    print(f"\n  Raw traceability is {traceability}%, and that is INFORMATIONAL, "
          "not a bar.")
    print("  v1 of this spec made it a >= 60% stop condition. Running the "
          "instrument showed\n  that is wrong: it fails a healthy "
          "infrastructure-heavy architecture, where half\n  the elements are "
          "load balancers and incumbent systems that legitimately have\n  no "
          "stakeholder requirement. The number that decides is UNEXPLAINED.")

    print(f"\n  A satisfies-only rule would have rejected {otherwise + unexplained} "
          f"of {total} elements.")
    print("  Rejecting them is what pressures an architect into inventing "
          "requirements.")

    print("\nCAVEAT")
    print("  Two, and they matter more than the numbers.")
    print("  1. This only means something if the model PREDATES the "
          "measurement. Scoring a")
    print("     model and evidence authored together measures your own "
          "consistency.")
    print("  2. 'Legitimately grounded otherwise' is SELF-CLASSIFIED. If you "
          "can rationalise")
    print("     every box as a standard, unexplained goes to zero and this "
          "measures nothing.")
    print(f"\n  verdict: {'proceed to §9b' if ok else 'do not proceed'}")

    if args.worksheet:
        with open(args.worksheet, "w", encoding="utf-8", newline="") as fh:
            writer = _csv.DictWriter(fh, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
        print(f"\nwrote {args.worksheet}")
    return EXIT_OK


def _blank_worksheet(args) -> int:
    """Emit the worksheet for an engagement that has no model yet.

    This is the §9a instrument for a PAST engagement: list the elements off your
    delivered diagram, one per line, and fill in the quote column by hand. No
    code, no schema, no install.
    """
    import csv as _csv

    with open(args.elements, "r", encoding="utf-8") as fh:
        names = [line.strip() for line in fh if line.strip()]
    target = args.worksheet or "baseline-worksheet.csv"
    with open(target, "w", encoding="utf-8", newline="") as fh:
        writer = _csv.writer(fh)
        writer.writerow(["element", "quotable_statement (yes/no)", "quote",
                         "speaker", "source",
                         "if no: standard / existing / derived / assumption / "
                         "UNEXPLAINED"])
        for name in names:
            writer.writerow([name, "", "", "", "", ""])
    print(f"wrote {target} — {len(names)} elements")
    print("\nFill the quote column by hand from the evidence you still have.")
    print("For every 'no', say why the element is there. If you cannot, mark it")
    print("UNEXPLAINED — that column, not the quote column, is the decision.")
    print("More than 20% UNEXPLAINED: stop. The problem was never automation.")
    print("\nBe honest in that column. If you can rationalise every box as a")
    print("standard, it goes to zero and you have measured nothing.")
    return EXIT_OK


def cmd_check(args) -> int:
    eng = _engagement(args)
    findings, code = gate.run(eng, strict=args.strict)
    blocks = [f for f in findings if f.severity == gate.BLOCK]
    warns = [f for f in findings if f.severity == gate.WARN]
    for finding in findings:
        print(finding)
    mix = eng.grounding_mix()
    print(f"\n{len(blocks)} blocking, {len(warns)} warning "
          f"| {len(eng.confirmed_requirements)} confirmed requirements "
          f"| grounding {mix['by_kind']}")
    # An empty engagement is not a passing one, and a pass with warnings is not
    # a clean pass. A gate that congratulates you for having nothing in it is
    # the false-green failure this whole design exists to avoid.
    if code != EXIT_OK:
        pass
    elif not eng.confirmed_requirements:
        print("archtrace: nothing to check yet — no confirmed requirements. "
              "This is an empty pass, not a clean one.")
    elif warns:
        print(f"archtrace: no blocking findings, {len(warns)} warning(s) "
              "outstanding. Grounded and internally consistent; correctness is "
              "still yours.")
    else:
        print("archtrace: model is grounded and internally consistent. "
              "Correctness is still yours.")
    return code


def cmd_render(args) -> int:
    eng = _engagement(args)
    out_dir = os.path.join(args.root, "render")
    os.makedirs(out_dir, exist_ok=True)
    outputs = render_all(eng)
    for name, data in sorted(outputs.items()):
        with open(os.path.join(out_dir, name), "wb") as fh:
            fh.write(data)
        if not getattr(args, "quiet", False):
            print(f"wrote render/{name} ({len(data)} bytes)")
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
        os.path.join(args.root, "evidence", "index.json"): eng.evidence_index,
        os.path.join(args.root, "requirements", "requirements.json"): eng.requirements_doc,
        os.path.join(args.root, "model", "model.json"): eng.model,
    }
    for path, doc in writes.items():
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(canon.canonical_json(doc))
        print(f"formatted {os.path.relpath(path, args.root)}")
    print(f"refreshed {refreshed} cached quote(s) from their spans")
    return EXIT_OK


def cmd_evidence_add(args) -> int:
    index_path = os.path.join(args.root, "evidence", "index.json")
    index = canon.load_json(index_path) if os.path.isfile(index_path) \
        else {"schema_version": SCHEMA_VERSION, "evidence": []}
    local = os.path.relpath(args.file, args.evidence_root)
    with open(args.file, "r", encoding="utf-8") as fh:
        normalized = canon.normalize(fh.read())
    record = {
        "id": args.id or f"EV-{len(index['evidence']) + 1:03d}",
        "source": args.source,
        "authority": args.authority,
        **({"document_owner": args.document_owner} if args.document_owner else {}),
        **({"effective_date": args.effective_date} if args.effective_date else {}),
        **({"document_version": args.document_version}
           if args.document_version else {}),
        "source_uri": args.source_uri,
        "local_path": local,
        "date": args.date,
        "participants": args.participants,
        "classification": args.classification,
        "retention_until": args.retention_until,
        "sha256_normalized": canon.sha256_text(normalized),
    }
    index["evidence"] = [e for e in index["evidence"] if e["id"] != record["id"]]
    index["evidence"].append(record)
    index["evidence"].sort(key=lambda e: e["id"])
    with open(index_path, "w", encoding="utf-8") as fh:
        fh.write(canon.canonical_json(index))
    print(f"registered {record['id']} ({len(normalized)} normalised chars)")
    print("Note: the content stays under --evidence-root and out of git. "
          "The repository holds claims about evidence, not evidence.")
    return EXIT_OK


def _register_facts(args, raw: bytes, local_path: str, commit: str,
                    facts, evidence_id: str | None = None) -> str:
    """Write one structured evidence record. Shared by `mine` and `add-facts`
    so the two paths cannot drift apart."""
    from .mining import CONTENT_STRUCTURED, sha256_bytes

    index_path = os.path.join(args.root, "evidence", "index.json")
    index = canon.load_json(index_path) if os.path.isfile(index_path) \
        else {"schema_version": SCHEMA_VERSION, "evidence": []}
    record = {
        "id": evidence_id or f"EV-{len(index['evidence']) + 1:03d}",
        "source": "code-mining",
        "content_kind": CONTENT_STRUCTURED,
        # Never negotiable: code is evidence of what exists, not of what is
        # required. G11 blocks any requirement resting on this tier.
        "authority": "observed-implementation",
        "commit": commit,
        "facts_schema_version": facts.schema_version,
        "source_uri": args.source_uri,
        "local_path": local_path,
        "date": args.date,
        "participants": [args.miner],
        "classification": args.classification,
        "retention_until": args.retention_until,
        "sha256_normalized": sha256_bytes(raw),
    }
    index["evidence"] = [e for e in index["evidence"] if e["id"] != record["id"]]
    index["evidence"].append(record)
    index["evidence"].sort(key=lambda e: e["id"])
    with open(index_path, "w", encoding="utf-8") as fh:
        fh.write(canon.canonical_json(index))
    return record["id"]


def _report_facts(evidence_id: str, commit: str, facts) -> None:
    from .mining import summarise
    stats = summarise(facts)
    print(f"registered {evidence_id} at commit {commit[:12]}")
    print(f"  {stats['symbols']} symbols, {stats['relations']} relations, "
          f"{stats['warnings']} parse warning(s)")
    if stats["relation_confidence"]:
        print(f"  relation confidence: {stats['relation_confidence']}")
    ambiguous = stats["relation_confidence"].get("AMBIGUOUS", 0)
    inferred = stats["relation_confidence"].get("INFERRED", 0)
    if ambiguous or inferred:
        print(f"  NOTE {inferred} inferred and {ambiguous} ambiguous relation(s). "
              "Name resolution is\n       a guess, not a compiler. Verify before "
              "grounding an element on one.")
    print("\nThis is observed-implementation evidence. It can ground an element "
          "as\n`existing` or `derived` with a symbol id. It can NEVER carry a "
          "requirement.")


DEFAULT_MINE_COMMAND = "archmine index && archmine artifacts"
DEFAULT_FACTS_PATH = "docs/architecture/generated/architecture-facts.json"


def cmd_mine(args) -> int:
    """Run a code miner over a repository and register its output as evidence.

    archtrace drives the miner as a SUBPROCESS and never imports it. That is what
    keeps the zero-dependency invariant intact while still letting the miner be
    an arbitrary toolchain — a different Python, a compiled binary, a container.

    The command comes from the operator's flags or the Makefile. It never comes
    from evidence content, and nothing this command reads can change it.
    """
    import shutil
    import subprocess

    from .mining import FactsError, parse_facts

    repo = os.path.abspath(os.path.expanduser(args.repo))
    if not os.path.isdir(repo):
        print(f"archtrace: {repo} is not a directory", file=sys.stderr)
        return EXIT_USAGE

    commit = args.commit or _git(repo, "rev-parse", "HEAD")
    dirty = _git(repo, "status", "--porcelain")
    if not commit:
        print("archtrace: could not resolve a commit for the mined repository. "
              "Pass --commit, or mine a git checkout: facts that cannot name a "
              "codebase state are not evidence.", file=sys.stderr)
        return EXIT_USAGE
    if dirty and not args.allow_dirty:
        print(f"archtrace: {repo} has uncommitted changes, so the facts would "
              f"describe something no commit names. Commit there first, or pass "
              f"--allow-dirty and accept that {commit[:12]} is approximate.",
              file=sys.stderr)
        return EXIT_USAGE

    facts_path = args.facts if os.path.isabs(args.facts) \
        else os.path.join(repo, args.facts)
    target = os.path.join(args.evidence_root,
                          args.local_name or f"{args.id or 'facts'}-facts.json")

    if args.dry_run:
        print(f"would run:   {args.command}")
        print(f"        in:  {repo}")
        print(f"     commit: {commit}{' (DIRTY)' if dirty else ''}")
        print(f"      facts: {facts_path}")
        print(f"    copy to: {target}")
        return EXIT_OK

    print(f"mining {repo} at {commit[:12]}{' (dirty)' if dirty else ''}")
    try:
        completed = subprocess.run(args.command, cwd=repo, shell=True,
                                   capture_output=True, text=True,
                                   timeout=args.timeout)
    except subprocess.TimeoutExpired:
        print(f"archtrace: miner exceeded {args.timeout}s", file=sys.stderr)
        return EXIT_BLOCKED
    except OSError as exc:
        print(f"archtrace: could not run the miner: {exc}", file=sys.stderr)
        return EXIT_BLOCKED
    if completed.returncode != 0:
        print(completed.stdout[-2000:], file=sys.stderr)
        print(completed.stderr[-2000:], file=sys.stderr)
        print(f"archtrace: miner exited {completed.returncode}", file=sys.stderr)
        return EXIT_BLOCKED
    if not os.path.isfile(facts_path):
        print(f"archtrace: the miner ran but produced no {facts_path}. "
              "Check --facts.", file=sys.stderr)
        return EXIT_BLOCKED

    with open(facts_path, "rb") as fh:
        raw = fh.read()
    try:
        facts = parse_facts(raw)
    except FactsError as exc:
        print(f"archtrace: {exc}", file=sys.stderr)
        return EXIT_BLOCKED

    if not facts.commit:
        # Stamped into the COPY, never into the miner's own output: evidence is a
        # snapshot, and the miner's output directory is scratch. archmine 0.1.0
        # declares `commit` and never populates it, so without this every facts
        # file it produces is unusable as evidence.
        import json as _json
        document = _json.loads(raw.decode("utf-8"))
        document["commit"] = commit
        raw = (_json.dumps(document, indent=2) + "\n").encode("utf-8")
        facts = parse_facts(raw)
        print(f"  stamped commit {commit[:12]} (the miner emitted none)")

    os.makedirs(os.path.dirname(target) or ".", exist_ok=True)
    with open(target, "wb") as fh:
        fh.write(raw)
    _ = shutil  # kept for callers that override the copy step

    evidence_id = _register_facts(
        args, raw, os.path.relpath(target, args.evidence_root), commit, facts,
        evidence_id=args.id)
    _report_facts(evidence_id, commit, facts)
    print(f"\nNext: archtrace --root {args.root} symbols {evidence_id} <pattern>")
    return EXIT_OK


def cmd_evidence_add_facts(args) -> int:
    """Register a code-mining facts file as observed-implementation evidence.

    archtrace does not run the miner and does not import it. Anything that emits
    the supported facts shape works — archmine, or a compiler-grade extractor you
    write later. The seam is the file.
    """
    from .mining import CONTENT_STRUCTURED, FactsError, parse_facts, sha256_bytes

    with open(args.file, "rb") as fh:
        raw = fh.read()
    try:
        facts = parse_facts(raw)
    except FactsError as exc:
        print(f"archtrace: {exc}", file=sys.stderr)
        return EXIT_USAGE

    commit = args.commit or facts.commit
    if not commit:
        print("archtrace: --commit is required. The facts file does not carry "
              "one, and a fact about a codebase that cannot say WHICH codebase "
              "state is not evidence.", file=sys.stderr)
        return EXIT_USAGE

    evidence_id = _register_facts(
        args, raw, os.path.relpath(args.file, args.evidence_root), commit, facts,
        evidence_id=args.id)
    _report_facts(evidence_id, commit, facts)
    return EXIT_OK


def cmd_symbols(args) -> int:
    """Search a registered facts file for a symbol to cite."""
    eng = _engagement(args)
    facts = eng.evidence_facts(args.evidence_id)
    if facts is None:
        print(f"archtrace: {args.evidence_id} is not readable structured "
              "evidence", file=sys.stderr)
        return EXIT_USAGE
    needle = args.pattern.lower()
    hits = [(sid, sym) for sid, sym in sorted(facts.symbols.items())
            if needle in str(sym.get("name", "")).lower()
            or needle in str(sym.get("path", "")).lower()]
    if not hits:
        print(f"archtrace: nothing matching {args.pattern!r} in "
              f"{args.evidence_id}", file=sys.stderr)
        return EXIT_BLOCKED
    for sid, sym in hits[:args.limit]:
        print(f"{sid}  {sym.get('kind', '?'):<10} {sym.get('name', '?')}")
        print(f"    {sym.get('path', '?')}:{sym.get('start_line', '?')}")
    if len(hits) > args.limit:
        print(f"... {len(hits) - args.limit} more")
    print(f"\nGround an element with:\n  {{\"kind\": \"existing\", "
          f"\"evidence_id\": \"{args.evidence_id}\", \"symbol\": "
          f"\"{hits[0][0]}\"}}")
    return EXIT_OK


def cmd_quote(args) -> int:
    """Resolve a fragment to a byte span, which is what provenance stores.

    Hand-authoring a verbatim quote into JSON is the worst possible payload:
    embedded quotes, backslashes and curly punctuation all have to survive
    byte-exact, and a mistake surfaces as a provenance failure rather than a
    syntax error. This command removes that class of mistake.
    """
    eng = _engagement(args)
    text = eng.evidence_text(args.evidence_id)
    if text is None:
        print(f"archtrace: no content for {args.evidence_id} under "
              f"{eng.evidence_root}", file=sys.stderr)
        return EXIT_USAGE
    needle = canon.normalize(args.fragment)
    start = text.find(needle)
    if start < 0:
        print(f"archtrace: fragment not found in {args.evidence_id} after "
              "normalisation", file=sys.stderr)
        return EXIT_BLOCKED
    if text.find(needle, start + 1) >= 0:
        print(f"archtrace: warning — fragment occurs more than once; "
              f"using the first at {start}", file=sys.stderr)
    end = start + len(needle)
    print(canon.canonical_json({"provenance": [{
        "evidence_id": args.evidence_id,
        "speaker": args.speaker or "<who said it>",
        "start": start, "end": end, "quote_cached": text[start:end],
    }]}))
    return EXIT_OK


def cmd_report(args) -> int:
    eng = _engagement(args)
    mix = eng.grounding_mix()
    total = mix["total"] or 1
    print(f"engagement: {eng.model.get('workspace', {}).get('name', '')}")
    print(f"renderer {RENDERER_VERSION}, schema {eng.model.get('schema_version')}")
    print(f"\nevidence records      {len(eng.evidence)}")
    print(f"requirements          {len(eng.requirements)} "
          f"({len(eng.confirmed_requirements)} confirmed)")
    print(f"elements              {len(list(eng.elements()))}")
    print(f"relationships         {len(eng.relationships)}")
    print("\ngrounding mix (a model that is 100% satisfies is the suspicious one)")
    for kind in sorted(mix["by_kind"]):
        count = mix["by_kind"][kind]
        bar = "#" * (30 * count // total)
        print(f"  {kind:<11} {count:>3}  {100 * count // total:>3}%  {bar}")
    coverage = eng.nfr_coverage
    by_req = {c for r in eng.confirmed_requirements
              for c in r.get("nfr_categories", [])}
    print("\nnon-functional coverage")
    for category in NFR_CATEGORIES:
        entry = coverage.get(category)
        if category in by_req or (entry and entry.get("status") == "covered"):
            state = "covered"
        elif entry is None:
            state = "UNDECLARED"
        else:
            state = entry.get("status", "?")
        print(f"  {category:<15} {state}")
    if eng.open_questions:
        print(f"\nopen questions        {len(eng.open_questions)}")
        for question in eng.open_questions:
            print(f"  {question['id']}  {question['question']}")
    return EXIT_OK


# --- wiring ----------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="archtrace", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--root", default=".", help="engagement directory")
    parser.add_argument("--evidence-root", default=None,
                        help="where evidence CONTENT lives (git-ignored)")
    sub = parser.add_subparsers(dest="command", required=True)

    check = sub.add_parser("check", help="run the deterministic gates")
    check.add_argument("--strict", action="store_true",
                       help="promote warnings to blocking")
    check.set_defaults(fn=cmd_check)

    init = sub.add_parser("init", help="scaffold an engagement")
    init.add_argument("name")
    init.add_argument("--client", default="")
    init.add_argument("--force", action="store_true")
    init.set_defaults(fn=cmd_init)

    promote = sub.add_parser(
        "promote",
        help="confirm a proposed requirement after reading its evidence")
    promote.add_argument("requirement_id")
    promote.add_argument("--yes", action="store_true",
                         help="actually promote; without it this is a dry run "
                              "that shows what you would be attesting to")
    promote.set_defaults(fn=cmd_promote)

    release = sub.add_parser(
        "release", help="bind an approval to an exact model and output state")
    release.add_argument("--approved-by",
                         help="the person accountable for this release")
    release.add_argument("--role",
                         help="the authority under which they approve")
    release.add_argument("--verify", action="store_true",
                         help="check whether the current state still matches "
                              "the approved one; publish only on MATCH")
    release.add_argument("--strict", action="store_true")
    release.add_argument("--allow-dirty", action="store_true")
    release.set_defaults(fn=cmd_release)

    sub.add_parser("render", help="regenerate build outputs").set_defaults(fn=cmd_render)
    sub.add_parser("fmt", help="canonicalise and refresh derived fields").set_defaults(fn=cmd_fmt)
    sub.add_parser("report", help="grounding mix summary").set_defaults(fn=cmd_report)

    baseline = sub.add_parser(
        "baseline", help="SPEC §9a — is this an automation problem at all?")
    baseline.add_argument("--worksheet", help="write the per-element CSV here")
    baseline.add_argument("--elements",
                          help="a plain list of element names from a PAST "
                               "engagement's delivered diagram; emits a blank "
                               "worksheet to fill in by hand")
    baseline.set_defaults(fn=cmd_baseline)

    evidence = sub.add_parser("evidence", help="evidence manifest").add_subparsers(
        dest="evidence_command", required=True)
    add = evidence.add_parser("add", help="register an evidence record")
    add.add_argument("file")
    add.add_argument("--id")
    add.add_argument("--authority", required=True,
                     choices=["stakeholder-confirmed", "authoritative-document",
                              "observed-implementation", "third-party"],
                     help="what the record proves: a stakeholder's statement, a "
                          "signed document, what the code does today, or "
                          "somebody else's claim")
    add.add_argument("--document-owner",
                     help="required for --authority authoritative-document")
    add.add_argument("--effective-date",
                     help="required for --authority authoritative-document")
    add.add_argument("--document-version")
    add.add_argument("--source", required=True,
                     choices=["teams-transcript", "email", "sharepoint",
                              "interview", "document"])
    add.add_argument("--source-uri", required=True,
                     help="URI in the system of record that owns retention")
    add.add_argument("--date", required=True)
    add.add_argument("--participants", nargs="+", required=True)
    add.add_argument("--classification", required=True)
    add.add_argument("--retention-until", required=True)
    add.set_defaults(fn=cmd_evidence_add)

    facts = evidence.add_parser(
        "add-facts", help="register a code-mining facts file as evidence")
    facts.add_argument("file")
    facts.add_argument("--id")
    facts.add_argument("--commit",
                       help="the commit the facts describe; required unless the "
                            "facts file carries one")
    facts.add_argument("--miner", default="archmine",
                       help="what produced the facts (recorded as the participant)")
    facts.add_argument("--source-uri", required=True)
    facts.add_argument("--date", required=True)
    facts.add_argument("--classification", required=True)
    facts.add_argument("--retention-until", required=True)
    facts.set_defaults(fn=cmd_evidence_add_facts)

    mine = sub.add_parser(
        "mine", help="run a code miner over a repository and register its facts")
    mine.add_argument("--id", help="evidence id to assign, e.g. EV-004")
    mine.add_argument("--repo", required=True, help="repository to mine")
    mine.add_argument("--command", default=DEFAULT_MINE_COMMAND,
                      help="how to run the miner, executed with cwd=repo "
                           f"(default: {DEFAULT_MINE_COMMAND!r})")
    mine.add_argument("--facts", default=DEFAULT_FACTS_PATH,
                      help="where the miner leaves its facts file, relative to "
                           f"the repo (default: {DEFAULT_FACTS_PATH})")
    mine.add_argument("--local-name",
                      help="filename for the copy under --evidence-root")
    mine.add_argument("--commit", help="override the resolved commit")
    mine.add_argument("--allow-dirty", action="store_true")
    mine.add_argument("--dry-run", action="store_true",
                      help="print what would run and stop")
    mine.add_argument("--timeout", type=int, default=900)
    mine.add_argument("--miner", default="archmine")
    mine.add_argument("--source-uri", required=True)
    mine.add_argument("--date", required=True)
    mine.add_argument("--classification", required=True)
    mine.add_argument("--retention-until", required=True)
    mine.set_defaults(fn=cmd_mine)

    symbols = sub.add_parser("symbols",
                             help="find a symbol in registered code evidence")
    symbols.add_argument("evidence_id")
    symbols.add_argument("pattern")
    symbols.add_argument("--limit", type=int, default=10)
    symbols.set_defaults(fn=cmd_symbols)

    quote = sub.add_parser("quote", help="resolve a fragment to a byte span")
    quote.add_argument("evidence_id")
    quote.add_argument("fragment")
    quote.add_argument("--speaker")
    quote.set_defaults(fn=cmd_quote)
    return parser


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    if args.evidence_root is None:
        args.evidence_root = os.path.join(args.root, "_evidence_root")
    return args.fn(args)


if __name__ == "__main__":
    raise SystemExit(main())
