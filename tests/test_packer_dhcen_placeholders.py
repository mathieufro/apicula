"""nextpnr's `$PACKER_DHCEN_*` placeholders are not missing cells.

`pack.cc` binds one placeholder to every `DHCEN` bel on the device as soon as
a design holds a single `DHCE`, and `globals.cc route_dhcen_net` later marks
only the ones the route needs with `DHCEN_USED` -- the attribute
`gowin_pack.GW5AST_138C.get_DHCEN_fuses` keys on.  An unmarked placeholder
writes no fuse, so `c1` must skip it; a `DHCE` the design named must not be.
"""
import json

from fuzz.gw5ast138c.harness import equiv
from fuzz.gw5ast138c.harness.equiv import Cell, Netlist


def _cells(tmp_path, extra=None):
    cells = {
        "$PACKER_DHCEN_21": {"type": "DHCEN", "attributes": {
            "NEXTPNR_BEL": "X117Y108/DHCEN0"}},
        "$PACKER_DHCEN_22": {"type": "DHCEN", "attributes": {
            "NEXTPNR_BEL": "X117Y108/DHCEN1"}},
    }
    cells.update(extra or {})
    path = tmp_path / "dhcen_pnr.json"
    path.write_text(json.dumps({"modules": {"top": {"cells": cells}}}))
    return equiv.read_pnr_cells(str(path))


EMPTY = Netlist(cells={})


def test_packer_dhcen_placeholders_are_skipped(tmp_path):
    """A bitstream with no DHCE gate at all still passes `c1`."""
    out = equiv.decode_check_c1(_cells(tmp_path), EMPTY)

    assert out["c1"] == "ok"
    assert out["required_cells"] == 0
    assert len(out["skipped"]) == 2
    assert all("DHCEN_USED" in s["why"] for s in out["skipped"])


def test_a_named_dhce_is_still_required(tmp_path):
    """The exemption is the placeholder's name, not the DHCEN bel type."""
    named = {"gate0": {"type": "DHCEN", "attributes": {
        "NEXTPNR_BEL": "X117Y108/DHCEN2"}}}
    out = equiv.decode_check_c1(_cells(tmp_path, named), EMPTY)

    assert out["c1"] == "mismatch"
    assert [m["name"] for m in out["missing"]] == ["gate0"]


# ------------------------------------------------------------------ the gate

#: The DHCE gate fuse is the bit every source of one HCLK input multiplexer
#: has in common (`chipdb.gw5a_dhce_gate_fuses`), so a two-source mux sharing
#: `(1, 2)` is the smallest shape that carries one.
GATE_MUX = {"HCLK_MUX_GATE0": {"srcA": [(1, 2), (3, 4)],
                               "srcB": [(1, 2), (5, 6)]}}
GATE_FUSE = (1, 2)


def _decoded(gate_set):
    """A decoded netlist of one HCLK block cell, with or without the gate."""
    import types
    tile = [[0] * 8 for _ in range(8)]
    if gate_set:
        tile[GATE_FUSE[0]][GATE_FUSE[1]] = 1
    db = types.SimpleNamespace(
        extra_func={(108, 117): {"dhcen": {0: {"gate": "HCLK_MUX_GATE0"}}}},
        hclk_pips={(108, 117): GATE_MUX})
    return Netlist(cells={}, tile_bitmap={(108, 117): tile}, db=db)


def _used(tmp_path):
    return _cells(tmp_path, {"$PACKER_DHCEN_23": {
        "type": "DHCEN",
        "attributes": {"NEXTPNR_BEL": "X117Y108/DHCEN0", "DHCEN_USED": 1}}})


def test_a_used_dhcen_placeholder_without_its_gate_fuse_fails_c1(tmp_path):
    """The `P1.T38b` regression: the flow marks the gate used and sets no fuse."""
    out = equiv.decode_check_c1(_used(tmp_path), _decoded(gate_set=False))

    assert out["c1"] == "mismatch"
    assert [m["name"] for m in out["missing"]] == ["$PACKER_DHCEN_23"]
    assert "gate fuse" in out["missing"][0]["why"]


def test_a_used_dhcen_placeholder_with_its_gate_fuse_passes_c1(tmp_path):
    """The same cell passes as soon as the gate bit is in the bitstream."""
    out = equiv.decode_check_c1(_used(tmp_path), _decoded(gate_set=True))

    assert out["c1"] == "ok"
    assert out["missing"] == []
    assert any(s["name"] == "$PACKER_DHCEN_23" and "used DHCE" in s["why"]
               for s in out["skipped"])
