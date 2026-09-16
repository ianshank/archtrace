# archtrace — automation spec for solutions-architecture engagements

**Version:** 2 (post peer review)
**Date:** 2026-09-14

v1 was reviewed adversarially and four defects were load-bearing enough to change the design: the element-grounding gate forced requirement fabrication; the provenance check would have blocked on nearly every real transcript; evidence-in-git cannot satisfy retention; and the go/no-go decision sat after maximum sunk cost. All four are fixed below. The review log is in `REVIEW.md`.

---

## 0. The challenge, first

**0.1 — Your stated constraint is self-contradicting. I designed for the strict reading anyway.** [Certain]
Copilot CLI is a local binary that executes shell under an allowlist. If it runs, Python runs. So "no arbitrary local tooling" is a policy posture, not a capability limit. Designed to the strict reading regardless: **everything here is Python 3.9+ standard library. Zero pip installs. No Java, Node, pandoc, drawio CLI or Structurizr CLI.** It runs wherever Copilot CLI runs, and unmodified on a default `ubuntu-latest` runner with no setup step.

**0.2 — A deterministic gate requires deterministic compute. No agent can gate this.** [Certain]
If no script runs anywhere, your only available gate is LLM-as-judge, which you have already ruled out. Establishing *somewhere* a script can run — your laptop, or Actions on the repo already hosting your Copilot agents — is the single unlock. Everything else is negotiable.

**0.3 — `drawio-skill`'s layout-preserving sync is a workaround for a schema defect, not the highest-value find.** [Likely]
You only need layout *preserved* if layout lives outside the model. Put integer `layout: {x, y}` on each element and layout becomes versioned, diffable and regenerable with no dependency. **Narrowed after review:** this is authoritative for `.drawio` and for the SVG renderer only. Mermaid and PlantUML have no coordinate input, so there `layout` drives *emission order* — which is the only layout lever those formats offer. Lucid's round-trip is unverified; see §6.1.

**0.4 — Evidence content in git cannot satisfy retention, and this is the program-killer.** [Certain — upgraded from [Likely] after review]
Not a gap, a contradiction. G1 demands evidence files hash identically forever; retention demands deletion. Both cannot hold in git — and deleting a file does not delete the blob, which stays reachable by SHA in every clone, fork and CI cache. **Fix: the repo stores the evidence *manifest*, never the evidence content.** Content stays in the system of record that already has a retention policy; the gate reads it through `--evidence-root` pointing at a git-ignored working copy. This also means the repo no longer inherits the recording's classification, which is probably what keeps you on GitHub.com instead of GHES.

Residual, and it needs a real decision: the ≤25-word verbatim quotes live in `requirements.json` forever. Is a 25-word quote from a confidential recording itself confidential? That has an answer at Comcast and it changes the design.

---

## 1. The inversion

Your source of truth today is the **rendered artifact**. Every revision loop therefore destroys prior work, which is why step 7 feels like cleanup.

> **The model lives in git. Everything downstream is a build output. Renders are never edited, only regenerated.**

| Today | Under archtrace |
|---|---|
| Traceability is an appendix written at the end | Grounding is a required field on every element; the build fails without it |
| "Traces to data" means a citation someone typed | A citation is a byte-range in a hashed evidence file, verified by the gate |
| Revision = redo the diagram and re-polish | Revision = edit the model, regenerate, re-import |
| Jira tickets are typed from the doc | A ticket is a model diff |
| Peer review reads the artifact | Peer review reads the **model diff**; artifacts are derived and cannot disagree with it |

---

## 2. Layout and format

```
engagement-<client>-<name>/
  evidence/index.json           # MANIFEST ONLY — no recording content in git
  requirements/proposed.json    # agent output
  requirements/requirements.json# human-confirmed
  model/model.json              # C4 + ADRs + out-of-scope + open questions
  render/                       # 100% generated; .gitattributes marks it generated
  review/advisory.md            # LLM-as-judge; never affects exit code
  .github/agents/*.agent.md
  .github/workflows/archtrace.yml
  tools/archtrace/              # zero-dependency Python
```

**JSON, not YAML.** [Certain] PyYAML is not stdlib. `tomllib` is read-only and 3.11+ (v1 wrongly implied it was available at 3.9). Structurizr DSL needs Java. JSON is stdlib, is what an LLM emits most reliably, and gives the gate exact JSON pointers.

Canonicalization uses an **explicit key order per object type**, not global `sort_keys` — stable diffs *and* readable files. `archtrace fmt` enforces it.

---

## 3. Stage 0 — Evidence intake (no LLM)

`evidence/index.json` holds records only:

```json
{"schema_version": 1, "evidence": [{
  "id": "EV-001",
  "source_uri": "https://…/stream/…",     // system of record, not a repo path
  "local_path": "EV-001-kickoff.txt",      // relative to --evidence-root, git-ignored
  "sha256_normalized": "…",                // hash of the NORMALIZED text
  "source": "teams-transcript",
  "date": "2026-09-02",
  "participants": ["A. Stakeholder", "B. PM", "I. Cruickshank"],
  "classification": "internal-confidential",
  "retention_until": "2027-09-02"
}]}
```

**Normalize at intake, then hash the normalized form.** [Certain — this is why v1's G2 would have failed]
Testing showed the naive substring rule fails on ordinary Teams exports: line-wrapped sentences, curly apostrophes (`’` vs `'` — and **NFKC does not fold these**), NBSP, zero-width characters (NFKC does not fix these either), and interleaved speaker/timestamp lines. Left as written, G2 blocks nearly every requirement and gets switched off in week two.

`archtrace normalize` is one canonical function: NFKC → explicit punctuation folding (`‘’‛→'`, `“”→"`, `–—→-`, `…→...`) → strip `​-‍﻿` → collapse all whitespace to single spaces → casefold. Intake stores the normalized text and hashes *that*, so G1 and G2 agree by construction.

`.docx`/`.pdf` evidence has no stdlib text extractor. Intake requires plain text; converting a SOW to `.txt` is a manual step and that is stated rather than hidden.

---

## 4. Stage 1 — Requirement extraction (one agent, human-confirmed)

**One agent. No council, no debate ensemble.** [Likely — downgraded from [Certain] after review]

The honest version of the arXiv 2510.22787 argument, which is stronger than v1's:

1. The study's **only deterministic metric** — Naming Consistency, regex-based — favors single-agent hard: GPT-4o 60.85 → 16.46 (1 round) → 8.24 (3 rounds), with token cost ~40K → ~500K. Traceability depends on stable naming, so this is the metric that matters for you.
2. The study's other three metrics (semantic consistency, clarity, feasibility) are **LLM-as-judge outputs from a judge never benchmarked against human experts**. v1 cited them as [Certain] evidence while simultaneously arguing that judge is unfit to gate. That was incoherent. They are supporting, not load-bearing.
3. **Multi-agent won on breadth**: compilation success 80.11 → 100.00, abstraction adherence 97.50 → 100.00, mean L2 components 7.0 → 8.2. For extraction from messy evidence, where the failure mode is *missing* something, breadth is arguably the axis that matters most. Stated plainly because it argues against the choice.
4. The authors attribute the collapse to their own implementation and name the fix: *"Agents lack a common, persistent data structure on which to ground nomenclature"* → *"a shared glossary or a central knowledge graph."* **`model.json` is exactly that.** The paper's own remedy for the failure being cited is the artifact you are building.
5. N=5 toy briefs with pre-numbered requirements; you have multi-hour transcripts. No repeated trials, no CIs. Gemini 1.5 Flash went *up* under collaboration (80.42 → 82.00).

**Revisit if the §9 baseline shows element-coverage misses** — that is the axis multi-agent won on.

**Chunking is real.** [Likely] A kickoff transcript + SOW + email thread exceeds any context window, so extraction is N calls, not the two §11 claims — which reintroduces the exact cross-chunk naming problem. Mitigation is the paper's: pass existing `requirements.json` plus a glossary into every chunk as grounding.

Requirement record:

```json
{"id": "REQ-014", "uid": "r_8f3a…",
 "statement": "Ingest must tolerate a 4-hour upstream outage without data loss.",
 "type": "nfr", "priority": "must", "status": "confirmed",
 "supersedes": null, "superseded_by": null, "conflicts_with": [],
 "provenance": [{"evidence_id": "EV-001", "speaker": "A. Stakeholder",
                 "start": 4192, "end": 4251, "quote_cached": "…"}]}
```

- **Provenance is a byte span into the normalized text**, not an authored quote string. [Certain] This kills JSON escaping problems (a verbatim quote is the worst possible payload for hand-authored JSON), makes the locator verifiable instead of decorative, and makes G2 an O(1) bounds-and-hash check. `quote_cached` is derived data written by `archtrace fmt`, and G2 verifies the cache matches the span.
- **`speaker` must appear in that evidence record's `participants`.** Catches "quoted the vendor's disclaimer as a client requirement."
- **Lifecycle**: `proposed | confirmed | superseded | retired`. Requirements change mid-engagement; that is the normal case. G3 ignores retired, and requires superseded ones to name a successor.
- **`uid`** is generated once and never derived from the name — see §8.
- Promotion `proposed → confirmed` is **a human git commit**. That commit is the human gate; git history is the audit trail.

---

## 5. Stage 2 — The model

The v1 schema's `satisfies`-everywhere rule was the worst defect in the spec. **[Certain]**

Real architectures are full of elements no stakeholder asked for: load balancers, logging sidecars, secret stores, CI runners, the platform team's mandated WAF, and above all *existing systems you integrate with because they exist*. Under v1's G4 those fail the build, and the architect's only escape is to invent a requirement — which then has to pass G2, so they go find a real but loosely-related sentence to attach. **The gate would have manufactured a verbatim-certified provenance record for a requirement nobody ever stated.** That is strictly worse than no gate: an ungrounded element is visibly ungrounded; a G2-certified fabrication is invisible. Relationships made it worse — "API writes to database" is a consequence of decomposition, never a stakeholder utterance, so every edge in the graph was fabrication pressure.

**Fix: grounding has a kind.**

```json
{"id": "c_lb", "uid": "e_1a2b…", "name": "Load Balancer",
 "layout": {"x": 240, "y": 120},
 "grounding": [{"kind": "derived", "from": "c_api", "adr": "ADR-004"}]}
```

| kind | requires | meaning |
|---|---|---|
| `satisfies` | a confirmed REQ id | a stakeholder asked for this |
| `derived` | another element id **+ an ADR** | a consequence of a decision you documented |
| `standard` | a named baseline + its document id | your platform/org mandates it |
| `existing` | an evidence id | it is already there; you are integrating, not choosing |
| `assumption` | an open-question id | you are guessing, and the register says so |

**Report the mix — that is the real quality signal.** A model that is 100% `satisfies` is the suspicious one, not the good one.

Layout coordinates are **integers**, rejected as floats at G5, because `json.dumps(0.1+0.2)` is `0.30000000000000004` and any computed coordinate would destabilize G6.

`schema_version` is present in all three files from day one. [Certain] Retrofitting a version field onto unversioned files is the one migration you cannot do cleanly, and v1 claimed the field while omitting it from every example.

Deployment view is **deferred, not dropped** — and it is deferred specifically because deployment elements (regions, clusters, nodes) are almost entirely the `derived`/`standard` category. Adding it before the grounding fix would have made the old G4 far worse.

---

## 6. Stage 3 — Renders

| Output | Notes |
|---|---|
| `c4-{context,container}.svg` | **Primary reviewable diagram.** Emitted directly from `layout`; GitHub renders SVG inline in PRs. Zero dependency. |
| `c4-*.puml` | PlantUML C4 — stable, non-experimental, what the cited paper uses |
| `c4-*.mmd` | Mermaid C4 — convenience only. **GitHub does not render Mermaid C4** (community #197898), and the syntax has been officially "experimental, may change" since 2022. Not the review surface. |
| `model.drawio` | `mxfile` XML, one `<diagram>` tab per level, honoring `layout` |
| `traceability.{md,csv}` | Both directions, plus grounding-mix summary and open questions |
| `architecture.docx` | Minimal OOXML via `zipfile` — narrative, tables **and native DrawingML diagrams.** See below. |
| `jira-delta.json` | Model diff → ticket payloads |

**The `.docx` carries its own diagrams, as shapes rather than pictures.** [Certain] Embedding a *picture* would need a rasteriser — Mermaid→SVG needs Node, draw.io→PNG needs the drawio CLI, both excluded by §0.1. **DrawingML needs neither:** `w:drawing` → `wpg:wgp` → `wps:wsp` boxes, connectors and grounding badges are XML written straight into `document.xml` from the same `layout.x`/`layout.y` the SVG uses, so the two cannot disagree. They arrive in Word as real shapes a reader can select and recolour. Emitted by `tools/archtrace/docx_shapes.py`; `.svg`/`.drawio`/Lucid remain the high-fidelity surfaces.

Two limits, stated because a diagram that hides its method is worse than no diagram. [Certain] **Text does not reflow:** Word will not measure a string for us, so wrapping is computed at the same character widths as the SVG and a long name clips exactly as it does there. [Certain] **Edge labels are omitted:** an unplated label in a shape group lands under box text, and plating each one costs a second shape; the relationship table carries them instead.

### 6.1 Lucid
Treat as a presentation surface only; re-import each time. **Unverified and needs a 30-minute spike before this spec is approved:** Lucid's own docs conflict on whether a hand-assembled `mxfile` (not exported *by* draw.io) imports at all, it states it "prioritizes functional fidelity over visual fidelity" — i.e. it may re-layout and discard your coordinates — and there are reports of labels not surviving the import. Test: does it (i) import, (ii) keep labels, (iii) keep coordinates, (iv) keep tabs as pages. If it fails, the fallback is open-in-draw.io-and-re-export, which is a manual step this spec otherwise claims to have removed.

---

## 7. Stage 4 — Gates

`archtrace check` — deterministic, offline, exit-code driven. This is `planlint` applied to architecture artifacts.

| ID | Rule | Sev |
|---|---|---|
| **G1** | Every evidence record's normalized text hashes to `sha256_normalized`; every referenced record exists | block |
| **G2** | *Citation integrity*: every provenance span is in bounds, `quote_cached` matches the span byte-for-byte, quote ≥ 8 words and ≥ 40 chars, not in the generic-phrase stoplist, and `speaker` ∈ that record's `participants` | block |
| **G3** | Every confirmed REQ is grounded by ≥1 element, or in `out_of_scope` with rationale + decided_by + date. Retired ignored; superseded must name a successor | block |
| **G4** | Every element and relationship carries ≥1 valid `grounding`; `derived` cites a real ADR; `assumption` cites an open question | block |
| **G5** | C4 well-formedness: containment, unique ids and uids, no dangling endpoints, integer layout | block |
| **G6** | Committed renders match a fresh regeneration under **canonical comparison** | block |
| **G7** | Every ADR `drivers` entry references a confirmed REQ | block |
| **G8** | Evidence records cited by zero requirements | warn |
| **G9** | Two confirmed REQs declaring `conflicts_with` each other without a resolving ADR | block |
| **G10** | `schema_version` known in all three files | block |
| **G5e** | An external system declaring containers | warn |
| **G11** | *Authority*: a confirmed REQ resting only on `observed-implementation` or `third-party`; an `authoritative-document` record without `document_owner` + `effective_date` | block |
| **G12** | An NFR category with no confirmed NFR and no declared position | warn |
| **G12n** | A declared NFR position that is malformed: unknown category, bad status, `open` without a real open question, `not_applicable` without rationale + decided_by + date | block |
| **G13** | *Code-fact citation integrity*: a cited symbol must exist in the structured evidence it claims to come from | block |

`--strict` promotes warnings. G5e — an external system declaring containers — is a **warn**, not a block: showing an external system's containers is legitimate C4 when you integrate at that level.

**These ids are the argument to `archtrace check --only RULE…`**, which runs a
subset for callers that can answer one question but not another. An unknown id
is a usage error (exit 2) and the message lists the known set. A subset run
prints a SUBSET verdict, reports any warnings outstanding, and never prints the
whole-gate claim — a rule that did not run has said nothing.

### 7.0 Exit codes

The tool's contract with CI. Defined once, in `commands/_shared.py`.

| code | meaning |
|---|---|
| 0 | the command did its job. For `check --only`, this means *the selected rules* passed and nothing else |
| 1 | a deterministic refusal: a blocking finding, `release` refusing a failing state, `--verify` reporting DRIFT, a breached coverage floor |
| 2 | usage: a missing required argument, an unknown `--only` rule id, a bad `archtrace.toml` or `ARCHTRACE_*` name, a dirty tree at `release` without `--allow-dirty`, no `release.json` to verify |

1 and 2 are deliberately distinct. CI should retry neither, but a human reading
a red build needs to know whether the *artifact* failed or the *invocation* did.

### 7.1 What G2 actually buys, stated honestly
**G2 is a citation-integrity check, not an anti-hallucination control.** [Certain] It proves the quote was not invented. It proves nothing about whether the quote *supports* the inference drawn from it, whether the speaker had authority, or whether the next sentence retracted it. Without the length floor and stoplist, an agent optimizing to pass G2 learns to quote short, high-frequency, trivially-safe fragments — `"data loss"`, `"Correct."` — and every one passes. The floor raises the cost of that strategy; it does not eliminate it.

The residual risk — a plausible-but-wrong requirement with a real, substantial, correctly-attributed quote — is caught **only by human confirmation**. That is why §4 promotion is a human commit and not an agent action, and why this paragraph exists instead of a claim that the gate makes output correct.

### 7.2 G6 compares canonical content, not bytes
[Certain — tested] Byte-identity is achievable but couples the gate to toolchain internals: `zipfile.writestr` stamps `time.localtime()` into every entry (fixed by explicit `ZipInfo(date_time=(1980,1,1,0,0,0))`), zlib output is not stable across builds so your laptop and `ubuntu-latest` can disagree (fixed by `ZIP_STORED` — a Word doc is a few KB, compression buys nothing and costs determinism), and `mxfile`'s conventional `modified="…Z"` attribute breaks it outright (omitted).

Even with all four fixed, byte-identity means a Python patch release fails the build with an error pointing at the architecture instead of the toolchain — and a gate that fails inexplicably gets disabled. So G6 compares **canonicalized content**: `ET.canonicalize` for XML parts (docx unzipped, drawio with `modified` excluded), normalized line-endings for text. Byte-identity stays as `--strict`. `render/.manifest.json` records `renderer_version` so a failure can say *"the renderer changed"* rather than *"you edited the diagram."*

### 7.3 LLM-as-judge is advisory
`archtrace review` writes `review/advisory.md` and always exits 0. Never gates.

### 7.4 Consent and retention — decide before EV-001 exists
1. **Consent**: does meeting-recording consent permit downstream automated processing? Per-meeting, not per-program.
2. **Boundary**: resolved by §0.4 — the repo holds claims about evidence, not evidence.
3. **Retention**: enforced by the system of record, which actually has a lifecycle policy. The repo cannot.
4. **Quotes**: the unresolved one. See §0.4.
5. **Telemetry**: agent invocations must not ship transcript content to vendor telemetry. Verify, do not assume.

---

## 8. Stage 5 — Jira is generated

`archtrace jira plan --since <ref>` diffs the model into ticket payloads carrying each element's grounding and quotes.

`external_id` hashes the element's immutable **`uid`**, not its `id`. [Certain] v1 hashed the id — and ids get renamed (`c_api` → `c_ingest_api`) constantly during an engagement, at which point the hash changes, the old ticket orphans, a duplicate appears, and the "update rather than duplicate" property fails silently at the exact moment it matters.

JSON + CSV for manual import today. Rovo MCP or the Jira REST API slots in at one seam.

---

## 9. The baseline experiment — split, because v1 put the go/no-go after maximum sunk cost

[Certain] v1 said build the whole system, *then* decide whether this was ever an automation problem. The cheapest and most likely decision rule needs no code at all.

### §9a — next week, zero code, one day
Take your last delivered C4 diagram. List every element. For each, try to find a quotable stakeholder statement in the evidence you still have. Record two numbers:

- **Traceability** = % of elements with a real quotable statement. **< 60% → stop.** The problem was never automation; your artifacts were not grounded to begin with, and an agent stack industrializes that gap at speed rather than closing it.
- **Grounding mix** = of the elements with no quote, how many are load-balancer/logging/existing-system class. This is the direct measurement of how much of your real architecture v1's G4 would have rejected, and it tells you whether §5's grounding kinds are drawn correctly.

### §9b — after the schema exists, before the renderers
Reconstruct `requirements.json` and `model.json` for that engagement by hand. **Coverage** = % of delivered elements reproducible from the model. **< 80% → the schema is wrong; fix the schema, not the agents.** You can eyeball reproducibility; this does not need `archtrace render`.

### §9c — renderers last.

---

## 10. Sequencing

**Next week — no code.** §9a.

**Then — nothing provisioned.** Repo, schema, `archtrace check`, renderers, two read-only agents. §9b, §9c.

Read-only is enforced by the harness: **`--deny-tool=write,shell`**. [Certain] v1 said `--deny-tool=write` alone, which does not make an agent read-only — `write` and `shell` are separate tool kinds, and an agent denied `write` but allowed `shell` writes files with `sh -c 'cat > …'`. Deny takes absolute precedence over allow and over `--allow-all`, so the flags are what actually protect you; the `tools:` frontmatter key is defence in depth only. Operator note: a user-level agent at `~/.copilot/agents/` **shadows** a repo-level agent of the same name, so a developer's personal copy silently overrides the locked-down one.

**Then — nothing new.** Actions runs `archtrace check` on every PR. `.gitattributes` marks `render/**` as `linguist-generated=true -diff` so GitHub collapses generated output; otherwise every one-line model change buries the model diff under eight regenerated files including a binary `.docx`, and the review behavior §1 is designed around will not happen. CI posts the model diff as a PR comment.

**Long-lead, parallel, never a dependency.** Work IQ is preview and needs an M365 Copilot license, a Global Admin provisioning a service principal, tenant-wide admin consent, a separate spending policy and consumptive billing — a security and procurement track measured in quarters, not the "this month" the source document assigned. One point in its favor the source document missed: **Work IQ is read-only unless an admin explicitly enables writes, which enforces your read-only constraint at the tenant rather than by prompt.** File it now; sequence nothing behind it. Same for the Graph transcript app registration, Rovo MCP and Lucid MCP.

---

## 11. Cost, latency, failure modes

- **Gate**: offline, seconds, $0.
- **Agents**: single-agent per chunk, ~40K-class per pass rather than the ~500K the multi-agent configuration burned. Chunk count scales with transcript length (§4).
- **Agent confidently wrong**: G2 catches invented citations, G4 catches ungrounded elements, G3 catches dropped requirements, G6 catches edited diagrams, G9 catches unresolved contradictions. Plausible-but-wrong is caught only by human confirmation (§7.1).
- **Agent unavailable**: degrades to manual authoring of the same JSON. Gate, renders and traceability all still work. **Nothing in the critical path requires an LLM.** Deliberate.
- **Schema outgrown**: expected. `schema_version` is checked and unknown versions are refused rather than guessed.

---

## 12. What this explicitly does not do

- Does not orchestrate agents. Microsoft Agent Framework is an endpoint, not a starting point.
- Does not automate Lucid polish.
- Does not gate on any LLM judgment.
- Does not put diagrams in the Word doc (§6).
- **Does not claim the gate makes output correct.** It makes output grounded and internally consistent. Correctness is still yours.
