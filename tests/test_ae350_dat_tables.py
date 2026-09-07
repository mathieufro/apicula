"""The GW5AST-138C `.dat` carries the `AE350_SOC` port map, under `gw5aStuff`.

`McuIns`/`McuOuts` -- the GW1NS-4 `EMCU` triple tables -- are all-sentinel on
this device, and the legacy triple block is dead across the whole GW5 family.
The port map a GW5 hard block needs lives in `dat.gw5aStuff` instead, the same
place `fse_create_adc` reads the ADC's ports from (`chipdb.py`, `Adc25kIns`).

These tests pin the two facts a future `fse_create_ae350()` depends on: that the
tables are present, and that their slot counts bracket the primitive's measured
port-bit counts. What the tables *decode to* is pinned next door, in
`test_dat_packed_grid16.py`.
"""

import os
from pathlib import Path

import pytest

from apycula import dat_parser

DEVICE = "GW5AST-138C"
#: Measured from `prim_syns/gw5a/primitive.xml`, the golden `.vo` netlists, the
#: apicula wiki table and LiteX -- four sources, no discrepancies.
INPUT_BITS = 416
OUTPUT_BITS = 495


def datfile():
    home = os.getenv("GOWINHOME")
    if not home:
        pytest.skip("GOWINHOME is not set")
    path = Path(home) / "IDE" / "share" / "device" / DEVICE / f"{DEVICE}.dat"
    if not path.is_file():
        pytest.skip(f"{path} is absent")
    return dat_parser.Datfile(path)


def test_ae350_port_tables_are_present_in_gw5a_stuff():
    """The device data names the AE350's port map; it is not missing, only misread."""
    stuff = datfile().gw5aStuff
    assert "Ae350SocIns" in stuff
    assert "Ae350SocOuts" in stuff


def test_ae350_table_lengths_bracket_the_measured_port_bit_counts():
    """Each table has at least one slot per port bit of its direction.

    433 and 518 slots against 416 input and 495 output bits: the tables are
    sized for this primitive and for no other.
    """
    stuff = datfile().gw5aStuff
    assert len(stuff["Ae350SocIns"]) >= INPUT_BITS
    assert len(stuff["Ae350SocOuts"]) >= OUTPUT_BITS


def test_legacy_mcu_triples_are_empty_on_this_device():
    """The control for the two tests above: the legacy block really is dead.

    If this ever starts passing live triples, the GW5 port-map story has changed
    and `fse_create_ae350` must be re-derived rather than patched.
    """
    compat = datfile().compat_dict
    for table in ("McuIns", "McuOuts"):
        live = [t for t in compat[table] if not all(v < 0 for v in t)]
        assert live == [], f"{table} unexpectedly holds live triples"
