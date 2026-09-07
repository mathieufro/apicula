"""`Ae350SocIns` names one fabric tap per fabric-driven `AE350_SOC` input bit.

The AE350's input table is not addressed by a fixed base -- the historical
0x86a0 points at another block's table on a Gowin IDE 1.9.12.03 GW5AST-138C --
so `Datfile.read_ae350_soc_ins` locates it from the block's own geometry. These
tests pin the geometry, not the base: whichever release the `.dat` comes from,
the table it finds must be a complete, collision-free set of tap wires inside
the band the block's output table drives.

The counts come from the measured port inventory (416 input bits, four
independent ways) and from the vendor's own fully connected AE350 design, whose
post-PnR netlist keeps all 410 fabric-driven input bits.
"""

import os
import re
from pathlib import Path

import pytest

from apycula import dat_parser
from apycula.wirenames import wirenames_5a25a

DEVICE = "GW5AST-138C"
#: Input bits the primitive declares.
INPUT_BITS = 416
#: Input bits the vendor's fully connected design drives from fabric flops;
#: the six clock inputs share one net, so the table may name fewer taps.
FABRIC_DRIVEN_INPUT_BITS = 410
#: Live taps the historical base reaches before it runs into the neighbouring
#: block's table -- the number this discovery had to beat.
HISTORICAL_BASE_TAPS = 256

SENTINEL = 0xffff


def gw5a_stuff():
    home = os.getenv("GOWINHOME")
    if not home:
        pytest.skip("GOWINHOME is not set")
    path = Path(home) / "IDE" / "share" / "device" / DEVICE / f"{DEVICE}.dat"
    if not path.is_file():
        pytest.skip(f"{path} is absent")
    return dat_parser.Datfile(path).gw5aStuff


def live(table):
    return [rec for rec in table if rec[0] != SENTINEL]


def test_every_fabric_driven_input_bit_has_a_tap():
    """The table names enough taps for the design the vendor itself routes."""
    taps = live(gw5a_stuff()["Ae350SocIns"])
    assert FABRIC_DRIVEN_INPUT_BITS <= len(taps) <= INPUT_BITS
    assert len(taps) > HISTORICAL_BASE_TAPS


def test_every_input_record_names_a_wire_a_fabric_tile_drives():
    """A block input reads the tile's output; that is what makes it an input."""
    for row, _col, wire in live(gw5a_stuff()["Ae350SocIns"]):
        assert row == 1, "the AE350 taps die row 0 only"
        assert re.fullmatch(r"(?:F|Q|OF)\d", wirenames_5a25a[wire])


def test_input_taps_lie_in_the_band_the_output_table_drives():
    """Inputs and outputs share the block's column band, not halves of it."""
    stuff = gw5a_stuff()
    driven = sorted({col for _row, col, _wire in live(stuff["Ae350SocOuts"])})
    taps = live(stuff["Ae350SocIns"])
    assert min(driven) <= min(col for _row, col, _wire in taps)
    assert max(col for _row, col, _wire in taps) <= max(driven)


def test_no_fabric_wire_is_tapped_twice():
    """Two input bits sharing a tap would be two ports on one wire."""
    taps = live(gw5a_stuff()["Ae350SocIns"])
    assert len({(col, wire) for _row, col, wire in taps}) == len(taps)


def test_the_table_starts_at_a_column_boundary():
    """The phase anchor: the table walks the band one whole column at a time.

    Without it the window slides by a few slots and rotates every bit's wire.
    """
    taps = live(gw5a_stuff()["Ae350SocIns"])
    first_column = [wire for _row, col, wire in taps if col == taps[0][1]]
    assert wirenames_5a25a[first_column[0]] == "Q0"
    assert len(first_column) == 24, "a whole fabric column of taps"
