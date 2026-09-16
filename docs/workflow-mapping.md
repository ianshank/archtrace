# Your workflow, step by step

Ten steps in, ten steps out. Three change materially, one mostly disappears, one
does not survive contact with the citation rule.

| # | Today | Under archtrace | Verdict |
|---|---|---|---|
| 1 | Gather requirements in recorded meetings, collect their docs | Unchanged, plus `evidence add` afterwards (~2 min) | **Same + 2 min** |
| 2 | Copilot 365 gathers from email, SharePoint, Teams | Copilot 365 becomes a **finding aid only**; its output cannot be evidence | **Changes materially** |
| 3 | Distill into Word + Excel, then add to Jira | Word, Excel and Jira become **generated outputs**; the model is the working medium | **Inverted** |
| 4 | Mine repos with a read-only architect Copilot agent | Same agent, but repo findings are `observed-implementation` and cannot carry a requirement | **Same + a hard separation** |
| 5 | Upload artifacts to SharePoint, point a 365 agent at them, peer review against requirements | Mostly **disappears** — the check is deterministic, runs in seconds, and runs *before* the artifacts exist | **Biggest win** |
| 6 | Final C4 draw.io + Mermaid + Word for stakeholders | `archtrace render` | **Automated** |
| 7 | Upload to Lucid and clean up | The *clean up* is deleted by design; the upload stays (and is unverified) | **Win, with a caveat** |
| 8 | Present to peers for review | Peers review the **model diff** on a PR, not the deck | **Changes what gets reviewed** |
| 9 | Revise | Edit the model, regenerate. Nothing is re-polished | **Where the time comes back** |
| 10 | Present | `release --verify` first | **Same + one command** |

---

## Step 2 is the one that breaks

**Copilot 365's output cannot become a requirement, and this is not a
configuration problem.** [Certain]

Copilot 365 synthesises. It hands you an answer assembled from sources, not a
verbatim span at a verifiable offset in a hashed document. The citation gate
needs the latter: an evidence id, a byte range, a speaker who was in the room,
and a hash that proves the document has not changed since. A synthesised summary
has none of those, and no amount of prompting produces them — the thing it
returns is model output about evidence, which is one layer removed from evidence.

So the split is:

- **Keep using it to find things.** "Which threads discuss the ingest SLA" is a
  search problem and it is good at it.
- **Export what it points you at.** The underlying email, the SOW, the
  transcript — those are the evidence, and those get `evidence add`.
- **Never paste its summary in as a requirement.** If you do, the quote will not
  resolve to a span and G2 will block it. The gate will catch this, but it is
  better to know now than to discover it mid-engagement.

This is the single largest habit change in the list, and it is worth being
honest that it makes step 2 slower, not faster. What you buy is that every
downstream claim survives being asked "where did that come from?"

---

## Step 3 inverts rather than speeds up

Today Word and Excel are where you think, and Jira is typed from them. That is
why revision is expensive: the thinking and the artifact are the same object, so
changing your mind means rewriting the deliverable.

Under archtrace the thinking lives in `requirements.json` and `model.json`, and
Word, Excel, draw.io and Jira are all *renders* of it. A ticket is a model delta
with a stable `external_id`, so re-importing updates rather than duplicates.

The cost is real: you author JSON. `archtrace quote` resolves fragments to spans
so you never type a quote by hand, and `archtrace fmt` canonicalises, but it is
still JSON and it is less pleasant than Word for a first draft.

---

## Step 4 gets a hard separation you do not have today

Your custom read-only architect agent maps onto
`.github/agents/architecture-modeler.agent.md`, run with
`--deny-tool=write,shell --allow-tool=read`. Same idea, enforced by the harness
rather than by prompt text.

The new constraint: **what the repo does is not what the stakeholder requires.**
Repo findings register as `observed-implementation`, and G11 blocks any confirmed
requirement resting only on that tier. Today those two blur together — the agent
reads the code, writes an architecture description, and "the system currently
retries three times" quietly becomes a constraint nobody ever asked for. Repo
evidence still grounds *elements*, via the `existing` grounding kind. It just
cannot become a requirement.

Your "traces to data" requirement is the `satisfies` / `derived` / `standard` /
`existing` / `assumption` grounding on every element, and the build fails without
it.

---

## Step 5 is where the time actually is

You currently upload artifacts to SharePoint, point a 365 agent at them, and ask
it to review the artifacts against the requirements and recordings. That is an
LLM checking whether a document agrees with other documents, after the document
exists, with no exit code.

Replaced by:

- **G2** — every citation resolves to a real span by a real participant.
- **G3** — every confirmed requirement is in the model or explicitly out of scope
  with who declined it and when.
- **G4** — every element has a stated reason to exist.
- **G6** — the artifacts cannot disagree with the model, because they are
  regenerated from it and a hand edit fails the build.

Seconds, deterministic, offline, and it runs before the artifacts exist. The 365
agent review survives as `review/advisory.md` — useful for unsupported inference,
which no rule can catch, and it always exits 0.

---

## Steps 7 and 9: where the cleanup loop goes

The reason step 7 feels like cleanup is that the render is your source of truth,
so every regeneration destroys your polish. Put layout in the model and the
problem class disappears — regeneration reproduces your positions.

Two caveats worth knowing before you rely on it:

- **Lucid's round-trip is unverified.** Its docs conflict on whether a
  hand-assembled `mxfile` imports at all, and it states it prioritises functional
  over visual fidelity, meaning it may re-lay-out and discard coordinates. Thirty
  minute spike, before you build a habit on it.
- **`architecture.docx` has no diagrams.** Embedding one needs Node or the
  drawio CLI. Insert the generated `.svg` into Word or PowerPoint directly —
  Office accepts SVG and can convert it to an editable shape.

Step 9 is where the investment pays back. Today a revision is: change the
thinking, redo the C4, redo the Word doc, re-upload, re-polish Lucid. Under
archtrace it is: edit the model, `make gate`, regenerate. The loop is deleted
rather than accelerated.

---

## Steps 8 and 10: what peers actually review

Today peers review the deck, which is a rendering of your thinking that they
cannot diff. Under archtrace they review the **model diff** on a PR —
`render/**` is marked generated so GitHub collapses it — with CODEOWNERS and
branch protection making the review independent.

Before it leaves: `archtrace release` binds the approver, the commit and a
SHA-256 of every source and output; `archtrace release --verify` says MATCH or
DRIFT. A commit says a state was approved once; only the recomputed hashes say
the file you are presenting is that state.

---

## What this costs you

Stated plainly, because a migration that only lists benefits is a sales pitch:

1. **Copilot 365 is demoted** from synthesiser to finding aid. Step 2 gets
   slower.
2. **You author JSON**, not Word, for the thinking.
3. **Evidence export stays manual** until a Graph app registration exists, which
   is a procurement track, not a sprint.
4. **The Word deliverable loses its diagrams** until the DrawingML renderer is
   written.
5. **Lucid is unverified** and may not round-trip at all.
6. **The gate will block you** in week one, mostly on G3 (confirmed a
   requirement, modelled nothing for it) and G2 (quote does not resolve). That is
   the tool working, and it is also friction.

---

## Do not start here

Run `SPEC.md` §9a first: last delivered C4 diagram, list every element, count how
many you can attach a quotable stakeholder statement to. **Under 60% and none of
the above is worth doing** — the artifacts were never grounded, and this pipeline
would industrialise that gap at speed rather than close it.

One day, a spreadsheet, no code.
