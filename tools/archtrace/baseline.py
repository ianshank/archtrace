"""The SPEC §9a instrument: measurement and decision, with no printing.

This lived inside `cmd_baseline` as 156 lines interleaving arithmetic with 54
`print` calls, which meant the numbers that decide whether the whole programme
is worth running existed only on stdout. A test could assert what the command
*said*, never what it *computed* -- and §9a is the one measurement NEXT-STEPS
calls blocking, so it is the worst thing in the codebase to have been unable to
test directly.

Splitting it here also gives the numbers somewhere to be reused from. The
baseline's own citation count currently disagrees with G2's -- it counts any
non-empty `quote_cached` while G2 additionally enforces a word floor, a
character floor and a generic-phrase stoplist -- so the instrument that decides
whether to run the programme can report a PASS on citations the gate would
refuse. Fixing that means importing the gate's thresholds, which is a change to
this module rather than to a function that prints things.

Nothing here writes to stdout or touches the filesystem. `commands/verify.py`
owns the presentation.
"""

from __future__ import annotations

from dataclasses import dataclass

from .model import Engagement


@dataclass(frozen=True)
class Baseline:
    """What §9a measured. Every field is a count; percentages are derived.

    `rows` stays a list of plain dicts because it is also the worksheet CSV,
    whose column order comes from the first row's key order.
    """

    rows: list
    by_kind: dict
    total: int
    quotable: int
    claims_req: int
    otherwise: int
    unexplained: int
    confirmed: int
    accounted: int

    @property
    def traceability(self) -> int:
        """Informational, deliberately not a bar. v1 made this a >= 60% stop
        condition; running the instrument showed that fails a healthy
        infrastructure-heavy architecture."""
        return _pct(self.quotable, self.total)

    @property
    def unexplained_pct(self) -> int:
        """The decision number: elements you can neither quote nor justify."""
        return _pct(self.unexplained, self.total)

    @property
    def otherwise_pct(self) -> int:
        return _pct(self.otherwise, self.total)

    @property
    def backed(self) -> int:
        """Of the elements claiming to satisfy a requirement, how many rest on
        a real quote. An empty numerator over an empty denominator is 100:
        nothing claimed, so nothing is unbacked."""
        return _pct(self.quotable, self.claims_req, empty=100)

    @property
    def coverage(self) -> int:
        """Confirmed requirements that are modelled or explicitly out of scope.
        Empty is 0, not 100 -- an engagement with no confirmed requirements has
        not covered them, it has not got any."""
        return _pct(self.accounted, self.confirmed, empty=0)


def _pct(part: int, whole: int, empty: int = 0) -> int:
    """Integer percent, with the caller stating the empty-denominator answer.

    The three call sites above want three different answers for an empty
    denominator, and getting that wrong silently is how a measurement reports
    100% of nothing.
    """
    return empty if not whole else 100 * part // whole


def measure(eng: Engagement) -> Baseline:
    """Score an engagement against §9a. Pure: no I/O, no printing."""
    elements = list(eng.elements())
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
        # cites two pieces of evidence for the same kind (both real; each entry
        # is independently gate-checked), and would also count an entry
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

    modelled = eng.requirements_grounded()
    # `.get("req")` rather than `["req"]`: an out_of_scope entry missing its
    # `req` is G3's finding to report, and indexing here raised a KeyError that
    # took the whole command down before G3 could say anything.
    excluded = {o.get("req") for o in eng.out_of_scope}
    return Baseline(
        rows=rows,
        by_kind=by_kind,
        total=len(elements),
        quotable=quotable,
        claims_req=sum(1 for r in rows if "satisfies" in r["grounding_kinds"]),
        otherwise=sum(1 for r in rows if r["grounding_kinds"]
                      and "satisfies" not in r["grounding_kinds"]),
        unexplained=sum(1 for r in rows if not r["grounding_kinds"]),
        confirmed=len(confirmed),
        accounted=len([r for r in confirmed if r in modelled or r in excluded]),
    )


@dataclass(frozen=True)
class Verdict:
    """The three decision rules, and whether they passed.

    `lines` carries the rendered output so the presentation stays byte-identical
    to what `cmd_baseline` printed inline, while the pass/fail is available to a
    caller that does not want the prose.
    """

    passed: bool
    lines: tuple


def decide(baseline: Baseline, policy) -> Verdict:
    """Apply the §9a decision rules. `policy` is a `config.BaselinePolicy`."""
    lines: list = []
    ok = True

    if baseline.unexplained_pct > policy.max_unexplained_pct:
        ok = False
        lines.append(f"  [STOP]  unexplained {baseline.unexplained_pct}% vs <= "
                     f"{policy.max_unexplained_pct}%")
        lines.append("          Elements you can neither quote nor justify. The "
                     "problem was never\n          automation — this pipeline "
                     "would industrialise that gap at speed.")
    else:
        lines.append(f"  [PASS]  unexplained {baseline.unexplained_pct}% vs <= "
                     f"{policy.max_unexplained_pct}%")

    if baseline.backed < policy.min_citation_backed_pct:
        ok = False
        lines.append(f"  [FIX]   {baseline.backed}% of requirement-linked "
                     "elements have a real quote behind them")
        lines.append("          An element claiming to satisfy a requirement "
                     "that has no citation is\n          the exact fabrication "
                     "this gate exists to stop.")
    else:
        lines.append("  [PASS]  every requirement-linked element has a real "
                     f"quote ({baseline.claims_req}/{baseline.claims_req})")

    if baseline.coverage < policy.min_coverage_pct:
        ok = False
        lines.append(f"  [FIX SCHEMA] coverage {baseline.coverage}% vs >= "
                     f"{policy.min_coverage_pct}%")
    else:
        lines.append(f"  [PASS]  coverage {baseline.coverage}%")

    return Verdict(passed=ok, lines=tuple(lines))
