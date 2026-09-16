"""archtrace command line.

    archtrace init NAME              scaffold an engagement
    archtrace evidence add FILE      register evidence (hashes normalised text)
    archtrace quote EV-ID "text"     resolve a quote to a verifiable byte span
    archtrace evidence add-facts     register code-mining facts (optional)
    archtrace symbols EV-ID PATTERN  find a symbol to cite in code evidence
    archtrace mine --repo PATH       drive a miner, register its facts (optional)
    archtrace promote REQ-ID         the human gate: confirm a proposed requirement
    archtrace render                 regenerate every build output
    archtrace check [--strict]       deterministic gates; exit 1 on any block
    archtrace fmt                    canonicalise JSON, refresh derived fields
    archtrace report                 grounding mix and NFR coverage summary
    archtrace release --approved-by  bind an approval to exact content hashes
    archtrace baseline               SPEC §9a — run this BEFORE anything else
    archtrace agents                 validate agent definitions deterministically
    archtrace config                 print the thresholds this build enforces

All commands accept --root (engagement directory) and --evidence-root (where the
evidence *content* lives; it is deliberately not in the repository).

Argument parsing and dispatch only. The verbs live in `archtrace.commands`,
one module per lifecycle stage, so adding a command touches one file rather
than a thousand-line switchboard.
"""

from __future__ import annotations

import argparse
import contextlib
import os
import sys

from . import commands
from .commands._shared import EXIT_BLOCKED, EXIT_OK, EXIT_USAGE
from .config import CONFIG_FILENAME, ENV_PREFIX
from .config import DEFAULT as CONFIG
from .log import configure as configure_logging
from .log import get_logger

LOG = get_logger("cli")


def cmd_config(_args) -> int:
    """Print the effective configuration and where each value came from.

    A gate whose thresholds can only be learned by reading source is a gate
    nobody can audit. `sources` lists the keys an override actually changed, so
    a surprising build result can be traced to a config file or an environment
    variable rather than guessed at.
    """
    overridden = set(CONFIG.sources)
    print(f"effective configuration (defaults < {CONFIG_FILENAME} < {ENV_PREFIX}*)\n")
    section = None
    for name, key, value in CONFIG.describe():
        if name != section:
            section = name
            print(f"[{section}]")
        mark = " <- overridden" if f"{name}.{key}" in overridden else ""
        print(f"  {key:<28} {value!r}{mark}")
    if not overridden:
        print(f"\nAll defaults. Override with {CONFIG_FILENAME} or "
              f"{ENV_PREFIX}<SECTION>_<KEY>.")
    return EXIT_OK


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="archtrace", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--root", default=".", help="engagement directory")
    parser.add_argument("--evidence-root", default=None,
                        help="where evidence CONTENT lives (git-ignored)")
    parser.add_argument("--log", choices=("debug", "info", "warning", "error",
                                          "silent"),
                        help="diagnostics to stderr; stdout stays machine-readable")
    sub = parser.add_subparsers(dest="command", required=True)

    check = sub.add_parser("check", help="run the deterministic gates")
    check.add_argument("--strict", action="store_true",
                       help="promote warnings to blocking")
    check.set_defaults(fn=commands.verify.cmd_check)

    init = sub.add_parser("init", help="scaffold an engagement")
    init.add_argument("name")
    init.add_argument("--client", default="")
    init.add_argument("--force", action="store_true")
    init.set_defaults(fn=commands.setup.cmd_init)

    promote = sub.add_parser(
        "promote",
        help="confirm a proposed requirement after reading its evidence")
    promote.add_argument("requirement_id")
    promote.add_argument("--yes", action="store_true",
                         help="actually promote; without it this is a dry run "
                              "that shows what you would be attesting to")
    promote.set_defaults(fn=commands.requirements.cmd_promote)

    release = sub.add_parser(
        "release", help="bind an approval to an exact model and output state")
    release.add_argument("--approved-by",
                         help="the person accountable for this release")
    release.add_argument("--role",
                         help="the authority under which they approve")
    release.add_argument("--verify", action="store_true",
                         help="check whether the current state still matches "
                              "the approved one; publish only on MATCH")
    release.add_argument("--strict", action="store_true")
    release.add_argument("--allow-dirty", action="store_true")
    release.set_defaults(fn=commands.release.cmd_release)

    sub.add_parser("render", help="regenerate build "
                              "outputs").set_defaults(fn=commands.build.cmd_render)
    sub.add_parser("fmt", help="canonicalise and refresh derived "
                           "fields").set_defaults(fn=commands.build.cmd_fmt)
    sub.add_parser("report", help="grounding mix "
                              "summary").set_defaults(fn=commands.verify.cmd_report)
    agents = sub.add_parser(
        "agents", help="deterministically validate agent definitions")
    agents.add_argument("--directory",
                        help="where the *.agent.md files live "
                             f"(default: {commands.verify.DEFAULT_AGENT_DIR})")
    agents.set_defaults(fn=commands.verify.cmd_agents)

    sub.add_parser("config",
                   help="print the thresholds this build actually enforces"
                   ).set_defaults(fn=cmd_config)

    baseline = sub.add_parser(
        "baseline", help="SPEC §9a — is this an automation problem at all?")
    baseline.add_argument("--worksheet", help="write the per-element CSV here")
    baseline.add_argument("--elements",
                          help="a plain list of element names from a PAST "
                               "engagement's delivered diagram; emits a blank "
                               "worksheet to fill in by hand")
    baseline.set_defaults(fn=commands.verify.cmd_baseline)

    evidence = sub.add_parser("evidence", help="evidence manifest").add_subparsers(
        dest="evidence_command", required=True)
    add = evidence.add_parser("add", help="register an evidence record")
    add.add_argument("file")
    add.add_argument("--id")
    add.add_argument("--authority", required=True,
                     choices=["stakeholder-confirmed", "authoritative-document",
                              "observed-implementation", "third-party"],
                     help="what the record proves: a stakeholder's statement, a "
                          "signed document, what the code does today, or "
                          "somebody else's claim")
    add.add_argument("--document-owner",
                     help="required for --authority authoritative-document")
    add.add_argument("--effective-date",
                     help="required for --authority authoritative-document")
    add.add_argument("--document-version")
    add.add_argument("--source", required=True,
                     choices=["teams-transcript", "email", "sharepoint",
                              "interview", "document"])
    add.add_argument("--source-uri", required=True,
                     help="URI in the system of record that owns retention")
    add.add_argument("--date", required=True)
    add.add_argument("--participants", nargs="+", required=True)
    add.add_argument("--classification", required=True)
    add.add_argument("--retention-until", required=True)
    add.set_defaults(fn=commands.evidence.cmd_evidence_add)

    facts = evidence.add_parser(
        "add-facts", help="register a code-mining facts file as evidence")
    facts.add_argument("file")
    facts.add_argument("--id")
    facts.add_argument("--commit",
                       help="the commit the facts describe; required unless the "
                            "facts file carries one")
    facts.add_argument("--miner", default="archmine",
                       help="what produced the facts (recorded as the participant)")
    facts.add_argument("--source-uri", required=True)
    facts.add_argument("--date", required=True)
    facts.add_argument("--classification", required=True)
    facts.add_argument("--retention-until", required=True)
    facts.set_defaults(fn=commands.evidence.cmd_evidence_add_facts)

    mine = sub.add_parser(
        "mine", help="run a code miner over a repository and register its facts")
    mine.add_argument("--id", help="evidence id to assign, e.g. EV-004")
    mine.add_argument("--repo", required=True, help="repository to mine")
    mine.add_argument("--command", default=commands.evidence.DEFAULT_MINE_COMMAND,
                      help="how to run the miner, executed with cwd=repo "
                           f"(default: {commands.evidence.DEFAULT_MINE_COMMAND!r})")
    mine.add_argument("--facts", default=commands.evidence.DEFAULT_FACTS_PATH,
                      help="where the miner leaves its facts file, relative to "
                           f"the repo (default: {commands.evidence.DEFAULT_FACTS_PATH})")
    mine.add_argument("--local-name",
                      help="filename for the copy under --evidence-root")
    mine.add_argument("--commit", help="override the resolved commit")
    mine.add_argument("--allow-dirty", action="store_true")
    mine.add_argument("--dry-run", action="store_true",
                      help="print what would run and stop")
    mine.add_argument("--timeout", type=int,
                      default=commands.evidence.CONFIG.mining.timeout_seconds)
    mine.add_argument("--miner",
                      default=commands.evidence.CONFIG.mining.default_miner)
    mine.add_argument("--source-uri", required=True)
    mine.add_argument("--date", required=True)
    mine.add_argument("--classification", required=True)
    mine.add_argument("--retention-until", required=True)
    mine.set_defaults(fn=commands.evidence.cmd_mine)

    symbols = sub.add_parser("symbols",
                             help="find a symbol in registered code evidence")
    symbols.add_argument("evidence_id")
    symbols.add_argument("pattern")
    symbols.add_argument("--limit", type=int, default=10)
    symbols.set_defaults(fn=commands.evidence.cmd_symbols)

    quote = sub.add_parser("quote", help="resolve a fragment to a byte span")
    quote.add_argument("evidence_id")
    quote.add_argument("fragment")
    quote.add_argument("--speaker")
    quote.set_defaults(fn=commands.evidence.cmd_quote)
    return parser


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    configure_logging(getattr(args, "log", None))
    if CONFIG.errors:
        # Refuse rather than silently using a default the operator did not
        # choose. A config typo that is quietly ignored is worse than one that
        # stops you -- the same rule the gate applies to an unknown schema.
        for problem in CONFIG.errors:
            print(f"archtrace: bad configuration -- {problem}", file=sys.stderr)
        return EXIT_USAGE
    if args.evidence_root is None:
        args.evidence_root = os.path.join(args.root, "_evidence_root")
    LOG.debug("dispatch command=%s root=%s", args.command, args.root)
    try:
        return args.fn(args)
    except BrokenPipeError:
        # `archtrace config | head` closes the pipe. Exiting quietly is correct
        # behaviour for a CLI; a traceback here is noise, not a defect.
        # Never `return` inside `finally` -- it swallows in-flight exceptions.
        with contextlib.suppress(OSError):
            sys.stdout.close()
        return EXIT_OK
    except KeyboardInterrupt:
        LOG.debug("interrupted")
        return EXIT_BLOCKED


if __name__ == "__main__":
    raise SystemExit(main())
