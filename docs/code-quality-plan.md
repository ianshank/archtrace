# Code quality and tech-debt remediation plan — v4

Written 2026-09-16 against `e34727e`; revised against `b9e5eb1` after
Copilot/CodeRabbit review of the pull request (§1.6–§1.7); revised again
against `6e9983a` after an 11-dimension adversarial audit — 93 agents, real
execution against the live repository, every finding above low severity
independently refute-checked — found 37 further confirmed defects (§12) and
re-verified every open finding in §2 still reproduces exactly as described.
A finding tagged **[Certain]** was verified by running something; the
command is named in the [appendix](#appendix--how-each-finding-was-produced).
A finding tagged **[Likely]** is reasoned from the code rather than
executed, and **[Guessing]** is judgement — say which a finding is, and do
not let "every [Certain] finding was verified" imply more than that about
the others.

Supersedes the ranked list in [`tech-debt.md`](tech-debt.md), supersedes v1 of
this document (§1.1–§1.5 is that correction), supersedes v2's own T1 and
T2/T3 fix designs (§1.6–§1.7, folded into §3 and §4.3 below), and adds §12,
which materially changes T1's fix (see §12.1) without invalidating anything
else already here.

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
| **T5** | Malformed JSON produces a Python traceback, not a refusal — 8 call sites, expanded §12.7 | **Medium→High** | open |
| **T6** | The agent authority check is a five-phrase substring tripwire — 2 sibling checks share it, §12.6 | **Medium→Critical** | open |
| **T7** | `release.json` has no integrity of its own; T1's fix alone doesn't close it | **Critical** | open |
| **T8** | `git()` treats a failed dirty-query as a clean tree | **High** | open |
| **T9** | G13 verifies a cited symbol exists, never that it's relevant | **Critical** | open |
| **T10** | `content_kind` is self-declared and never checked against the bytes | **Critical** | open |
| **T11** | Auto-generated evidence ids silently destroy hand-assigned records | **High** | open |
| **T12** | Agent read-only enforcement (A5) is a body-wide substring search | **Critical** | open |
| **F1–F4** | Gate/CI defects from rounds 1–2 | Critical/High | **fixed** |

T1–T3 share a root cause worth naming: **the tool is rigorous about the
representation it controls and casual at the boundary where that representation
meets a human.** Hashes, spans and canonical forms are handled with real care.
What a stakeholder actually reads — the quote in the Word document, the file
about to be emailed — is where all three defects live. §12's round found the
same pattern one layer down, in the tool's own trust machinery: T7 and T12 are
both cases where the *check* is rigorous about existence and casual about
whether the thing that exists is the thing that was meant. T5's expansion and
T8/T9/T10/T11 share a second pattern — every one is a place this codebase's
own stated design principle (refuse loudly, verify the claim, never guess)
was written down once and not carried to every call site that needed it.

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

Reordered from v1, then again from v3. The dependency v1 got wrong was
**§5.1 before §6.1**; §12's round adds six more phases and one deliberate
non-inclusion (T7, below the table).

| Phase | Work | Depends on | Effort | Risk | Status |
|---|---|---|---|---|---|
| **0** | F2, F2b — gitleaks config and token | — | 10 min | none | **done** |
| **1** | F1 + F4 — gates can fail; pin ruff/mypy | — | 2 h | low | **done** |
| **2** | F3 — `archtrace.yml` manual-only; `permissions`/`concurrency` | — | 1 h | low | **done** |
| **2b** | §12.8 config fixes (gitleaks `(?m)`, `.dockerignore`, `RETAIN`) + §12.11 doc-accuracy (6 items) | — | — | none | **done** |
| **3** | **T8** — `git()` distinguishes a failed query from a clean tree | — | 1 h | low | next |
| **4** | **T1** — `--verify` calls `g6_render_freshness` alone | 3 | 2 h | low | |
| **5** | **T11** — evidence-id collision; §12.8's path-traversal item | — | 3 h | low | |
| **6** | **T5, expanded** — one typed `CanonError`, 8 call sites, broaden `main()`'s except | — | 4 h | low | |
| **7** | **T4** — recursive coverage walk + shrink detection | — | 3 h | low | |
| **8** | **T9 + T10** — G13 relevance signal; validate `content_kind` against bytes; G1 and/or mutation-gap test | 6 | 1 d | medium | |
| **9** | §9.2 — test the docs generators; `make docs`; freshness check | 7 | 4 h | low | |
| **10** | §7.3–7.5 + §12.10 — dead code, enum binding, redundancies, and the six more duplication/drift items §12 found | — | 1 d | low | |
| **11** | **§6.1** — split `renders.py`, byte-identical; `_boundary` geometry test; coverage-floor boundary test | 7 | 1 d | low, verifiable | |
| **12** | §7.1, §7.2 — palette, `wrap`, macro tables, ref chain | 11 | 4 h | low | |
| **13** | **T2 + T3** — case-preserving normalisation **+ migration** | 4, 8 | 1 d | **medium — breaking** | |
| **14** | **T6 + T12** — reclassify/strengthen all three substring checks (A5, A6, A7) together; §8.1 `shell=False` | — | 1 d | medium | |
| **15** | §6.2, §8.2, §8.3 — test split, remaining pinning, compliance; release AND/OR + G2-speaker mutation-gap tests | — | 4 h | none | |

Five ordering constraints, each for a reason:

- **T8 first among the open work, not T1.** T8 is tiny, and both T1's fix
  (phase 4) and T7 (below) touch `release.py`; fixing the shared `git()`
  helper first means neither later change inherits a known-bad dependency.
- **T1 stays early** — it is still the fix that matters most for the common
  case (someone edits `render/` without also touching `release.json`), even
  though §12.1 shows it is not sufficient against a more capable attacker.
  Do not wait for T7 to ship it.
- **T9/T10 before T2/T3, both before §6.1.** T9 and T10 harden the same
  citation-integrity subsystem T2/T3's breaking migration touches; doing
  that hardening first means the migration lands on a subsystem that is
  already coherent, not one with two more known holes in it. §6.1 still
  needs T4 first, for the same reason v1 got wrong the first time (§1.3):
  measuring a split module requires a coverage gate that can see it.
- **T2/T3 stays last among the behavioural fixes.** It is the only breaking
  change, needs the migration path in §4.3, and rewrites `quote_cached`
  across every engagement — far safer once `--verify` actually verifies
  (phase 4), evidence integrity is hardened (phases 5, 8), and coverage is
  trustworthy (phase 7).
- **T6, T12 and A5/A6 move together, late.** All three are the identical
  bypassable-substring pattern in the same file; fixing them once, together,
  after the higher-severity citation/release work, avoids three separate
  reviews of the same design question ("how much structure should an agent
  governance check actually parse?").

**T7 (release.json signing) is deliberately not in this table.** It is the
single highest-severity open item, and it is also the one genuinely
architectural decision here — who holds the signing key, and whether the
manifest should live outside the repository the same way evidence content
already does. That is a decision for whoever owns this tool's deployment
model, not something to default into a phase number. Until it is designed,
consider a cheap interim mitigation alongside phase 4: have `--verify` print
a standing warning that `release.json`'s own integrity is not yet
cryptographically enforced, so the gap is visible rather than implied.

**Expect newly-visible findings, not regressions.** F1 masked lint, types and
secrets for the repository's entire life, and fixing F2 immediately revealed
F2b beneath it. §12's round found 37 more this way, at ten times the depth,
because it actually ran things instead of only reading them (§1.1's lesson,
one round further in). A gate — or an audit — that has never been able to
fail has never been telling you anything. Treat each round's output as
backlog that was always there, not as regressions introduced by looking
harder.

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
12. `release.json` is signed (or stored write-once outside the repository);
    `--verify` refuses before trusting any field in it, `approved_by`
    included, if the signature does not match — proven by a test that
    tampers with the manifest itself, not only with `render/`.
13. `git()` distinguishes a failed dirty-query from a clean tree; a test
    simulates the query failing (not merely a clean or dirty result) and
    asserts `release`/`mine` refuse rather than proceed.
14. G13 rejects a real, existing symbol id cited for an element/relationship
    it has no relationship to, proven by a seeded-defect test parallel to
    every other G-rule's.
15. A record whose declared `content_kind` does not match its actual bytes
    (structured content labelled prose, or the reverse) is rejected by G1,
    not silently accepted under whichever validation path the label happens
    to route it through.
16. Registering evidence with an id that collides with an existing record
    refuses (or requires an explicit confirm), rather than silently deleting
    the older record — proven by a test that registers, then re-registers
    with no `--id`, and asserts the first record still exists.
17. An `.agent.md` file whose actual invocation keeps `shell` open (via
    `--allow-tool=shell` after a `--deny-tool=write,shell` appearing
    elsewhere in the file) is rejected by `archtrace agents`.

---

## 12. Deep audit — round 3 (11-dimension adversarial sweep)

Rounds 1 and 2 (§1) were single-pass reads, with or without execution. This
round was different in kind: 11 parallel agents each audited one dimension of
the live repository — executing real commands, mutating source in isolated
scratch copies (never touching the working tree), and building the Docker
image — and every finding above low severity then went to one to three
independent skeptics instructed to *refute* it, defaulting to refuted unless
they could not. 93 agents, ~7.1M tokens, zero agent errors. 45 findings were
raised; 37 survived adversarial verification; 1 was refuted outright
(`errors="replace"` silently substituting undecodable bytes — three skeptics
agreed the corruption is real but does not compound into a citation-integrity
failure the way the claim argued); 7 were low-severity and not independently
verified beyond the originating agent's own reproduction.

Six of the 37 are summarised here directly, chosen for severity or for
correcting something this document itself already got wrong (§1.6/§1.7's
pattern, one level deeper). The rest are grouped by theme in §12.7–§12.12,
in the same compact format as §7 and §8. Three of the six — T7 (release.json
integrity), the gitleaks `(?m)` gap, and the evidence-id collision — were
independently re-verified by me, not just by the workflow's own skeptics,
before being written up here.

This round also re-ran T1–T6 and F1–F4 against the current HEAD (`6e9983a`).
All six T-findings reproduce exactly as §3–§5 describe; all four F-fixes hold.
Nothing in this document needed correcting on that count — see the appendix.

### 12.1 T7 — `release.json` has no integrity of its own; T1's fix is necessary but not sufficient [Certain]

**Severity: critical.** §3's fix (call `gate.g6_render_freshness` instead of
the full gate) is still correct and still needed — but it assumed the
*comparison* was the weak point. It is not the only one. `release.json`
itself is a plain, unsigned JSON file, and `_verify_release` trusts every
field in it, including the very hashes it checks against:

```python
manifest = canon.load_json(path)          # release.py:127 — no signature check
...
if "sha256:" + hashlib.sha256(data).hexdigest() != expected:   # expected comes from the file itself
```

Anyone with the repository write access needed to tamper a source document in
the first place has exactly the access needed to also edit `release.json` so
its stored hashes match the tampered content — and, separately, to run the
ordinary `archtrace render` command so `render/` on disk is internally
consistent with the tampered model. At that point §3's fix finds nothing:
`gate.g6_render_freshness` compares disk against a fresh render of the
model, and both now agree, because both are tampered together.

**Reproduction.** In an isolated scratch copy: ran a genuine
`archtrace release --approved-by "Real Approver" --role architect`; as the
attacker, appended an unreviewed line to `model/model.json`'s content; hand-
edited `release.json`'s `sources["model/model.json"]` hash to match the
tampered file, hand-edited every `outputs` entry to the hash of a fresh
`render_all(eng)` of the tampered model (exactly what `archtrace render`
would produce), and set `approved_by` to `"Fabricated CISO Signoff"`. Ran
`archtrace release --verify`:

```
release.json  approved by Fabricated CISO Signoff (ciso) at ...
              commit 2485717...
MATCH — every source and output is byte-identical to what was approved. Safe to publish.
```

Exit 0. Confirmed independently: `_verify_release` (`release.py:113-160`)
performs no HMAC, signature, or any other check on `manifest` before trusting
it.

**Fix.** §3's `g6_render_freshness` change is still the right first step —
it closes the case where only `render/` drifts from a still-honest
`release.json`. It does not close this one. `release.json`'s trust value
depends on being harder to forge than the thing it certifies:

1. Sign the manifest — HMAC with a key not stored in the repository, or a
   detached signature — and have `--verify` refuse before trusting *any*
   field, `approved_by`/`authority_role` included, if the signature does not
   match.
2. A signature alone leaves the reference value and the tampered value
   colocated and equally writable. Storing the manifest (or its signature)
   outside the repository, or in a write-once location, is what actually
   separates "can tamper the deliverable" from "can also rewrite the ledger
   checked against it."

### 12.2 T8 — the git() helper turns "the query failed" into "the tree is clean" [Certain]

**Severity: high.** `commands/_shared.py`'s `git()` helper returns `None` for
*any* non-zero exit from the subprocess — not only "not a git repository."
Both `cmd_release` and `cmd_mine` treat a falsy `dirty` as "clean":

```python
dirty = git(root, "status", "--porcelain")     # None if the query itself failed
...
elif dirty and not args.allow_dirty:           # None is falsy — silently passes
```

**Reproduction.** In a scratch git repo: added a genuinely untracked file
(`?? SNEAKY_UNTRACKED.txt`, a real dirty tree), then corrupted `.git/index`
(`printf 'GARBAGE' > .git/index`) so `git status --porcelain` fails (exit
128) while `git rev-parse HEAD` still succeeds. Ran
`archtrace release --approved-by Tester --role architect` with **no**
`--allow-dirty`: exit 0, `release.json` written with
`"working_tree_clean": true` bound to a real commit hash, zero warning.
Reproduced the identical bypass in `cmd_mine` — a real uncommitted edit plus
the same corrupted index produced a dry-run print with no `(DIRTY)` marker
and no `--allow-dirty` requirement.

**Fix.** Have `git()` distinguish "ran and reported clean" from "the query
itself failed" — a typed error or a sentinel other than the empty-string
case — and have `cmd_release`/`cmd_mine` treat a failed dirty-query as a hard
refusal, not an implicit pass.

### 12.3 T9 — G13 verifies a symbol exists; it never checks the citation is *about* that symbol [Certain]

**Severity: critical.** G13 is documented as "G2 for code evidence" — the
control that makes "grounded in the repository" a checkable claim rather
than an assertion. Its entire check is:

```python
if facts.symbol(symbol) is None:     # gate.py:567 — existence only
    yield Finding("G13", BLOCK, ...)
```

**Reproduction.** Grounded `c_telemetry` ("Telemetry Sidecar") as `existing`
against a real evidence record, citing a real symbol id — which actually
names `list_users`, an unrelated method with no connection to telemetry.
`archtrace check` produced zero G13 findings.

**Fix.** At minimum, cross-check the cited symbol's own name or file path
against the element/relationship it is attached to for a plausibility
signal (not a semantic guarantee, but better than none); at most, require
the citing model entry to name which fact record field it is grounded on
(name, kind, or file) and validate that field matches, the way G4 validates
a grounding kind's *shape* rather than only its existence.

### 12.4 T10 — `content_kind` is a self-declared label, never checked against the bytes it describes [Certain]

**Severity: critical.** G1 only runs format validation (`parse_facts`) when
`content_kind == "structured"`. A record mislabeled — or defaulted — to
`prose` skips that validation entirely, and G2/G11 then treat its raw bytes
as quotable stakeholder speech with independently self-declared authority.

**Reproduction.** Registered a byte-identical copy of a real code-facts JSON
file with `content_kind` omitted (defaults to prose) and
`authority=stakeholder-confirmed`. Cited 150 bytes of raw JSON syntax as a
stakeholder's quote backing a confirmed requirement. `archtrace check`
produced zero findings — defeating G11's entire stated purpose (observed
implementation can never carry a requirement) via one omitted field.

**Fix.** Validate `content_kind` against the bytes themselves — attempt
`parse_facts` regardless of the declared kind and flag a mismatch either
direction (declared prose that parses as structured facts, or declared
structured that doesn't parse) — rather than trusting the label to gate
which validation runs.

### 12.5 T11 — auto-generated evidence ids collide with, and silently destroy, hand-assigned records [Certain — confirmed independently by two separate dimension agents]

**Severity: high.** Both evidence-registration entry points derive a new id
from `len(index['evidence']) + 1` — a record-count sequence, not a
collision check. `--id` is a fully documented flag on `evidence add`,
`evidence add-facts`, and `mine`, so an out-of-sequence id is ordinary usage.
Both intake paths then do delete-then-append before writing:

```python
"id": args.id or f"EV-{len(index['evidence']) + 1:03d}",   # evidence.py:275
...
index["evidence"] = [e for e in index["evidence"] if e["id"] != record["id"]]
index["evidence"].append(record)
```

**Reproduction.** Two ordinary CLI calls, no hand-edited JSON: registered an
authoritative-document record as `EV-002` explicitly. Registered a second,
unrelated interview transcript with **no** `--id` — the index then has one
record, so the auto-id computes `EV-002` again. Output: `registered EV-002`,
no error. The index afterward contains exactly one record, `EV-002`, and
every field is the *second* transcript's; the first record is gone with no
trace. G1's duplicate-id check can never fire — by the time the gate runs,
the collision has already resolved itself by destroying the older record
before it was ever written to disk.

**Fix.** Derive the next id from the maximum existing numeric suffix, not
list length (still not collision-proof against hand-assigned ids, but
strictly better); in all cases, refuse a same-id write whose existing
record's content differs from what is being written, unless the operator
explicitly confirms a replace.

### 12.6 T12 — the substring-check pattern behind the already-documented T6 is not confined to A7 [Certain]

**Severity: critical for A5, high for A6.** T6 named `A7-no-authority-claims`
as five hardcoded substrings. Two more checks in the same module share the
identical design, and one of them is more consequential than A7 — it's the
control that decides whether an agent can actually reach a shell.

**A5-read-only-invocation** (`agents.py:195-203`) only checks whether the
literal string `--deny-tool=write,shell` appears *anywhere* in the body — not
that it governs the agent's actual invocation, and not for a contradicting
`--allow-tool=shell` elsewhere. A file whose real, documented command is
`--deny-tool=write --allow-tool=read,shell` (shell explicitly re-enabled)
passes with zero findings as long as the fully-compliant string also appears
somewhere else in the prose — reproduced with a "historical note" section
citing the old, correct string after the real command overrides it.
`archtrace agents`: `0 finding(s)`, exit 0. This is the exact capability the
module's own top-of-file docstring warns about: an agent denied `write` but
not `shell` writes files with `sh -c 'cat > file'`.

**A6-evidence-is-not-instruction** (`agents.py:206-214`) has the same shape:
it passes if the literal phrases `"evidence is data"` or
`"never instructions"` appear anywhere, with no check of what they assert.
Reproduced with a body that explicitly describes obeying instructions found
inside retrieved documents, while the required phrase appears in a sentence
*describing that it does not do that*. Zero findings.

**Fix.** Same remediation family as T6: stop matching prose, start matching
structure. For A5, extract the agent's actual invocation (the fenced/
indented command block) and validate *that*, plus flag any `--allow-tool=`
naming write or shell anywhere in the file. For A6, require the phrase
inside a recognisable section rather than a bare substring anywhere.

### 12.7 The missing-refusal pattern is systemic, not confined to model.json — T5, expanded [Certain]

T5 named one call site (`Engagement.load`'s `json.load`). The sweep found
seven more, several worse in kind because no fix to `Engagement.load` would
touch them:

- **`archtrace.toml` crashes at *import* time**, before `main()`'s
  `try/except` exists to run at all. `config.py`'s `_from_toml` has no
  exception handling around `tomllib.load`, and `DEFAULT = load()` executes
  at module import (`config.py:218`). A syntax slip in `archtrace.toml`
  crashes `--help` and `config` — the commands someone would run to diagnose
  it — with a traceback, before reaching `Config.errors`, the mechanism this
  codebase built specifically for this. **This one needs its fix outside
  `main()` entirely**: wrap `tomllib.load` in `_from_toml` and route into the
  same `errors` list `_apply()` already populates.
- **`agents._safe_load`'s own docstring guarantee is false.**
  `except (AgentError, OSError)` does not catch `UnicodeDecodeError` (a
  `ValueError` subclass), so one non-UTF-8 `.agent.md` file crashes the whole
  `agents` command instead of being reported as one bad file among many — the
  exact guarantee `_safe_load`'s docstring makes ("one unparseable file must
  not hide the findings in every other file").
- **`evidence add` / `evidence add-facts`** open the user-supplied `FILE`
  with no existence, permission, or encoding guard — reproduced crashing on a
  missing file, a non-UTF-8 file, and a permission-denied file, none guarded
  the way `cmd_mine`'s own `--repo` check already is in the same file.
- **`release --verify` crashes on a corrupted `release.json`** — a second,
  independent failure mode in the same function T7/T1 already flag as
  unsound. `canon.load_json(path)` has no guard; a truncated or bad-merge
  manifest crashes instead of refusing.
- **`promote`** crashes on malformed `requirements/proposed.json` — a fourth
  file loaded through a `canon.load_json` call site a narrow fix to
  `Engagement.load` alone would not reach.
- **`baseline --elements <file>`** crashes on a missing file — notable
  because `baseline` is documented as "run this BEFORE anything else," the
  first command a new user runs.
- **`main()`'s except clause is confirmed incomplete.** Every reproduction
  above escapes `args.fn(args)` uncaught and exits via Python's default (1),
  never this codebase's own `EXIT_USAGE`/`EXIT_BLOCKED` conventions.

**Fix, once, at the root:** give `canon.load_json` itself a
`try/except json.JSONDecodeError` that raises a typed `CanonError` (the same
role `config.ConfigError` should already be playing, §5.2), and have every
direct caller catch that one type consistently rather than patching each
call site ad hoc. Broaden `main()`'s except clause as a last-resort net
beneath the specific fixes, and move `archtrace.toml`'s error surface into
`Config.errors` as its own, separate change (§5.2's `ConfigError` revival is
the natural home for this too).

### 12.8 Security & supply chain — additional findings

Four found; three fixed directly in this pass — each config-only, no
application logic touched, and (for the first two) independently verified by
me, not only by the audit's own skeptics:

- **The gitleaks rule this PR already fixed once still didn't detect
  anything — fixed. [Certain]** Its regex anchored `^` with no `(?m)` flag,
  so in RE2 (as in every standard regex engine — confirmed against Python's
  `re`, which follows the identical convention) `^` matches only the
  absolute start of the scanned content, not each line. Built and ran the
  exact pinned gitleaks binary (v8.21.2): the rule fired on a synthetic
  3-line transcript's first line only; lines 2 and 3, identical in shape,
  were silently missed. The repo's own real fixture transcript — which has
  header lines before the first turn, like every real transcript — was
  **not detected at all**. `(?m)` added.
- **`.dockerignore`'s cache-exclusion patterns didn't match nested paths —
  fixed. [Certain]** Lines 7-18 were bare (`__pycache__/`, `*.py[cod]`, …)
  while line 3 (`**/_evidence_root/`) was correctly prefixed. Docker's
  ignore matcher is not implicitly recursive the way `.gitignore`'s is.
  Built the image from a working tree with real `__pycache__` directories
  under `tools/` (exactly where `make test` writes them): 20 stale `.pyc`
  files landed in the image, undermining the Dockerfile's own stated
  purpose ("reproducible"). Every pattern now prefixed with `**/`.
- **`make mine`'s `RETAIN ?= 2029-01-01` silently satisfied the CLI's
  required `--retention-until` — fixed. [Certain]** `archtrace mine`'s flag
  is `required=True` specifically so an operator cannot register evidence
  without consciously choosing a date; the Makefile wrapper always supplied
  one, so the CLI's own check could never fire through this entry point.
  `RETAIN` is now required explicitly, mirroring `REPO`/`URI`; verified
  `make mine-dry` with no `RETAIN` now refuses (exit 2) and with one
  supplied proceeds past the check into the mine logic unchanged.
- **`mine --local-name`/`--id` allow path traversal. [Certain, still open —
  application-logic change, not config]** Neither is validated against
  escaping `--evidence-root`; `os.path.join` with an absolute `--local-name`
  discards the base path entirely. Reproduced writing a file two directories
  above the evidence root, and — via `evidence add` + `quote` — reading back
  the contents of a file entirely outside `--evidence-root` (a fake secret
  string) as if it were legitimate, citable evidence. **Resolve both the
  write target and the stored `local_path` with `os.path.realpath` and
  reject anything outside `--evidence-root`.**

### 12.9 Test-suite mutation-resistance gaps [Certain]

Five real assertion gaps, each demonstrated by mutating a real line of
production code in a scratch copy and showing the named test(s) still pass:

- `release.py`'s `--approved-by and --role` check mutated to `or` (release
  proceeds with only one flag supplied) — **zero test failures anywhere in
  the 182-test suite.**
- G1's code-evidence commit check (`gate.py:139`, an `and` — blocks only when
  *both* the record and the facts file lack a commit) mutated to `or` — 182
  tests still green, **and** produces a real false-positive block against
  the legitimate, fully-supported "miner didn't set a commit but `--commit`
  was passed" case. `evidence add-facts` has no direct test coverage at all.
- `coverage.Report.failures()`'s `<` mutated to `<=` at the exact
  configured floor — no test uses a boundary-equal value, so an off-by-one
  changing "at the floor" from pass to fail is invisible.
- `renders._boundary` (the real connector-clipping geometry) mutated to
  point away from its target instead of toward it — `test_docx_shapes.py`'s
  21 tests, all passing, never call the real function; they inject a stub
  that does no clipping at all. Only caught incidentally, at the whole-suite
  level, by G6 comparing regenerated SVGs against the committed ones.
- `test_g2_speaker_not_in_the_room` passes for the wrong reason when the
  speaker check (`gate.py:171`) is inverted: the inversion also mis-fires on
  four unrelated, legitimate provenance entries, and `assertFires` only
  checks that G2 fired *somewhere*, not on the seeded record.

**Fix pattern common to all five:** add the missing boundary/partial-input
test case per item above; for `test_g2_speaker_not_in_the_room` specifically,
assert on the finding's `where`, not merely that the rule id appears.

### 12.10 Additional duplication, dead code and drift [Certain]

- **`archtrace baseline`'s citation-quality metric silently diverges from
  G2's actual gate.** `cmd_baseline` counts a quote as sufficient on
  non-emptiness alone, never applying `MIN_QUOTE_WORDS`/`MIN_QUOTE_CHARS`/
  `GENERIC_PHRASES`. A two-word quote scores 100% "citation-backed" in
  `baseline` and then G2 immediately BLOCKs the identical citation under
  `check` — the instrument that decides whether the programme is worth
  running gives a false PASS. **Import the same thresholds `gate.py` uses.**
- The grounding-reference `or`-chain (§7.5) is not the only place a
  canonical lookup got re-derived by hand: `_grounding_text` and
  `_traceability_csv` both bypass `GROUNDING_KINDS`'s kind→field mapping
  that `gate.py` uses correctly, so an entry with a stray leftover field from
  a prior edit can resolve to a different reference in the traceability
  deliverables than the one G4 actually validated.
- The "decline requires rationale+decided_by+date" policy (G3, G12n) is
  hardcoded as an identical literal tuple in two places in `gate.py` with no
  shared constant — an organisational policy this codebase otherwise always
  centralises.
- The SVG legend hardcodes a *third* independent copy of the five grounding
  kinds, alongside `FILL`/`_DRAWIO_STYLE` (§7.2) and `GROUNDING_BADGE`
  itself — never derived from `model.GROUNDING_KINDS`.
- `model.LEVELS` — meant to be the canonical four-level enumeration — is
  dead code with zero references; every consumer hardcodes its own copy
  instead (the exact duplication §7.2 already flags).
- `renders.py:395` compares `content_kind` against the bare string
  `"structured"` instead of importing `mining.CONTENT_STRUCTURED`, unlike
  every other consumer of that constant.

### 12.11 Documentation accuracy — fixed directly in this pass [Certain]

Six drifted or fabricated claims, found and corrected without waiting for a
future phase, since each was mechanical and low-risk:

- README.md and RUNBOOK.md each hardcoded a test count (157, 88) that
  disagreed with each other and with reality (182). Both now say "runs the
  suite" / "confirms the toolchain" instead of a number that will drift
  again.
- CHANGELOG.md's 0.3.0 entry said `cli.py` reached 215 lines and 155 tests;
  the commit it describes (`4839c10`) actually produced 248 lines and 157
  tests, confirmed via `git show <commit>:file | wc -l` against that exact
  commit — wrong on arrival, not drifted since. Corrected to 248 / 157.
- CHANGELOG.md and `docs/tech-debt.md` both stated the post-refactor largest
  module was "312" lines — a figure that matches no file at any inspected
  commit, and directly contradicts `tech-debt.md`'s *own* item 1, three
  paragraphs earlier, which says 598. Corrected to the verified true figure
  (601 lines at that commit; `renders.py` is 656 today, already the figure
  §1.2 of this document uses).
- `docs/example-baseline.txt`, the artifact README.md cites as proof the
  worked example scores 50% traceability, no longer matched a fresh run of
  the same command (`existing: 1` committed vs `2` live — `example/model.json`
  gained a second `existing`-kind grounding entry since the file was
  committed, and nothing regenerates this artifact). Regenerated from the
  live tool — which is where a second, follow-up CodeRabbit review (on this
  same push) caught that the regenerated numbers were *themselves* internally
  inconsistent: the four grounding-kind rows summed to 6, not the 5 the
  subtotal above them stated. That traced to a real, previously-uncaught
  counting bug in `cmd_baseline` (`verify.py`), not to anything wrong with
  the doc: the subtotal counts *elements* with a non-`satisfies` kind, once
  each, but the breakdown below it counted every grounding *entry* — so an
  element citing two separate pieces of evidence for the same kind (real,
  legitimate, independently gate-checked — exactly `s_mam`'s case) inflated
  its row past what the subtotal it explains could account for. Fixed at the
  root: the breakdown now tallies the identical bucket the subtotal does,
  deduplicated per kind per element, with a regression test that parses the
  printed output and asserts the invariant generically (not today's specific
  numbers) — mutation-tested against the original bug to confirm it fails
  the way it should (`6 != 5`).

None of this affected the two numbers the baseline instrument actually
decides on (50% traceability, 0% unexplained — both computed at the element
level throughout, never touched by the entry-counting bug) — but a
repository whose thesis is "verified by running it" should not fail that
standard on its own worked example, and CodeRabbit's arithmetic check found
a real bug my own regeneration had missed.

### 12.12 Live CI/CD state — confirmed clean [Certain]

A full static sweep of both workflow files at the current HEAD, specifically
for the F1 defect class (a shell idiom that swallows failure, a stray
`continue-on-error: true`, output piped through something that discards an
exit code): **none found.** `make lint`/`make types` run as bare steps and
correctly propagate failure; the gitleaks step has `GITHUB_TOKEN` and scoped
`pull-requests: read`; `archtrace.yml`'s `workflow_dispatch`-only trigger
means its intentional placeholder `exit 1` no longer runs on any PR or push.
This is a negative finding worth recording: the specific defect class that
produced F1 has not reappeared elsewhere.

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
| §12 (all) | a `Workflow` run: 11 parallel agents, each executing real commands against a scratch copy of the repository (never the working tree directly); every finding above low severity independently re-checked by 1–3 skeptic agents instructed to default to refuted; 93 agents total, 0 errors, 45 findings raised, 37 confirmed, 1 refuted, 7 low-severity and not independently re-checked. Full transcript: `wf_78854115-8b9` |
| T7 (my own check) | read `release.py:113-160`'s `_verify_release`, confirmed `canon.load_json(path)` performs no signature/HMAC check before trusting `manifest` |
| gitleaks `(?m)` (my own check) | `python3 -c` comparing `re.search` with and without `re.MULTILINE` against a multi-line transcript-shaped string — RE2 follows the identical `^`-anchoring convention |
| T11 (my own check) | reproduced the id collision directly with two ordinary `archtrace evidence add` calls in a scratch engagement — no hand-edited JSON |
| reverify (§12, all of T1–T6, F1–F4) | every reproduction in §3–§5 and §1 re-run against `6e9983a` inside the same Workflow run, as its own dimension; all ten still reproduce exactly as described |

Two rounds of external review (Copilot and CodeRabbit, both against `b9e5eb1`
on [PR #2](https://github.com/ianshank/archtrace/pull/2)) are folded into
§1.6, §1.7, §6.1, §7.5, and acceptance criteria 1–3 and 9 above. Every claim
either bot made was independently re-derived against the code before being
accepted — none was taken on the bot's word alone. §12's findings carry the
same standard: three of its six full-treatment findings (T7, the gitleaks
`(?m)` gap, T11) were independently re-verified by me before being written
up, beyond the adversarial verification already performed inside the
Workflow run.
