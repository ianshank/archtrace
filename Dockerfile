# archtrace needs no dependencies, so this image exists for one reason: to give
# CI a pinned interpreter where the gate's behaviour is reproducible. It is NOT
# how the tool is normally run -- on a developer machine `./archtrace` against
# the system python3 is the supported path and needs no build step.
#
# The miner is deliberately absent. It has seven dependencies and ~100 MB of
# compiled grammars, and putting it here would quietly make the gate's image
# depend on it. Mining runs elsewhere and hands over a file.

FROM python:3.11-slim AS gate

LABEL org.opencontainers.image.title="archtrace" \
      org.opencontainers.image.description="Evidence-grounded architecture gate" \
      org.opencontainers.image.licenses="Apache-2.0" \
      org.opencontainers.image.source="https://github.com/ianshank/archtrace"

# Non-root by default: the gate only ever reads the repository and writes
# render outputs, so it has no reason to run as root.
RUN useradd --create-home --uid 10001 archtrace
WORKDIR /work

COPY --chown=archtrace:archtrace tools/ /opt/archtrace/tools/
COPY --chown=archtrace:archtrace archtrace Makefile /opt/archtrace/

ENV PYTHONPATH=/opt/archtrace/tools \
    PYTHONDONTWRITEBYTECODE=1 \
    ARCHTRACE_LOG=silent
USER archtrace

# Fails the build if the zero-dependency invariant was broken while packaging.
RUN python3 -c "import archtrace.cli, archtrace.gate, archtrace.renders" \
 && python3 -m archtrace.cli --help > /dev/null

ENTRYPOINT ["python3", "-m", "archtrace.cli"]
CMD ["--help"]
