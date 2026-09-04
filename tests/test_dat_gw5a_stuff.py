"""P0.T13 -- `gw5aStuff` on the real installs, both editions.

Deliberately named so `pytest -k "dat_version"` does NOT select it. These
tests need a Gowin install and skip without one.
"""
import os
from pathlib import Path

import pytest

from apycula import dat_parser, fse_parser


EDITIONS = {
    'education': '/Users/alex/Desktop/GowinIDE.app/Contents/Resources/Gowin_EDA',
    'standard': '/Applications/GowinIDE.app/Contents/Resources/Gowin_EDA',
}
DEVICE = 'GW5AST-138C'
# Every key `read_5Astuff` returns; the count is the regression guard.
GW5A_STUFF_KEYS = 120
# Keys `chipdb.fse_create_5a138_clocks` -> `get_clock_ins` actually reads.
CLOCK_KEYS = ('CMuxTopIns', 'CMuxBotIns', 'CMuxTopInNodes', 'CMuxBotInNodes')


def _dat(gowinhome, device=DEVICE):
    return Path(gowinhome) / 'IDE/share/device' / device / f'{device}.dat'


def _parse(gowinhome, device=DEVICE):
    os.environ['GOWINHOME'] = gowinhome
    os.environ.pop('GOWIN_IDE_VERSION', None)
    return dat_parser.Datfile(_dat(gowinhome, device))


@pytest.mark.parametrize('edition', sorted(EDITIONS))
def test_dat_gw5a_stuff_present_on_both_editions(edition, monkeypatch):
    gowinhome = EDITIONS[edition]
    if not os.path.isdir(gowinhome):
        pytest.skip(f'{edition} install not present at {gowinhome}')
    monkeypatch.setenv('GOWINHOME', gowinhome)
    monkeypatch.delenv('GOWIN_IDE_VERSION', raising=False)
    dat = dat_parser.Datfile(_dat(gowinhome))
    assert dat.part_type == 2
    assert hasattr(dat, 'gw5aStuff'), 'the T13 AttributeError is back'
    assert len(dat.gw5aStuff) == GW5A_STUFF_KEYS
    for key in CLOCK_KEYS:
        assert dat.gw5aStuff[key], key


def test_dat_gw5a_stuff_layout_follows_the_installed_version(monkeypatch):
    for edition, gowinhome in sorted(EDITIONS.items()):
        if not os.path.isdir(gowinhome):
            pytest.skip(f'{edition} install not present')
    expected = {'1.9.11.03': ('v1_9_11minus', 0x7b4a4, 0x7b4a8),
                '1.9.12.03': ('v1_9_12plus', 0x7b4aa, 0x7b4ac)}
    for gowinhome in EDITIONS.values():
        monkeypatch.setenv('GOWINHOME', gowinhome)
        monkeypatch.delenv('GOWIN_IDE_VERSION', raising=False)
        version = fse_parser.detect_ide_version(gowinhome)
        dat = dat_parser.Datfile(_dat(gowinhome))
        shape_set, pt_off, rs_off = expected[version]
        assert (dat.dat_shape_set, dat._part_type_offset,
                dat._rs_table_offset) == (shape_set, pt_off, rs_off)


def test_dat_gw5a_stuff_identical_across_editions(monkeypatch):
    """1.9.11 and 1.9.12 ship the same GW5AST-138C device data.

    The two `.dat` files differ by exactly the four header bytes, so every
    table the parser extracts must come out equal. This is what proves the
    new offsets are right rather than merely non-crashing.
    """
    for gowinhome in EDITIONS.values():
        if not os.path.isdir(gowinhome):
            pytest.skip('both installs required')
    parsed = {}
    for edition, gowinhome in sorted(EDITIONS.items()):
        monkeypatch.setenv('GOWINHOME', gowinhome)
        monkeypatch.delenv('GOWIN_IDE_VERSION', raising=False)
        parsed[edition] = dat_parser.Datfile(_dat(gowinhome))
    edu, std = parsed['education'], parsed['standard']
    assert edu.gw5aStuff == std.gw5aStuff
    assert edu.compat_dict == std.compat_dict
    assert edu.portmap == std.portmap
    assert edu.cmux_ins == std.cmux_ins
    assert edu.grid.rows == std.grid.rows
    assert (edu.grid.num_rows, edu.grid.num_cols) == (std.grid.num_rows,
                                                      std.grid.num_cols)


@pytest.mark.parametrize('device', ['GW2A-18C', 'GW1NR-9C', 'GW1NSR-4C'])
def test_dat_gw5a_stuff_pre_gw5_devices_take_no_5a_path(device, monkeypatch):
    """No change for older `.dat` files: partType 0, no gw5aStuff, no error."""
    for edition, gowinhome in sorted(EDITIONS.items()):
        if not os.path.isdir(_dat(gowinhome, device).parent):
            continue
        monkeypatch.setenv('GOWINHOME', gowinhome)
        monkeypatch.delenv('GOWIN_IDE_VERSION', raising=False)
        dat = dat_parser.Datfile(_dat(gowinhome, device))
        assert dat.part_type == 0, (edition, device)
        assert not hasattr(dat, 'gw5aStuff'), (edition, device)
