"""`P2.T24`/`P2.T23`: the AE350's interface band, and why nothing emits it.

`P2.T24` measured 77 bits over 9 tiles that one AE350 design sets and the
AE350-free control does not, and read them as the block's configuration.
`P2.T23` ran the second AE350 design that measurement asked for: it sets
**three** such bits, at a different tile, and the two designs' sets intersect
in **zero**.  So the band is a per-design configuration, no bit marks the
block's presence, and `get_AE350_SOC_fuses` emits nothing -- exactly as
`get_EMCU_fuses` does.  The table survives as recorded evidence about one
design, and these tests pin that split: the shape of the record, and the
emptiness of the emission.
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


def test_the_recorded_table_is_never_emitted():
    """One design's interface band must not be written into another's."""
    assert gowin_pack.GW5AST_138C.get_AE350_SOC_fuses(
        gowin_pack.GW5AST_138C, bel=None) == []


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
