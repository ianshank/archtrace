"""The deterministic gate and the SPEC §9a baseline instrument."""

from __future__ import annotations

import os
import sys

from .. import gate
from ..config import DEFAULT as CONFIG
from ..log import get_logger
from ..model import (
    NFR_CATEGORIES,
    RENDERER_VERSION,
)
from ._shared import EXIT_BLOCKED, EXIT_OK, EXIT_USAGE
from ._shared import engagement as _engagement

LOG = get_logger("verify")

def cmd_check(args) -> int:
    eng = _engagement(args)
    only = getattr(args, "only", None)
    try:
        findings, code = gate.run(eng, strict=args.strict, only=only)
    except ValueError as exc:
        print(f"archtrace: {exc}", file=sys.stderr)
        return EXIT_USAGE
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
    elif only:
        # A subset run must never claim what a full run claims. "Grounded and
        # internally consistent" is a statement about every rule; printing it
        # after `--only G6` would be the same false green in a smaller costume.
        # It must not swallow warnings either: `--only G12` exits 0 with a WARN
        # outstanding, and reporting that as simply "passed" is the same defect
        # one level down.
        selected = ", ".join(sorted(only))
        outstanding = (f", {len(warns)} warning(s) outstanding" if warns else "")
        print(f"archtrace: {selected} passed{outstanding}. This was a SUBSET "
              "of the gate — it says nothing about the rules that did not run.")
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
    rows: list = []
    quotable = 0
    by_kind: dict = {}
    for element in elements:
        kinds = [g.get("kind") for g in element.grounding]
        # `by_kind` breaks down the SAME bucket `otherwise` counts below, so it
        # must tally exactly the elements `otherwise` does (no `satisfies`
        # present), once each, regardless of how many grounding entries an
        # element carries. Counting every entry double-counts an element that
        # cites two pieces of evidence for the same kind (both real; each
        # entry is independently gate-checked), and would also count an entry
        # belonging to an element that DOES have `satisfies` and so is not in
        # this bucket at all. Either way the per-kind rows would no longer sum
        # to the subtotal printed above them.
        if kinds and "satisfies" not in kinds:
            for kind in set(kinds):
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
    if unexplained_pct > CONFIG.baseline.max_unexplained_pct:
        ok = False
        print(f"  [STOP]  unexplained {unexplained_pct}% vs <= "
              f"{CONFIG.baseline.max_unexplained_pct}%")
        print("          Elements you can neither quote nor justify. The problem "
              "was never\n          automation — this pipeline would "
              "industrialise that gap at speed.")
    else:
        print(f"  [PASS]  unexplained {unexplained_pct}% vs <= "
              f"{CONFIG.baseline.max_unexplained_pct}%")
    if backed < CONFIG.baseline.min_citation_backed_pct:
        ok = False
        print(f"  [FIX]   {backed}% of requirement-linked elements have a real "
              "quote behind them")
        print("          An element claiming to satisfy a requirement that has "
              "no citation is\n          the exact fabrication this gate exists "
              "to stop.")
    else:
        print(f"  [PASS]  every requirement-linked element has a real quote "
              f"({claims_req}/{claims_req})")
    if coverage < CONFIG.baseline.min_coverage_pct:
        ok = False
        print(f"  [FIX SCHEMA] coverage {coverage}% vs >= "
                  f"{CONFIG.baseline.min_coverage_pct}%")
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

    with open(args.elements, encoding="utf-8") as fh:
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


DEFAULT_AGENT_DIR = os.path.join(".github", "agents")


def cmd_agents(args) -> int:
    """Validate agent definitions deterministically.

    Agent files encode controls -- read-only invocation, the
    evidence-is-not-instruction rule, no authority claims -- as prose. Prose
    drifts. This makes the drift a build failure instead of a surprise.
    """
    from ..agents import CHECKS, discover, validate

    directory = args.directory or DEFAULT_AGENT_DIR
    paths = discover(directory)
    if not paths:
        print(f"archtrace: no *.agent.md under {directory}", file=sys.stderr)
        return EXIT_USAGE
    findings = validate(directory)
    for finding in findings:
        print(finding)
    print(f"\n{len(paths)} agent definition(s), {len(CHECKS)} check(s), "
          f"{len(findings)} finding(s)")
    if findings:
        print("agent validation FAILED — a control that only lives in prose is "
              "a control nobody is enforcing.")
        return EXIT_BLOCKED
    for path in paths:
        print(f"  ok  {os.path.basename(path)}")
    return EXIT_OK
