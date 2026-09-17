# Changelog

Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
Versioning is semantic, with one project-specific rule: **a new blocking gate
rule is a MINOR bump, never a PATCH.** A rule that starts failing builds is a
behaviour change however small the diff.

## [0.6.0] — 2026-09-17

The gate certified a model in which two boxes justified each other and nothing
else. A MINOR bump rather than a PATCH, per the rule at the top of this file: a
new blocking rule is a behaviour change however small the diff.

### Added

- **G14 — derivation soundness.** A chain of `derived` groundings must bottom
  out in a reason that is not itself derived. Found by asking what G4 does
  *not* check and then reproducing it: rewire two containers in `example/` to
  cite each other as `derived`, each naming a real ADR, regenerate, and
  `archtrace check` printed `0 blocking, 0 warning` and *"model is grounded and
  internally consistent."* Every G4 predicate held — the kind is known, `from`
  resolves, the ADR exists — because G4 reads one grounding entry at a time and
  `derived` is the one kind that points at another element. The reasons in a
  model form a graph, and a graph can be locally valid at every edge and
  globally empty.

  This is the SPEC §5 failure without a fabricated quote. §5 argues a certified
  fabrication is worse than a visible gap; a derivation cycle is a fabrication
  the gate certifies, and the escape hatch §5 opened to relieve fabrication
  pressure turned out to have one of its own. Written up as SPEC §7.1a.

  G14 blocks on the absence of a reason, never on the shape of the graph: a
  cycle in which one member also satisfies a confirmed requirement is odd
  modelling and passes, because a reason exists and the operator can point at
  it. A gate that enforces taste is one that gets switched off.
- **`tools/archtrace/grounding.py`** — the derivation graph as a module, so the
  transitive questions are asked once and answered the same way by the gate and
  the report. Foundedness is a least fixpoint, depth is a breadth-first search,
  cycles are strongly connected components via iterative Tarjan. Iterative
  rather than recursive on purpose: the pathological model is exactly the input
  this code exists to describe, and a rule that crashes on the defect it is
  hunting reports nothing at all.
- **Three transitive numbers in `archtrace report`**, reported and deliberately
  not gated, because each is a smell whose healthy value depends on the
  architecture: **derivation depth** (hops to the nearest real reason),
  **assumption taint** (elements where *every* route to ground passes through a
  guess — they render as `derived`, a consequence of a documented decision,
  while resting on an open question two hops down), and **ADR load** (how many
  groundings one decision holds up). Not "ADR coverage": G4 already forces
  every `derived` entry to cite an ADR, so coverage is 100% on any model that
  passes and measures nothing. Concentration is the number worth knowing.

- **`archtrace review` exists.** SPEC §7.3 has promised it since v2 and
  nothing implemented it: `review/advisory.md` was a path in three diagrams, a
  heading in the RUNBOOK and a prompt an operator pasted into `copilot` by
  hand. No subcommand wrote it, no schema described it, no test asserted
  anything about it, and neither shipped engagement had a `review/` directory.
  The half of this design that is *allowed* to be wrong had nowhere to put its
  output — which is how a careful reader concludes the neural half was left
  deliberately weak when it was only left unbuilt.

  Two things arrive in the advisory and stay apart. The **worklist** is
  computed offline from `model.json` and the evidence manifest, ranked by how
  likely a record is to not mean what it claims: `near-floor-citation`,
  `assumption-tainted`, `adr-concentration`, `deep-derivation`,
  `evidence-concentration`. The **neural half arrives as a file** —
  `--findings` takes JSON from an NLI support scorer, a defeater generator or
  a person, in six kinds with this repository's own `certain`/`likely`/
  `guessing` vocabulary. `docs/advisory-findings.example.json` is the shape.

  A file, not an import — the same seam `docs/archmine-integration.md` §3
  draws for the miner, and what lets the producer be a 400 MB transformer
  stack while `check` stays stdlib-only on a bare runner.

- **Elements grounded directly on an `assumption` are excluded from the
  tainted list**, deliberately. The kind is already visible in the model, in
  every render and in the grounding mix, and the open-question register names
  what is unknown; reporting it would be reporting the design working. The
  finding is the element two hops down that reads as `derived` while
  everything underneath it is a guess.

- **Evidence concentration is one observation, not one per requirement.** Most
  requirements are said once, so the per-requirement version fires on nearly
  everything and buries the tiers above it. The agent definitions' "do not
  pad" applies to this document too.

### Changed

- **No solver, no ontology, no rule engine**, and that is now a recorded
  decision rather than an omission — see the new SPEC §13. The questions G14
  asks are reachability and a least fixpoint over a few hundred nodes; an
  interpreted rule layer in the blocking path would be new untested code whose
  bugs are false BLOCKs and, worse, false passes.
- **`archtrace review` is not part of `make gate`.** A target that can only
  exit 0 has no business in a pipeline whose job is to refuse things.

### Security

- **An external finding cannot forge document structure.** `detail` and
  `where` are evidence-derived text rendered into an artifact a human skims,
  so leading markdown is stripped, newlines flattened and pipes neutralised: a
  reviewer cannot emit `## Approved by archtrace`. There is no deterministic
  gate for prompt injection and the agent definitions say so; that is not a
  reason to render its output credulously.
- **The advisory carries a model fingerprint, never a timestamp.** Byte-
  identical across runs, and still able to tell you whether it describes the
  tree in front of you. A clock in a generated artifact is defect A1 this
  repository found in `archmine`'s own drift gate and patched upstream.

### Tests

- **56 tests** (305 → 361). Six seeded-defect cases for G14, sixteen for the
  graph underneath it, thirty-two for the advisory plane, two for the report.

  Each was verified by re-seeding the branch it guards. For G14: emptying the
  unfounded set kills four, suppressing the cycle lookup kills three, dropping
  relationships from the traversal kills one, treating `derived` as solid
  ground kills four. For the advisory: removing the markdown strip, the pipe
  escape, the kind allowlist, the direct-assumption filter and the
  concentration threshold each kill at least one.

  Two of those started as survivors and are recorded because the reason
  generalises. `test_a_finding_cannot_forge_a_heading` asserted the injected
  heading did not start a line — true with the strip deleted, because
  flattening the newline alone was enough. `..._is_one_row_not_one_per_requirement`
  asserted the only reported record was `EV-001` — true with the threshold
  deleted, because `EV-001` is the only record the example cites. Both were
  passing on a property of the fixture rather than of the code.

  `test_g14_two_elements_deriving_from_each_other` asserts that **G4 stays
  silent**, not merely that G14 fires. The point of the rule is that
  entry-at-a-time validation misses this; a test that passed because G4 also
  caught it would be proving the opposite of what it claims.

## [0.5.0] — 2026-09-16

Both controls that were supposed to refuse a hand-edited artifact could not see
one.

### Fixed

- **`release --verify` reported "Safe to publish" on a tampered deliverable**
  (closes T1 in `docs/code-quality-plan.md`, previously the plan's only open
  Critical with a phase number). `_verify_release` hashed `render_all(eng)` — a
  fresh render *from the model* — instead of the files in `render/`. It answered
  "could the model still produce this?" when the question at publication time is
  "is the artifact in my hand the one that was approved?". Sources were already
  hashed from disk; outputs now are too, through one shared helper so signing
  and verifying cannot drift apart. "Has the model moved since approval?" is
  still reported, separately — conflating the two questions is what hid this.
- **Nothing in CI could fail a hand-edited render.** `make gate` is
  `fmt render check`, so it regenerates every artifact *before* checking it: the
  edit is overwritten, not reported, and the job goes green. CI ran only
  `make gate`; the one workflow running a bare `check` is `workflow_dispatch`-only
  and exits 1 at its evidence step by design. CI now runs `make check` against
  the bytes as committed.
- **`engagements/archtrace-self` carried renders from renderer 1.1.0** after the
  renderer moved to 1.2.0, and CI could not see it: `ROOT` defaults to `example`
  and nothing enumerated the others. Regenerated, and `make freshness` now fails
  on it.
- **An unparseable or unreadable module scored 100% coverage and passed the
  floor.** `executable_lines` returned an empty set on error, which `percent`
  treats as "nothing to cover, therefore complete" — a correct answer for a
  genuinely empty module and a silent bypass for one that could not be read.
- **A misspelled configuration key, and a misspelled section, were both
  discarded in silence** while a bad *value* was refused loudly.
- **`archtrace.toml` was silently ignored on Python 3.9/3.10**, because
  `tomllib` is 3.11+. 3.9 is the declared floor and CI tests it, so two runners
  could enforce two different policies for the same repository while
  `archtrace config` printed advice that could not work there.
- **Ordinary punctuation in a model field corrupted three artifacts.** PlantUML
  and Mermaid took model text raw into quoted C4 macro arguments, so a name
  containing `"` terminated the argument and the diagram stopped parsing
  entirely; the Markdown table took a `|` straight into a cell, turning a
  five-column row into six and shifting every cell after it. Every free-text
  Markdown cell now escapes — element names, requirement statements, grounding
  references, mined source locators, open questions, speakers and source URIs —
  not only the ones somebody remembered.
- **`release` signed stray dotfiles into the approved deliverable set.** A
  `.DS_Store` in `render/` was hashed into the audit manifest as an approved
  output; every later `--verify` then reported the model no longer reproduced
  it, and deleting the junk blocked publication of an intact set. The approved
  *set* is now the renderer's contract while the approved *bytes* still come
  from disk, and `--verify` follows G6 in ignoring dotfile strays.
- **`release --verify` needed the model to load.** It compares bytes on disk
  against the manifest and needs neither the model nor a renderer, so it now
  runs before the engagement is loaded — it answers when the model will not
  load, which is when someone most needs it.
- **A misspelled `ARCHTRACE_*` section was still silent** after the key and
  file-section fixes, in the one layer the missing-`tomllib` error tells
  3.9/3.10 users to use instead.
- **`ARCHTRACE_LOG` was rejected as an unknown configuration section**, which
  bricked the CLI: `DEFAULT = load()` runs at import and `cli.main` refuses to
  dispatch while any error stands, so every command exited 2 for anyone who set
  it -- and the Dockerfile sets it, so the shipped container was broken for any
  real command (`--help` survived only because argparse exits first). Reserved
  names are now imported from the module that owns them, so a second spelling
  cannot drift.
- **A stray *directory* in `render/` evaded `release --verify`.** G6 blocks it
  as a stray; verification listed only regular files and reported MATCH. Two
  controls disagreeing about one tree is the failure this release is about.
- **A manifest that was valid JSON but not an object** (`null`, `[]`, a string)
  raised `AttributeError` out of the helper whose contract is to degrade to a
  byte comparison.
- **G6 claimed a renderer it could not know.** With no recorded version it said
  the render came from "the same one running now", pointing the operator at the
  model when the renderer may have moved.
- **A `--only` subset reported a WARN as a clean pass.** `--only G12` exits 0
  with warnings outstanding; the verdict now says so.

### Added

- **`make freshness`** — asks G6, and only G6, of every engagement *discovered*
  in the repo (glob-driven via `ENGAGEMENT_GLOBS`, covering `engagements/<name>`
  and one level below by default). It is non-mutating:
  an earlier version re-rendered onto disk and diffed afterwards, which
  reproduced the `make gate` defect it exists to close and, on any machine
  where the evidence content lives outside the repository, rewrote three
  committed deliverables with degraded placeholder versions and left them
  there. It fails when discovery finds nothing rather than reporting success
  for having checked none, and refuses a path it cannot resolve rather than
  silently checking a different one. `make engagements` lists what it found.
- **`archtrace check --only RULE…`** — run a subset of the gate by rule id,
  taken from the registry rather than a hardcoded list. For callers that can
  answer one question but not another — asking G6 alone keeps G1 and G2 from
  drowning the result on an engagement whose evidence content is elsewhere,
  though G6 re-renders and so is not itself independent of that content; see
  `FRESHNESS_EVIDENCE_ROOT`. A subset run says so in its verdict, reports any
  warnings outstanding, and never prints the whole-gate claim.
- The pre-commit hook now runs `freshness` as well as `gate`, and fires on
  `render/` — editing a build output previously triggered no hook at all.
- **Nothing regenerated or checked the documentation diagrams.** G6 asks of
  `render/` exactly the question nothing asked of `docs/`, and both generated
  SVGs had drifted from what a document should say: `architecture.svg` drew
  "157 tests" across four releases, and both it and `workflow-sequence.mmd`
  named eleven of the fifteen registered gate rules — a picture of the gate with
  four rules missing. `make docs` regenerates them, `make docs-fresh` refuses a
  stale one, and both are in `pre-pr` and CI. `docs-fresh` is non-mutating by
  construction (`--stdout` into a `mktemp`, never into `docs/`), because the
  first draft wrote its comparison file beside the artifact it was checking —
  the same mistake `make freshness` made, caught this time before it shipped.
- **G4 and G13 never checked relationship grounding.** Both rules end with
  `for rel in eng.relationships`, and both loops could be replaced with
  `for rel in []` while the whole suite passed. Relationships carry grounding
  exactly as elements do — the worked example has ten, every one grounded — so
  half the model's citations were ungated by anything. Three tests now reach
  those loops, verified by disabling each.
- **G2's generic-phrase stoplist can never fire alone at default settings.**
  Writing its first test turned up that every phrase in `GENERIC_PHRASES` is
  below both default floors — the longest, "at the end of the day", is 6 words
  and 21 characters against 8 and 40 — and the floor check does not `continue`.
  The stoplist is therefore strictly redundant unless an organisation lowers the
  floors in `archtrace.toml`. Recorded rather than changed, because whether the
  stoplist should carry phrases long enough to clear the floors is a policy
  question. `test_every_stoplist_phrase_is_shorter_than_the_floors` fails if that
  relationship ever changes, so whoever changes it finds out.
- **No test ever walked the path an adopter walks.** Every other test starts
  from the worked example — a fixture somebody already got right — and
  `ColdStart` scaffolds a real engagement but stops at a *blocked* gate. Nothing
  took a scaffolded engagement through `init → evidence add → quote → promote →
  model → fmt → render → check → release → verify` to a green gate and a MATCH.
  `FullLifecycle` does, driven only through the CLI.

  It is also the first test to use `quote`. Every other test that needs a byte
  span computes it with `canon.normalize` plus `str.find` — the exact mistake
  `quote` exists to remove — so the one command written to stop a class of error
  was never the input to anything. Here its stdout is parsed and spliced into
  `proposed.json` as an agent would, and the transcript says the fragment
  **twice**: `quote` promises the first occurrence, and with a single occurrence
  that promise is unfalsifiable and `find` could be `rfind` forever.

  Five mutations killed that nothing else caught: `quote` resolving to the last
  occurrence, `quote` dropping its duplicate warning, evidence auto-numbering
  off by one, `release` signing a fresh render, and `promote` confirming on a
  dry run.
- **`make pre-pr` ran one interpreter while CI runs three.** Not theoretical:
  the configuration tests added in this release were written against `tomllib`,
  passed locally on 3.11, and failed the 3.9 job — because this tool
  deliberately *refuses* a present config file on an interpreter that cannot
  read it, which is a fix from this same release. Green on a laptop said nothing
  about the floor the project claims to support. `make test-matrix` runs the
  suite on every interpreter installed and **names the ones it did not run**,
  because "tested on 3.9" when 3.9 was absent is the false green this repository
  is about. It is not a `pre-pr` step (it runs the suite once per interpreter);
  `pre-pr` now closes by saying which interpreter it used and pointing at it.
  The tests themselves were split so 3.9 still exercises the new path-resolution
  logic and skips only the part that genuinely needs `tomllib`.
- **A fold-table entry that never ran, and the citation mismatch it left.**
  `PUNCTUATION_FOLD` maps `″` (U+2033 DOUBLE PRIME) to `"`, but `normalize`
  applies NFKC *first* and NFKC decomposes `″` into two PRIME characters — so by
  the time the table ran there was no `″` left to match. The entry sat there
  looking correct and did nothing: `6″` normalised to `6''` while `6"`
  normalised to `6"`, so a transcript using one form and a requirement quoting
  the other never matched, which is precisely the failure this table exists to
  prevent. The sequence is now folded before the single PRIME, because the
  single rule would otherwise consume both halves first.

  Found by asserting the whole table rather than a sample. `test_no_fold_key_is_
  destroyed_by_nfkc_before_the_table_sees_it` generalises it, so any future key
  NFKC decomposes is caught rather than discovered. **Note for adopters:** this
  changes `sha256_normalized` for evidence containing `″`. No engagement in this
  repository contains one, so nothing here re-hashes.
- **The comment above `PUNCTUATION_FOLD` was wrong about its own table.** It
  said "NFKC does NOT fold these"; NFKC folds two of the thirteen (the ellipsis
  and NBSP). Corrected, with a test asserting the comment's claim so it cannot
  drift again. The two entries are kept rather than deleted — removing them
  would make the result depend on NFKC having run first, which is a coupling
  not worth introducing to save two dict entries.
- **`deterministic_zip` did not enforce the compression it documents.**
  `ZipFile(buf, "w", ZIP_STORED)` reads like the guarantee, but `writestr` with
  a `ZipInfo` takes compression from the *info* and ignores the archive default.
  It held only because a fresh `ZipInfo` happens to default to `ZIP_STORED` —
  which nothing stated and no test could have caught. Now set on the `ZipInfo`,
  where the docstring's claim is actually made. Output is byte-identical.
- **Configuration came from the process working directory, not from `--root`.**
  `config.DEFAULT = load()` resolves at import with `root="."`, so the
  `archtrace.toml` that took effect was the one where the operator was standing:
  `cd engagements/aurora && archtrace check` read none at all, and
  `cd ~ && archtrace --root /work/proj check` enforced `~/archtrace.toml`. The
  sharpest consequence was that **a repository legitimately configuring archtrace
  could not run archtrace's own suite** — a plausible `[citation]` block at this
  repo's root turned 26 of its own tests red, which made those assertions
  statements about the developer's working directory rather than about the gate.
  `find_config_root` now walks up to the nearest `.git`/`.hg`/`pyproject.toml`,
  `cli.main` re-resolves from `--root` after argparse and applies it to the gate,
  and `archtrace config` resolves the same way and prints the root it used. The
  suite pins the policy it asserts against, which it must now do for a second
  reason as well: `apply_config` rebinds module constants, so test *ordering*
  would otherwise decide the thresholds. Deliberately *not* changed:
  configuration is still one repository, one policy — per-engagement policy is a
  separate API decision, recorded in `docs/tech-debt.md` §0.
- **Twenty-nine blocking gate branches had never fired in a test run.** A
  mutation audit (208 mutations, 104 survivors) found 29 `Finding` branches that
  could each be replaced with `if False:` with the suite still green — G1's
  duplicate-id and required-field checks, G3's status/type/priority validation,
  five of G4's reference checks, G5's duplicate id and uid, G6's missing-render
  and stray-file findings, G7, G9's unknown-counterpart, both G12n branches, and
  G5e's only finding. Each now has a test, and each test was verified by
  re-seeding the branch it guards: 29 of 29 killed. Line coverage rose 94% → 96%
  as a side effect, which is the more honest way round — the coverage was
  missing because the enforcement was.

  The last two were a contract rather than a branch. G13 skips a symbol whose
  facts file will not parse, with the comment "G1 already reported the
  unreadable facts file" — and nothing checked that G1 does. With G1's branch
  deleted the file is unreadable, G13 stays silent on its own authority, and the
  gate passes an engagement whose code citations resolve against nothing. One
  test now asserts both halves: G1 must speak, and G13 must not speak twice.
- **`assertFires` asserted only that a rule id appeared *somewhere*.** Inverting
  G2's speaker predicate left `test_g2_speaker_not_in_the_room` passing: G2 still
  fired, on the four requirements whose speakers *are* participants, for the
  opposite reason. The suite went red only through 27 unrelated tests breaking on
  the clean example. `where` and `message` are now threaded through all 35 call
  sites, harvested from the findings the rules actually emit. The first thing
  that caught was five of these new tests, written against the assumption that
  `requirements[0]` is REQ-001 — it is REQ-000.
- **Every number a document states about this repository is now derived.**
  `tools/repo_facts.py` computes the test count, rule count, renderer version
  and coverage floors; the diagram generators read from it, and
  `CountedClaims` fails the suite when the changelog or readme states a count
  the suite does not run. This was never carelessness — the count in this very
  entry was correct the day it was typed (226 at `a02eb09`) and wrong two
  commits later. `gen_sequence.py` now refuses to generate at all when a
  registered rule has no diagram label, so a new rule breaks the build instead
  of quietly vanishing from the picture. The diagrams cite the coverage
  **floor** rather than a measured percentage, because a floor is a claim the
  build keeps on every commit and a measurement is a snapshot.
- **122 tests** (183 → 305) covering exactly the gaps that let the above through:
  edits seeded into `render/` rather than into a source; `HostileModelText`
  pushing quotes, pipes and ampersands through every renderer; the G6 drift and
  hand-edit messages and the unreadable-manifest fallback; and the config
  refusals. Reverting any one fix fails tests written for it. Three of the
  `HostileModelText` cases guard `escape()`/`quoteattr()` in the SVG and docx
  paths, which this release did not change — they close a mutation that
  previously survived rather than covering new code.

### Changed

- **`RENDERER_VERSION` 1.2.0 → 1.3.0.** Markdown output changes for any element
  name, requirement statement, grounding reference, open question, speaker or
  source URI containing a pipe, a backslash or a newline; PlantUML output for a
  quote or ampersand; Mermaid for a quote. Everything else is byte-identical.
  Without the bump G6's new message would tell an adopter with a pipe in an
  element name that they had hand-edited something they never touched.
- **G6 names toolchain drift *as* toolchain drift.** `.manifest.json` has
  recorded `renderer_version` since it existed; G6 never read it, so a renderer
  upgrade and a hand edit produced one hedging message about two situations
  needing different actions. An absent or corrupt manifest falls back to the
  plain byte comparison, so the diagnosis can never make a stale render pass.
- `pyproject.toml` version was 0.3.0 while this file was already at 0.4.0.
  Aligned at 0.5.0.

### Documentation

- **`SPEC.md`'s rule table stopped at G10** while the registry shipped fifteen
  ids. That was untidy until `check --only RULE…` made those ids something a
  user types, at which point an undocumented id is a usability defect. G5e,
  G11, G12, G12n and G13 are documented, and a test now asserts the table and
  the registry agree in both directions — the last three releases each added a
  rule and none updated the table.
- **Exit codes are documented** (SPEC §7.0). They were defined in
  `commands/_shared.py` under a docstring calling them "the tool's contract
  with CI" and appeared in no document.
- **`RUNBOOK.md` prescribed `make gate`** as the pre-publish loop — the one
  command that cannot report a hand-edited render. Loops 2 and 3 now run
  `check` first and say why. `README.md` likewise.
- **The documented `make mine` examples exited 2**: `RETAIN` became a required
  argument and neither example passed it.
- A test asserts `pyproject.toml` and the newest `CHANGELOG.md` heading agree
  on the version. They disagreed for a whole release with nothing to notice.

### Test hygiene

- 17 temp directories leaked per suite run; now 0. An uncaptured `main()` no
  longer spews render output into the suite.

## [0.4.0] — 2026-09-16

The Word deliverable stops being an appendix.

### Added

- **`tools/archtrace/docx_shapes.py`** and diagrams in `architecture.docx`.
  Both C4 views are emitted as native DrawingML shapes — `wpg:wgp` groups of
  `wps:wsp` round-rects, straight connectors and grounding badges — written
  straight into `document.xml` from the same `layout.x`/`layout.y` the SVG uses.
  No rasteriser, so no Node and no drawio CLI, and the zero-dependency invariant
  is untouched. They arrive in Word as real shapes a reader can select and
  recolour rather than a flattened picture, and the grounding badges travel with
  them, so the one thing the tool exists to show — which boxes nobody asked for
  — survives into the document stakeholders actually read.
- **21 tests** in `tools/tests/test_docx_shapes.py`, asserting on the XML that
  ships: it parses, every modelled element reaches a diagram, ids are unique
  across views, connector flips and the zero-extent clamp are correct, and the
  bytes are identical across runs. Verified end to end by converting the
  rendered document with LibreOffice and reading the output, because a malformed
  shape does not raise — Word simply refuses to open the file, and the gate would
  have passed a document nobody could read.

### Fixed

- **Element names containing a double quote produced a document Word reports as
  corrupt.** Shape names are XML *attributes* and the emitter used `escape()`,
  which does not escape `"`. Now `quoteattr`. Found by the escaping test before
  it ever reached a model — an element called `the "golden" path` is not exotic.
- **Grounding badge letters were illegible in Word.** A 15px circle cannot give
  up ~3px of inset on each side; the letter was squeezed to a smudge. Badges now
  render with zero insets at a slightly larger radius than the SVG's, because
  Word's line box for a bold capital is taller than the glyph.

### Changed

- `RENDERER_VERSION` 1.1.0 → **1.2.0**. The docx output format changed, so G6
  render-freshness must treat previously generated documents as stale rather
  than as a hand edit.
- `_docx()` takes the view list instead of deriving nothing, and `w:document`
  declares the `wp`, `a`, `wpg`, `wps` and `mc` namespaces.
- **`example/release.json` now reports DRIFT, deliberately.** The renderer
  changed after that state was approved, so the approval no longer describes the
  artifact — which is exactly what `release --verify` exists to say. Re-signing
  it here would mean typing someone else's approval into a file, the failure mode
  the release binding was built to prevent. It stays drifted until the named
  approver re-runs `archtrace release`.

## [0.3.0] — 2026-09-16

The hygiene pass. No change to what the gate decides; substantial change to how
much of the tool is verified and how much of its policy is visible.

### Added

- **`archtrace config`** and `tools/archtrace/config.py`. Every threshold in one
  place, overridable by `archtrace.toml` or `ARCHTRACE_*`, with the command
  printing which values an override actually changed. The SPEC §9a decision
  numbers previously lived inside a print statement, which meant the rule that
  decides whether the whole programme is worth running could only be changed by
  editing a formatting function.
- **`archtrace agents`** and `tools/archtrace/agents.py`. Seven deterministic
  checks over agent definitions: name matches filename, names unique (the
  archmine-kit collision in rule form), description present and bounded, tools
  allowlisted to read-only, the body shows `--deny-tool=write,shell`, the
  evidence-is-not-instruction section exists, and no agent claims authority it
  does not have. Controls that live only in prose are controls nobody enforces.
- **`tools/archtrace/coverage.py`** and `tools/coverage_gate.py`. Line coverage
  measured with the standard-library tracer and enforced against floors from
  config. `coverage.py` is the better tool; this exists because the coverage
  *gate* has to run wherever the rest of the gate runs.
- **`tools/archtrace/log.py`**. Diagnostics to stderr, silent by default,
  `--log debug` or `ARCHTRACE_LOG`. Two invariants under test: logging never
  touches stdout (which carries machine-readable output), and never reaches a
  rendered artifact (which G6 byte-compares).
- **`tools/tests/test_cli.py`** (24 tests) — end-to-end regression coverage for
  every verb, asserting exit codes as the contract with CI.
- **`tools/tests/test_agents.py`** (20) and **`test_infrastructure.py`** (24).
- `pyproject.toml`, `Dockerfile`, `.dockerignore`, `.gitleaks.toml`, a rewritten
  `.pre-commit-config.yaml`, `.github/workflows/ci.yml`, and `make pre-pr`.

### Changed

- **`cli.py` decomposed from 1,008 lines to 248.** Verbs moved into
  `archtrace.commands.{setup,evidence,requirements,build,verify,release}` with
  shared helpers in `_shared.py`. Adding a command now touches one module
  instead of a switchboard.
- `_git` promoted from `release.py` to `commands._shared.git` — both `mine` and
  `release` need it, so it belonged to neither.
- Thresholds now resolve through `config`: G2's quote floor, the §9a decision
  numbers, render geometry, and the mining defaults.
- `renders._kind` lost an unused `engagement` parameter.

### Fixed

- **`return` inside `finally`** in the CLI's `BrokenPipeError` handling, which
  would have swallowed any in-flight exception. Introduced and caught in the
  same session; `ruff` B012 found it.
- **Nested coverage measurement silently disarmed the outer tracer.**
  `trace.Trace.runfunc` calls `sys.settrace(None)` unconditionally in its
  `finally`, so measuring coverage of the coverage module reported every module
  after that point as uncovered. `measure()` now saves and restores.
- `__exit__` on `log.timed` annotated `Literal[False]` — a `bool` return type
  tells readers and type checkers the context manager may swallow exceptions.
- `release --verify` now reports an approved output the renderer no longer
  produces as drift, rather than comparing against `None`.
- `canon.load_json` is typed, which removed 11 downstream type errors at once.

### Quality

| | before | after |
|---|---|---|
| tests | 88 | 157 |
| line coverage | not measured | 94% (floor 85%, per-module 70%) |
| ruff findings | 129 | 0 |
| mypy errors | 12 | 0 |
| largest module | 1,008 lines | 601 (`renders.py`) |

## [0.2.0] — 2026-09-16

- Phase 2 of the archmine integration: `archtrace mine` drives a miner as a
  subprocess, stamps a missing commit into the evidence copy, and refuses a
  dirty tree. Source locators resolved into the traceability render.
- `docs/patches/archmine-a1-a2.patch` — verified upstream fix for archmine's
  non-deterministic inventory artifact and its never-populated `commit` field.

## [0.1.0] — 2026-09-14

- Initial scaffold: SPEC, G1–G12, renderers, `release`/`--verify`, `baseline`,
  and phase 1 of the archmine integration (G13, structured evidence).
