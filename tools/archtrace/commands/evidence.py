"""Evidence intake: prose, code-mining facts, and citation resolution."""

from __future__ import annotations

import os
import sys
from typing import Any

from .. import canon
from ..config import DEFAULT as CONFIG
from ..log import get_logger
from ..model import (
    SCHEMA_VERSION,
)
from ._shared import EXIT_BLOCKED, EXIT_OK, EXIT_USAGE, git
from ._shared import engagement as _engagement

LOG = get_logger("evidence")

def _register_facts(args, raw: bytes, local_path: str, commit: str,
                    facts, evidence_id: str | None = None) -> str:
    """Write one structured evidence record. Shared by `mine` and `add-facts`
    so the two paths cannot drift apart."""
    from ..mining import CONTENT_STRUCTURED, sha256_bytes

    index_path = os.path.join(args.root, "evidence", "index.json")
    index: dict[str, Any] = (
        canon.load_json(index_path) if os.path.isfile(index_path)
        else {"schema_version": SCHEMA_VERSION, "evidence": []})
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
    from ..mining import summarise
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

DEFAULT_MINE_COMMAND = CONFIG.mining.command

DEFAULT_FACTS_PATH = CONFIG.mining.facts_path

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

    from ..mining import FactsError, parse_facts

    repo = os.path.abspath(os.path.expanduser(args.repo))
    if not os.path.isdir(repo):
        print(f"archtrace: {repo} is not a directory", file=sys.stderr)
        return EXIT_USAGE

    commit = args.commit or git(repo, "rev-parse", "HEAD")
    dirty = git(repo, "status", "--porcelain")
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
        completed = subprocess.run(  # noqa: S602
            # shell=True is the point: the command is operator-supplied via flags
            # or the Makefile, and never derived from evidence content.
            args.command, cwd=repo, shell=True,  # nosec
            capture_output=True, text=True, timeout=args.timeout,
            check=False)
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
    from ..mining import FactsError, parse_facts

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

def cmd_evidence_add(args) -> int:
    index_path = os.path.join(args.root, "evidence", "index.json")
    index: dict[str, Any] = (
        canon.load_json(index_path) if os.path.isfile(index_path)
        else {"schema_version": SCHEMA_VERSION, "evidence": []})
    local = os.path.relpath(args.file, args.evidence_root)
    with open(args.file, encoding="utf-8") as fh:
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
