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

**2b. Configuration resolved from the process working directory, not from
`--root`** — **fixed.** `cd engagements/aurora && archtrace check` read no
configuration; `cd ~ && archtrace --root /work/proj check` applied
`~/archtrace.toml`; and a legitimate `archtrace.toml` at this repository's root
turned 26 of its own tests red. Config now resolves to the nearest repository
marker, `cli.main` re-resolves from `--root` after argparse, and the suite pins
the policy it asserts against rather than inheriting the ambient one. See
`docs/tech-debt.md` §0 for what deliberately stays open: configuration is still
one-repository-one-policy, not per-engagement.

**2a. The test suite has a 50% mutation score, and the survivors are not
random.** Measured, not estimated: 208 single-line mutations applied to a frozen
tree, each run against the full suite. 104 survived. The distribution is what
makes this urgent rather than merely untidy — **29 of the survivors are gate
rule branches whose blocking `Finding` has never once fired in a test run.**
G1's duplicate-evidence-id check, G3's status/type/priority validation, G4's
unknown-standard and unknown-ADR checks, G5's duplicate-id and duplicate-uid
checks, G6's missing-file and stray-file findings, G13's unknown-record check:
all deletable, suite green. Two rules can have their entire relationship loop
replaced with `for rel in []` — relationship grounding and relationship symbol
citations are unchecked by any test.

Three survivors were fixed in this pass: the release signing path, `fmt` as a
no-op, and the documentation-diagram guards. **Every item below was reproduced
by hand before being written down** — the audit was run by a subagent, and a
finding about this repository's own controls is exactly the kind of claim it
would be embarrassing to repeat without checking. The backlog, in order:

1. ~~**`assertFires(rule, where=...)`**~~ — **done.** The helper asserted only
   that a rule id appeared *somewhere*, across 35 call sites. Inverting G2's
   speaker check left `test_g2_speaker_not_in_the_room` passing: G2 still fired,
   on the four requirements whose speakers *are* participants, for the opposite
   reason. `where` and `message` are now threaded through every site, harvested
   from the findings the rules actually emit rather than written from memory.
   Six predicates verified killed by their own test. **This was the
   prerequisite for everything below it** — there was no point writing tests for
   the 29 dead branches while the helper could not tell which finding it caught.
2. **`tools/tests/support.py`.** `sys.path.insert` is copied 7 times,
   `mkdtemp` 20, `copytree(EXAMPLE)` 12, and `run_cli` exists in five divergent
   variants. The duplication is not the cost; the drift is — two copies of
   `assertFires` have already diverged, and the policy pin added for
   `docs/tech-debt.md` §0 is now a third thing copied into four `setUp`s.
2a. ~~**The 29 dead gate branches**~~ — **27 of them done.** Each has a
   seeded-defect test, each verified by re-seeding the branch it guards: 27 of
   27 killed, coverage 94% → 95%.

   The two worst were G4's and G13's relationship loops: both end with
   `for rel in eng.relationships` and both could be replaced with
   `for rel in []` while the entire suite passed, so **half the model's
   citations — the ten grounded relationships in the worked example — were
   ungated by any test.**

   Writing G2's stoplist test turned up that the stoplist **cannot fire alone at
   default settings**: every phrase in it is below both floors, and the floor
   check does not `continue`. It is redundant unless the floors are lowered.
   Left as-is (a policy question, not a defect) with a test that fails if that
   relationship changes.

   The last two were a pair, and closing them turned out to be closing a
   *contract*: G13 skips a symbol whose facts file will not parse, with the
   comment "G1 already reported the unreadable facts file". Nothing checked
   that G1 does. With G1's branch deleted the file is unreadable, G13 stays
   quiet on its own authority, and the gate passes an engagement whose code
   citations resolve against nothing. Both halves are now asserted in one test —
   G1 must speak, and G13 must not speak twice.

   **§2a is now closed: 29 of 29.**
3. ~~**One true end-to-end test**~~ — **done.** `FullLifecycle` drives a
   scaffolded engagement through `init → evidence add → quote → promote →
   model → fmt → render → check → release → verify` to a green gate and a
   MATCH, then edits a render and asserts both `--verify` and G6 refuse it.
   It is the first test to use `quote` as an input rather than hand-computing
   the span.

   **Measured five mutations killed, not the nine the audit projected** — and
   two of the five it listed turned out to be untestable rather than untested:
   `quote`'s `quote_cached` is `text[start:end]` where `start = text.find(
   needle)` and `needle` is already normalised, so emitting `needle` instead is
   an *equivalent* mutant. Worth recording, because "nine survivors" would have
   been repeated as a result rather than a projection.
4. ~~**`canon.normalize` is under-specified by its tests**~~ — **done, and it
   was hiding a live defect.** Removing the NFKC call entirely left the suite
   green, as did the `stable_uid` separator, the `modified`-attribute strip and
   zip entry ordering. Asserting the *whole* fold table rather than a sample
   found that `″` (DOUBLE PRIME) never folded at all: NFKC decomposes it to two
   PRIMEs before the table runs, so `6″` and `6"` normalised differently and a
   citation using one never matched a quote using the other. Fixed, with a
   general check for any future key NFKC decomposes. Two smaller claims were
   also false: the table's comment about what NFKC does, and
   `deterministic_zip`'s compression, which the line that looked load-bearing
   did not actually control.
5. **`release` will sign an engagement with zero confirmed requirements.**
   Reproduced: `init` a scaffold, `release`, `--verify` → MATCH, exit 0, with
   `"confirmed_requirements": []` in the manifest. `check` refuses to call that
   state clean ("an empty pass, not a clean one"); `release` signs it anyway.
6. **Malformed JSON in any source document is a raw traceback, not a refusal**
   (T5). `printf '{ this is not json' > model/model.json && archtrace check`
   → `json.decoder.JSONDecodeError` on stderr and exit 1. Exit 1 means
   "blocked", which CI reads as a gate finding; this is a usage error and
   SPEC §exit-codes says 2.
7. **`retention_until`, `date` and `classification` are never format-checked.**
   Reproduced: `retention_until="not-a-date"` together with
   `classification="<script>alert(1)</script>"` gives `0 blocking, 0 warning`.
   G1 tests truthiness only, so a retention obligation the repository claims to
   record can be an arbitrary string.

**2c. Calibrate the advisory thresholds on a real engagement — after §9a, not
before.** `near_floor_margin_words`, `deep_derivation_hops`,
`adr_load_share_pct` and `evidence_share_pct` are judgements printed by
`archtrace config`, and every one of them is currently a guess. They cannot be
calibrated here: `example/` is synthetic and `archtrace-self` is this tool
modelling itself, so both were authored with their evidence in one sitting.
Scoring them measures consistency, not grounding — §9a's own caveat. The same
bar blocks an NLI support-scorer distribution, and for the same reason; see
SPEC §13.5. The 60% traceability threshold was disproved by running the
instrument on real output, and these deserve no less.

**3. Lucid round-trip is unverified.** Thirty-minute spike. Lucid's docs
conflict on whether a hand-assembled `mxfile` imports at all, and it states it
prioritises functional over visual fidelity — meaning it may discard the
coordinates the whole layout-in-the-model design depends on. If it fails, the
fallback reintroduces a manual step the design claims to have removed.

**4. archmine Phase 3 — durable symbol identity.** `_id()` hashes
`path:kind:name:line`, so inserting a line above a symbol changes its id and a
model that cited it last month fails G13 this month for no architectural reason.
Prefer content-addressed ids (hash the normalised body) over a resolver that
silently repairs broken citations — a fallback that heals a broken citation is a
gate that has stopped meaning anything.

**5. Send `docs/patches/archmine-a1-a2.patch` upstream.** Verified: it makes all
four of archmine's artifacts deterministic and populates `commit`. The stamping
fallback keeps working either way and becomes a no-op once it lands.

### Done

**`architecture.docx` now carries its diagrams** (`tools/archtrace/docx_shapes.py`,
renderer 1.2.0). Native DrawingML shapes from the same layout coordinates the SVG
uses: no rasteriser, so the zero-dependency invariant holds, and they land in Word
as real shapes rather than a flattened image. Verified by converting the rendered
document with LibreOffice and reading the result, not by assuming the XML was
right — the escaping test caught a name containing a double quote producing a
document Word would have called corrupt.

Two limits stand, both documented in SPEC §6: text does not reflow to fit its box,
and edge labels are omitted. The `.svg` remains the high-fidelity surface.

## Deferred, with reasons

**6. archmine Phase 4 — the MCP server.** Additive, not load-bearing: facts
still arrive as a hashed file, so the gate is unaffected. But it gives an agent
live query access to the symbol graph, which is a new trust surface. Hold it to
the adapter contract tests in `REVIEW.md` first.

**7. Branch coverage.** The stdlib tracer gives line coverage only, so a
half-tested `if` counts as covered. Adding branch coverage means either
`coverage.py` as an optional dev path — which splits the number between
environments — or a `sys.monitoring` implementation on 3.12+. Neither is worth
it before §9a passes.

**8. Deployment view in the C4 model.** Deferred deliberately: deployment
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
