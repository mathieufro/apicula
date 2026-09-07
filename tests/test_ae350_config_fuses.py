"""The AE350's "configuration band", and why there is none.

A first measurement kept, of the bits an AE350 design sets and its AE350-free
control does not, those in tile types 224/228 that belong to no pip and to no
bel `modes`/`flags` table, and read the 77 that survived as the block's
configuration.  Tile types 224 and 228 are ordinary CLS logic tiles, and that
filter never subtracted their `shortval` tables -- which occupy exactly the
tile rows the 77 bits are in.  Subtract every modelled table and the count is
zero, in every AE350 bitstream measured and in the control
(`$OTC/evidence/ae350/fuse-set-138c.md`, `band-bits-138c.json`).

These tests pin the two halves of that: the emission is empty, and the record
that says so is a measurement over both filters rather than one number.
"""
import json
import os

import pytest

from apycula import chipdb, gowin_pack
from fuzz.gw5ast138c.harness import evidence

#: The tile types the block's port columns pass through.
BAND_TTYPS = (224, 228)
#: Bels that make a tile ordinary user logic rather than an interface band.
CLS_BELS = {'LUT0', 'DFF0', 'ALU0', 'RAM16'}


def _band_bits():
    path = os.path.join(evidence.evidence_root(), 'ae350',
                        'band-bits-138c.json')
    if not os.path.isfile(path):
        pytest.skip(f'{path} not written yet')
    with open(path) as fh:
        return json.load(fh)


def _db():
    path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        'apycula', 'GW5AST-138C.msgpack.xz')
    if not os.path.isfile(path):
        pytest.skip(f'{path} is absent')
    return chipdb.load_chipdb(path)


def test_the_band_tile_types_are_ordinary_logic_tiles():
    """The premise of the whole reading: 224/228 are CLS tiles, not a band."""
    db = _db()
    for ttyp in BAND_TTYPS:
        assert CLS_BELS <= set(db.tiles[ttyp].bels)
        assert set(db.shortval[ttyp]) >= {'LUT', 'CLS0', 'CLS1', 'CLS2', 'CLS3'}


def test_no_bitstream_sets_an_unmodelled_bit_in_the_band():
    """Zero for every AE350 design measured, and for the control."""
    for name, entry in _band_bits().items():
        assert entry['every_modelled_table']['bits'] == 0, name


def test_the_first_filter_disagrees_with_itself_across_equal_port_sets():
    """Four bitstreams of one shape, one port set, four different sets.

    `ae350_soc_batch1`, `ae350_soc_batch2`, `pll_l` and `ddr_clk` instantiate
    the same 149 ports; they differ in the capture fold and the PLL site.  A
    set that varies over them is not a function of the port set, which is the
    reading the empty intersection could not rule out on its own.
    """
    measured = _band_bits()
    same_ports = ('ae350_soc_batch1', 'ae350_soc_batch2', 'pll_l', 'ddr_clk')
    tiles = {name: sorted(measured[name]['routing_and_bels']['tiles'])
             for name in same_ports if name in measured}
    assert len(set(map(tuple, tiles.values()))) > 1, tiles


def test_nothing_is_emitted_for_the_bel():
    """One design's LUT configuration must not reach another's bitstream."""
    assert gowin_pack.GW5AST_138C.get_AE350_SOC_fuses(
        gowin_pack.GW5AST_138C, bel=None) == []


def test_no_device_carries_a_recorded_ae350_fuse_table():
    """The mis-attributed table is retracted, not merely unused."""
    for device in (gowin_pack.GW5AST_138C, gowin_pack.GW5A_25A,
                   gowin_pack.GW5AT_60B):
        assert not hasattr(device, 'AE350_SOC_CONFIG_FUSES')
