# Changelog

Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
Versioning is semantic, with one project-specific rule: **a new blocking gate
rule is a MINOR bump, never a PATCH.** A rule that starts failing builds is a
behaviour change however small the diff.

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

- **`cli.py` decomposed from 1,008 lines to 215.** Verbs moved into
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
| tests | 88 | 155 |
| line coverage | not measured | 94% (floor 85%, per-module 70%) |
| ruff findings | 129 | 0 |
| mypy errors | 12 | 0 |
| largest module | 1,008 lines | 312 |

## [0.2.0] — 2026-09-16

- Phase 2 of the archmine integration: `archtrace mine` drives a miner as a
  subprocess, stamps a missing commit into the evidence copy, and refuses a
  dirty tree. Source locators resolved into the traceability render.
- `docs/patches/archmine-a1-a2.patch` — verified upstream fix for archmine's
  non-deterministic inventory artifact and its never-populated `commit` field.

## [0.1.0] — 2026-09-14

- Initial scaffold: SPEC, G1–G12, renderers, `release`/`--verify`, `baseline`,
  and phase 1 of the archmine integration (G13, structured evidence).
