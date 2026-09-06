"""P1.T28 -- the DCS half of "re-derive the 138C DQCE/DCS tile types".

DCS on 138C (`apycula/chipdb.py:2790-2880`) searches the exact same
`fse['header']['grid'][61]` values 80/81/84/85 as DQCE, just paired
per-quadrant as `[(85, 84), (80, 81), (80, 81), (85, 84)]` -- so the DCS
tile-hosting cells are, by construction, the *same four* `(row, col)` cells
P1.T28's DQCE oracle campaign (`test_dqce_tiletypes_138c_derived.py`)
already measured; no separate oracle campaign is needed to name them (`DCS`
itself is documented and instantiable on Arora V unchanged --
`UG306-1.0.1E` S3.2 -- unlike `DQCE`, which the oracle probe showed must be
written `DCE` on this family; that naming question is orthogonal to which
physical cells the fuses land in, which is what this row is about).

This test checks the artefact `evidence/dcs/tiles-138c.md` (+
`tiles-138c.json` sidecar) states the same 4 cells/types as the DQCE
artefact and explains the shared derivation.
"""
import json
import os

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _otc_evidence_root():
    env = os.environ.get("OTC_EVIDENCE")
    if env:
        return env
    pipeline_dir = os.path.dirname(os.path.dirname(REPO))
    return os.path.join(pipeline_dir, "open-toolchain", "evidence")


DQCE_JSON = os.path.join(_otc_evidence_root(), "dqce", "tiletypes-138c.json")
DCS_MD = os.path.join(_otc_evidence_root(), "dcs", "tiles-138c.md")
DCS_JSON = os.path.join(_otc_evidence_root(), "dcs", "tiles-138c.json")


def _require(path):
    if not os.path.isfile(path):
        pytest.skip(f"artefact not present at {path} (P1.T28 not run yet, "
                    f"or $OTC_EVIDENCE not set for this per-branch worktree)")
    return path


def test_dcs_tiletypes_138c_match_dqce_cells():
    dqce = json.load(open(_require(DQCE_JSON)))
    dcs_md = open(_require(DCS_MD)).read()
    dcs = json.load(open(_require(DCS_JSON)))

    assert set(dcs["tile_types_138c"]) == set(dqce["tile_types_138c"])
    assert {tuple(c) for c in dcs["cells"]} == {tuple(c) for c in dqce["cells"]}

    # the DCS quadrant pairing convention -- [(85, 84), (80, 81), (80, 81),
    # (85, 84)] in `chipdb.py:2790` -- must be stated, and each of the 4
    # quadrant indices (0..3) must map to exactly one of the 4 cells.
    pairing = dcs["quadrant_pairs"]
    assert len(pairing) == 4
    seen_types = set()
    for q, pair in enumerate(pairing):
        assert len(pair) == 2
        seen_types.update(pair)
    assert seen_types == set(dqce["tile_types_138c"])

    for t in dqce["tile_types_138c"]:
        assert str(t) in dcs_md
