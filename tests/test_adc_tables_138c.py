"""Locating the GW5AST-138C's two ADC port tables (`P3.T28b`).

The tables are located, never addressed: their declared bases have drifted
between IDE releases, and a portmap read one slot out of phase is silently
wrong.  What fixes both the region and the phase is the block's own port
geometry -- 7 controls, 10 `FSCAL_VALUE` and 12 `OFFSET_VALUE` separated by
unbound slots on the input side, `ADCRDY` plus one cell's fourteen-wire
`ADCVALUE` run on the output side.

The device-file tests need a Gowin install; the shape tests do not.
"""
import os
import pathlib

import pytest

from apycula import dat_parser
from apycula.wirenames import wirenames_5ast138c

GOWINHOME = os.environ.get("GOWINHOME")
needs_ide = pytest.mark.skipif(not GOWINHOME, reason="no GOWINHOME")


@pytest.fixture(scope="module")
def blocks():
    path = (pathlib.Path(GOWINHOME) / "IDE/share/device/GW5AST-138C"
            / "GW5AST-138C.dat")
    return dat_parser.Datfile(path).locate_adc_tables(wirenames_5ast138c)


def test_port_slots_cover_every_fabric_port_once():
    """29 input bits and 17 output bits, each named exactly one slot."""
    ins = dat_parser.Datfile.ADC_IN_PORTS
    outs = dat_parser.Datfile.ADC_OUT_PORTS
    assert len(ins) == 29 and len(set(ins.values())) == 29
    assert len(outs) == 17 and len(set(outs.values())) == 17
    assert max(ins) < dat_parser.Datfile.ADC_IN_SLOTS
    assert max(outs) < dat_parser.Datfile.ADC_OUT_SLOTS


def test_input_fingerprint_rejects_a_window_off_by_one():
    """A region match that is one slot out must not pass as a table."""
    match = dat_parser.Datfile._adc_ins_match
    good = [None] * 40
    for slot in dat_parser.Datfile.ADC_IN_PORTS:
        good[slot] = (109, 181, "CLK0" if slot == 13 else "A0")
    assert match(good)
    assert not match([None] + good[:-1])


def test_output_fingerprint_needs_one_cell_for_the_value_run():
    """`ADCVALUE` is fourteen wires of one cell, or it is not this table."""
    match = dat_parser.Datfile._adc_outs_match
    wires = dat_parser.Datfile._ADC_VALUE_WIRES
    good = [(109, 169, "Q1"), None] + [(109, 169, w) for w in wires] + [
        (109, 180, "F0"), (109, 180, "F1")]
    assert match(good)
    split = list(good)
    split[5] = (109, 168, wires[3])
    assert not match(split)


@needs_ide
def test_exactly_two_blocks_are_located(blocks):
    """The fingerprint matches once per ADC and nowhere else on the die."""
    assert len(blocks) == 2


@needs_ide
def test_located_bases_keep_the_declared_table_spacing(blocks):
    """`Outs` follows `Ins` by the declared 0x28 records, for both blocks."""
    for block in blocks:
        assert block["outs_base"] - block["ins_base"] == 3 * 0x28


@needs_ide
def test_each_block_taps_a_clock_wire_for_its_clk_port(blocks):
    """The phase check the region match cannot make."""
    for block in blocks:
        assert block["inputs"]["CLK"][2].startswith("CLK")


@needs_ide
def test_the_two_blocks_sit_in_opposite_corners(blocks):
    """One ADC clocks off the last die row, the other off the first."""
    rows = sorted(block["inputs"]["CLK"][0] for block in blocks)
    assert rows[0] == 1 and rows[1] == 109


@needs_ide
def test_adcvalue_lands_on_the_cell_the_vendor_bitstream_drives(blocks):
    """Both value runs are one cell's `F0`-`F5`/`OF0`-`OF7`, as measured."""
    for block in blocks:
        value = [block["outputs"][f"ADCVALUE{i}"] for i in range(14)]
        assert len({(row, col) for row, col, _ in value}) == 1
        assert [wire for _, _, wire in value] == list(
            dat_parser.Datfile._ADC_VALUE_WIRES)
