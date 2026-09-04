"""`CibFabricNode` -- the PINCFG bel's input wires (`P0.T21` regression).

`chipdb.fse_create_pincfg` reads six `(row, col, wire)` triples from
`Datfile.gw5aStuff['CibFabricNode']` and turns them into the `SSPI` /
`UNK*_VCC` inputs of the `PINCFG` bel. The table's delta from the 5-series
anchor moved by 0xb8 between Gowin IDE 1.9.10.03 (the release upstream apicula
pins) and 1.9.11.03; reading the stale delta yields an all-0xffff grid, which
is silently legal -- 0xffff is the "port absent" marker.

The failure it caused is not silent downstream: apicula still sets
`HAS_PINCFG`, `nextpnr-himbaechel` unconditionally packs a `PINCFG` cell
(`himbaechel/uarch/gowin/pack.cc:56-71`), and routing dies with
`No wire found for port UNK0_VCC on destination cell PINCFG` -- i.e. **no
design of any shape could be placed and routed**. These are the guards that
would have caught it.
"""
import pytest

from apycula import dat_parser

pytest.importorskip("apycula.chipdb")

#: `(device, expected pincfg tile row, expected pincfg tile col)` --
#: `chipdb.fse_create_pincfg` places the bel at `(row, col)` and the table's
#: triples are the 1-based coordinates of the same or an adjacent tile.
DEVICES = [("GW5AST-138C", 109, 167), ("GW5A-25A", 10, 89)]


def _cib_fabric_node(gowinhome, device):
    from pathlib import Path
    path = Path(f"{gowinhome}/IDE/share/device/{device}/{device}.dat")
    if not path.is_file():
        pytest.skip(f"{path} absent")
    return dat_parser.Datfile(path).gw5aStuff["CibFabricNode"]


@pytest.mark.parametrize("device,tile_row,tile_col", DEVICES)
def test_cib_fabric_node_is_populated(gowinhome, device, tile_row, tile_col):
    grid = _cib_fabric_node(gowinhome, device)
    assert len(grid) == 6
    populated = [row for row in grid if row != [0xffff] * 3]
    # SSPI plus at least three UNK*_VCC inputs are present on both devices.
    assert len(populated) >= 4, f"{device}: CibFabricNode is empty ({grid})"
    for row, col, wire in populated:
        assert abs(row - tile_row) <= 1, f"{device}: implausible row {row}"
        assert abs(col - tile_col) <= 1, f"{device}: implausible col {col}"
        assert wire < 0x8000, f"{device}: implausible wire index {wire}"


def test_pincfg_bel_has_its_input_wires(gowinhome):
    """The end of the chain: the shipped chipdb's `PINCFG` bel has inputs."""
    import os
    from apycula import chipdb
    path = os.path.join(os.path.dirname(chipdb.__file__),
                        "GW5AST-138C.msgpack.xz")
    if not os.path.isfile(path):
        pytest.skip(f"{path} absent (build it with apycula.chipdb_builder)")
    db = chipdb.load_chipdb(path)
    pincfg = next(func["pincfg"] for func in db.extra_func.values()
                  if "pincfg" in func)
    ins = pincfg["ins"]
    assert "SSPI" in ins
    for port in ("UNK0_VCC", "UNK1_VCC", "UNK2_VCC", "UNK3_VCC"):
        assert port in ins, f"PINCFG has no {port}: nextpnr cannot route"
