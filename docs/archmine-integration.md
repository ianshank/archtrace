# Integrating archmine-kit

**Status: Phases 1 and 2 are built and shipped. Phases 3–4 are planned, not written.**

---

## 1. What the kit is

A local-first codebase miner: Tree-sitter AST extraction → incremental SQLite
symbol graph → lexical seeding + Personalized PageRank → token-budgeted context
packs, plus `architecture-facts.json`, a Mermaid dependency map, an inventory, a
review checklist, a Typer CLI, an MCP server, Copilot agent files and a CI gate.
~1,400 lines, MIT, seven runtime dependencies.

**It is good, and it fills a real hole.** archtrace has no code analysis at all.
The `existing` and `derived` grounding kinds have had no automated evidence
source since they were introduced — you typed them by hand and nothing checked
them. archmine is exactly that source. This is complementary, not overlapping.

I installed it, ran its test suite (3 tests, all pass) and mined a fixture. It
works.

## 2. Defects found, verified by running it

**A1 — The CI drift gate cannot pass. [Certain, demonstrated]**
`artifacts.py` writes `datetime.now(UTC).isoformat()` into
`architecture-inventory.md`, and `.github/workflows/architecture.yml` ends with
`git diff --exit-code -- docs/architecture/generated`. Two runs 1.1 s apart:

```
architecture-facts.json     SAME     ff8a87e528a7 ff8a87e528a7
architecture-inventory.md   DIFFERS  6a45d44b11a7 fc5fe68d735b
dependency-map.md           SAME     aa34237ff538 aa34237ff538
review-checklist.md         SAME     71931a4506bc 71931a4506bc
```

The other three artifacts are already deterministic, so the fix is one line:
drop the timestamp, or move it to a field the gate excludes. This is the same
class of defect archtrace hit at G6 and solved by comparing canonicalised
content — a gate that fails for reasons nobody can diagnose gets disabled inside
two weeks.

**A2 — `Extraction.commit` is declared and never populated. [Certain]**
`models.py:39` declares it; nothing in `src/` ever assigns it. The generated
review checklist says *"Confirm repository boundary and indexed commit"* — the
field is always `null`. For a context pack that is cosmetic. **For evidence it is
fatal**: a fact about a codebase that cannot say *which* codebase state cannot be
re-verified, so it is not evidence. Phase 1 therefore refuses to register facts
without a commit and makes `--commit` mandatory.

**A3 — Symbol ids churn on unrelated edits. [Likely]**
`_id()` hashes `path:kind:name:line`. Insert a line above a symbol and its id
changes, which is fine for a transient index and wrong for a durable citation —
the same defect archtrace had when Jira `external_id` hashed a renameable id.
Phase 1 lives with it and G13 catches the consequence loudly; Phase 3 proposes
the fix.

**A4 — `architecture-reviewer.agent.md` name-collides with archtrace's. [Certain]**
Both define an agent called `architecture-reviewer`. A user-level agent shadows a
repo-level one silently, so whichever lands last wins with no error. The kit's
version also grants `archmine/*` tools and does not carry the
evidence-is-not-instruction rule.

## 3. The four conflicts, and how each is resolved

| Conflict | Resolution |
|---|---|
| **Dependencies.** Seven runtime deps (tree-sitter-language-pack alone ships ~100 MB of compiled grammars) against archtrace's zero-dependency invariant | **The seam is a file, not an import.** archtrace reads `architecture-facts.json`; it never imports archmine. The gate runs on a bare runner whether or not a miner exists anywhere. Enforced by a test. |
| **Authority.** archmine output is observed implementation by construction | **It grounds elements, never requirements.** G11 already blocked this tier from carrying a requirement; G2 now refuses it a second time with a message that explains where it *does* belong. Two independent refusals, because this boundary is what the whole grounding design rests on. |
| **Two renderers.** archmine writes Mermaid/inventory/facts to `docs/architecture/generated`; archtrace writes to `render/` under G6 | **archmine's output is an evidence input, not a deliverable.** Its facts file goes under `_evidence_root/`. Its Mermaid and inventory are not adopted — archtrace already renders those from the model, and two generators of the same artifact is guaranteed drift. |
| **Two CI gates.** archmine's ends in `git diff --exit-code` | **One gate.** `archtrace check` is the blocking gate. Mining runs as a separate, earlier, non-blocking step that produces evidence. Do not adopt `architecture.yml` — see A1. |

## 4. Phase 1 — built

New module `tools/archtrace/mining.py`, standard library only.

**Evidence gains a content kind.** Prose is normalised and cited by byte span;
structured evidence is hashed raw and cited by symbol id. Casefolding a symbol
table would destroy the identifiers it exists to carry, so these cannot share a
hash path. Records with no `content_kind` are prose — which is what every record
written before this existed already was.

```bash
archtrace evidence add-facts architecture-facts.json \
  --commit 4f2c9ab... --source-uri https://github.example.com/media/mam-legacy \
  --date 2026-09-16 --classification internal --retention-until 2029-09-16

archtrace symbols EV-003 UserService     # find a symbol to cite
```

**Grounding gains an optional `symbol`:**

```json
{"kind": "existing", "evidence_id": "EV-003", "symbol": "sym:9d3c379feee242b7"}
```

**New rule G13 — code-fact citation integrity.** This is G2 for code evidence: a
cited symbol must exist in the facts file it claims to come from. Without it,
"grounded in the repository" is an assertion rather than a claim anyone can
check, and the mining step buys nothing a hand-written note would not. It fired
correctly on a fabricated symbol id the first time it ran.

**G1 extended:** structured content hashes raw bytes (one changed byte blocks),
and code evidence without a commit blocks.

### Backwards compatibility

Guaranteed by construction and by test:

- Every new field is additive and optional; `schema_version` stays `1`.
- A missing `content_kind` means prose. Existing engagements are untouched.
- G13 is inert when no grounding carries a `symbol`.
- `archtrace check` behaves identically with archmine absent, uninstalled, or
  never heard of.

### Tests — 75, up from 56

`tools/tests/test_mining.py` adds 19:

- **Facts parsing**: unknown `schema_version` refused, malformed JSON refused,
  symbol without an id refused, unknown extra fields tolerated.
- **G1 on structured content**: one changed byte blocks; missing commit blocks;
  unknown content kind blocks.
- **G13**: unmined symbol, symbol against prose evidence, symbol on a `satisfies`
  grounding, symbol with no `evidence_id`.
- **Authority boundary**: a requirement citing code evidence is refused *twice*,
  by G2 and by G11 independently.
- **Backwards compatibility**: an engagement stripped of all code evidence still
  passes; records without `content_kind` behave as prose; G13 returns nothing.
- **Dependency boundary**: importing every archtrace module pulls in nothing
  outside the standard library, and `mining.py` imports no miner.

One real bug surfaced while writing these: G8 indexed `grounding["evidence_id"]`
directly and raised `KeyError` on a malformed entry, masking every other finding.
Gate rules are now total over malformed input — a missing field is another rule's
finding to report, never a traceback.

## 5. Phase 2 — built

### `archtrace mine`

```bash
make mine REPO=~/work/mam-legacy ID=EV-004 URI=https://github.example.com/media/mam-legacy
make mine-dry REPO=... URI=...        # print what would run, touch nothing
```

**Driven as a subprocess, never imported.** That is what lets the miner be an
arbitrary toolchain — a different Python, a compiled binary, a container — while
archtrace stays stdlib-only. The command comes from the operator's flags or the
Makefile; nothing this step reads can change it, which is the same
evidence-is-not-instruction boundary the agents carry.

What it refuses, and why:

| Refusal | Reason |
|---|---|
| No resolvable commit | Facts that cannot name a codebase state are not evidence |
| Dirty working tree | The facts would describe something no commit names (`--allow-dirty` to override, and the message says the commit is then approximate) |
| Miner exits non-zero | Last 2 KB of stdout and stderr are printed rather than swallowed |
| Miner produced no facts file | Names the path it looked for |
| Facts fail `parse_facts` | Unknown `schema_version` is refused, not guessed |

**Commit stamping (the A2 fallback).** When the miner emits no commit, archtrace
stamps the resolved one into the **copy** placed under `_evidence_root/` and
leaves the miner's own output untouched — evidence is a snapshot; the miner's
output directory is scratch. Verified by test both ways: the copy carries the
commit, the source still does not.

**Inferred-relation warning.** Mining the kit's own repository reports
`{'INFERRED': 37, 'EXTRACTED': 126}`, and the command now says so out loud: name
resolution is a guess, not a compiler. Grounding an element on an inferred
relation without checking it is exactly the unsupported inference the advisory
reviewer exists to find.

### Source locators in the traceability render

A symbol id is verifiable but unreadable, so `traceability.md` now resolves it:

```
| `s_mam` | system | Existing MAM | existing:EV-001, existing:EV-003 @sym:9d3c… | src/service.py:1 (class UserService) |
```

`traceability.csv` gains `symbol` and `source_locator` columns, and a new **Code
evidence** section lists each facts file with its repository, commit, and symbol
and relation counts. Locators are resolved at render time rather than stored, so
they cannot drift from the facts file.

### A1 and A2 fixed upstream — `docs/patches/archmine-a1-a2.patch`

A 61-line patch against archmine-kit 0.1.0. Applied it, reinstalled, re-ran:

```
A1 — determinism after the patch:
  architecture-inventory.md        SAME
  dependency-map.md                SAME
  review-checklist.md              SAME
  architecture-facts.json          SAME

A2 — commit in the facts file:
   d31b83363d7eea452747e1cc873abcade08393c6
```

All four artifacts are now deterministic, so the kit's own drift gate becomes
capable of passing, and `commit` populates from `git rev-parse HEAD`. The kit's
own 3 tests still pass. **Send this upstream** — archtrace's stamping fallback
keeps working either way, and becomes a no-op once the patch lands.

### Tests — 88, up from 75

13 more: dry-run writes nothing; dirty tree refused and overridable; non-repo
refused; failing miner refused; miner producing nothing refused; malformed facts
refused; evidence registered with the right shape and a hash matching the copy;
commit stamped into the copy but not the source; a miner-supplied commit left
alone; mined evidence passing the gate once cited; locators resolved in both
renders; an unresolvable symbol degrading to its id rather than crashing.

The mine tests use a **fake miner** — a six-line script — so the suite runs on a
machine where nothing is installed. That is the same property the gate has, and
it is worth keeping.

## 6. Phase 3 — durable symbol identity (not built)

A3 makes symbol ids churn on unrelated edits, so a model that cited a symbol last
month may fail G13 this month for no architectural reason. Options, in order of
preference:

1. **Content-addressed ids** — hash the symbol's normalised body rather than its
   line number. Survives movement, changes on real modification. A patch to
   `extractors._id()`.
2. **A resolver** — keep churning ids but let G13 fall back to matching
   `path` + `kind` + `name`, and warn that the id moved.
3. **Accept it** and re-index whenever the gate complains. Cheapest, noisiest.

Do not build 2 before trying 1; a fallback that silently repairs broken citations
is a gate that stops meaning anything.

## 7. Phase 4 — agents and MCP (not built, and mostly should not be)

- **Rename the kit's reviewer** to `archmine-reviewer` before copying it anywhere
  (A4), and port the evidence-is-not-instruction section into it.
- **Adopt `architecture-miner.agent.md`** as a third read-only agent, run with
  `--deny-tool=write,shell`. It maps onto the existing mining step.
- **The MCP server is the one piece to think hardest about.** It gives an agent
  live query access to the symbol graph, which is genuinely useful for the
  modeler and genuinely a new trust surface: a tool that answers questions about
  the codebase is a tool whose answers enter the model. It changes nothing about
  the gate — facts still arrive as a hashed file — so it is additive rather than
  load-bearing. Treat it as an adapter and hold it to the adapter contract tests
  in `REVIEW.md` before wiring it up.

## 8. What is deliberately not adopted

- **`architecture.yml`** — broken (A1), and archtrace already has a gate.
- **archmine's Mermaid and inventory renders** — archtrace renders those from the
  model. Two generators of the same artifact is drift by construction.
- **`validate_artifacts.py`** — needs `jsonschema`; `parse_facts` validates the
  shape archtrace actually reasons over, in stdlib.
- **pydantic/networkx/typer inside archtrace** — the boundary test exists to stop
  this arriving by accident.
- **archmine's `review-checklist.md`** — a good checklist, but a markdown file of
  unticked boxes is not a gate. Every line on it that can be made deterministic
  already is a G-rule.
