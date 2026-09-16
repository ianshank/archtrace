#!/bin/bash
# Make `make lint` and `make types` capable of running in a web session.
#
# archtrace has NO runtime dependencies, and that is load-bearing: `make test`,
# `make gate`, `make coverage`, `make check` and `make freshness` all run on a
# bare interpreter with no setup step, and CI proves it by diffing `pip list`
# either side of the gate job. Nothing here changes that -- this installs the
# `dev` extra only, which is exactly what CI's separate `quality` job does
# (`pip install -e ".[dev]"`), and only inside a Claude session.
#
# Without it, `make lint` and `make types` find no ruff and no mypy and print
# "SKIP". They exit 0 when they skip, deliberately, so a session would run
# `make pre-pr`, see nine green steps, and have silently checked neither.
set -uo pipefail

# Local machines already have whatever the developer chose. Only the remote
# container starts empty.
if [ "${CLAUDE_CODE_REMOTE:-}" != "true" ]; then
  exit 0
fi

cd "${CLAUDE_PROJECT_DIR:-.}" || exit 0

# Deliberately NOT `set -e` past this point, and deliberately not fatal. The
# whole argument of this repository is that the gate runs without a toolchain;
# a session that cannot reach a package index must still be able to run the
# tests and the gate. Losing lint and types is a degraded session, not a broken
# one -- and `make lint`/`make types` already say "SKIP" loudly enough to
# notice.
#
# Two attempts, because a read timeout against the package index was observed
# on this exact path while writing the hook and a second attempt succeeded.
# Two, not a loop: if the index is genuinely unreachable, failing fast and
# saying so beats holding up every session start.
installed=""
for attempt in 1 2; do
  if python3 -m pip install -e ".[dev]" --quiet --disable-pip-version-check; then
    installed="yes"
    break
  fi
  [ "$attempt" = "1" ] && echo "session-start: install attempt 1 failed, retrying once..." >&2
done

if [ -n "$installed" ]; then
  echo "session-start: dev extras installed; 'make lint' and 'make types' will run"
else
  echo "session-start: could not install the dev extras (offline?)." >&2
  echo "  'make test', 'make gate', 'make check', 'make freshness' and" >&2
  echo "  'make coverage' are unaffected -- they need nothing installed." >&2
  echo "  'make lint' and 'make types' will print SKIP and exit 0, so do not" >&2
  echo "  read a green 'make pre-pr' as having linted or type-checked." >&2
fi

exit 0
