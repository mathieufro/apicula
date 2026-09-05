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
@pytest.mark.heavy
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


# --------------------------------------------------------------------------
# The §5.3 mask conditions (gestalt G1, G2, G3) -- each test is the audit's
# own counter-example, turned into a regression test.
# --------------------------------------------------------------------------
IOB_TTYP = 48
#: `(row, col)` inside `stub_db`'s grid, away from the bottom configuration
#: row so an unowned bit does not become a device-config gap by position.
IOB_TILE = (1, 0)


def stub_db(longval=None, pips=None, rev_logicinfo=None):
    """The smallest object `classify_residual` reads a chipdb through.

    A hand-built grid, exactly as the gestalt's method note prescribes: the
    mask questions are decided by the fuse-group tables and the cell sets, so
    a 34 MB bitstream would only make the test slower and less specific.
    """
    from types import SimpleNamespace

    tile = SimpleNamespace(pips=pips or {}, clock_pips=None,
                           alonenode=None, alonenode_6=None)
    return SimpleNamespace(
        grid=[[IOB_TTYP], [IOB_TTYP], [IOB_TTYP], [IOB_TTYP]],
        rows=4, cols=1, center_col=None,
        tiles={IOB_TTYP: tile},
        longval=longval or {}, shortval={}, longfuses={},
        # `Device.rev_logicinfo` is a method that builds the reverse table on
        # demand, so the stub is one too -- not a dict that only looks like it.
        rev_logicinfo=lambda name: (rev_logicinfo or {}).get(name, {}))


def iob_stub_db():
    """An IO tile whose `IOBA` table has one defaulted and one `DRIVE` fuse."""
    from apycula import attrids

    io_type, drive = attrids.iob_attrids["IO_TYPE"], attrids.iob_attrids["DRIVE"]
    return stub_db(
        longval={IOB_TTYP: {"IOBA": {(11,): {(2, 3)}, (13,): {(2, 4)}}}},
        rev_logicinfo={"IOB": {11: (io_type, 1), 13: (drive, 2)}})


def iob_cells(z=0):
    nl = Netlist(cells={Cell(IOB_TILE[1], IOB_TILE[0], z, "IOB"):
                        frozenset([("IO_TYPE", "LVCMOS33")])})
    return equiv.cells_by_tile(nl)


def _classify(db, coords, cells_v, cells_o, **kw):
    return equiv.classify_residual(
        {IOB_TILE: len(coords)}, cells_v, cells_o, outside_every_tile=0,
        outside={}, tile_coords={IOB_TILE: set(coords)}, db=db, **kw)


def test_io_default_mask_refuses_used_pin():
    """G1's counter-example: a differing IOBA fuse on a **used** pin is a DIFF.

    §5.3 row 6 masks the IO default only on "pins used by neither design".
    Before this guard the category was decided by the fuse-group name alone,
    so a differing `longval:IOBA` fuse in a tile where BOTH sides instantiate
    a used IOB came back `explained: io_default_unused_pins, unexplained: 0`.
    """
    used = iob_cells()
    res = _classify(iob_stub_db(), [(2, 3)], used, used)

    assert [r["category"] for r in res["explained"]] == []
    assert [r["category"] for r in res["unexplained_bits"]] == \
        ["io_used_pin_config"]
    assert res["unexplained_total_bits"] == 1
    assert res["unexplained_bits"][0]["justification"]


def test_io_default_mask_holds_on_a_pin_neither_side_uses():
    """The other half of row 6: the masked case is still masked."""
    res = _classify(iob_stub_db(), [(2, 3)], {}, {})

    assert res["unexplained_bits"] == []
    entry, = [r for r in res["explained"]
              if r["category"] == "io_default_unused_pins"]
    assert entry["mask_entry"] == "io_default_unused_pins"


def test_io_default_mask_refuses_a_non_defaulted_value():
    """Row 6's second condition: `DRIVE`/`PULLMODE` is the PR #423 class."""
    res = _classify(iob_stub_db(), [(2, 4)], {}, {})

    assert [r["category"] for r in res["unexplained_bits"]] == \
        ["io_nondefault_config"]


def test_open_only_fill_is_never_masked():
    """G2: a cell the OPEN side placed and the vendor did not is not fill.

    §5.3 row 3 excludes "configuration of any instantiated cell" in as many
    words, so `open_only_fill` may not resolve to the `unused_tile_fill` mask
    entry the way its vendor-side mirror does.
    """
    open_side = equiv.cells_by_tile(one_tile_netlist(x=9, y=9))
    res = equiv.classify_residual({(9, 9): 7}, {}, open_side,
                                  outside_every_tile=0, outside={})

    assert [r["category"] for r in res["unexplained_bits"]] == ["open_only_fill"]
    assert res["unexplained_total_bits"] == 7
    assert "unused_tile_fill" not in {r.get("mask_entry")
                                      for r in res["explained"]}


def route_netlist(port="I"):
    cell = Cell(IOB_TILE[1], IOB_TILE[0], 0, "IOB")
    nl = Netlist(cells={cell: frozenset()})
    nl.nets = {"A0": frozenset([(cell, port)])}
    nl.wire_net = {"A0": "A0"}
    return nl


def test_net_route_masked_only_when_endpoint_sets_match(monkeypatch):
    """G3: a flipped routing bit that changes a net is a DIFF, not a route.

    §5.3 row 5 masks "the physical route of a net whose endpoint set
    matches". Before this guard any bit in a `pip`/`alonenode` fuse group was
    masked with no endpoint test at all, so one clear fuse bit set in the open
    bitstream was silently absorbed into `net_route`.
    """
    monkeypatch.setattr(equiv, "db_wire2global",
                        lambda db, row, col, wire: wire)
    db = stub_db(pips={"A0": {"E111": [(9, 17)]}})
    same, changed = route_netlist(), route_netlist(port="O")

    ok = _classify(db, [(9, 17)], {}, {}, nl_v=same, nl_o=route_netlist())
    entry, = [r for r in ok["explained"] if r["category"] == "net_route"]
    assert entry["mask_entry"] == "net_route"
    assert ok["unexplained_bits"] == []

    bad = _classify(db, [(9, 17)], {}, {}, nl_v=same, nl_o=changed)
    assert [r["category"] for r in bad["unexplained_bits"]] == \
        ["net_route_endpoint_diff"]
    assert bad["explained"] == []
