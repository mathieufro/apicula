"""`fse_create_ae350()` against the measured input table (`P2.T08b`).

`P2.T07` built the port map on a split-band reading of the block: inputs to the
left of the band, outputs to the right. The relocated `Ae350SocIns` table
refutes it -- the block reads and drives the *same* columns over disjoint wire
classes -- so the builder must bind what the tables say and stop filtering bits
out by column. Which direction a record belongs to is then the wire's, not the
table's: the two tables interleave one map each way
(`tests/test_ae350_tap_directions.py`).
"""

import re
from collections import Counter

import pytest

from apycula import chipdb

from apycula import wirenames as wnames

from tests.test_ae350 import (DEVICE, INPUT_BITS, OUTPUT_BITS, ae350, built_device,
                              datfile, _wire_table)  # noqa: F401  (autouse fixture)

#: `evidence/ae350/wire-map-138c.md` §7: three of the sentinel slots inside the
#: relocated `Ae350SocIns` run, and so the *output* bits they leave with no tap.
#: They were read as input bits while the tables were taken one direction each.
RESISTING_BITS = ('DDR_HWDATA10', 'GPIO_OE11', 'GPIO_OUT12')

#: `Ae350SocOuts` names three columns far to the left of the band -- the clock
#: spine. They are real taps and must not be filtered out.
SPINE_COLS = (22, 23, 87)


def test_ae350_anchor_is_the_first_column_of_the_measured_band():
    """The bel follows the measurement, not the refuted split-band reading."""
    assert chipdb._AE350_SOC_ANCHOR == (0, chipdb._AE350_SOC_BAND_COLS[0])
    assert chipdb._AE350_SOC_BAND_COLS[0] == 159
    assert chipdb._AE350_SOC_BAND_COLS[-1] == 180


def _live(record):
    return record is not None and chipdb._AE350_DAT_ABSENT not in record[:3]


def _reads_the_block(record):
    """True when a live record names a wire only the block can drive."""
    return bool(re.fullmatch(r'(?:Q|F|OF)\d+', wnames.wirenames[record[2]]))


def test_ae350_binds_every_live_record_of_both_tables():
    """A live record is a tap; only a slot the data omits leaves a bit unmapped.

    The two maps are counted here the way the wire classes define them, not the
    way the table names suggest: the input map is the run of `Ae350SocOuts`
    records the fabric drives, the output map is the rest of `Ae350SocOuts`
    with `Ae350SocIns` filling the run.
    """
    dat = datfile()
    outs_table = dat.gw5aStuff['Ae350SocOuts']
    ins_table = dat.gw5aStuff['Ae350SocIns']
    block = ae350(built_device())

    driven = [slot for slot, record in enumerate(outs_table)
              if _live(record) and not _reads_the_block(record)]
    assert len(driven) == INPUT_BITS
    bound = [port for port in block['ins'] if port not in block['unmapped']]
    assert len(bound) == INPUT_BITS

    first, last = driven[0], driven[-1]
    records = []
    for bit in range(OUTPUT_BITS):
        if first <= bit <= last:
            offset = bit - first
            records.append(ins_table[offset] if offset < len(ins_table) else None)
        else:
            records.append(outs_table[bit])
    bound = [port for port in block['outs'] if port not in block['unmapped']]
    assert len(bound) == len([r for r in records if _live(r)])


def test_ae350_binds_the_taps_outside_the_band():
    """Three taps sit far to the left of the band; a band filter would drop them.

    Two are output taps of `ROM_HADDR` and one is the clock-spine alternative
    for `CORE_CLK`, so they are not one direction either -- what they have in
    common is only that a column filter would lose them.
    """
    dat = datfile()
    dev = built_device()
    spine = [record for record in dat.gw5aStuff['Ae350SocOuts']
             if _live(record) and record[1] - 1 in SPINE_COLS]
    assert len(spine) == len(SPINE_COLS)
    taps = {tap for _wire_type, wires in dev.nodes.values() for tap in wires}
    for record in spine:
        assert (record[0] - 1, record[1] - 1,
                wnames.wirenames[record[2]]) in taps


def test_ae350_placeholders_are_exactly_the_slots_the_data_omits():
    """No bit is unmapped for any reason but the device data omitting it.

    Two ways of omitting one: a sentinel record, and the single bit past the
    end of `Ae350SocIns` inside the run it fills. Neither an off-grid record
    nor an unknown wire index may appear -- those would mean the tables were
    misread rather than incomplete.
    """
    block = ae350(built_device())
    reasons = Counter(block['unmapped'].values())
    assert set(reasons) == {'unbound', 'no-record'}
    assert reasons['no-record'] == 1


def test_ae350_the_three_resisting_bits_stay_named_placeholders():
    """The bits `P2.T08b` could not close are named, not guessed at.

    They are output bits: the sentinel slots are in the run `Ae350SocIns`
    fills, and that run is the middle of the output map.
    """
    block = ae350(built_device())
    for port in RESISTING_BITS:
        assert block['unmapped'][port] == 'unbound'
        assert block['outs'][port] == f'{chipdb._AE350_UNMAPPED_PREFIX}{port}'
