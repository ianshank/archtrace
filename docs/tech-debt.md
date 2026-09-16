# Gap analysis and tech debt

Written against this branch, not against a prior release — `main` is empty, so
everything here is net-new and the comparison is with the SPEC's own invariants
rather than with a previous revision.

Confidence tags: [Certain] verified by running it, [Likely] reasoned from the
code, [Guessing] judgement.

---

## Defects found and fixed in this pass

Listed because *how* they were found matters more than that they were.

| # | Defect | Found by | Severity |
|---|---|---|---|
| 1 | `return` inside `finally` in the CLI's BrokenPipe handler — would swallow any in-flight exception | `ruff` B012 | real, introduced this session |
| 2 | Nested coverage measurement silently disarmed the outer tracer (`trace.Trace.runfunc` calls `sys.settrace(None)` unconditionally), reporting every module after the inner run as uncovered | the coverage gate measuring itself | real |
| 3 | A typo'd `ARCHTRACE_*` variable produced a traceback out of module import | manual probe | real |
| 4 | `release --verify` compared a removed output's hash against `None` instead of reporting drift | `mypy` | real, latent |
| 5 | `log.timed.__exit__` annotated `bool`, implying it might swallow exceptions | `mypy` | documentation-level, real |
| 6 | 11 type errors cascading from one untyped `load_json` return | `mypy` | latent |
| 7 | An unused `engagement` parameter on `renders._kind` | `ruff` ARG001 | dead weight |

Two of those were introduced *in this session* and caught by tooling added in
the same session. That is the argument for the tooling, and it is worth being
plain that they existed at all.

---

## Open tech debt, ranked

### 0. ~~Configuration resolved from the process CWD~~ — fixed [Certain]

`config.DEFAULT = load()` resolved at import with `root="."`, so the
`archtrace.toml` that took effect was the one in the directory the operator was
standing in. `--root` never reached this layer at all. Both consequences were
reproduced:

```
$ cd engagements/aurora && archtrace check      # read NO configuration
$ cd ~ && archtrace --root /work/proj check     # applied ~/archtrace.toml
```

```
$ printf '[citation]\nmin_quote_words = 99\n' > archtrace.toml
$ make test
FAILED (failures=26)
```

That last one is the sharpest statement: **a repository that legitimately
configured archtrace could not run archtrace's own test suite.** Twenty-six
assertions depended on the developer's working directory, which made them
statements about the environment rather than about the gate.

**Fixed in two halves.** `config.find_config_root` walks up to the nearest
`.git`, `.hg` or `pyproject.toml` and reads the file there, falling back to the
starting directory when there is no marker — deliberately, rather than walking
on into someone's home directory, which is how the second defect happened.
`cli.main` then re-resolves from `--root` after argparse and calls
`gate.apply_config`, so the policy reaching the rules is the project's and not
the operator's. `archtrace config` resolves the same way and prints the
configuration root it used, because a tool that reports one threshold while
enforcing another is the failure that command exists to prevent.

The suite pins its own policy in `setUp` rather than inheriting the ambient one.
That is now necessary for a second reason as well as the first: `apply_config`
rebinds module constants, so any test driving the CLI leaves them rebound and
test *ordering* would otherwise decide the thresholds. `ConfigurationRoot`
asserts both directions, and the full suite passes with and without a
`[citation] min_quote_words = 99` at this repository's root.

**Still open, and deliberately:** this does not make configuration
per-engagement. One repository, one policy. `renders.py` still binds six
constants at import across 25 usages in helpers that take no `Engagement`, and
a stray `[render] box_width` does change two of the twelve committed outputs
(G6 blocks afterwards, so it cannot publish silently). Splitting citation policy
from render house style would mean one file configuring two scopes, which
changes what `archtrace.toml` means — a deliberate API decision, not a bug fix.

### 1. `renders.py` is now the largest module at 598 lines [Certain]

`cli.py` went from 1,008 to 248; `renders.py` inherited the title. It contains
five unrelated emitters — SVG, PlantUML/Mermaid, draw.io XML, OOXML, and the
traceability tables — sharing only the model they read.

**Why it was not split in this pass:** every renderer is under G6, which
byte-compares output. Moving them is a large diff with a non-zero chance of a
whitespace change that fails the gate for no architectural reason, and this pass
already carried a decomposition. Splitting it into `renders/` mirroring
`commands/` is a clean, mechanical follow-up.

**Risk of leaving it:** low. It is cohesive by output type, fully covered (98%),
and changes rarely.

### 2. The docs generators are still unmeasured, now partly tested [Certain]

`docs/gen_architecture.py` and `gen_sequence.py` remain outside the coverage
measurement, which scopes to `tools/archtrace`.

**Partly closed.** "Visible immediately assumes somebody looks", written here
earlier, turned out to be the whole problem: nobody did, and both diagrams had
drifted — one drew a test count four releases old, both named eleven of fifteen
gate rules. `make docs-fresh` now asks of `docs/` what G6 asks of `render/`, and
`DocsFreshness` exercises the target's failure paths. `tools/repo_facts.py`
removes the class of defect that produced the stale count.

**Still open:** nothing asserts the emitted SVG *parses*, or that its text stays
inside the canvas. Both were checked by hand while writing that change, which is
the same "not a process" this entry complained about. The generators' own
drawing logic — `wrap`, `arrow`, the self-message overflow flip in
`gen_sequence.py:176` — has no test at all.

### 3. Line coverage only, not branch [Certain]

The stdlib tracer reports lines. A half-tested `if` counts as covered, so 94%
overstates what is actually exercised. Stated in the module docstring rather
than left for someone to discover. Branch coverage needs either `coverage.py` as
an optional path — which splits the number between environments, defeating the
point — or `sys.monitoring` on 3.12+, which breaks the 3.9 floor.

### 4. `A7-no-authority-claims` is a substring match [Likely]

The agent check for authority claims looks for literal phrases. It will miss
"once I am satisfied the change can land" and would false-positive on a
definition that *quotes* a forbidden phrase in order to forbid it. It is a
tripwire, not a control, and the check's own docstring should say so more
plainly than it currently does.

### 5. `mine` runs `shell=True` [Certain, accepted]

The command is operator-supplied via flags or the Makefile and never derived
from evidence, which is documented at the call site, tested, and the reason the
`S602` suppression is targeted rather than global. It is still the single
sharpest edge in the codebase: anyone who wires `--command` to a value that
reaches it from a file has created an injection path. A follow-up that accepts
`argv` as a list and reserves the shell for an explicit `--shell` flag would
close it properly.

### 6. `test_gate.py` is 666 lines [Likely]

The seeded-defect suite grew organically and now mixes G1–G13 cases, determinism
tests, normalisation tests and the release manifest. It should split along the
same seams as `commands/`. Low risk, pure churn, deferred.

### 7. `docs/gen_*.py` duplicate an SVG primitive layer [Certain]

`rect`, `text`, `wrap` and `para` exist in near-identical form in both
generators and again inside `renders.py`. Three copies of a text-wrapping
function is how they drift. A shared `archtrace.svg` module is the obvious fix;
it was not done here because the two generators are documentation and the third
is gated output, and merging gated and ungated code paths needs more care than
a hygiene pass should take.

### 8. The `archtrace` shell shim is untested [Certain]

Every test drives `main()` in-process. The bash entrypoint that users actually
type has one implicit test — the `test_a_bad_configuration_override_refuses_to_run`
subprocess case — and that one invokes `python -m` rather than the shim.

---

## Anti-patterns checked for, and what was found

| Pattern | Status |
|---|---|
| God file | **Was present** — `cli.py` at 1,008 lines. Fixed; largest module was 598 lines at this point (not 312, corrected — see code-quality-plan.md, which also has the current figure: it has grown since). |
| Magic numbers | **Was present** — the §9a decision thresholds lived inside a print statement. Now in `config`, printable via `archtrace config`. |
| Hidden global state | Config is a frozen dataclass resolved once; no mutable module globals. |
| Swallowed exceptions | One found (defect 1), fixed. `agents._safe_load` returns `(value, error)` rather than raising inside a loop. |
| Silent fallback | Deliberately absent: unknown `schema_version`, unknown `content_kind`, unknown facts version and bad config all refuse rather than guess. |
| Circular imports | `gate` imports `renders` lazily inside G6; `model` imports `mining` lazily. Both are deliberate and commented. |
| Duplicate logic | One found (defect: `_register_facts` was duplicated between `mine` and `add-facts`) — factored into a shared helper so the two paths cannot drift. |
| Untested control | **Was present** — agent definitions encoded controls in prose that nothing enforced. Now 7 deterministic checks with seeded-defect tests for each. |

---

## What "no hardcoded values" should mean here

Taken literally it is bad advice — `sha256`, `"---"` frontmatter delimiters and
`utf-8` are not configuration, and making them so would add ceremony and a way
to break the tool. The useful version is: **a value that encodes a judgement
belongs where it can be argued about.** Three did and have moved; the rest are
named constants at the top of the module that owns them.

The ones that moved: G2's quote floor (a judgement about what makes a citation
substantial), the §9a decision thresholds (the rule that decides whether the
programme runs at all), and the mining defaults (site-specific). Geometry moved
too, though that is closer to taste than policy.
