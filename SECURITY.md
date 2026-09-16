# Security

## Reporting

Use GitHub's private vulnerability reporting on this repository
(**Security → Report a vulnerability**). Please do not open a public issue for
a security problem.

Expect an acknowledgement within a week. This is a small project with one
maintainer; that is the honest number rather than an aspirational one.

## Supported versions

`main` only. There are no release branches and no backports.

## Scope

**Evidence content is out of scope, because it is never in the repository.**
That is the whole of SPEC §0.4: archtrace holds *claims about* evidence — a
manifest of hashes, byte spans and retention metadata — while the content stays
in the system of record that owns its lifecycle, reached through
`--evidence-root`. A vulnerability in archtrace cannot leak recording content
the repository does not hold. `make evidence-guard` fails the build if any
ever does.

The ≤25-word verbatim quotes cached in `requirements.json` are the deliberate
exception, and they are a known open question rather than a solved problem —
see `SPEC.md` §0.4 and §7.4. If your organisation treats a short quotation from
a confidential recording as confidential, that decision belongs to you and the
tool cannot make it for you.

### In scope

- A path that writes outside `--evidence-root`, or reads a file outside it.
  There is a known open finding of exactly this shape in `mine --local-name` /
  `--id` (`docs/code-quality-plan.md` §12.8), reproduced and unfixed.
- Anything that makes a gate report success on a state it should refuse. The
  tool's only product is a refusal; a false green is its worst possible defect,
  and several have been found and fixed in `CHANGELOG.md` 0.5.0.
- Anything that lets `release --verify` report MATCH on bytes that are not the
  approved bytes. Note the standing limitation: `release.json` has no integrity
  of its own, so an attacker who can edit `render/` can edit the manifest too
  (`docs/code-quality-plan.md` §12.1, open).
- Command injection through `mine --command`. The command is operator-supplied
  and runs with `shell=True`, which is documented and accepted
  (`docs/tech-debt.md`) — but a path where *evidence* reaches it is a defect.

### Out of scope

- The advisory LLM reviewer. It always exits 0 and cannot affect the gate; that
  is the design, not an oversight.
- An agent definition that documents constraints it does not enforce.
  `archtrace agents` validates the file, and cannot prove an agent ran under
  those flags — the harness is the only enforcement.
- Anything requiring write access to the repository. If an attacker can push,
  the gate is not the control that failed.
