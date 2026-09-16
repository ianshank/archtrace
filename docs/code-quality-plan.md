# Code quality and tech-debt remediation plan

Written 2026-09-16 against `55fddb5`. Every finding below was verified by running
something, and the command that produced it is named. Confidence tags follow the
house convention: **[Certain]** verified by execution, **[Likely]** reasoned from
the code, **[Guessing]** judgement.

This plan supersedes the *ranked* list in [`tech-debt.md`](tech-debt.md) but not
its history section. Where the two disagree, this document is the current one —
see [§7](#7-the-tech-debt-doc-has-itself-drifted).

---

## 0. Executive summary

The codebase is small (6,848 Python LOC), well-commented, dependency-free by
design, and 94% line-covered. The structure is sound. **The problem is not the
code; it is that three of the seven quality gates cannot fail**, and two CI
workflows have been red since the repository's first push.

| | Finding | Severity |
|---|---|---|
| **F1** | `make lint`, `make types` and `make secrets` **exit 0 when the tool fails**. Three of seven `pre-pr` gates are decorative. | **Critical** |
| **F2** | `.gitleaks.toml` uses a regex construct Go's engine cannot compile. The `ci / quality` job has never passed. | **Critical** |
| **F3** | `.github/workflows/archtrace.yml` contains a literal `exit 1`. It fails on every PR and every push, by construction. | **High** |
| **F4** | 8 lint violations are in the tree right now, masked by F1. | **High** |

F1 is the one that matters. It is the exact defect class this tool exists to
prevent — a control that is present, documented, and enforcing nothing — and it
is currently sitting inside archtrace's own build.

**Sequencing constraint:** F1 and F4 must ship together. Fixing the Makefile
without fixing the violations turns CI red; fixing the violations without the
Makefile leaves the gate decorative. They are one change.

---

## 1. Critical — gates that cannot fail

### F1. `make lint` / `types` / `secrets` swallow failure [Certain]

`Makefile:58-69` uses the `A && B || C` idiom:

```make
lint:
	@command -v ruff >/dev/null 2>&1 \
	  && ruff check tools docs \
	  || echo "SKIP lint: ruff not installed (pip install -e \".[dev]\")"
```

In shell, `||` fires when **anything** to its left fails — tool absent *or* tool
found violations. The `echo` then exits 0 and the recipe succeeds.

Verified:

```console
$ make lint
... Found 8 errors.
SKIP lint: ruff not installed (pip install -e ".[dev]")   # ruff IS installed
>>> make lint exit code: 0
```

The message is not merely unhelpful, it is false: ruff was installed, ran, and
reported 8 errors. Consequences:

- `ci / quality` runs `make lint` and `make types` — **both always pass**.
- `make pre-pr` steps 1/7, 2/7 and 3/7 cannot go red.
- `pre-pr`'s closing line, *"pre-pr passed. 'Green' means grounded and
  internally consistent"*, is not true of lint, types or secrets.

**Fix.** Separate "absent" from "failed", and keep the graceful skip:

```make
lint:
	@if command -v ruff >/dev/null 2>&1; then ruff check tools docs; \
	 else echo "SKIP lint: ruff not installed (pip install -e \".[dev]\")"; fi
```

Apply the same shape to `types` and `secrets`.

**Acceptance.** A deliberately introduced violation makes `make lint` exit 1, and
`make lint` with ruff uninstalled still exits 0 with the SKIP message. Add both
as cases in `test_infrastructure.py`, so the gate that guards the gates is itself
tested.

### F4. Eight lint violations, currently masked [Certain]

`ruff 0.15.8` reports:

| Rule | Location | Note |
|---|---|---|
| `RUF046` | `docx_shapes.py:44` | `int(round(...))` — `round` already returns `int` |
| `PERF401` ×2 | `docx_shapes.py:203,210` | loop-append → comprehension / `extend` |
| `ARG001` ×3 | `test_docx_shapes.py:57` | unused `tx`, `ty`, `pad` on a stub |
| `C408` | `test_docx_shapes.py:69` | `dict()` → literal |
| `RUF015` | `test_docx_shapes.py:149` | `[...][0]` → `next(...)` |

All are mechanical. Note the per-file-ignore list in `pyproject.toml:76-77`
already covers `tools/tests/*` for several rule families but not `ARG001`,
`C408` or `RUF015` — decide per rule whether to fix or to widen the ignore, and
say which in the commit.

**Root cause worth fixing separately:** `pyproject.toml:25` pins
`ruff>=0.6,<1`. Ruff ships new rules in minor releases, so the violation set
grows without a code change. Today that is invisible because of F1; once F1 is
fixed it becomes a build that breaks on someone else's release schedule. Pin to
a compatible range (`ruff>=0.15,<0.16`) and bump deliberately.

---

## 2. Critical — CI has never been green

Both workflows failed on the last push to `main`
([run 35050591082](https://github.com/ianshank/archtrace/actions/runs/35050591082),
[run 35050591013](https://github.com/ianshank/archtrace/actions/runs/35050591013)).

### F2. `.gitleaks.toml` cannot compile [Certain]

`.gitleaks.toml:37`:

```toml
path = '''^(?!example/).*\.(json|md|txt)$'''
```

gitleaks uses Go's RE2 engine, which has no lookahead. It does not warn — it
panics, produces no `results.sarif`, and the action then fails trying to upload
the artifact it never wrote:

```
panic: regexp: Compile(`^(?!example/).*\.(json|md|txt)$`): bad perl operator: `(?!`
Error: File results.sarif does not exist
```

The vendor documentation is explicit: *"Note Golang's regex engine does not
support lookaheads."* The supported way to express "everything except this
directory" is a rule-level allowlist, not a negated path:

```toml
[[rules]]
id = "evidence-content-in-git"
regex = '''(?i)^\s*\d{2}:\d{2}:\d{2}\s+[A-Z]\.\s+\w+:'''
path  = '''\.(json|md|txt)$'''

  [[rules.allowlists]]
  description = "the worked example is invented; its transcripts are fixtures"
  paths = ['''^example/''']
```

**Why nobody caught it locally:** `.pre-commit-config.yaml:43` pins gitleaks
`v8.21.2`, while `ci.yml:67` uses `gitleaks-action@v2`, which resolved `8.24.3`
on the last run. Two different gitleaks versions guard the same rule. Pin both.

This fix is applied in this PR — it is a config defect with exactly one correct
form, and it is what makes `ci / quality` capable of passing at all.

### F2b. A second failure the panic was hiding [Certain]

Fixing F2 got gitleaks as far as loading the config and reading the event type,
and then it stopped on a different error:

```
🛑 GITHUB_TOKEN is now required to scan pull requests.
```

`gitleaks-action@v2` enumerates a PR's commits through the API, and `ci.yml:67-69`
passed only `GITLEAKS_CONFIG`. This was invisible for as long as F2 held, because
the config panic killed the process before the token check ran.

This is worth recording as its own finding rather than folding into F2. **A step
that fails for two independent reasons looks exactly like a step that fails for
one**, and the second only becomes observable once the first is fixed. Expect
more of this in phase 1: F1 has been masking the true state of lint, types *and*
secrets simultaneously, so the first honest `make pre-pr` will likely surface
findings that no one has seen yet. Budget for that rather than treating it as a
regression.

Also fixed in this PR: `GITHUB_TOKEN` supplied, and `pull-requests: read` added
at **job** scope — the workflow-level `contents: read` is correct and should stay
that way, so the extra grant belongs on the one job that needs it.

### F3. `archtrace.yml` is a placeholder shipped enabled [Certain]

`.github/workflows/archtrace.yml:26-28` is the first step of the only job:

```yaml
run: |
  echo "::error::wire this step to your evidence store before enabling the gate"
  exit 1
```

It triggers on every `pull_request` and every push to `main`, so the repository
has a permanently red check that no change can turn green. A check that is
always red trains reviewers to ignore red checks, which costs more than the
check was ever worth.

**This one needs a decision, not a patch.** Three options:

| Option | Effect | Recommendation |
|---|---|---|
| **A.** `on: workflow_dispatch` only | Stops the noise; template stays available and honest | **Recommended** — it is a template, and templates should not vote on PRs |
| **B.** Gate on a repo variable (`if: vars.EVIDENCE_STORE_URL != ''`) | Self-enabling once an adopter wires it | Good if this ships to adopters as-is |
| **C.** Move to `docs/` as an example | Removes it from Actions entirely | Cleanest if nobody will ever wire it here |

Deliberately **not** changed in this PR. The `exit 1` is intentional (SPEC §0.4 —
evidence content is never in git), and which of A/B/C is right depends on whether
this repository is the product or the reference implementation.

### CI hardening, same pass [Certain]

- `archtrace.yml` has **no `permissions:` block**, so it inherits the repository
  default token scope. `ci.yml:13-14` correctly sets `contents: read`; mirror it.
- `archtrace.yml` has no `concurrency:` block, so superseded runs are not
  cancelled. Mirror `ci.yml:16-18`.
- All actions are tag-pinned (`@v4`, `@v5`, `@v2`), not SHA-pinned. Tags are
  mutable. SHA-pin with a comment naming the version.
- `actions/checkout@v4`, `setup-python@v5` and `gitleaks-action@v2` all target
  Node 20, which is deprecated and already forced onto Node 24 by the runner.
  Track the majors.

---

## 3. Hardening

### H1. `shell=True` in `cmd_mine` [Certain — open, previously accepted]

`commands/evidence.py:125-130`:

```python
completed = subprocess.run(  # noqa: S602
    args.command, cwd=repo, shell=True,  # nosec
```

The reasoning at the call site is sound today: the command is operator-supplied
via `--command` or the Makefile and never derived from evidence content. But the
safety property is *"no caller ever routes file content into `--command`"*,
which is a convention, not a control — and this repository's whole thesis is that
conventions are not controls.

**Fix.** Accept `argv` as a list and use `shell=False` by default; reserve the
shell for an explicit `--shell` flag that has to be typed. That converts the
guarantee from documented to structural, and lets the targeted `S602`
suppression be deleted rather than justified.

### H2. Supply-chain pinning [Certain, low]

- `Dockerfile:10` — `FROM python:3.11-slim` is tag-pinned, not digest-pinned.
  Pin `@sha256:...` for a reproducible gate image.
- `renders.py:203-204` — the emitted PlantUML embeds
  `.../C4-PlantUML/master/C4_Context.puml`. Every generated `.puml` carries a
  reference to a moving branch, so a render that verified today can render
  differently next month. Pin the tag, and move the URL to `config.RenderPolicy`
  so it is arguable without a patch.

### H3. Missing compliance files [Certain]

`pyproject.toml:17` and `Dockerfile:14` both declare Apache-2.0, but there is
**no `LICENSE` file**. Also absent: `SECURITY.md`, `CONTRIBUTING.md`,
`CODEOWNERS`, `.github/dependabot.yml`, and PR/issue templates. For a repository
whose selling point is governance, these are cheap and conspicuous.

---

## 4. God-file reduction

`cli.py` was decomposed in the last pass (1,008 → 248 lines) and `commands/` is a
good template. Two files inherited the problem.

### D1. `renders.py` — 656 lines, eight output formats [Certain]

It grew 58 lines since `tech-debt.md` recorded it at 598. It contains SVG,
PlantUML, Mermaid, draw.io XML, Markdown traceability, CSV traceability, OOXML
and Jira JSON — eight emitters whose only shared concern is the model they read.

**Target**, mirroring `commands/`:

```
renders/
  __init__.py      render_all() + the output registry
  _shared.py       palette, _wrap, _boundary, _kind, _grounding_ref
  svg.py           _svg
  diagrams.py      _puml, _mermaid  (one C4 macro table, not two)
  drawio.py        _drawio
  trace.py         _traceability_md, _traceability_csv
  docx.py          _docx, _diagram
  jira.py          _jira
```

**The constraint that makes this safe:** every emitter is under G6, which
byte-compares output. Do the move in one commit that changes *no bytes* — if
`make check` passes, the refactor is provably behaviour-preserving. That is a
stronger guarantee than a test suite, and it is the reason to do this refactor
rather than fear it. Any behavioural change goes in a separate, later commit.

### D2. `test_gate.py` — 669 lines [Certain]

Split along the same seams: `test_gate_evidence.py` (G1, G2, G11),
`test_gate_model.py` (G3–G5, G7, G9), `test_gate_render.py` (G6, G13),
`test_gate_nfr.py` (G12, G12n). Pure churn, zero risk, do it after D1.

---

## 5. Duplication, dead code and hardcoded values

### R1. Three copies of `wrap()`, already drifted [Certain]

`renders.py:39`, `docs/gen_architecture.py:44`, `docs/gen_sequence.py:99`.

The first two are line-for-line identical modulo variable names. The third is
**not** — it handles `\n`-separated paragraphs and appends `current`
unconditionally, so an empty paragraph yields an empty line where the other two
skip it. Three copies, two behaviours, no test pinning any of them to the others.
This is the drift the prior pass predicted, already arrived.

**Fix.** One `archtrace.svgtext.wrap` with the paragraph behaviour as a flag.
Sequence it *after* D1, so the gated and ungated paths merge once rather than
twice.

### R2. Identical C4 macro tables [Certain]

`renders.py:198` `_PUML_MACRO` and `renders.py:222` `_MMD_MACRO` are byte-identical
five-entry dicts. Collapse to one.

### R3. The palette exists twice [Certain]

`FILL` (`renders.py:31-34`) and `_DRAWIO_STYLE` (`renders.py:244-250`) hardcode
the *same five* hex colours; `#33415c` appears 6 times across the module and
`#c7d7ee` 3 times. Change a colour in one and the SVG and the `.drawio` disagree
silently — G6 will not catch it, because both are regenerated from the same
divergent source.

**Fix.** One `PALETTE` mapping in `renders/_shared.py`; `_DRAWIO_STYLE` becomes a
format string over it. Whether the palette belongs in `config.RenderPolicy` is a
judgement — geometry already moved there, and colour is the same kind of value.

### R4. Grounding-ref extraction, twice [Certain]

The five-way `or` chain over `req / from / standard / evidence_id /
open_question` appears at `renders.py:298-299` and again at `renders.py:432-433`.
Add a `grounding_kind` to `model.GROUNDING_KINDS` lookups instead — the mapping
already exists at `model.py:59-65` and encodes exactly this.

### R5. Dead code [Certain]

A static sweep of every top-level symbol in `tools/archtrace` against all of
`tools/` and `docs/` found two genuinely unreferenced (the decorator-registered
`g*` rules and `agents._*` checks are false positives and were discounted):

- **`model.EVIDENCE_SOURCES`** (`model.py:43-46`) — **zero** references. Nothing
  validates an evidence record's `source` against it. See R6; this one is worse
  than dead, it is *misleadingly* dead.
- **`config.ConfigError`** (`config.py:94`) — defined with a nine-line docstring
  explaining why config errors are collected rather than raised, then never
  raised, caught or referenced. The `errors` tuple holds plain strings. Either
  use it or delete it; the docstring is worth keeping either way.

### R6. A hardcoded enum that has already drifted [Certain]

`cli.py:142-147` and `cli.py:153-155` hardcode argparse `choices` that duplicate
`model.EVIDENCE_AUTHORITY` and `model.EVIDENCE_SOURCES`. Verified:

```
model EVIDENCE_AUTHORITY : [authoritative-document, observed-implementation,
                            stakeholder-confirmed, third-party]
cli   --authority choices: [ ...identical... ]            → IDENTICAL (today)

model EVIDENCE_SOURCES   : [code-mining, document, email, interview,
                            sharepoint, teams-transcript]
cli   --source choices   : [document, email, interview, sharepoint,
                            teams-transcript]              → DRIFTED
```

`--authority` is the dangerous one: it is identical today, nothing binds it, and
`G11` validates against the model constant. Add an authority tier to the model
and the CLI silently refuses it — with a message pointing at the wrong list.

**Fix.** `choices=sorted(EVIDENCE_AUTHORITY)`. Where a CLI surface intentionally
exposes a *subset* — `code-mining` is reached via `add-facts`/`mine`, not
`evidence add`, so its omission is probably correct — derive the subset
explicitly (`sorted(EVIDENCE_SOURCES - {"code-mining"})`) so the intent is in the
code and a new member cannot be forgotten. Add a test asserting the two agree.

### R7. Small redundancies [Certain, low]

- `renders.py:632-633` and `:641-642` build the same two `(title, nodes, edges)`
  tuples twice. Build once, pass twice.
- `renders.py:654` writes `.manifest.json` with `json.dumps(...)` while every
  other JSON output goes through `canon.canonical_json`. Two canonicalisers is
  one too many for a project whose gate is byte-comparison.

---

## 6. Coverage

Reported: **94% total, 85% floor, per-module floor 70%** — genuinely good, and
the per-module floor is the right shape.

Three caveats, in order of how much they overstate the number:

### C1. 565 lines are outside the measurement entirely [Certain]

`coverage_gate.py:33` scopes measurement to `tools/archtrace`.
`docs/gen_architecture.py` (311) and `docs/gen_sequence.py` (254) have **no
tests, no coverage measurement, and no Makefile or CI target**. They are linted
and nothing else. They do still run (verified: both exit 0, and neither drifts
from its committed SVG), but nothing would notice if that stopped being true.

Folding them into the denominator at 0% would put the repository nearer **73%**
than 94%. The honest move is not to lower the floor — it is to test them.

**Minimum viable:** assert each generator's output parses as XML and contains the
expected element count. `tech-debt.md` notes that two of three rendering defects
found last pass would have been caught by exactly that.

**Then:** add a `make docs` target, run it in CI, and add a freshness check —
regenerate and compare, the same rule G6 applies to `example/render/`. Right now
archtrace does not apply its own central invariant to its own build outputs.

### C2. Line coverage, not branch [Certain, structurally hard]

A half-tested `if` counts as covered. Already documented and honestly stated;
the constraint is real (`coverage.py` would split the number between
environments; `sys.monitoring` needs 3.12+ against a 3.9 floor). **Recommendation:
leave it.** Re-evaluate when the Python floor moves past 3.12. Not worth breaking
the zero-dependency invariant for.

### C3. Untested seams [Certain]

- The `./archtrace` shell shim — every test drives `main()` in-process.
- The Makefile gate recipes — F1 is precisely a defect no test could have caught,
  because nothing tests the Makefile.
- `commands.evidence` is the weakest module at 85% and holds the `shell=True`
  path (H1).

---

## 7. The tech-debt doc has itself drifted

`docs/tech-debt.md` is a good document making claims that are no longer true
[Certain]:

| Claim | Stated | Actual |
|---|---|---|
| `renders.py` | 598 lines | **656** |
| "largest module is now 312" | 312 | **656** |
| `cli.py` | 215 lines | **248** |
| `test_gate.py` | 666 lines | **669** |
| `gen_architecture.py` | 308 lines | **311** |
| "Magic numbers: fixed" | fixed | palette still duplicated (R3) |

None is serious alone. Together they are the documentation equivalent of a stale
render — and this repository has a strong opinion about those. Either stop
putting line counts in prose, or generate that table. Given what archtrace *is*,
generating it is the more consistent answer.

---

## 8. Sequencing

Ordered so each phase leaves the build greener than it found it, and so no phase
depends on a later one.

| Phase | Work | Why here | Effort | Risk |
|---|---|---|---|---|
| **0** | F2 gitleaks config *(done in this PR)* | Nothing else can be verified while `quality` cannot run | 10 min | none |
| **1** | F1 + F4 together; pin ruff | The gates must be able to fail before any refactor can be trusted. **Must be one commit.** | 2 h | low |
| **2** | F3 decision (A/B/C) + `permissions`/`concurrency` + SHA-pin actions | Gets every check green and keeps the token scoped | 1 h | low — needs a decision |
| **3** | C1 — test the docs generators, `make docs`, freshness check | Closes the largest measurement hole; eat the dog food | 4 h | low |
| **4** | R5, R6, R7 — dead code, enum binding, small redundancies | Small, independent, each with a test | 3 h | low |
| **5** | D1 — split `renders.py`, byte-identical | Now safe: gates work (1), G6 proves it | 1 d | low, **verifiable** |
| **6** | R1–R4 — palette, wrap, macro tables, ref chain | Needs D1's `_shared.py` to land in | 4 h | low |
| **7** | H1 — `shell=False` by default | Independent; sequence by appetite | 3 h | medium — CLI surface change |
| **8** | D2, H2, H3 — test split, pinning, compliance files | Cleanup | 4 h | none |

Phases 0–2 are the ones that change what "green" means. Everything after is
ordinary improvement, and none of it should start before phase 1 lands.

## 9. Acceptance criteria

The plan is done when all of the following hold:

1. A deliberately broken lint rule, type error, or secret makes `make pre-pr`
   exit non-zero — each verified by a test, not by inspection.
2. Both workflows are green on `main`, and no workflow is red by construction.
3. `make lint` with the tool uninstalled still exits 0 with an accurate message.
4. Coverage is measured over every executable line the repository ships,
   `docs/gen_*.py` included, with the floor held at 85%.
5. `make docs` regenerates `docs/*.svg` and a freshness check fails on drift.
6. No module exceeds 400 lines.
7. `grep -c '#[0-9a-f]\{6\}' tools/archtrace/renders.py` returns 0 — the palette
   has one home.
8. A new member of `EVIDENCE_AUTHORITY` is accepted by the CLI with no CLI edit,
   and a test fails if that stops being true.
9. `tech-debt.md`'s figures are generated, or absent.

---

## Appendix — how each finding was produced

| Finding | Command |
|---|---|
| F1 | `make lint` with ruff installed; exit code inspected |
| F2 | `mcp__github__get_job_logs` on run 35050591082; gitleaks docs via Context7 |
| F3 | `mcp__github__get_job_logs` on run 35050591013 |
| F4 | `ruff check tools docs` |
| C1 | `python3 docs/gen_*.py` + `git status`; `coverage_gate.py:33` read |
| R1–R4 | `grep -n` across the three emitters; side-by-side diff |
| R5 | AST sweep of top-level symbols vs. references in `tools/` + `docs/` |
| R6 | `python3 -c` comparing `model` constants to `cli.py` choice lists |
| §7 | `wc -l` against the figures quoted in `tech-debt.md` |
