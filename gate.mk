# The local blocking gate's single entry point (C8, D77, P0.T42).
#
# `pre-commit`, `pre-push` and a human/agent typing `make gate` all invoke
# this same target -- there is exactly one definition of "green". Included
# from the root Makefile (see the ifeq guard there for why this lives in a
# separate file, F87).

include gate.env

GATE_SCOPE ?= fast

# `open-toolchain` submodule (C10/D80): evidence, DEL-e tools and manifests
# live here, checked out as a sibling of this apicula checkout.
# Every root below is derived from where THIS makefile is, so the gate runs
# from any checkout on any box; each is still overridable from the command
# line or the environment (`make gate OTC=... PYTHON=...`).
APICULA_DIR := $(patsubst %/,%,$(dir $(abspath $(lastword $(MAKEFILE_LIST)))))
WORKTREE_DIR := $(patsubst %/,%,$(dir $(APICULA_DIR)))
PIPELINE_SLUG ?= 2026-09-03-open-toolchain-gw5ast-7e84

OTC ?= $(WORKTREE_DIR)/open-toolchain
# Pipeline docs dir: documents only (spec-primitives.md), never code/evidence.
PIPE_DOCS ?= $(WORKTREE_DIR)/.atelier/pipelines/$(PIPELINE_SLUG)
# The umbrella's editable-install venv: three levels above the worktree.
FL_ROOT ?= $(abspath $(WORKTREE_DIR)/../../..)
PYTHON ?= $(FL_ROOT)/vendor/venv/bin/python

.PHONY: gate _gate-fast _gate-full _gate-all _gate-bogus

gate:
	@case "$(GATE_SCOPE)" in \
	  fast) $(MAKE) --no-print-directory _gate-fast ;; \
	  full) $(MAKE) --no-print-directory _gate-full ;; \
	  all)  $(MAKE) --no-print-directory _gate-all ;; \
	  *) echo "GATE $(GATE_SCOPE): unknown GATE_SCOPE (legal: fast full all)"; exit 1 ;; \
	esac

# fast: unit tests (heavy/bitstream tests deselected), parser/error tests,
# check_evidence.py, check_criteria.py --phase 0. Builds no bitstream.
# Budget: ~90 s (design), 180 s hard cap (test_gate_fast_budget).
_gate-fast:
	@echo "GATE fast: pytest -m 'not heavy and not gate_proof'"
	@$(PYTHON) -m pytest tests -q -m "not heavy and not gate_proof" || { echo "GATE fast: pytest FAILED"; exit 1; }
	@echo "GATE fast: check_evidence.py"
	@$(PYTHON) $(OTC)/tools/check_evidence.py $(PIPE_DOCS)/spec-primitives.md $(OTC)/evidence || { echo "GATE fast: check_evidence.py FAILED"; exit 1; }
	@echo "GATE fast: check_criteria.py --phase 0"
	@$(PYTHON) $(OTC)/tools/check_criteria.py $(PIPE_DOCS)/spec-primitives.md $(OTC)/evidence --phase 0 || { echo "GATE fast: check_criteria.py FAILED"; exit 1; }
	@echo "GATE fast: ok, 3 checks"

# full: fast, plus the heavy tests (unpack + cell-presence, smoke self-tests,
# c2 round-trip, calibration -- the golden-netlist equivalence diffs for the
# examples the branch touches).
_gate-full: _gate-fast
	@echo "GATE full: pytest -m 'heavy and not gate_proof'"
	@$(PYTHON) -m pytest tests -q -m "heavy and not gate_proof" || { echo "GATE full: pytest heavy FAILED"; exit 1; }
	@echo "GATE full: ok, 4 checks"

# all: the whole suite -- the exact scope the CI mirror's body invokes
# (D78). Phase 0 has one example (the smoke pair); later phases append
# per-example checks here without adding a second entry point.
_gate-all: _gate-full
	@echo "GATE all: ok, 4 checks"
