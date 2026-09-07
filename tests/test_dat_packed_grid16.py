"""The packed `.dat` grids of the 5-series table block, and who they touch.

`read_5Astuff` holds two families of grid tables. One family spells its shape
out by hand (`PllLTIns` and friends) and always decoded correctly. The other
was transcribed with its arguments in a different order and its base offsets
left in u16 words, so it decoded unrelated bytes; `read_packed_grid16` is the
repair. These tests pin the repair's arithmetic, the blast radius (5-series
parts only), and the two `AE350_SOC` port tables it unlocks.
"""
import os
from pathlib import Path

import pytest

from apycula import dat_parser
from apycula.wirenames import wirenames_5a25a

STANDARD_HOME = '/Applications/GowinIDE.app/Contents/Resources/Gowin_EDA'
DEVICE = 'GW5AST-138C'

#: `AE350_SOC`'s fabric footprint on the 138C, measured as the columns holding
#: 99.99 % of the bits that move between a bitstream that instantiates the block
#: and one that does not (`$OTC/evidence/ae350/wire-map-138c.md`).
FOOTPRINT_COLS = range(145, 182)

SENTINEL = [0xffff] * 3


def _device_file(device):
    path = Path(STANDARD_HOME) / 'IDE/share/device' / device / f'{device}.dat'
    if not path.is_file():
        pytest.skip(f'{path} is absent')
    return path


@pytest.fixture(scope='module')
def gw5ast138c():
    os.environ.setdefault('GOWINHOME', STANDARD_HOME)
    return dat_parser.Datfile(_device_file(DEVICE))


def _live(table):
    return [record for record in table if record != SENTINEL]


class _Buffer(dat_parser.Datfile):
    """A `Datfile` standing in for a file, so the reader can be read alone."""

    def __init__(self, data, rs_table_offset=0):  # noqa: D107 - test double
        self.data = data
        self._rs_table_offset = rs_table_offset


def test_packed_grid16_reads_records_back_to_back_from_a_word_offset():
    """Record r field c sits at `2 * (base_words + r * num_cols + c)`."""
    data = b'\xff\xff' * 4 + b''.join(
        v.to_bytes(2, 'little') for v in range(10, 22))
    grid = _Buffer(data).read_packed_grid16(4, 3, 4)
    assert grid == [[10, 11, 12], [13, 14, 15], [16, 17, 18], [19, 20, 21]]


@pytest.mark.parametrize('device', ['GW1N-9', 'GW1N-4', 'GW2A-18'])
def test_pre_five_series_devices_never_reach_the_packed_grids(device):
    """The repair cannot move a pre-5A table: those parts skip `read_5Astuff`."""
    os.environ.setdefault('GOWINHOME', STANDARD_HOME)
    dat = dat_parser.Datfile(_device_file(device))
    assert dat.part_type not in (2, 10)
    assert not hasattr(dat, 'gw5aStuff')


def test_ae350_outs_records_are_coordinates_of_this_device_grid(gw5ast138c):
    """Every live output record is a (row, col, wire) of the 138C grid."""
    dat = gw5ast138c
    for row, col, wire in _live(dat.gw5aStuff['Ae350SocOuts']):
        assert 1 <= row <= dat.grid.num_rows
        assert 1 <= col <= dat.grid.num_cols
        assert wire in wirenames_5a25a


def test_ae350_outs_records_land_in_the_measured_fabric_footprint(gw5ast138c):
    """The table the parser now reads describes the block the vendor placed."""
    live = _live(gw5ast138c.gw5aStuff['Ae350SocOuts'])
    inside = [r for r in live if (r[1] - 1) in FOOTPRINT_COLS]
    assert len(inside) >= 0.98 * len(live)


def test_ae350_input_taps_and_output_drives_share_one_column_band(gw5ast138c):
    """A hard block reads the left of its band and drives the right of it."""
    stuff = gw5ast138c.gw5aStuff
    tapped = {r[1] for r in _live(stuff['Ae350SocIns'])}
    driven = {r[1] for r in _live(stuff['Ae350SocOuts'])}
    assert max(c for c in tapped if c - 1 in FOOTPRINT_COLS) + 1 in driven


def test_ae350_input_taps_are_tile_output_wires(gw5ast138c):
    """An input tap can only be an F, Q or OF wire: what a tile drives."""
    live = _live(gw5ast138c.gw5aStuff['Ae350SocIns'])
    in_band = [r for r in live if (r[1] - 1) in FOOTPRINT_COLS]
    assert in_band
    assert all(32 <= wire < 56 for _row, _col, wire in in_band)


def test_ae350_ins_base_candidates_reject_the_stale_base(gw5ast138c):
    """The historical base names another block's table and must lose."""
    stale = dat_parser.Datfile.AE350_SOC_INS_BASES[0]
    stale_grid = gw5ast138c.read_packed_grid16(0x1b1, 3, stale)
    assert gw5ast138c.gw5aStuff['Ae350SocIns'] != stale_grid
