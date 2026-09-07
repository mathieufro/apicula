"""`P2.T24`: the AE350's configuration fuse set, and who is allowed to emit it.

`EMCU` sets no fuse at all. This block does: nine tiles of the interface bands
carry bits in the vendor bitstream that instantiates `AE350_SOC` and in no tile
of either band in the bitstream that does not. The set is measured, so the test
pins its shape and its ownership, not a guess about the block's internals.
"""

import pytest

from apycula import gowin_pack

#: `$OTC/evidence/ae350/config-fuses-138c.md`.
CONFIG_BITS = 77
CONFIG_TILES = 9
#: The bits live in the last two rows of a 12-row `ttyp` 224/228 tile bitmap.
CONFIG_BIT_ROWS = {10, 11}


def test_config_fuses_are_the_measured_set():
    """77 bits over 9 tiles, all in the interface bands' own fuse rows."""
    table = gowin_pack.GW5AST_138C.AE350_SOC_CONFIG_FUSES
    assert len(table) == CONFIG_TILES
    assert sum(len(bits) for bits in table.values()) == CONFIG_BITS
    for bits in table.values():
        assert {row for row, _col in bits} <= CONFIG_BIT_ROWS
        assert len(set(bits)) == len(bits)


def test_config_fuses_are_emitted_against_their_own_cells():
    """The bits sit far from the bel, so each carries its own `(x, y)`."""
    table = gowin_pack.GW5AST_138C.AE350_SOC_CONFIG_FUSES
    emitted = gowin_pack.GW5AST_138C.get_AE350_SOC_fuses(
        gowin_pack.GW5AST_138C, bel=None)
    assert {(cell.x, cell.y) for cell in emitted} == set(table)
    assert sum(len(cell.bits) for cell in emitted) == CONFIG_BITS


def test_other_devices_refuse_the_ae350():
    """The block exists on one die; every other device must say so, not guess."""
    assert hasattr(gowin_pack.Device, 'get_AE350_SOC_fuses')
    assert not hasattr(gowin_pack.GW5A_25A, 'AE350_SOC_CONFIG_FUSES')
    assert not hasattr(gowin_pack.GW5AT_60B, 'AE350_SOC_CONFIG_FUSES')


def test_the_bel_name_matcher_accepts_the_block():
    """`gowin_pack` must recognise `X<c>Y<r>/AE350_SOC` as a bel."""
    import re
    source = open(gowin_pack.__file__).read()
    pattern = re.search(r'belre = re\.compile\(r"([^"]+)"\)', source).group(1)
    assert re.compile(pattern).match('X159Y0/AE350_SOC')
