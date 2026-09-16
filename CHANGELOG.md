# Changelog

Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
Versioning is semantic, with one project-specific rule: **a new blocking gate
rule is a MINOR bump, never a PATCH.** A rule that starts failing builds is a
behaviour change however small the diff.

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
- **73 tests** (183 → 256) covering exactly the gaps that let the above through:
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
