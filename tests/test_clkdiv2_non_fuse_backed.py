"""`D103` -- a CLKDIV2 is recovered through the CLKDIV it is chained to.

A GW5A `CLKDIV2` writes no fuse.  Its only bitstream signature is negative --
the absent `HCLK_BUF_BO` select bit for its lane -- plus the `DIV_MODE=2` bit
of the `CLKDIV` on the same lane, so the §5.4 `c1` check cannot ask the decode
for a `CLKDIV2` cell.  It asks for that chained `CLKDIV` instead.
"""
import json
import os

from fuzz.gw5ast138c.harness import equiv
from fuzz.gw5ast138c.harness.equiv import Cell, Netlist


def _pnr_cells(tmp_path):
    """One CLKDIV2 and its chained CLKDIV, both placed in the same HCLK tile."""
    pnr = {"modules": {"top": {"cells": {
        "dut_clkdiv2": {"type": "CLKDIV2", "attributes": {
            "NEXTPNR_BEL": "X20Y41/CLKDIV2_1"}},
        "dut_clkdiv": {"type": "CLKDIV", "attributes": {
            "NEXTPNR_BEL": "X20Y41/CLKDIV_1"},
            "parameters": {"DIV_MODE": "2"}},
    }}}}
    path = tmp_path / "clkdiv2_pnr.json"
    path.write_text(json.dumps(pnr))
    return equiv.read_pnr_cells(str(path))


def _decoded(div_mode):
    """What the vendor bitstream decodes in that tile: a CLKDIV, no CLKDIV2."""
    return Netlist(cells={
        Cell(20, 41, 1, "CLKDIV_"): frozenset({("DIV_MODE", div_mode)}),
    })


def test_clkdiv2_is_recovered_by_the_chained_clkdiv_div_mode_2(tmp_path):
    """`c1` passes with no CLKDIV2 in the decode when the CLKDIV says DIV_MODE=2."""
    cells = _pnr_cells(tmp_path)
    out = equiv.decode_check_c1(cells, _decoded("2"))

    assert out["c1"] == "ok"
    assert out["missing"] == []
    assert out["required_cells"] == 1            # the CLKDIV alone is fuse-backed
    skipped = [s for s in out["skipped"] if s["type"] == "CLKDIV2"]
    assert len(skipped) == 1
    assert "chained CLKDIV" in skipped[0]["why"]


def test_clkdiv2_without_a_halved_clkdiv_is_a_mismatch(tmp_path):
    """The exemption stays narrow: no DIV_MODE=2 on the lane, no free pass."""
    cells = _pnr_cells(tmp_path)
    out = equiv.decode_check_c1(cells, _decoded("4"))

    assert out["c1"] == "mismatch"
    assert [m["type"] for m in out["missing"]] == ["CLKDIV2"]


def test_clkdiv2_is_listed_as_non_fuse_backed():
    """The list is the documented place a fuseless bel is recorded, never a silent drop."""
    assert "CLKDIV2" in equiv.NON_FUSE_BACKED_BELS


def test_hclk_type_does_not_eat_the_2_of_clkdiv2():
    """`CLKDIV2` and `CLKDIV` stay distinguishable once the index is stripped."""
    assert equiv._hclk_type("CLKDIV2_1") == "CLKDIV2"
    assert equiv._hclk_type("CLKDIV2") == "CLKDIV2"
    assert equiv._hclk_type("CLKDIV_1") == "CLKDIV"
    assert equiv._hclk_type("IOB") is None
