"""P0.T13 -- `gw5aStuff` on both IDE versions, 1.9.11 and 1.9.12.

Deliberately named so `pytest -k "dat_version"` does NOT select it. These
tests need device files and skip without them.

Since 2026-09-04 (owner constraint C9 / D79) there is only one Gowin install
on the box: the licensed Standard 1.9.12.03. The Education 1.9.11.03 install
was removed; its `IDE/share/device/` tree was archived first, as a bare
`<device>/<device>.<ext>` tree. So the 1.9.11 side is read from that archive
by path, with `GOWIN_IDE_VERSION` forced -- there is no `IDE/doc/` to detect
the version from and no `gw_sh` to run (none is needed: `.dat` parsing is
pure file reading).
"""
import os
from pathlib import Path

import pytest

from apycula import dat_parser, fse_parser
from fuzz.gw5ast138c.harness import paths


STANDARD_HOME = '/Applications/GowinIDE.app/Contents/Resources/Gowin_EDA'
ARCHIVED_EDU_TREE = os.path.join(
    paths.datastore(), 'ide-share-device', 'edu-1.9.11.03')

# name -> (device-file root, forced GOWIN_IDE_VERSION or None to detect)
SOURCES = {
    'education-1.9.11-archive': (ARCHIVED_EDU_TREE, '1.9.11.03'),
    'standard-1.9.12-install': (
        os.path.join(STANDARD_HOME, 'IDE/share/device'), None),
}
VERSION_OF = {'education-1.9.11-archive': '1.9.11.03',
              'standard-1.9.12-install': '1.9.12.03'}

DEVICE = 'GW5AST-138C'
# Every key `read_5Astuff` returns; the count is the regression guard.
GW5A_STUFF_KEYS = 120
# Keys `chipdb.fse_create_5a138_clocks` -> `get_clock_ins` actually reads.
CLOCK_KEYS = ('CMuxTopIns', 'CMuxBotIns', 'CMuxTopInNodes', 'CMuxBotInNodes')


def _dat(source, device=DEVICE):
    root, _forced = SOURCES[source]
    return Path(root) / device / f'{device}.dat'


def _use(source, monkeypatch):
    """Point the parser's version detection at `source`; skip if absent."""
    root, forced = SOURCES[source]
    if not os.path.isdir(root):
        pytest.skip(f'{source} device files not present at {root}')
    monkeypatch.setenv('GOWINHOME', STANDARD_HOME)
    if forced:
        monkeypatch.setenv('GOWIN_IDE_VERSION', forced)
    else:
        monkeypatch.delenv('GOWIN_IDE_VERSION', raising=False)


@pytest.mark.parametrize('source', sorted(SOURCES))
def test_dat_gw5a_stuff_present_on_both_editions(source, monkeypatch):
    _use(source, monkeypatch)
    dat = dat_parser.Datfile(_dat(source))
    assert dat.part_type == 2
    assert hasattr(dat, 'gw5aStuff'), 'the T13 AttributeError is back'
    assert len(dat.gw5aStuff) == GW5A_STUFF_KEYS
    for key in CLOCK_KEYS:
        assert dat.gw5aStuff[key], key


def test_dat_gw5a_stuff_layout_follows_the_installed_version(monkeypatch):
    expected = {'1.9.11.03': ('v1_9_11minus', 0x7b4a4, 0x7b4a8),
                '1.9.12.03': ('v1_9_12plus', 0x7b4aa, 0x7b4ac)}
    for source in sorted(SOURCES):
        _use(source, monkeypatch)
        version = fse_parser.detect_ide_version(STANDARD_HOME)
        assert version == VERSION_OF[source], (source, version)
        dat = dat_parser.Datfile(_dat(source))
        shape_set, pt_off, rs_off = expected[version]
        assert (dat.dat_shape_set, dat._part_type_offset,
                dat._rs_table_offset) == (shape_set, pt_off, rs_off)


def test_dat_gw5a_stuff_identical_across_editions(monkeypatch):
    """1.9.11 and 1.9.12 ship the same GW5AST-138C device data.

    The two `.dat` files differ by exactly the four header bytes, so every
    table the parser extracts must come out equal. This is what proves the
    new offsets are right rather than merely non-crashing.
    """
    parsed = {}
    for source in sorted(SOURCES):
        _use(source, monkeypatch)
        parsed[source] = dat_parser.Datfile(_dat(source))
    edu = parsed['education-1.9.11-archive']
    std = parsed['standard-1.9.12-install']
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
    seen = 0
    for source in sorted(SOURCES):
        if not _dat(source, device).is_file():
            continue
        _use(source, monkeypatch)
        dat = dat_parser.Datfile(_dat(source, device))
        assert dat.part_type == 0, (source, device)
        assert not hasattr(dat, 'gw5aStuff'), (source, device)
        seen += 1
    if not seen:
        pytest.skip(f'no {device}.dat in either source')
