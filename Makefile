# archtrace — zero runtime dependencies by design.
#
# `gate`, `test` and `coverage` run with nothing installed. `lint` and `types`
# need the dev extras (`pip install -e ".[dev]"`) and degrade to a clear skip
# rather than a confusing failure when they are absent.

ROOT ?= example
EVIDENCE_ROOT ?= $(ROOT)/_evidence_root
PY ?= python3
ARCHTRACE = ./archtrace --root $(ROOT) --evidence-root $(EVIDENCE_ROOT)
AGENT_DIR ?= .github/agents

.DEFAULT_GOAL := help

.PHONY: help
help:
	@echo "Deterministic, no dependencies:"
	@echo "  make check      the gates; exit 1 on any block"
	@echo "  make render     regenerate build outputs"
	@echo "  make gate       fmt + render + check (the pre-publish loop)"
	@echo "  make fmt        canonicalise JSON, refresh derived fields"
	@echo "  make report     grounding mix and NFR coverage"
	@echo "  make baseline   SPEC 9a — run this BEFORE anything else"
	@echo "  make agents     deterministic validation of agent definitions"
	@echo "  make config     print the thresholds this build enforces"
	@echo "  make test       full test suite"
	@echo "  make coverage   test suite under the stdlib tracer + floors"
	@echo ""
	@echo "Needs dev extras (pip install -e \".[dev]\"):"
	@echo "  make lint       ruff"
	@echo "  make types      mypy"
	@echo "  make secrets    gitleaks (also needs the gitleaks binary)"
	@echo ""
	@echo "  make pre-pr     everything above, in the order CI runs it"
	@echo "  make mine       run a code miner (needs REPO= and URI=); NOT in gate"
	@echo ""
	@echo "Override the engagement with ROOT=engagements/<name>"

# --- deterministic, dependency-free ----------------------------------------

.PHONY: check render fmt report baseline agents config gate test coverage
check:    ; @$(ARCHTRACE) check
render:   ; @$(ARCHTRACE) render
fmt:      ; @$(ARCHTRACE) fmt
report:   ; @$(ARCHTRACE) report
baseline: ; @$(ARCHTRACE) baseline
config:   ; @$(ARCHTRACE) config
agents:   ; @./archtrace agents --directory "$(AGENT_DIR)"
gate: fmt render check
test:
	@$(PY) -m unittest discover -s tools/tests -t tools
coverage:
	@$(PY) tools/coverage_gate.py

# --- developer tooling, optional -------------------------------------------

.PHONY: lint types secrets
lint:
	@command -v ruff >/dev/null 2>&1 \
	  && ruff check tools docs \
	  || echo "SKIP lint: ruff not installed (pip install -e \".[dev]\")"
types:
	@command -v mypy >/dev/null 2>&1 \
	  && mypy \
	  || echo "SKIP types: mypy not installed (pip install -e \".[dev]\")"
secrets:
	@command -v gitleaks >/dev/null 2>&1 \
	  && gitleaks detect --config .gitleaks.toml --redact --no-banner \
	  || echo "SKIP secrets: gitleaks not installed"

# --- the pre-PR gate --------------------------------------------------------
# Ordered cheapest-first so a trivial failure does not wait behind the suite.

.PHONY: pre-pr
pre-pr:
	@echo "== 1/7 lint ==";        $(MAKE) --no-print-directory lint
	@echo "== 2/7 types ==";       $(MAKE) --no-print-directory types
	@echo "== 3/7 secrets ==";     $(MAKE) --no-print-directory secrets
	@echo "== 4/7 agents ==";      $(MAKE) --no-print-directory agents
	@echo "== 5/7 tests ==";       $(MAKE) --no-print-directory test
	@echo "== 6/7 coverage ==";    $(MAKE) --no-print-directory coverage
	@echo "== 7/7 gate ==";        $(MAKE) --no-print-directory gate
	@echo ""
	@echo "pre-pr passed. 'Green' means grounded and internally consistent."
	@echo "It never means correct."

# --- mining (third-party toolchain; deliberately outside the gate) ----------

REPO ?=
ID ?=
URI ?=
CLASS ?= internal
RETAIN ?= 2029-01-01
.PHONY: mine mine-dry
mine mine-dry:
	@test -n "$(REPO)" || { echo "set REPO=/path/to/repository"; exit 2; }
	@test -n "$(URI)"  || { echo "set URI=<repository URL for the record>"; exit 2; }
	@$(ARCHTRACE) mine --repo "$(REPO)" $(if $(ID),--id "$(ID)",) \
	  --source-uri "$(URI)" --date "$$(date -u +%Y-%m-%d)" \
	  --classification "$(CLASS)" --retention-until "$(RETAIN)" \
	  $(if $(filter mine-dry,$(MAKECMDGOALS)),--dry-run,)
