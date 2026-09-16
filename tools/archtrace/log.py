"""Diagnostics that cannot corrupt a deterministic build.

Two hard rules, both enforced by test:

1. **Logging goes to stderr, never stdout.** stdout carries machine-readable
   output — `archtrace quote` emits JSON that agents paste into files. A log line
   on stdout would silently corrupt it.
2. **Logging is silent by default and never reaches a rendered artifact.**
   Renders are byte-compared by G6; a timestamp or a hostname leaking into one
   would fail the build for reasons nobody could diagnose.

Named `log` rather than `logging` so it cannot shadow the standard library
module it wraps.
"""

from __future__ import annotations

import logging
import os
import sys
import time
from typing import Literal

LOGGER_NAME = "archtrace"
ENV_LEVEL = "ARCHTRACE_LOG"
LEVELS = {"debug": logging.DEBUG, "info": logging.INFO,
          "warning": logging.WARNING, "error": logging.ERROR,
          "silent": logging.CRITICAL + 1}
DEFAULT_LEVEL = "silent"


def get_logger(name: str = "") -> logging.Logger:
    """A child logger under the archtrace namespace."""
    return logging.getLogger(f"{LOGGER_NAME}.{name}" if name else LOGGER_NAME)


def configure(level: str | None = None, stream=None) -> logging.Logger:
    """Attach a single stderr handler at the requested level.

    Idempotent: repeated calls replace the handler rather than stacking, so a
    command that configures logging twice does not print everything twice.
    """
    resolved = (level or os.environ.get(ENV_LEVEL, DEFAULT_LEVEL)).strip().lower()
    if resolved not in LEVELS:
        resolved = DEFAULT_LEVEL
    logger = logging.getLogger(LOGGER_NAME)
    logger.setLevel(LEVELS[resolved])
    logger.propagate = False
    for handler in list(logger.handlers):
        logger.removeHandler(handler)
    handler = logging.StreamHandler(stream or sys.stderr)
    handler.setFormatter(logging.Formatter(
        "%(levelname)-7s %(name)s: %(message)s"))
    logger.addHandler(handler)
    return logger


class timed:
    """Context manager logging how long a step took, at DEBUG.

    Deliberately not a decorator on the gate rules: a wall-clock read inside a
    deterministic function is an invitation for a timestamp to escape into an
    artifact. This is for the imperative commands only.
    """

    def __init__(self, label: str, logger: logging.Logger | None = None):
        self.label = label
        self.logger = logger or get_logger()
        self.start = 0.0

    def __enter__(self) -> timed:
        self.start = time.perf_counter()
        self.logger.debug("%s: start", self.label)
        return self

    def __exit__(self, exc_type, exc, tb) -> Literal[False]:
        elapsed = (time.perf_counter() - self.start) * 1000
        if exc_type is None:
            self.logger.debug("%s: ok in %.1f ms", self.label, elapsed)
        else:
            self.logger.debug("%s: failed after %.1f ms (%s)",
                              self.label, elapsed, exc_type.__name__)
        # Literal[False], not bool: a bool return type tells readers (and mypy)
        # that this context manager might swallow an exception. It must not.
        return False
