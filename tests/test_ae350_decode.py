"""`gowin_unpack.parse_ae350`: recovering a block that sets no fuse.

The `AE350_SOC` writes no bel fuse, no attribute and no configuration bit --
MEASURED (`$OTC/evidence/ae350/config-fuses-138c.md`, restated by
`$OTC/evidence/ae350/e1-138c.md`).  Its whole bitstream signature is the
routing of its port taps: those wires are a dead end for every other cell on
the die, so a pip that drives one, or is driven by one, exists only because the
block is there.  That is the substitute signature `D103` asks for before a bel
may be excused from the decode check, and these tests are what pins it.
"""
import os

import pytest

from apycula import chipdb, gowin_unpack as gu

DEVICE = 'GW5AST-138C'
ANCHOR = gu._AE350_ANCHOR


@pytest.fixture(scope='module')
def db():
    path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        'apycula', f'{DEVICE}.msgpack.xz')
    if not os.path.isfile(path):
        pytest.skip(f'{path} is absent; run `make apycula/{DEVICE}.msgpack.xz`')
    return chipdb.load_chipdb(path)


def a_remote_tap(db):
    """One tap of the block that lives outside the anchor cell."""
    return next((cell, wire) for (row, col, wire), _port
                in sorted(gu.ae350_tap_wires(db).items())
                for cell in [(row, col)] if cell != ANCHOR)


def test_every_mapped_port_has_a_tap_and_no_unmapped_one_does(db):
    ae350 = db.extra_func[ANCHOR]['ae350']
    ports = set(gu.ae350_tap_wires(db).values())
    mapped = {port for direction in ('ins', 'outs')
              for port, wire in ae350[direction].items()
              if not wire.startswith('AE350_UNMAPPED_')}
    assert ports == mapped
    assert not ports & set(ae350['unmapped'])


def test_a_routed_tap_recovers_the_block(db):
    cell, wire = a_remote_tap(db)
    assert gu.parse_ae350(db, {cell: {wire: 'X01'}}, device=DEVICE) == {
        'AE350_SOC': set()}


def test_a_tap_driving_a_wire_recovers_the_block(db):
    """Output taps are pip sources, not destinations; both count."""
    cell, wire = a_remote_tap(db)
    assert gu.parse_ae350(db, {cell: {'X01': wire}}, device=DEVICE) == {
        'AE350_SOC': set()}


def test_routing_that_touches_no_tap_recovers_nothing(db):
    cell, _wire = a_remote_tap(db)
    assert gu.parse_ae350(db, {cell: {'X01': 'X02'}}, device=DEVICE) == {}


def test_no_routing_at_all_recovers_nothing(db):
    assert gu.parse_ae350(db, {}, device=DEVICE) == {}


def test_another_device_is_never_given_an_ae350(db):
    cell, wire = a_remote_tap(db)
    assert gu.parse_ae350(db, {cell: {wire: 'X01'}}, device='GW5A-25A') == {}
