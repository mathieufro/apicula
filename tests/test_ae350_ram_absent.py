"""`P2.T25` -- the `AE350_RAM` primitive is not a resource of the GW5AST-138C.

MEASURED, twice, by the vendor's own synthesiser on this device
(`$OTC/evidence/ae350-ram/summary.md`):

    ERROR (RP0008) : There is no AE350_RAM resource in current device,
    please change device

once with an `AE350_SOC` beside it and once alone, so the refusal is the
primitive's and not a contest over the one `AE350_SOC` site.  The control is
`P2.T23`: the same tool, the same device, the same Tcl header builds an
`AE350_SOC` design to a bitstream.

These tests pin the consequence for the database: a bel for a resource the
vendor says the device does not have would let the open flow accept a netlist
the vendor refuses, which is the parity defect this phase exists to prevent.
"""
import os
from pathlib import Path

import pytest

from apycula import chipdb
from apycula import dat_parser
from apycula import wirenames as wnames

DEVICE = 'GW5AST-138C'

#: The vendor error, byte for byte, as the row records it.
VENDOR_REFUSAL = ("ERROR (RP0008) : There is no AE350_RAM resource in "
                  "current device, please change device")


@pytest.fixture(autouse=True)
def _wire_table():
    chipdb.wire2node.clear()
    wnames.select_wires(DEVICE)
    yield
    chipdb.wire2node.clear()


def _datfile():
    home = os.getenv('GOWINHOME')
    if not home:
        pytest.skip('GOWINHOME is not set')
    path = Path(home) / 'IDE' / 'share' / 'device' / DEVICE / f'{DEVICE}.dat'
    if not path.is_file():
        pytest.skip(f'{path} is absent')
    return dat_parser.Datfile(path)


def _built_device():
    grid = [[0] * 182 for _ in range(109)]
    for row in (10, 28, 46, 64, 82, 100):
        for col in range(145, 181):
            grid[row][col] = 224 if row < 64 else 228
    dev = chipdb.Device(grid=grid, tiles={0: chipdb.Tile(1, 1, 0)})
    chipdb.fse_create_ae350(dev, DEVICE, _datfile())
    return dev


def test_the_138c_database_declares_no_ae350_ram_bel():
    dev = _built_device()
    named = {name for funcs in dev.extra_func.values() for name in funcs}
    assert 'ae350' in named                     # the control: the SoC is there
    assert not [name for name in named if 'ram' in name.lower()]


def test_the_138c_device_data_carries_no_ae350_ram_port_table():
    """`gw5aStuff` maps the SoC's 149 ports and names no RAM table at all."""
    stuff = _datfile().gw5aStuff
    assert 'Ae350SocIns' in stuff and 'Ae350SocOuts' in stuff
    assert [key for key in stuff if 'ram' in key.lower()] == []
