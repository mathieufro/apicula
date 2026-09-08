"""The `B` half of a GW5AST-138C pad pair carries a real IOLOGIC (`P3.F3`).

`P3.T11` read `db.shortval[247]['IOLOGICB']` -- three fuse coordinates against
`IOLOGICA`'s hundred -- and published "an IOLOGIC is configurable on the A half
only", which confined every Phase-3 IOLOGIC point to an `A`-half ball.  The
stub is the table that is *designed* to stay clear: a `B` half's IOLOGIC fuses
live in the **adjacent aux cell**, whose own `IOLOGICB` table is the full one,
and the vendor writes them there.

These guards pin both halves of that: the database shape the misreading
depended on, and the three shapes that put the claim to the vendor.
"""
import os

import pytest

from apycula import chipdb
from apycula.gowin_pack import ChipDB

DEVICE = "GW5AST-138C"

#: One pad pair of the bottom edge and its aux cell, `(row, col)` as the
#: chipdb addresses them.  `AB16`/`AB17` are `IOB80A`/`IOB80B`
#: (`$OTC/evidence/iologic/pin-hclk-138c.json`).
PAD_CELL = (108, 79)
AUX_CELL = (108, 80)

#: The three shapes that measure the `B` half against the vendor.
B_HALF_SHAPES = ("io_basic_b", "io_ser_b", "io_des_b")


@pytest.fixture(scope="module")
def db_138c():
    try:
        return ChipDB(DEVICE).db
    except FileNotFoundError:  # pragma: no cover - build it first
        pytest.skip(f"{DEVICE}.msgpack.xz absent; run apycula.chipdb_builder")


def test_the_b_half_stub_table_is_not_the_b_half_table(db_138c):
    """The pad cell's `IOLOGICB` is a stub; the aux cell's is the real table.

    This is the database shape the retracted conclusion misread, asserted so
    that a future reader meets it with its meaning attached.
    """
    pad_ttyp = db_138c.grid[PAD_CELL[0]][PAD_CELL[1]]
    aux_ttyp = db_138c.grid[AUX_CELL[0]][AUX_CELL[1]]
    pad = db_138c.shortval[pad_ttyp]
    aux = db_138c.shortval[aux_ttyp]
    assert len(pad["IOLOGICA"]) == len(aux["IOLOGICB"])
    assert len(pad["IOLOGICB"]) == len(aux["IOLOGICA"])
    assert len(pad["IOLOGICB"]) < len(pad["IOLOGICA"])


def test_a_b_half_iologic_is_written_into_the_aux_cell(db_138c):
    """`IOLOGICB` follows its pad into the aux cell, and `IOLOGICA` does not."""
    tile = db_138c.tiles[db_138c.grid[PAD_CELL[0]][PAD_CELL[1]]]
    assert tile.bels["IOLOGICB"].fuse_cell_offset == tile.bels["IOBB"].fuse_cell_offset
    assert tile.bels["IOLOGICB"].fuse_cell_offset == (0, 1)
    assert tile.bels["IOLOGICA"].fuse_cell_offset is None


@pytest.mark.parametrize("name", B_HALF_SHAPES)
def test_a_b_half_shape_scopes_both_of_its_cells(name):
    """A scope naming only the pad cell would compare no IOLOGIC fuse at all."""
    from fuzz.gw5ast138c.harness import gen

    spec = gen.load_shape(name)
    tiles = {tuple(t) for t in spec.scope.tiles}
    assert len(tiles) == 2
    (x0, y0), (x1, y1) = sorted(tiles)
    assert y0 == y1 and x1 == x0 + 1, tiles


@pytest.mark.parametrize("name", B_HALF_SHAPES)
def test_a_b_half_shape_drives_a_b_half_ball(name):
    """The pad under test is a `B` half, or the shape measures the old claim."""
    from fuzz.gw5ast138c.harness import gen
    from fuzz.gw5ast138c.shapes._io_base import SAFE_PINS

    spec = gen.load_shape(name)
    under_test = {"io_basic_b": "dout", "io_ser_b": "dout",
                  "io_des_b": "din"}[name]
    ball = spec.pins[under_test].loc
    assert SAFE_PINS[ball].site.endswith("B"), (name, ball)


@pytest.mark.parametrize("name", B_HALF_SHAPES)
def test_a_b_half_shape_carries_exactly_one_point(name):
    """One run each: the question is the half, not a second sweep."""
    from fuzz.gw5ast138c.harness import gen

    assert len(gen.load_shape(name).sweep_values) == 1
