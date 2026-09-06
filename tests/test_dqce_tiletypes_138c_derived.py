"""P1.T28 -- re-derive the 138C DQCE/DCS tile types (`spec-primitives.md`
`DQCE` row; `blueprints/P1-clocking.md` P1.T28).

Ground truth for this test is the artefact `evidence/dqce/tiletypes-138c.md`
(+ its `tiletypes-138c.json` sidecar) in the `open-toolchain` evidence tree,
and the batch log `evidence/_runs/p1-dqce-types.log` that the 8-run vendor
probe (`evidence/dqce/run_probe.py`, using
`fuzz.gw5ast138c.shapes.clocking_dqce_probe`) appended to.

This worktree is a **per-branch worktree**
(`.atelier/worktrees/<pipeline>/apicula-wt/dqce`, LOOP-BRIEF "Per-branch
worktrees for submodules"), so `harness.paths.otc_evidence()`'s default
guess (a sibling of the *repo* root) does not resolve to the real
`$OTC/evidence` -- it would need `$OTC_EVIDENCE` set, which the gate does
not currently export (a pre-existing gap, not something this task's `Files
it may touch` list lets it fix: `harness/paths.py` is frozen for this task).
`_otc_evidence_root` below does the one extra `dirname` a per-branch
worktree needs, with `$OTC_EVIDENCE` still taking priority when set.
"""
import json
import os
import re

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _otc_evidence_root():
    env = os.environ.get("OTC_EVIDENCE")
    if env:
        return env
    # REPO = .../<pipeline>/apicula-wt/dqce -> two dirnames up is
    # .../<pipeline>, whose sibling "open-toolchain/evidence" is $OTC/evidence.
    pipeline_dir = os.path.dirname(os.path.dirname(REPO))
    return os.path.join(pipeline_dir, "open-toolchain", "evidence")


ARTIFACT_MD = os.path.join(_otc_evidence_root(), "dqce", "tiletypes-138c.md")
ARTIFACT_JSON = os.path.join(_otc_evidence_root(), "dqce", "tiletypes-138c.json")
BATCH_LOG = os.path.join(_otc_evidence_root(), "_runs", "p1-dqce-types.log")

PRE5A_TYPES = ("80", "81", "84", "85")


def _require(path):
    if not os.path.isfile(path):
        pytest.skip(f"artefact not present at {path} (P1.T28 not run yet, "
                    f"or $OTC_EVIDENCE not set for this per-branch worktree)")
    return path


def test_dqce_tiletypes_138c_derived():
    md = open(_require(ARTIFACT_MD)).read()
    data = json.load(open(_require(ARTIFACT_JSON)))

    # -- exactly 4 tile types, 4 distinct (row, col) pairs -----------------
    types = data["tile_types_138c"]
    assert len(types) == 4, f"expected 4 138C tile types, got {types}"
    assert len(set(types)) == 4, "the 4 types must be distinct"

    cells = [tuple(c) for c in data["cells"]]
    assert len(cells) == 4, f"expected 4 (row, col) cells, got {cells}"
    assert len(set(cells)) == 4, "the 4 cells must be distinct"

    # -- every named type actually occurs in fse['header']['grid'][61] -----
    occ = data["occurrence_counts"]
    assert set(occ.keys()) == {str(t) for t in types}
    for t, count in occ.items():
        assert count >= 1, f"type {t} does not occur in the 138C grid[61] at all"

    # -- the artefact's "why they differ" paragraph -------------------------
    # non-empty (>= 1 sentence) and names all four pre-5A numbers.
    why = data.get("why_they_differ", "")
    assert len(why.strip()) > 0
    assert why.strip().count(".") >= 1 or why.strip().count("--") >= 1
    for n in PRE5A_TYPES:
        assert n in why, f"'why they differ' must mention {n}"
        assert n in md, f"the markdown artefact must mention {n}"

    # sanity: the markdown states the same 4 types/cells as the JSON.
    for t in types:
        assert str(t) in md
    for (r, c) in cells:
        assert f"({r}, {c})" in md or f"({r},{c})" in md


def test_dqce_tiletypes_138c_batch_complete():
    log = open(_require(BATCH_LOG)).read()
    m = re.search(
        r"BATCH_COMPLETE p1-dqce-types runs=(\d+) ok=(\d+) diff=(\d+) aborted=(\d+)",
        log)
    assert m, f"no BATCH_COMPLETE line in {BATCH_LOG}"
    runs, ok, diff, aborted = (int(x) for x in m.groups())
    assert runs == 8, f"expected 8 oracle runs, log says {runs}"
    assert aborted == 0, f"{aborted} of {runs} runs aborted -- see {BATCH_LOG}"
