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
