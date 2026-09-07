"""`iodelay_a` must compare something, on a tile whose IOLOGIC has ports.

Two defects the shape carried, both MEASURED (`P3.T21`):

* it declared no `scope_tiles`, and `equiv.in_scope` reads an empty tile list
  as the empty set -- an `E0` that compares nothing and passes vacuously;
* its delayed ball was `N15` (`IOB146A`, ttyp 63), one of the fourteen IOLOGIC
  bels on this die whose portmap is empty because `chipdb.dat_portmap` builds
  a GW5A IOLOGIC portmap only for a tile that carries an `IOBB`.  The router
  reached it with no wire for `DF` and every run of the batch aborted.
"""
import pytest

from fuzz.gw5ast138c.shapes import iodelay_a
from fuzz.gw5ast138c.shapes._io_base import SAFE_PINS


@pytest.fixture(scope="module")
def chipdb_138c():
    """The installed 138C chipdb, loaded once for this file."""
    from fuzz.gw5ast138c.harness import equiv
    return equiv.load_db(equiv.DEVICE)


def test_the_sweep_has_a_scope():
    assert iodelay_a.SPEC.scope.tiles


def test_every_ball_is_on_the_allowlist():
    for name, spec in iodelay_a.IodelayShape.ports.items():
        assert spec[0] in SAFE_PINS, (name, spec[0])


def test_the_delayed_ball_sits_in_the_scoped_tile():
    """The scope is the delayed input's own IO cell: `IODELAY` is attributes
    on that cell's IOLOGIC bel, so a scope naming any other tile would compare
    a tile the primitive never touches."""
    assert tuple(iodelay_a.SPEC.scope.tiles[0]) == (52, 108)
    assert iodelay_a.IodelayShape.ports["din"][0] == "AA9"


def test_the_scoped_tile_has_an_iologic_with_delay_ports(chipdb_138c):
    tile = chipdb_138c[108, 52]
    portmap = tile.bels["IOLOGICA"].portmap
    for port in ("DI", "DO", "DF", "SDTAP", "VALUE"):
        assert port in portmap, port


@pytest.mark.parametrize("changed", iodelay_a.gray_adjacent_bit_changes())
def test_the_static_delay_sweep_is_gray_coded(changed):
    assert changed == 1
