# The local gate's single entry point (C12, D94, D95; supersedes
# C8/D75-D78's blocking pre-commit shape). `.githooks/pre-push` is the only
# hook: task-branch pushes get no gate; a push to main/dev/integration/epic
# spawns this gate detached at GATE_SCOPE=branch. A human/agent typing
# `make gate` invokes this same target -- there is exactly one definition of
# "green". Included from the root Makefile (see the ifeq guard there for why
# this lives in a separate file, F87).

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

.PHONY: gate _gate-fast _gate-branch _gate-full

gate:
	@case "$(GATE_SCOPE)" in \
	  fast)   $(MAKE) --no-print-directory _gate-fast ;; \
	  branch) $(MAKE) --no-print-directory _gate-branch ;; \
	  full)   $(MAKE) --no-print-directory _gate-full ;; \
	  *) echo "GATE $(GATE_SCOPE): unknown GATE_SCOPE (legal: fast branch full)"; exit 1 ;; \
	esac

# fast: unit tests ONLY -- every test that shells out to gw_sh, yosys,
# nextpnr or gowin_pack, or reads a real .fs bitstream, is marked `heavy`
# and deselected here (C12/D94: target < 30 s, measured in
# test_gate_fast_budget). Builds no bitstream, touches no evidence.
_gate-fast:
	@echo "GATE fast: pytest -m 'not heavy and not gate_proof'"
	@$(PYTHON) -m pytest tests -q -m "not heavy and not gate_proof" || { echo "GATE fast: pytest FAILED"; exit 1; }
	@echo "GATE fast: ok, 1 check"

# branch: fast, plus evidence/criteria tools -- apicula owns none of those
# (open-toolchain and the umbrella do, against the shared evidence store);
# alias for fast (D94: "branch = fast + evidence/criteria tools
# (open-toolchain/umbrella)"). This is the scope the detached pre-push gate
# runs on main/dev/integration/epic pushes.
_gate-branch: _gate-fast
	@echo "GATE branch: no evidence/criteria tools owned by apicula -- ok, 1 check"

# full: everything, including the heavy tests (unpack + cell-presence, smoke
# self-tests, c2 round-trip, calibration -- the golden-netlist equivalence
# diffs for the examples the branch touches). Orchestrator-only, run in the
# foreground at phase close / pre-merge, never from a hook (C12).
_gate-full: _gate-branch
	@echo "GATE full: pytest -m 'heavy and not gate_proof'"
	@$(PYTHON) -m pytest tests -q -m "heavy and not gate_proof" || { echo "GATE full: pytest heavy FAILED"; exit 1; }
	@echo "GATE full: ok, 2 checks"
