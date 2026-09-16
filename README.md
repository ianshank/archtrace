# archtrace

The architecture model lives in git. Everything downstream is a build output.

Your current source of truth is the rendered artifact — the draw.io file, the
Lucid board, the Word doc. That is why every revision loop destroys prior work,
and why the last step of your workflow feels like cleanup. archtrace inverts it:
the model is authoritative, renders are disposable, traceability is a required
field rather than an appendix, and a deterministic gate refuses to merge an
artifact that is ungrounded, uncited or hand-edited.

`SPEC.md` is the design and the argument. `REVIEW.md` is what an adversarial
review found in the first draft and what changed as a result. **`docs/workflow-mapping.md` maps
it onto your existing ten-step workflow**, and **`RUNBOOK.md` is
how you actually operate it day to day** — start there if you want to use it
rather than evaluate it.

## Run it

```bash
make help              # every target, grouped by whether it needs dependencies
make check             # the gates, against the bytes AS COMMITTED
make freshness         # G6 for every engagement discovered in the repo
make engagements       # list what freshness discovered
make gate              # fmt + render + check, the pre-publish loop
make test              # runs the suite
make coverage          # the suite under the stdlib tracer, against floors
make agents            # deterministic validation of the agent definitions
make config            # print the thresholds this build actually enforces
make docs              # regenerate the documentation diagrams
make pre-pr            # everything, cheapest-first (11 steps)

./archtrace --root engagements/aurora init "Project Aurora"   # a real one
```

`check` before `gate`, deliberately. `gate` is `fmt render check` — it
regenerates every artifact before checking it, so a hand edit to `render/` is
overwritten rather than reported. `check` reads the bytes as committed and is
the only one of the two that can fail on a tampered deliverable; `freshness`
asks that question of every engagement in the repository rather than just one.

Python 3.9+, standard library only. No pip, no venv, no Java, no Node, no
pandoc, no drawio CLI, no Structurizr CLI, no setup step in CI. CI proves that
by diffing `pip list` either side of the gate job and failing if anything was
installed.

`ruff` and `mypy` are development tooling in the `dev` extra; nothing in the
package imports them, and `tools/tests/test_mining.py::DependencyBoundary`
fails the build if that ever changes.

`docs/tech-debt.md` is the gap analysis, the defects this pass found, and what
is knowingly left. `CHANGELOG.md` and `NEXT-STEPS.md` say what changed and what
is blocking. `docs/archmine-integration.md` is the plan for folding a code miner in — what it
adds, the four conflicts, and the phase that is already built.
`docs/architecture.svg` is the platform on one page — the deterministic core,
where the two human gates sit, and what is deliberately **not** built.
`docs/workflow-sequence.svg` is the operating model on one page — three loops,
two human gates, and where the deterministic gate sits relative to the advisory
one. `docs/workflow-sequence.mmd` is the editable source (GitHub renders mermaid
`sequenceDiagram` natively, unlike the C4 extension); `docs/gen_sequence.py`
emits the SVG when layout control matters more than editability.

## The five-minute tour

```
evidence/index.json         claims about evidence — never the content itself
requirements/*.json         REQ records with verifiable byte-span citations
model/model.json            C4 elements, relationships, ADRs, out-of-scope
render/                     generated; a hand edit fails `make check`
.github/agents/*.agent.md   three read-only agents; none of them can gate
```

## The two decisions worth arguing about

**1. An element does not need a requirement — it needs a *reason*.**

The obvious design says every model element must trace to a stakeholder
requirement. It is wrong, and it is dangerous. Real architectures are full of
things nobody asked for: load balancers, telemetry sidecars, secret stores, the
platform team's mandated WAF, and the incumbent system you integrate with
because it exists. Under a satisfies-only rule the architect's only escape is to
invent a requirement — which then has to pass the citation check, so they go find
a real but loosely-related sentence to attach. The gate would end up
*manufacturing a verbatim-certified provenance record for a requirement nobody
ever stated*. That is strictly worse than no gate: an ungrounded element is
visibly ungrounded; a certified fabrication is invisible.

So grounding has a kind: `satisfies`, `derived` (+ADR), `standard`, `existing`,
`assumption` (+open question). The distribution is the quality signal, and
`archtrace report` prints it. **A model that is 100% `satisfies` is the
suspicious one.**

**2. Citation integrity is not hallucination detection, and this repo says so
out loud.**

The gate proves a quote is real, long enough to mean something, and attributed
to someone who was in the room. It proves nothing about whether the quote
*supports* the requirement drawn from it. That gap is closed by a human commit
promoting `proposed` to `confirmed` — nothing else. The gate makes output
grounded and internally consistent. Correctness is still yours.

## Authoring a citation

Never type a quote into JSON by hand. A verbatim transcript quote is the worst
possible payload for hand-authored JSON, and a mistake surfaces as a provenance
failure rather than a syntax error.

```bash
./archtrace --root example quote EV-001 "if the feed drops for half a day"
```

That resolves the fragment against the *normalised* evidence and prints a
provenance block with a verifiable byte span. Normalisation matters more than it
sounds: real Teams exports wrap sentences mid-line and use curly apostrophes,
and `unicodedata.normalize("NFKC", …)` does **not** fold `’` to `'` or strip
zero-width characters. Without folding at intake, the citation gate blocks
nearly every requirement and gets switched off in week two.

## What is deliberately not here

- **Evidence content.** A git repository cannot satisfy a retention obligation,
  and deleting a file does not delete the blob. The repo holds the manifest; the
  content stays in the system of record that owns its lifecycle, reached through
  `--evidence-root`.
- **Raster or vector *images* in the Word document.** Embedding a picture needs
  Node or the drawio CLI. Diagrams ship instead as native DrawingML shapes
  emitted from the same layout coordinates the SVG uses — real Word shapes, no
  rasteriser — with `.svg`, `.drawio` and Lucid as the high-fidelity surfaces.
- **Any LLM in the critical path.** If every agent is unavailable, you author the
  same JSON by hand and the gate, the renders and the traceability all still
  work.
- **An LLM gate.** `review/advisory.md` is advisory and always exits 0.

## Known limits

- One `layout` per element across all views, so an element that appears in both
  the context and container diagram uses the same coordinates in each. Fine for
  small models; add per-view layout when it stops being fine.
- Mermaid C4 is emitted as a convenience only. **GitHub does not render it**, and
  its syntax has been officially experimental since 2022. The reviewable diagram
  is the generated SVG, which GitHub does render inline in a PR.
- The Lucid round-trip is **unverified**. Lucid's own docs conflict on whether a
  hand-assembled `mxfile` imports at all, and it states it prioritises functional
  over visual fidelity — meaning it may discard your coordinates. Spike this for
  thirty minutes before relying on it.

## Before you install anything

```bash
./archtrace baseline --elements my-last-diagram.txt   # blank worksheet, no code
./archtrace --root example baseline                   # see it on the example
```

List every element off your last delivered C4 diagram. Find a quotable
stakeholder statement for each, and where there is none, say why the element is
there. **The decision number is UNEXPLAINED — over 20% and stop.** The problem was
never automation; the artifacts were not grounded to begin with.

Raw traceability is informational, not a bar. The worked example scores **50% and
is healthy**: half of it is an edge tier, a sidecar, a worker and an incumbent
system that legitimately have no stakeholder requirement. v1 of the spec made 60%
a stop condition; running the instrument proved that wrong, and
`docs/example-baseline.txt` is the output that showed it.
