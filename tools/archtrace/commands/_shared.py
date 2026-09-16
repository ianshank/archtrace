"""Values every command needs, defined once.

Exit codes are part of the tool's contract with CI, so they live here rather
than in whichever module happened to need them first.
"""

from __future__ import annotations

from ..log import get_logger
from ..model import Engagement

EXIT_OK = 0
EXIT_BLOCKED = 1
EXIT_USAGE = 2

LOG = get_logger("commands")


def engagement(args) -> Engagement:
    """Load the engagement a command was pointed at."""
    LOG.debug("loading engagement root=%s evidence_root=%s",
              args.root, args.evidence_root)
    return Engagement.load(args.root, args.evidence_root)


def git(root: str, *argv) -> str | None:
    """Read-only git query against an arbitrary checkout.

    Shared by `mine` (which commit are these facts about?) and `release` (which
    commit is being approved?). Returns None rather than raising when git is
    absent, so both callers can decide what a missing commit means for them.
    """
    import subprocess
    try:
        out = subprocess.run(["git", "-C", root, *argv], capture_output=True,
                             text=True, timeout=10, check=False)
    except (OSError, subprocess.SubprocessError):
        return None
    return out.stdout.strip() if out.returncode == 0 else None
