# Zero-dependency by design: no venv, no pip, no setup step.
ROOT ?= example
EVIDENCE_ROOT ?= $(ROOT)/_evidence_root
ARCHTRACE = ./archtrace --root $(ROOT) --evidence-root $(EVIDENCE_ROOT)

.PHONY: help check render fmt report test gate
help:
	@echo "make check    deterministic gates (exit 1 on any block)"
	@echo "make render   regenerate build outputs"
	@echo "make gate     render + check, the pre-publish loop"
	@echo "make fmt      canonicalise JSON, refresh derived fields"
	@echo "make report   grounding mix and NFR coverage"
	@echo "make test     seeded-defect suite"
	@echo "make mine     run a code miner (needs REPO= and URI=); NOT part of gate"
	@echo ""
	@echo "Override the engagement with ROOT=engagements/<name>"

check:  ; @$(ARCHTRACE) check
render: ; @$(ARCHTRACE) render
fmt:    ; @$(ARCHTRACE) fmt
report: ; @$(ARCHTRACE) report
test:   ; @python3 -m unittest discover -s tools/tests
gate: fmt render check

# Mining is NOT part of `gate`, and that is the point: it needs a third-party
# toolchain, it touches another repository, and it produces evidence rather than
# verdicts. The gate must keep running on a bare CI runner with no setup step.
#   make mine REPO=~/work/mam-legacy ID=EV-004 URI=https://github.example.com/x
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
