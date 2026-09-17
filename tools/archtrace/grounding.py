"""What a *chain* of `derived` groundings adds up to.

G4 validates one grounding entry at a time: the kind is known, the field it
requires is present, and the id it names resolves. That is necessary and it is
not sufficient, because `derived` is the one kind that points at another
element — so the reasons in a model form a graph, and a graph can be locally
valid everywhere and globally meaningless.

Two containers that cite each other as `derived`, each naming a real ADR, pass
G4 on every entry and the whole gate reports "grounded and internally
consistent". Nothing underneath them is a stakeholder requirement, a standard,
an incumbent system or a declared assumption. They are boxes justifying each
other. That is SPEC §5's certified fabrication reached through the derivation
graph rather than through a fabricated quote, and it is invisible to every
rule that reads one entry at a time.

So this module answers the transitive questions:

- **Founded.** Does every chain of `derived` bottom out in a reason that is not
  itself derived? This is the one that blocks (G14).
- **Depth.** How many hops from a real reason is an element? Depth is a smell,
  not a defect: a chain of six says the architecture is being justified by
  other architecture.
- **Assumption taint.** Is every route from an element down to solid ground
  through an `assumption`? The element presents as `derived` — a consequence of
  a documented decision — while resting entirely on a guess.
- **ADR load.** How many elements does a single ADR hold up? If one decision is
  load-bearing for half the model and it turns out wrong, half the model is
  wrong, and nothing else in the tool says so.

Deliberately not a rule engine. The council review that prompted this argued
for a Datalog or ASP-lite layer with stratified negation. The questions above
are reachability and a least fixpoint over a graph of at most a few hundred
nodes; plain iteration answers them in a module that can be read in one sitting
and tested with seeded defects, where an interpreter in the blocking path is
new untested code whose bugs are false BLOCKs and, worse, false passes. The
formalism was not doing any work the graph does not.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass

from .log import get_logger
from .model import Engagement

LOG = get_logger("grounding")

DERIVED = "derived"
ASSUMPTION = "assumption"


def carriers(eng: Engagement) -> Iterator[tuple]:
    """Every (where, grounding) pair in the model, elements then relationships.

    The same traversal G4 does, in the same order, so a G14 finding lands on
    the same `where` string an operator has already seen from G4.
    """
    for element in eng.elements():
        yield element.id, element.grounding
    for rel in eng.relationships:
        yield f"{rel.get('source')}->{rel.get('destination')}", \
            rel.get("grounding", [])


def _targets(grounding: list) -> tuple:
    """Element ids this grounding derives from."""
    return tuple(entry.get("from") for entry in grounding
                 if isinstance(entry, dict) and entry.get("kind") == DERIVED
                 and entry.get("from"))


def _grounded_outright(grounding: list, through: frozenset) -> bool:
    """True when some entry is a reason in its own right rather than a pointer.

    `through` names the kinds that do NOT count as solid ground for the
    question being asked. For foundedness that is `derived` alone. For
    assumption taint it is `derived` and `assumption` together, which is the
    whole difference between the two analyses — one predicate, asked twice.
    """
    return any(isinstance(entry, dict) and entry.get("kind")
               and entry.get("kind") not in through
               for entry in grounding)


def _reaches(edges: dict, seeds: set) -> frozenset:
    """Least fixpoint: `seeds`, plus anything deriving from something in it.

    Iterate to a fixpoint rather than condensing the graph and sorting it
    topologically. Both are correct; this one is three lines, has no ordering
    to get wrong, and terminates on a cyclic graph by construction because the
    settled set only ever grows. Architecture models are tens to hundreds of
    elements, so the quadratic worst case is not a cost anyone can measure.
    """
    settled = set(seeds)
    changed = True
    while changed:
        changed = False
        for node, targets in edges.items():
            if node not in settled and any(t in settled for t in targets):
                settled.add(node)
                changed = True
    return frozenset(settled)


def _depths(edges: dict, seeds: set) -> dict:
    """Hops from each node to the nearest node that stands on its own.

    Breadth-first, so the number is the SHORTEST justification path. An element
    with one short route and one long one is as well founded as its best route,
    which is the reading that does not punish an architect for recording extra
    reasons.
    """
    depth = dict.fromkeys(seeds, 0)
    frontier, hop = set(seeds), 0
    while frontier:
        hop += 1
        reached = {node for node, targets in edges.items()
                   if node not in depth and any(t in frontier for t in targets)}
        for node in reached:
            depth[node] = hop
        frontier = reached
    return depth


def _cycles(edges: dict) -> tuple:
    """Strongly connected components of size > 1, plus self-derivations.

    Tarjan, iterative. Recursion would be the shorter spelling and would blow
    the stack on a pathological model, which is precisely the input this
    function exists to describe; a gate that crashes on the defect it is
    hunting reports nothing at all.

    An SCC is exactly the right shape for the message: every element in it can
    reach every other, so "these derive from each other" is true of the whole
    set without having to pick one elementary cycle out of many.
    """
    index: dict = {}
    low: dict = {}
    on_stack: set = set()
    stack: list = []
    found: list = []
    counter = 0

    for root in sorted(edges):
        if root in index:
            continue
        # Each frame is (node, iterator over its targets). Popping a frame is
        # the point at which recursion would have returned, so that is where
        # the low-link is propagated to the parent.
        work: list = [(root, iter(edges.get(root, ())))]
        index[root] = low[root] = counter
        counter += 1
        stack.append(root)
        on_stack.add(root)
        while work:
            node, targets = work[-1]
            advanced = False
            for target in targets:
                if target not in edges:
                    continue  # dangling; G4 reports it, this is not its job
                if target not in index:
                    index[target] = low[target] = counter
                    counter += 1
                    stack.append(target)
                    on_stack.add(target)
                    work.append((target, iter(edges.get(target, ()))))
                    advanced = True
                    break
                if target in on_stack:
                    low[node] = min(low[node], index[target])
            if advanced:
                continue
            work.pop()
            if work:
                parent = work[-1][0]
                low[parent] = min(low[parent], low[node])
            if low[node] != index[node]:
                continue
            component = []
            while True:
                member = stack.pop()
                on_stack.discard(member)
                component.append(member)
                if member == node:
                    break
            if len(component) > 1 or node in edges.get(node, ()):
                found.append(tuple(sorted(component)))
    return tuple(sorted(found))


@dataclass(frozen=True)
class Analysis:
    """Everything the derivation graph says, computed once."""

    edges: dict
    founded: frozenset
    unfounded: tuple
    depth: dict
    tainted: tuple
    cycles: tuple
    adr_load: dict

    @property
    def max_depth(self) -> int:
        return max(self.depth.values(), default=0)

    def cycle_containing(self, where: str) -> tuple | None:
        """The derivation cycle `where` sits in, when it sits in one.

        Returned so a finding can name the loop instead of announcing that an
        element is unfounded and leaving the operator to trace the chain by
        hand. An unfounded element with no cycle is a different defect with a
        different fix, and the message should not have to guess which it is.
        """
        return next((c for c in self.cycles if where in c), None)


def analyse(eng: Engagement) -> Analysis:
    """Resolve the derivation graph into foundedness, depth, taint and load."""
    edges = {element.id: _targets(element.grounding)
             for element in eng.elements()}

    solid = {eid for eid, grounding in
             ((e.id, e.grounding) for e in eng.elements())
             if _grounded_outright(grounding, frozenset({DERIVED}))}
    founded = _reaches(edges, solid)

    # The same fixpoint with `assumption` demoted out of solid ground. An
    # element is tainted when it IS founded but every route down to a reason
    # passes through a declared guess: it presents as a consequence of a
    # documented decision while resting on nothing firmer than an open
    # question. Untainted-and-unfounded is not a case -- unfounded is strictly
    # worse and G14 reports it -- so taint is scoped to the founded set.
    firm = {eid for eid, grounding in
            ((e.id, e.grounding) for e in eng.elements())
            if _grounded_outright(grounding, frozenset({DERIVED, ASSUMPTION}))}
    assumption_free = _reaches(edges, firm)

    unfounded = []
    for where, grounding in carriers(eng):
        if not grounding:
            continue  # G4 owns the empty case and says it better
        if _grounded_outright(grounding, frozenset({DERIVED})):
            continue
        if not any(target in founded for target in _targets(grounding)):
            unfounded.append(where)

    adr_load: dict = {}
    for _where, grounding in carriers(eng):
        for entry in grounding:
            if isinstance(entry, dict) and entry.get("kind") == DERIVED \
                    and entry.get("adr"):
                adr_load[entry["adr"]] = adr_load.get(entry["adr"], 0) + 1

    analysis = Analysis(
        edges=edges,
        founded=founded,
        unfounded=tuple(sorted(unfounded)),
        depth=_depths(edges, solid),
        tainted=tuple(sorted(founded - assumption_free)),
        cycles=_cycles(edges),
        adr_load=adr_load,
    )
    LOG.debug("derivation graph: %d element(s), %d unfounded, %d cycle(s), "
              "max depth %d", len(edges), len(analysis.unfounded),
              len(analysis.cycles), analysis.max_depth)
    return analysis
