# Code quality and tech-debt remediation plan — v3

Written 2026-09-16 against `e34727e`; revised the same day against `b9e5eb1`
after Copilot and CodeRabbit's independent review of the pull request
surfaced two genuine defects in v2's own proposed fixes (§1.6–§1.7). A finding
tagged **[Certain]** was verified by running something; the command is named
in the [appendix](#appendix--how-each-finding-was-produced). A finding tagged
**[Likely]** is reasoned from the code rather than executed, and
**[Guessing]** is judgement — say which a finding is, and do not let "every
[Certain] finding was verified" imply more than that about the others.

Supersedes the ranked list in [`tech-debt.md`](tech-debt.md), supersedes v1 of
this document (§1.1–§1.5 is that correction), and supersedes v2's own T1 and
T2/T3 fix designs (§1.6–§1.7, folded into §3 and §4.3 below).

---

## 1. Peer review, two rounds

v1 audited **structure and CI**. It did not audit **behaviour**, and said so
nowhere — which is how it reached a confident headline that was wrong
(§1.1–§1.5). v2 then audited behaviour and found three real defects in the
trust path — but two of its *own* proposed fixes were themselves wrong,
caught by external review of the pull request and confirmed by re-running
the exact scenario each fix claimed to solve (§1.6–§1.7). The pattern repeats
for a reason worth stating plainly: a fix that has not been run against the
case it is supposed to handle is a hypothesis, not a fix — which is the same
lesson v1's headline taught, one level down.

### 1.1 The v1 headline was wrong [Certain]

> *"The codebase is in good shape. The problem is not the code; it is that three
> of the seven quality gates cannot fail."*

The gate finding was real and is now fixed. The first clause was not earned. A
behavioural pass over the same code found three defects in the trust path, one
of them critical (§3). An audit that reads for shape and does not execute the
thing will always produce that sentence, because shape is what it looked at.

**Correction:** the gates were the most *urgent* problem. They were not the
worst one.

### 1.2 The coverage figure was arithmetically wrong [Certain]

v1 said folding the untested generators in would put the repository "nearer
**73%** than 94%". That divided covered *statements* by statements **plus
lines**, which is not a denominator. Measured consistently:

| | statements | covered | |
|---|---|---|---|
| measured today | 2,027 | 1,912 | 94% |
| unmeasured (`docs/gen_*.py`, `coverage_gate.py`) | 316 | 0 | — |
| **honest total** | **2,343** | **1,912** | **81%** |

81%, not 73%. Still below the 85% floor the project sets for itself, so the
conclusion survives — but the number was wrong and was stated as though
measured.

### 1.3 The sequencing had an ordering defect that would have caused harm [Certain]

v1 put "split `renders.py` into `renders/`" at phase 5 and called it "low risk,
**verifiable**". It is neither, in that order. `coverage.measure()` walks the
package root plus a hardcoded `commands/` subdirectory and is **not recursive**
(§5.1). Creating `renders/` silently drops all 314 of its statements out of the
report — the largest module, at 98% — while the gate still prints *"coverage
gate passed"*.

v1 would have destroyed the measurement that was supposed to make the refactor
safe, and nothing would have said so. **Fixed by reordering: §5.1 now gates §6.1.**

### 1.4 The `renders/` split was over-specified [Guessing]

v1 proposed eight modules for 656 lines — an average of 82 lines each. That is
fragmentation, not decomposition; it trades one navigation problem for another.
Revised to four in §6.1.

### 1.5 What v1 got right

The gate defect and its fix; the CI root-causes; the dead code, drifted enum and
duplication findings in §7 — all verified and unchanged. Phases 0–2 landed and
`ci` is green.

### 1.6 v2's T1 fix would have false-blocked every release with expired evidence [Certain]

v2 proposed: *"`--verify` runs `gate.run(eng)` and refuses on any BLOCK."*
Copilot's review of the pull request caught what that means in practice:
`gate.run` includes G1, and G1 blocks the moment evidence content is absent
under `--evidence-root`:

```python
raw = eng.evidence_bytes(rec["id"])
if raw is None:
    yield Finding("G1", BLOCK, rec["id"],
                  "evidence content not present under --evidence-root; "
                  "citation integrity cannot be verified")
```

Evidence content is deliberately not kept forever — SPEC §0.4 puts it outside
git precisely so a retention policy can delete it on schedule. A release
approved last quarter, re-verified today after its evidence's
`retention_until` has passed, would report DRIFT under v2's fix — not because
anything was tampered with, but because the evidence store did exactly what
it was told to do. `--verify` would then treat that release identically to an
actually-tampered one, with no way to tell the two apart. **Corrected in §3.**

### 1.7 v2's T2/T3 fix solved one distortion out of five [Certain]

v2 proposed removing `.casefold()` and claimed the quote then "displays
verbatim" with "offsets stay valid." Both Copilot and CodeRabbit flagged the
same gap independently, and isolating exactly which step inside `normalize()`
produces each distortion confirms they were right:

| input | step responsible | fixed by removing casefold? |
|---|---|---|
| `Straße` → `strasse` (6→7 chars) | `.casefold()` | yes |
| ligature `ﬁle` → `file` (3→4 chars) | **NFKC** | no |
| curly quotes `“yes”` → `"yes"` | **punctuation fold** | no |
| em-dash `a — b` → `a - b` | **punctuation fold** | no |
| multi-space `a    b` → `a b` | **whitespace collapse** | no |

Casefold is one of five lossy steps in `normalize()`, and it is the only one
v2's fix touches. Punctuation folding is not an edge case — `canon.py`'s own
comment says it exists because "every Teams/Word/SharePoint export contains"
curly quotes and en-dashes. A real evidence transcript hits the
punctuation-fold or whitespace-collapse path routinely; v2's "verified"
example used a sentence containing none of the other four distortions, so it
demonstrated the fix for an input chosen to not need it. **Corrected in
§4.3.**

---

## 2. Executive summary

| | Finding | Severity | Status |
|---|---|---|---|
| **T1** | `release --verify` reports *"Safe to publish"* on a tampered deliverable | **Critical** | open |
| **T2** | Every stakeholder quote in every deliverable is casefolded, not verbatim | **High** | open |
| **T3** | Citation offsets cannot be mapped back to the source document by hand | **High** | open |
| **T4** | The coverage gate is blind to any new subpackage | **High** | open |
| **T5** | Malformed JSON produces a Python traceback, not a refusal | **Medium** | open |
| **T6** | The agent authority check is a five-phrase substring tripwire | **Medium** | open |
| **F1** | `make lint`/`types`/`secrets` exited 0 when the tool failed | Critical | **fixed** |
| **F2/F2b** | gitleaks config uncompilable; then `GITHUB_TOKEN` missing | Critical | **fixed** |
| **F3** | `archtrace.yml` red by construction | High | **fixed** |
| **F4** | 8 lint violations masked by F1 | High | **fixed** |

T1–T3 share a root cause worth naming: **the tool is rigorous about the
representation it controls and casual at the boundary where that representation
meets a human.** Hashes, spans and canonical forms are handled with real care.
What a stakeholder actually reads — the quote in the Word document, the file
about to be emailed — is where all three defects live.

---

## 3. T1 — `release --verify` cannot detect a tampered deliverable [Certain]

**Severity: critical.** This is the tool's trust anchor.

`commands/release.py:113-120` states the control's purpose:

> *"This is the control that matters at publication time. A commit id says a
> state was approved once; only recomputing the hashes says the artifact in your
> hand is that state."*

It does not hash the artifact in your hand. `release.py:134` re-renders from the
model:

```python
outputs = render_all(eng)          # fresh render, NOT render/ on disk
for name, expected in manifest.get("outputs", {}).items():
    data = outputs.get(name)
    if "sha256:" + hashlib.sha256(data).hexdigest() != expected:
```

So it verifies *"the model still renders to what was approved"* — not *"the file
I am about to send is what was approved"*. Those differ in exactly one case:
someone edited a build output. Which is the case the control exists to catch.

### Reproduction

```console
$ archtrace release --approved-by "Test Approver" --role architect
$ archtrace release --verify
MATCH — every source and output is byte-identical to what was approved.

$ # edit render/traceability.md, replacing "**none**" with "APPROVED BY LEGAL"
$ archtrace release --verify
MATCH — every source and output is byte-identical to what was approved.
                                                          Safe to publish.
$ echo $?
0
```

A deliverable now carrying a fabricated legal approval is certified safe to
publish, by name, against a real approver's recorded authority. `archtrace
check` catches it (G6 reads disk and reports one BLOCK) — but `--verify` does
not run the gate, and `--verify` is the step documented as the publication-time
control.

### Fix, and why the two obvious ones are both wrong

The first obvious fix — hash `render/<name>` from disk and compare to the
manifest — **introduces false positives**. `release.json` stores `sha256` of
the *raw* fresh-render bytes, but G6 compares *canonical* form, and two
byte-different files can be canonically equal:

```
two byte-different but canonically-equal SVGs:
  raw bytes equal      : False
  canonical_bytes equal: True
```

So a legitimately reformatted tree would fail a naive disk-hash check.

The second obvious fix — have `--verify` call `gate.run(eng)` and refuse on
any BLOCK — was this plan's own v2 proposal, and it is wrong for close to the
opposite reason: it introduces **false blocks**. `gate.run` includes G1, which
blocks whenever evidence content is not present under `--evidence-root`
(`gate.py:112-116`) — the ordinary, expected state once a record's
`retention_until` has passed and the evidence store has deleted it, exactly as
SPEC §0.4 designs it to. Running the whole gate from `--verify` reports DRIFT
on every release whose evidence has since expired, indistinguishable from an
actually-tampered deliverable (§1.6).

**Do this instead: call the render-freshness check alone, not the whole
gate.** `gate.g6_render_freshness` already performs exactly the
disk-versus-fresh canonical comparison this control needs, is already
tested, and depends only on the model and `render/` — never on evidence
content, so an expired retention window cannot make it block. Requires **no
change to the `release.json` schema**, so every existing manifest keeps
verifying. Report its findings as drift of a third kind alongside `source`
and `output`, and leave G1, G2, G11 and the rest of the gate suite out of
`--verify` entirely: they answer "is this model well-formed," not "is this
deliverable what was approved," and conflating the two produced §1.6.

Keep the existing fresh-render comparison too: it catches model drift, which
is a different failure and still worth reporting.

---

## 4. T2 and T3 — the citation boundary

### 4.1 T2. Quotes are casefolded in every deliverable [Certain]

`canon.normalize()` ends with `.casefold()` (`canon.py:50`). `quote_cached` is a
slice of that normalised text (`commands/evidence.py:262`), and it flows
unmodified into all three stakeholder artifacts — `traceability.md`
(`renders.py:416`), `architecture.docx` (`renders.py:523`) and
`jira-tickets.json` (`renders.py:597`).

What is in the repository today:

```
A. Stakeholder: "if the feed drops for half a day we cannot lose those events"
```

That is rendered inside quotation marks, attributed to a named person, in a
document going to stakeholders. It is not what they said.

The gate cannot notice. G2 compares `text[start:end]` against `quote_cached`
where `text` is the same normalised string — they agree by construction
(`gate.py:189-196`). Meanwhile `gate.py:426-427` tells the user *"both quotes
are verbatim"*, which is false for every quote the tool has ever emitted.

For a tool whose thesis is that a citation must be checkable, silently altering
the cited text before showing it is the defect that matters most after T1.

### 4.2 T3. Offsets do not map to the source document [Certain]

`casefold()` is not length-preserving, and neither is the NFKC pass before it:

| input | length | normalised | length |
|---|---|---|---|
| `Straße` | 6 | `strasse` | **7** |
| `ﬁle` | 3 | `file` | **4** |
| `İstanbul` | 8 | `i̇stanbul` | **9** |

The gate stays self-consistent, because every offset indexes the normalised
text. But a reviewer handed `[start:end]` cannot find that span in the source
document, and the drift is unbounded — every character after the first `ß` or
`ﬁ` ligature is displaced. Neither is exotic: German names, and ligatures from
any PDF export.

"Verifiable by a human against the system of record" is the claim. These offsets
are verifiable only by the tool that produced them.

### 4.3 Fix — casefold is one distortion of five, and the wrong one to isolate alone [Certain]

v2 stopped at `.casefold()` and called it "one change addresses both." §1.7
showed that overclaims what removing it actually does:

```
'ligature'   raw='ﬁle'     NFKC:        'file'    (len 3->4)   NOT casefold
'sharp-s'    raw='Straße'  casefold:    'strasse' (len 6->7)   IS  casefold
'curly "'    raw='"yes"'   punct-fold:  '"yes"'   (bytes differ) NOT casefold
'em-dash'    raw='a—b'     punct-fold:  'a-b'     (bytes differ) NOT casefold
'multi-sp'   raw='a    b'  ws-collapse: 'a b'     (len 10->5)  NOT casefold
```

Removing `.casefold()` fixes **T2 completely** — the displayed text keeps its
original case, a real and self-contained improvement worth shipping on its
own. It fixes only the casefold-shaped slice of **T3**: NFKC's ligature
decomposition, punctuation folding and whitespace collapsing are three
*separate* lossy transforms, none removed by dropping casefold, and none
rare — `canon.py`'s own comment says punctuation folding exists because
"every Teams/Word/SharePoint export contains" curly quotes and en-dashes. A
citation from a real transcript routinely hits at least one of the other
four.

**T2 (display) — ship this now.** Match case-insensitively at the point a
fragment resolves to a span (`cmd_quote`, `g2_citation_integrity`); stop
calling `.casefold()` inside `normalize()`. Small, independent, and solves a
real problem completely.

**T3 (source-mapping) — needs more than one change, or an honest scope-down.**
Two shapes; pick one per adopter's risk tolerance:

1. **Track a raw-to-canonical alignment, not just the canonical text.**
   `normalize()`'s four remaining steps (NFKC, punctuation-fold, zero-width
   removal, whitespace-collapse) are each a sequence of single-span
   replacements; a variant that records source-offset ⟷ canonical-offset
   pairs as it runs can map a matched canonical span back to the exact raw
   bytes. Real engineering, not a one-liner — budget it as such — but it is
   the only version of "verifiable by a human against the source document"
   that is actually true.
2. **Scope the claim down instead.** Keep matching and hashing on canonical
   text as today, store the canonical `quote_cached` for display (now
   case-preserving once T2 ships), and change the tool's own claim from
   "verbatim" to "a citation is checkable against the canonical form of the
   evidence, not against its raw bytes." Cheaper, honest, and consistent
   with the NFKC ligature residue already being accepted as a documented
   limitation rather than a solved problem.

Either way, **do not claim offsets "remain valid"** for a record normalised
under the old, casefold-including pipeline: its stored span was computed
against text that no longer exists once casefold is removed, and there is no
alignment to recover after the fact — the raw source may not even still be
present (evidence content can be retention-deleted, same failure mode as
§1.6). **Re-ingestion, not re-hashing, is the correct migration for a record
that cannot be recomputed against its current raw source**; a bare version
bump is only valid where that source is still available.

**This is still the plan's one breaking change**, for a narrower reason than
v2 stated: `sha256_normalized` changes for any evidence record whose
canonical form contains a character `.casefold()` would have altered — an
uppercase letter, or a special-casefolding character like `ß` — **not, as v2
claimed, for every record**. A record whose normalised text happens to be
already all-lowercase ASCII keeps its hash unchanged. Handle the ones that do
change properly:

1. Add `normalization_version` to the evidence record, defaulting to `1`.
2. `canon.normalize(text, version=...)` keeps v1 behaviour reachable, so old
   records keep verifying — the same courtesy `SUPPORTED_SCHEMA_VERSIONS`
   already extends to the model.
3. `archtrace fmt` re-hashes a v1 record to v2 **only when the raw source is
   still available** under `--evidence-root`; where it is not, refuse and
   name the record for re-ingestion rather than silently keeping a stale v1
   hash or guessing at a v2 one.
4. Refuse an unknown version, matching G10's existing posture.

Without step 2 this is a flag day for every adopter. With it, it is a
migration — and with step 3's availability check, an honest one.

---

## 5. T4–T6 — measurement and refusal

### 5.1 T4. The coverage gate is blind to new subpackages [Certain]

`coverage.py:154-162` walks `package_dir`, then one hardcoded subdirectory:

```python
modules = [_module(package_dir, entry) for entry in sorted(os.listdir(package_dir)) ...]
sub = os.path.join(package_dir, "commands")
if os.path.isdir(sub):
    modules.extend(...)
```

A synthetic package containing `top.py`, `commands/c.py` and `renders/svg.py`
reports exactly two modules: `top` and `commands.c`. `renders.*` is absent, and
the gate prints *"coverage gate passed"*.

The failure mode is the dangerous one: coverage does not drop, it **shrinks the
denominator**, so a module can leave measurement entirely while the headline
number stays flat or improves.

**Fix.** Walk recursively (`os.walk`), derive the module name from the relative
path, and — because the whole point is that silence should not be safe — fail
the gate if the set of measured modules shrinks relative to a committed
baseline. Do this **before** §6.1, not after.

### 5.2 T5. Malformed JSON produces a traceback [Certain]

`canon.load_json` (`canon.py:138`) has no error handling, and `cli.main`
(`cli.py:233-244`) catches only `BrokenPipeError` and `KeyboardInterrupt`. A
single stray comma in `model.json`:

```
json.decoder.JSONDecodeError: Expecting property name enclosed in double quotes:
line 1 column 22 (char 21)
```

— eleven frames of traceback, exit 1. Every other refusal in this codebase names
the file, the rule and the fix; `config.py:94-102` has a nine-line docstring on
exactly this principle. This path does not follow it.

**Fix.** Catch `JSONDecodeError` in `load_json`, re-raise as a typed error
carrying the path and position, and have `cli.main` render it as a refusal with
exit 2 (usage) rather than a traceback. The same treatment covers the unguarded
`open()` calls in `release.py:73-75` and `release.py:127`.

`config.ConfigError` — dead in §7.3 — is the natural base class. That turns a
deletion into a use.

### 5.3 T6. The agent authority check is a tripwire, not a control [Certain]

`agents.py` opens with: *"A control that lives only in prose is a control nobody
is enforcing."* Its structural checks earn that — `ALLOWED_TOOLS` and
`REQUIRED_DENY` are real. `A7-no-authority-claims` does not:

```python
FORBIDDEN_CLAIMS = ("i approve", "you may merge", "auto-merge",
                    "sets the exit code", "blocks the build")
for phrase in FORBIDDEN_CLAIMS:
    if phrase in lowered:
```

Five substrings against the lowercased body. "I will approve", "once I am
satisfied this can land" and "I'll merge it" all pass; a document quoting a
forbidden phrase *in order to forbid it* fails. It is prose-matching used to
enforce a rule about prose — the thing the module's own docstring identifies as
insufficient.

**Fix.** Stop calling it a control. Rename to `A7-authority-language-smell`,
downgrade to WARN, and say in the docstring that it is a prompt to read the
file. Then put the real control where it can hold: the structural checks already
prevent an agent from writing or gating, whatever its prose claims.

---

## 6. God-file reduction

### 6.1 `renders.py` — 656 lines, eight emitters [Certain]

**Blocked by §5.1.** Do not start this until the coverage gate walks
subpackages, or 314 statements leave measurement silently.

Four modules, not v1's eight:

```
renders/
  __init__.py   render_all() + the output registry
  _shared.py    palette, _wrap, _boundary, _kind, grounding-ref resolution
  diagrams.py   SVG, PlantUML, Mermaid, draw.io  — the four coordinate emitters
  documents.py  traceability md/csv, docx, jira  — the four narrative emitters
```

The seam is real: `diagrams.py` consumes `layout.x/y` and a palette;
`documents.py` consumes requirements, grounding and provenance. They share
almost nothing beyond `_shared`, which is why the palette and `wrap` duplication
(§7.1, §7.2) resolves naturally once it exists.

**The constraint that makes this safe:** every emitter is under G6, which
compares *canonicalised* output (`canon.canonical_bytes`), not raw bytes — so
attribute ordering or insignificant whitespace does not block, and a real
content change does. Do the move in one commit changing no canonical output
for the models `make check` actually exercises — if it passes, the refactor
is behaviour-preserving for every branch `render_all` reaches on those
models (both C4 views, across all eight output formats), which is a stronger
guarantee than a hand-written test asserting the same thing, though it is
not a proof over every input the renderers could ever see. Treat a passing
`make check` as strong evidence for this specific move, not as a substitute
for the existing renders tests. Any behavioural change goes in a later
commit.

### 6.2 `test_gate.py` — 669 lines [Certain]

Split along the rule seams: `test_gate_evidence.py` (G1, G2, G11),
`test_gate_model.py` (G3–G5, G7, G9), `test_gate_render.py` (G6, G13),
`test_gate_nfr.py` (G12, G12n). Pure churn, zero risk, after §6.1.

---

## 7. Duplication, dead code and hardcoded values

Unchanged from v1 and re-verified. Condensed.

### 7.1 Three copies of `wrap()`, already drifted [Certain]

`renders.py:39`, `docs/gen_architecture.py:44`, `docs/gen_sequence.py:99`. The
first two are identical modulo variable names. The third handles `\n` paragraphs
**and appends `current` unconditionally**, so an empty paragraph yields an empty
line where the others skip it. Three copies, two behaviours, nothing pinning
them together.

### 7.2 The palette exists twice [Certain]

`FILL` (`renders.py:31-34`) and `_DRAWIO_STYLE` (`renders.py:244-250`) hardcode
the same five colours; `#33415c` appears six times in the module. Change one and
the SVG and the `.drawio` disagree silently — G6 cannot catch it, because both
regenerate from the same divergent source. One `PALETTE` in `renders/_shared.py`.

### 7.3 Dead code [Certain]

- **`model.EVIDENCE_SOURCES`** — zero references anywhere. Worse than dead: it
  looks like the enum that validates an evidence record's `source`, and **no
  gate validates `source` at all**. The CLI's hardcoded `choices` is the only
  enforcement, and it applies solely at `evidence add`. A hand-edited
  `index.json` can carry any `source` string past every gate.
- **`config.ConfigError`** — defined with a nine-line docstring, never raised,
  caught or referenced. §5.2 gives it a job.

### 7.4 A hardcoded enum that has already drifted [Certain]

`cli.py:142-147` and `:153-155` duplicate `model.EVIDENCE_AUTHORITY` and
`model.EVIDENCE_SOURCES`:

```
model EVIDENCE_AUTHORITY : identical to the CLI's choices — today
model EVIDENCE_SOURCES   : has `code-mining`; the CLI's --source does not — DRIFTED
```

`--authority` is the dangerous one: identical now, nothing binding it, and G11
validates against the model constant. Add an authority tier and the CLI refuses
it with a message naming the wrong list. Fix with
`choices=sorted(EVIDENCE_AUTHORITY)`; where a subset is intended, derive it
explicitly (`sorted(EVIDENCE_SOURCES - {"code-mining"})`) and test the
agreement.

### 7.5 Small redundancies [Certain, low]

`_PUML_MACRO` and `_MMD_MACRO` (`renders.py:198`, `:222`) are byte-identical.
The grounding-ref `or`-chain appears at `:298` and `:432`. `render_all` builds
the same `(title, nodes, edges)` tuples twice (`:632`, `:641`).
`.manifest.json` uses `json.dumps` while every other JSON output goes through
`canon.canonical_json` — two canonicalisers is one too many in a project whose
gate exists specifically to compare canonical form (G6, `canon.canonical_bytes`).

---

## 8. Hardening

### 8.1 `shell=True` in `cmd_mine` [Certain, open]

`commands/evidence.py:125-130`. The call-site reasoning is sound *today*: the
command comes from operator flags, never from evidence. But that is a
convention, and this repository's whole thesis is that conventions are not
controls. Accept `argv` as a list, `shell=False` by default, reserve the shell
for an explicit `--shell` flag. Then the `S602` suppression can be deleted
rather than justified.

### 8.2 Supply chain [Certain]

- Actions are tag-pinned, not SHA-pinned. gitleaks' own workflow SHA-pins;
  follow it.
- `.pre-commit-config.yaml:43` pins gitleaks `v8.21.2`; CI resolved `8.24.3`.
  Two versions guard the same rule — which is why F2 was never caught locally.
- `Dockerfile:10` — `python:3.11-slim` is tag-pinned, not digest-pinned.
- `renders.py:203` — emitted PlantUML embeds a `master` branch URL, so a render
  that verified today can render differently next month. Pin the tag; move the
  URL into `config.RenderPolicy`.

### 8.3 Compliance files [Certain]

`pyproject.toml:17` and `Dockerfile:14` both declare Apache-2.0 and there is
**no `LICENSE` file**. Also absent: `SECURITY.md`, `CONTRIBUTING.md`,
`CODEOWNERS`, `dependabot.yml`, PR/issue templates. Cheap, and conspicuous in a
governance tool.

---

## 9. Coverage

94% measured; **81% honest** (§1.2). Three gaps, in order of severity:

1. **T4 (§5.1)** — the gate cannot see a new subpackage. Fix first; everything
   else in this section assumes the measurement is trustworthy.
2. **316 unmeasured statements** — `docs/gen_*.py` and `coverage_gate.py` are
   linted and never executed, tested or measured. They do run today (both exit
   0, neither drifts from its committed SVG), but nothing would notice if that
   changed. Minimum viable: assert the output parses as XML and has the expected
   element count. Then add `make docs`, run it in CI, and apply a freshness
   check — **archtrace does not currently apply G6's own invariant to its own
   build outputs.**
3. **Line coverage, not branch** — a half-tested `if` counts as covered.
   Honestly documented, and the constraint is real (`coverage.py` splits the
   number between environments; `sys.monitoring` needs 3.12+ against a 3.9
   floor). **Recommendation: leave it**, and revisit when the floor moves.

Untested seams worth naming: the `./archtrace` shim (every test drives `main()`
in-process), and `commands.evidence` at 85% — the weakest module, and the one
holding the `shell=True` path.

---

## 10. Sequencing

Reordered from v1. The dependency that v1 got wrong is **§5.1 before §6.1**.

| Phase | Work | Depends on | Effort | Risk | Status |
|---|---|---|---|---|---|
| **0** | F2, F2b — gitleaks config and token | — | 10 min | none | **done** |
| **1** | F1 + F4 — gates can fail; pin ruff/mypy | — | 2 h | low | **done** |
| **2** | F3 — `archtrace.yml` manual-only; `permissions`/`concurrency` | — | 1 h | low | **done** |
| **3** | **T1** — `--verify` runs the gate | — | 2 h | low | **next** |
| **4** | **T4** — recursive coverage walk + shrink detection | — | 3 h | low | |
| **5** | T5 — typed refusal for malformed JSON (revives `ConfigError`) | — | 2 h | low | |
| **6** | §9.2 — test the docs generators; `make docs`; freshness check | 4 | 4 h | low | |
| **7** | §7.3–7.5 — dead code, enum binding, small redundancies | — | 3 h | low | |
| **8** | **§6.1** — split `renders.py`, byte-identical | **4** | 1 d | low, verifiable | |
| **9** | §7.1, §7.2 — palette, `wrap`, macro tables, ref chain | 8 | 4 h | low | |
| **10** | **T2 + T3** — case-preserving normalisation **+ migration** | 3, 4 | 1 d | **medium — breaking** | |
| **11** | T6 — reclassify A7; §8.1 `shell=False` | — | 4 h | medium | |
| **12** | §6.2, §8.2, §8.3 — test split, pinning, compliance | — | 4 h | none | |

Three ordering constraints, each for a reason:

- **T1 first among the open work.** It is the only finding where the tool
  actively certifies something false. Everything else degrades quality; this one
  manufactures unwarranted confidence.
- **T4 before §6.1 and before §9.2.** Both create or move modules. Measuring
  them with a gate that cannot see subpackages is how the largest module leaves
  coverage without a sound.
- **T2/T3 late, and last among the behavioural fixes.** It is the only breaking
  change, it needs the migration path in §4.3, and it rewrites `quote_cached`
  across every engagement — which is far safer once `--verify` actually verifies
  (phase 3) and coverage is trustworthy (phase 4).

**Expect newly-visible findings, not regressions.** F1 masked lint, types and
secrets for the repository's entire life, and fixing F2 immediately revealed
F2b beneath it. A gate that has never been able to fail has never been telling
you anything. Treat the first output of a newly-honest gate as backlog that was
always there.

---

## 11. Acceptance criteria

1. `release --verify` exits non-zero on a hand-edited file in `render/`, with
   a test that tampers with a real deliverable and asserts the refusal — and
   a separate test proves it does **not** refuse when evidence content is
   simply absent (the expired-retention case, §1.6): `--verify` must tell
   "the deliverable changed" apart from "the evidence store did its job."
2. A quote in `traceability.md`, `architecture.docx` and `jira-tickets.json`
   preserves the source's original capitalisation (T2). Whether it is also
   byte-identical to the raw source transcript depends on which §4.3 option
   is taken — record which, and test against that claim, not against
   "verbatim" by default.
3. An evidence record whose normalised text is unaffected by the
   normalisation change still verifies without modification; one that IS
   affected either re-hashes cleanly against its still-available raw source,
   or is named for re-ingestion — proven by two fixtures, not one: an
   unaffected v1 record, and an affected one whose source has been deleted.
4. Adding a module under a new subpackage changes the coverage denominator; a
   test asserts the module set cannot silently shrink.
5. Coverage is measured over every executable statement the repository ships,
   with the floor held at 85% — the honest figure, not a re-based one.
6. A malformed JSON document produces a named refusal and exit 2. No traceback
   reaches a user from any CLI path.
7. `make docs` regenerates `docs/*.svg`, and a freshness check fails on drift.
8. No module exceeds 400 lines.
9. No hex colour literal appears outside
   `tools/archtrace/renders/_shared.py`, checked with a command whose
   failure mode is unambiguous — for example a loop that greps each
   `renders/*.py` file individually and fails on any hit outside
   `_shared.py` — not a bare `grep -c` across multiple files, whose exit
   status reports "matched somewhere," not "count is zero," and would pass
   by accident on a mixed result.
10. A new member of `EVIDENCE_AUTHORITY` is accepted by the CLI with no CLI
    edit, and a test fails if that stops being true.
11. `tech-debt.md`'s line-count figures are generated, or absent.

---

## Appendix — how each finding was produced

| Finding | Command |
|---|---|
| T1 | `release` then `--verify` on a clean tree; edit `render/traceability.md`; `--verify` again |
| T1 fix shape | `canonical_bytes` on two byte-different, canonically-equal SVGs |
| §1.6 | read `gate.py`'s G1 rule and SPEC §0.4's retention design; the false-block is a direct reading, not a repro that needed running |
| T2 | read `quote_cached` from `example/requirements/requirements.json`; `grep` the same string in `example/render/traceability.md` |
| T3 | `canon.normalize` over `Straße`, `ﬁle`, `İstanbul`; compared lengths |
| §1.7 | isolated NFKC / punctuation-fold / zero-width / whitespace-collapse / casefold as five separate steps and ran each input through each step individually, printing the length and value after every step, to attribute which step causes which distortion |
| T4 | `coverage.measure()` against a synthetic package containing `renders/` |
| T5 | `./archtrace --root <tmp> check` with a stray comma in `model.json` |
| T6 | read `agents.py FORBIDDEN_CLAIMS` and `_authority` |
| §1.2 | `coverage.executable_lines()` over `docs/gen_*.py` and `coverage_gate.py` |
| F1 | `make lint` with ruff installed; exit code inspected; mutation-tested |
| F2/F2b | `get_job_logs` on runs 35050591082 and 35051293467; gitleaks docs via Context7 |
| §7.1–7.5 | `grep -n` across the three emitters; AST sweep of top-level symbols |
| §7.4 | `python3 -c` comparing `model` constants to `cli.py` choice lists |
| pin consistency | `which ruff mypy gitleaks`; `git ls-remote --tags` against astral-sh/ruff-pre-commit and pre-commit/mirrors-mypy to find real tags in the pinned ranges |
| PATH-isolation fix | `make lint` invoked directly (absolute `make` path) with `PATH` restricted to a scratch bindir only, for each of: no stub, a failing stub, a clean stub — confirmed skip/fail/pass all still work with no `/usr/bin` or `/bin` on `PATH` |

Two rounds of external review (Copilot and CodeRabbit, both against `b9e5eb1`
on [PR #2](https://github.com/ianshank/archtrace/pull/2)) are folded into
§1.6, §1.7, §6.1, §7.5, and acceptance criteria 1–3 and 9 above. Every claim
either bot made was independently re-derived against the code before being
accepted — none was taken on the bot's word alone.
