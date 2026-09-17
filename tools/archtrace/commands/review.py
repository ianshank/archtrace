"""`archtrace review` — the advisory plane, which never gates.

Separated from `verify.py` on purpose. Everything in that module answers a
question with a pass or a fail; nothing here does, and putting the two behind
one import would be the first step toward someone reading an advisory exit
code as a verdict.
"""

from __future__ import annotations

import sys

from ..advisory import FindingsError, load_findings, render, worklist, write
from ..log import get_logger
from ._shared import EXIT_OK, EXIT_USAGE
from ._shared import engagement as _engagement

LOG = get_logger("review")


def cmd_review(args) -> int:
    """Write `review/advisory.md`, and exit 0 whatever it says.

    The one non-zero path is a findings file the operator named and this could
    not read. That is a usage error in the §7.0 sense -- the invocation was
    wrong, not the artifact -- and it is the same answer `check` gives an
    unknown `--only` id. Degrading to "no external findings" instead would
    mean a reviewer whose output silently stopped parsing looked exactly like
    a reviewer that found nothing, which is the failure this repository keeps
    calling a false green.
    """
    eng = _engagement(args)
    observations = worklist(eng)
    if args.findings:
        try:
            observations += load_findings(args.findings)
        except FindingsError as exc:
            print(f"archtrace: {exc}", file=sys.stderr)
            return EXIT_USAGE
    observations.sort(key=lambda o: o.sort_key)

    text = render(eng, observations)
    if args.stdout:
        print(text, end="")
    else:
        path = write(eng, text)
        print(f"wrote {path} — {len(observations)} observation(s)")
    external = sum(1 for o in observations if o.tier == 0)
    if external:
        print(f"{external} from an external reviewer, validated for shape "
              "only. archtrace takes no position on whether they are right.")
    print("Advisory. This exits 0 whatever it found; promotion from "
          "`proposed` to `confirmed` is still a human commit.")
    return EXIT_OK
