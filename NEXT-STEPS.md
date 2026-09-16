# Next steps

Ordered by what is actually blocking, not by what is most fun to build.

## Blocking — nothing here is worth doing until this happens

**1. Run SPEC §9a on a real engagement.** Still not done, across every session
this design has existed. One day, a spreadsheet, no code:

```bash
./archtrace baseline --elements my-last-diagram.txt --worksheet ws.csv
```

Under 20% UNEXPLAINED and the programme is worth running. Over, and this
pipeline would industrialise an ungrounded practice at speed rather than close
it. **Every item below assumes this passed.**

**2. Answer the consent and retention question.** Before a real transcript
touches a disk: who owns retention on the evidence root, does meeting-recording
consent permit downstream automated processing, and is a 25-word verbatim quote
from a confidential recording itself confidential? The repo deliberately cannot
hold the content; something has to.

## Known gaps, in priority order

**3. Lucid round-trip is unverified.** Thirty-minute spike. Lucid's docs
conflict on whether a hand-assembled `mxfile` imports at all, and it states it
prioritises functional over visual fidelity — meaning it may discard the
coordinates the whole layout-in-the-model design depends on. If it fails, the
fallback reintroduces a manual step the design claims to have removed.

**4. `architecture.docx` has no diagrams.** Named increment: emit native
DrawingML shapes into `document.xml` from the same layout coordinates the SVG
uses. Pure stdlib, editable in Word, roughly 200 lines. It is the single
highest-value renderer left, because it turns the Word deliverable from an
appendix into the artifact.

**5. archmine Phase 3 — durable symbol identity.** `_id()` hashes
`path:kind:name:line`, so inserting a line above a symbol changes its id and a
model that cited it last month fails G13 this month for no architectural reason.
Prefer content-addressed ids (hash the normalised body) over a resolver that
silently repairs broken citations — a fallback that heals a broken citation is a
gate that has stopped meaning anything.

**6. Send `docs/patches/archmine-a1-a2.patch` upstream.** Verified: it makes all
four of archmine's artifacts deterministic and populates `commit`. The stamping
fallback keeps working either way and becomes a no-op once it lands.

## Deferred, with reasons

**7. archmine Phase 4 — the MCP server.** Additive, not load-bearing: facts
still arrive as a hashed file, so the gate is unaffected. But it gives an agent
live query access to the symbol graph, which is a new trust surface. Hold it to
the adapter contract tests in `REVIEW.md` first.

**8. Branch coverage.** The stdlib tracer gives line coverage only, so a
half-tested `if` counts as covered. Adding branch coverage means either
`coverage.py` as an optional dev path — which splits the number between
environments — or a `sys.monitoring` implementation on 3.12+. Neither is worth
it before §9a passes.

**9. Deployment view in the C4 model.** Deferred deliberately: deployment
elements (regions, clusters, nodes) are almost entirely `derived`/`standard`
grounding, so the view is cheap to add and easy to fill with unexamined boxes.

## Explicitly not doing

- **numpy.** There is no numerical code. Adding it would break the
  zero-dependency invariant to no end.
- **Adopting archmine's `architecture.yml`.** Its drift gate cannot pass (A1),
  and one blocking gate is the design.
- **An LLM anywhere in the critical path.** If every agent is unavailable you
  author the same JSON by hand and the gate, renders and traceability all still
  work. That is the property that makes the rest defensible.
