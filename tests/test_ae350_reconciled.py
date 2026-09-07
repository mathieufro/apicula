"""`fse_create_ae350()` against the measured input table (`P2.T08b`).

`P2.T07` built the port map on a split-band reading of the block: inputs to the
left of the band, outputs to the right. The relocated `Ae350SocIns` table
refutes it -- the block reads and drives the *same* columns over disjoint wire
classes -- so the builder must bind what the tables say and stop filtering bits
out by column.
"""

import pytest

from apycula import chipdb

from tests.test_ae350 import (DEVICE, INPUT_BITS, OUTPUT_BITS, ae350, built_device,
                              datfile, _wire_table)  # noqa: F401  (autouse fixture)

#: `evidence/ae350/wire-map-138c.md` §6: the three bits whose slot is a sentinel
#: inside the relocated table and which therefore still carry no tap.
RESISTING_INPUT_BITS = ('DDR_HRDATA12', 'GPIO_IN25', 'EMA1')

#: `Ae350SocOuts` names three columns far to the left of the band -- the clock
#: spine. They are real taps and must not be filtered out.
SPINE_OUTPUT_COLS = (22, 23, 87)


def test_ae350_anchor_is_the_first_column_of_the_measured_band():
    """The bel follows the measurement, not the refuted split-band reading."""
    assert chipdb._AE350_SOC_ANCHOR == (0, chipdb._AE350_SOC_BAND_COLS[0])
    assert chipdb._AE350_SOC_BAND_COLS[0] == 159
    assert chipdb._AE350_SOC_BAND_COLS[-1] == 180


def test_ae350_binds_every_live_record_of_both_tables():
    """A live record is a tap; only a sentinel slot leaves a bit unmapped."""
    dat = datfile()
    block = ae350(built_device())
    for table_name, bits, pins in (
            ('Ae350SocIns', INPUT_BITS, block['ins']),
            ('Ae350SocOuts', OUTPUT_BITS, block['outs'])):
        table = dat.gw5aStuff[table_name]
        live = [bit for bit in range(bits)
                if chipdb._AE350_DAT_ABSENT not in table[bit][:3]]
        bound = [port for port in pins if port not in block['unmapped']]
        assert len(bound) == len(live), table_name


def test_ae350_binds_the_clock_spine_output_taps_outside_the_band():
    """Three output bits tap the clock spine; a band filter would drop them."""
    dat = datfile()
    table = dat.gw5aStuff['Ae350SocOuts']
    ports = list(chipdb._ae350_port_bits(chipdb._AE350_SOC_OUTPUTS))
    block = ae350(built_device())
    spine = [ports[bit] for bit in range(OUTPUT_BITS)
             if table[bit][1] - 1 in SPINE_OUTPUT_COLS]
    assert len(spine) == len(SPINE_OUTPUT_COLS)
    for port in spine:
        assert port not in block['unmapped']


def test_ae350_placeholders_are_exactly_the_sentinel_slots():
    """No bit is unmapped for any reason but the device data omitting it."""
    block = ae350(built_device())
    assert set(block['unmapped'].values()) == {'unbound'}


def test_ae350_the_three_resisting_input_bits_stay_named_placeholders():
    """The bits `P2.T08b` could not close are named, not guessed at."""
    block = ae350(built_device())
    for port in RESISTING_INPUT_BITS:
        assert block['unmapped'][port] == 'unbound'
        assert block['ins'][port] == f'{chipdb._AE350_UNMAPPED_PREFIX}{port}'
