"""`P0.T25` -- the mandatory raw residual (`D35`) and the decode check (`D34`).

Four tests, named by the blueprint.  The two residual tests drive the pure
classifier, so they say what they mean without a 34 MB bitstream; the two
decode-check tests use the real smoke artefacts and skip, with a named reason,
where those are not on the box.
"""
import json
import os

import pytest

from fuzz.gw5ast138c.harness import equiv
from fuzz.gw5ast138c.harness.equiv import Cell, Netlist


SMOKE = os.path.join(equiv.DATASTORE, "oracle-smoke")
SMOKE_OPEN_FS = os.path.join(SMOKE, "top.fs")
SMOKE_PNR = os.path.join(SMOKE, "top_pnr.json")

needs_smoke = pytest.mark.skipif(
    not os.path.isfile(SMOKE_OPEN_FS),
    reason=f"no open-flow smoke bitstream at {SMOKE_OPEN_FS} (P0.T21 builds it)")


def one_tile_netlist(x=2, y=1, typ="DFF", attrs=(("FF_TYPE", "DFF"),)):
    return Netlist(cells={Cell(x, y, 0, typ): frozenset(attrs)})


# --------------------------------------------------------------------------
# D35 -- the raw residual
# --------------------------------------------------------------------------
def test_residual_empty_on_self_compare():
    """A bitstream compared with itself has nothing left over, by definition."""
    tiles = {(1, 2): [[1, 0, 1], [0, 1, 0]], (5, 5): [[1, 1], [0, 0]]}
    delta, in_tiles = equiv.tile_delta_from_tiles(tiles, tiles)
    assert delta == {} and in_tiles == 0

    nl = one_tile_netlist()
    res = equiv.classify_residual(delta, equiv.cells_by_tile(nl),
                                  equiv.cells_by_tile(nl),
                                  outside_every_tile=0,
                                  outside={"comment_delta_bytes": 0,
                                           "unaccounted_bytes": 0})
    assert res["unexplained_bits"] == []
    assert res["unexplained_total_bits"] == 0
    assert not equiv._residual_is_dirty(res)

    result = equiv.compare_e0(nl, nl, residual=res)
    assert result.verdict == "EQUIV E0 ok"
    assert equiv.evidence_rows(result)[0]["unexplained_bits"] == []


def test_residual_nonempty_forces_diff():
    """One bit no cell accounts for is a DIFF even when all three sets match."""
    nl = one_tile_netlist()
    cells = equiv.cells_by_tile(nl)
    # (1,2) is the DFF's own tile: both sides unpack the SAME cell and the
    # same attributes there, so the set comparison sees nothing, yet a raw bit
    # differs -- a fuse apicula does not model, dropped on both sides during
    # unpack.  That is precisely the blind spot D35 exists to catch.
    res = equiv.classify_residual({(1, 2): 1}, cells, cells,
                                  outside_every_tile=0,
                                  outside={"comment_delta_bytes": 0,
                                           "unaccounted_bytes": 0})
    assert len(res["unexplained_bits"]) == 1
    entry = res["unexplained_bits"][0]
    assert entry["category"] == "unmodelled_fuse"
    assert entry["bits"] == 1
    assert entry["justification"]

    result = equiv.compare_e0(nl, nl, residual=res)
    assert result.diff_count == {"cells": 0, "attrs": 0, "conns": 0, "pips": 0}
    assert result.verdict == "DIFF"
    assert len(equiv.evidence_rows(result)[0]["unexplained_bits"]) == 1


def test_residual_masked_fill_is_accounted_not_unexplained():
    """§5.3 row 3: unused-tile fill is accounted for, and says by which entry."""
    vendor = equiv.cells_by_tile(one_tile_netlist(x=9, y=9))
    res = equiv.classify_residual({(9, 9): 1234}, vendor, {},
                                  outside_every_tile=0, outside={})
    assert res["unexplained_bits"] == []
    fill = [r for r in res["explained"] if r["category"] == "vendor_only_fill"]
    assert len(fill) == 1
    assert fill[0]["bits"] == 1234
    assert fill[0]["mask_entry"] == "unused_tile_fill"


# --------------------------------------------------------------------------
# D34 -- the two-part decode check
# --------------------------------------------------------------------------
@needs_smoke
def test_decode_check_c2_bitmap_roundtrip(tmp_path):
    """bslib out and back in: the fuse bitmap must be byte-identical."""
    out = equiv.decode_check_c2(SMOKE_OPEN_FS,
                                tmp_path=str(tmp_path / "roundtrip.fs"))
    assert out["c2"] == "ok"
    assert out["differing_bytes"] == 0
    assert out["bitmap_bytes"] > 0


def test_decode_check_c1_recovers_every_cell():
    """Every fuse-backed placed cell comes back out of the decode."""
    pnr = {"modules": {"top": {"cells": {
        "dut_dff": {"type": "DFF", "attributes": {
            "NEXTPNR_BEL": "X2Y1/DFF1"}},
        "din_IBUF_I": {"type": "IBUF", "attributes": {
            "NEXTPNR_BEL": "X55Y108/IOBB", "&IO_TYPE=LVCMOS33": "1"}},
        "$PACKER_VCC_DRV": {"type": "GOWIN_VCC", "attributes": {
            "NEXTPNR_BEL": "X0Y0/VCC"}},
        "spine_select$top": {"type": "SPINE_SELECT", "attributes": {}},
    }}}}
    path = os.path.join(os.path.dirname(__file__), "_c1.json")
    with open(path, "w") as f:
        json.dump(pnr, f)
    try:
        cells = equiv.read_pnr_cells(path)
    finally:
        os.remove(path)
    assert len(cells) == 4

    netlist = Netlist(cells={
        Cell(2, 1, 1, "DFF"): frozenset(),
        Cell(55, 108, 1, "IOB"): frozenset({("IO_TYPE", "LVCMOS33")}),
    })
    out = equiv.decode_check_c1(cells, netlist)
    assert out["c1"] == "ok"
    assert out["required_cells"] == 2          # VCC and the unplaced cell drop out
    assert out["recovered_cells"] == out["required_cells"]
    assert out["missing"] == [] and out["attr_mismatch"] == []
    assert len(out["skipped"]) == 2

    # ... and a cell the decode does NOT bring back is a mismatch, never a pass.
    out = equiv.decode_check_c1(cells, Netlist(cells={
        Cell(55, 108, 1, "IOB"): frozenset({("IO_TYPE", "LVCMOS33")})}))
    assert out["c1"] == "mismatch"
    assert out["recovered_cells"] == 1 and len(out["missing"]) == 1
