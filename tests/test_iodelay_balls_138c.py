"""`iodelay_a_balls`: the `D105` re-shape of shape A (`P3.T22`).

The properties the re-shape exists for -- no fabric cell, every `DLYSTEP` bit
on a board ball, the same scope tile -- plus the `conns` residual the rows
must show closed.
"""
import json
import os

import pytest

from fuzz.gw5ast138c.harness import gen
from fuzz.gw5ast138c.shapes import iodelay_a, iodelay_a_balls
from fuzz.gw5ast138c.shapes._io_base import SAFE_PINS

OTC = os.environ.get(
    "OTC",
    os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                 "..", "open-toolchain"))
ROWS = os.path.normpath(os.path.join(OTC, "evidence", "iodelay", "runs.jsonl"))


def test_dlystep_bits_all_come_from_board_balls():
    assert len(iodelay_a_balls.DLYSTEP_BALLS) == 8
    assert len(set(iodelay_a_balls.DLYSTEP_BALLS)) == 8
    for ball in iodelay_a_balls.DLYSTEP_BALLS:
        assert ball in SAFE_PINS


def test_reshape_design_holds_no_fabric_cell():
    spec = gen.load_shape("iodelay_a_balls")
    for point in spec.sweep_values:
        rtl = gen.render_verilog(spec, point)
        assert "always" not in rtl
        assert "reg " not in rtl


def test_reshape_keeps_the_scope_tile_of_shape_a():
    assert iodelay_a_balls.IodelayBallsShape.scope_tiles == \
        iodelay_a.IodelayShape.scope_tiles


def test_reshape_closes_the_conns_residual():
    """The residual `P3.F2` left at 8 is 0 once no net leaves the scope."""
    if not os.path.isfile(ROWS):
        pytest.skip(f"no evidence at {ROWS}")
    with open(ROWS) as fh:
        rows = [json.loads(l) for l in fh if l.strip()]
    reshaped = [r for r in rows if r.get("shape") == "iodelay_a_balls"]
    assert reshaped, "the re-shape produced no row"
    baseline = [r for r in reshaped
                if list(r["sweep"].values())[0] == iodelay_a_balls.BASELINE]
    assert len(baseline) == 1
    assert baseline[0]["diff_count"]["conns"] == 0
    assert baseline[0]["level"] == "E1"
