"""`gowin_unpack` must recover an `IODELAY`'s static delay step (`P3.T22`).

The GW5AST-138C spends one enumerated IOLOGIC attribute on the whole 0-255
step, not the seven one-bit `DELAY_DEL0`-`DELAY_DEL6` attributes the pre-5A
families use.  Everything asserted here was MEASURED from the 28 vendor
bitstreams of the `P3.T21` sweep (`$OTC/evidence/iodelay/fuse-attribution.json`).
"""
import pytest

from apycula import attrids
from apycula import gowin_unpack


def test_the_delay_step_attribute_is_named():
    assert attrids.iologic_attrids['C_STATIC_DLY'] == 118


@pytest.mark.parametrize("value_id,step", [(2, 1), (1002, 2), (1016, 16),
                                           (1128, 128), (1152, 152), (1255, 255)])
def test_a_value_id_reads_back_as_its_step(value_id, step):
    assert gowin_unpack.c_static_dly_of(value_id) == step


def test_the_whole_range_is_enumerated(chipdb_138c):
    """255 rows, one per non-zero step: step 0 sets no fuse and has no row,
    so an absent attribute is a delay of zero and not a hole in the table."""
    tile = chipdb_138c[108, 52]
    table = chipdb_138c.shortval[tile.ttyp]['IOLOGICA']
    rev = chipdb_138c.rev_logicinfo('IOLOGIC')
    steps = {gowin_unpack.c_static_dly_of(rev[key[0]][1])
             for key in table
             if isinstance(key, tuple) and rev.get(key[0])
             and rev[key[0]][0] == attrids.iologic_attrids['C_STATIC_DLY']}
    assert steps == set(range(1, 256))


def test_bit_seven_is_fuse_backed(chipdb_138c):
    """The step the pre-5A `DELAY_DEL` window cannot express has a fuse here:
    the eight bits are plain binary weights in tile row 21, columns 3-10."""
    tile = chipdb_138c[108, 52]
    table = chipdb_138c.shortval[tile.ttyp]['IOLOGICA']
    rev = chipdb_138c.rev_logicinfo('IOLOGIC')
    by_step = {gowin_unpack.c_static_dly_of(rev[key[0]][1]): {tuple(b) for b in bits}
               for key, bits in table.items()
               if isinstance(key, tuple) and rev.get(key[0])
               and rev[key[0]][0] == attrids.iologic_attrids['C_STATIC_DLY']}
    for bit in range(8):
        assert by_step[1 << bit] == {(21, 3 + bit)}


@pytest.fixture(scope="module")
def chipdb_138c():
    from fuzz.gw5ast138c.harness import equiv
    return equiv.load_db(equiv.DEVICE)
