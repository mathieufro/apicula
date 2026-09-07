"""`AE350_SOC`: the bel, its fabric port map and the bits the device data omits.

The port map is read from `dat.gw5aStuff['Ae350SocIns'/'Ae350SocOuts']` -- the
5-series table block, not the legacy `McuIns`/`McuOuts` triples, which are
all-sentinel on every GW5 device (`test_ae350_dat_tables.py` is the control for
that). Slot *i* of a direction's table is bit *i* of that direction, counting
`primitive.xml`'s 149 ports in declaration order with each bus LSB first.

Neither table is one direction: a tap's direction is its wire's, so the input
map is the fabric-driven run of `Ae350SocOuts` and the output map is what lies
either side of that run with `Ae350SocIns` filling it
(`tests/test_ae350_tap_directions.py`). Both tables are read whole: every live
record is bound, and the only bits left unmapped are the ones the device data
itself omits. They are placeholders, not guesses -- see
`test_ae350_unmapped_bits_get_unroutable_placeholder_wires`.
"""

import os
from pathlib import Path

import pytest

from apycula import chipdb
from apycula import dat_parser
from apycula import wirenames as wnames

DEVICE = 'GW5AST-138C'

#: Measured in `evidence/ae350/wire-map-138c.md` §7: the bits carrying a live
#: record, per direction. Every input bit has one; the 27 that do not are all
#: outputs, and every one of them is a slot the device data omits.
BOUND_INPUT_BITS = 416
BOUND_OUTPUT_BITS = 468
#: `evidence/ae350/port-inventory.json`: 149 ports, 911 bits.
INPUT_BITS = 416
OUTPUT_BITS = 495

#: The top PLL sites `CORE_CLK` can be driven from, measured in
#: `evidence/ae350/core-clock.md`: the dedicated hop costs 0.000 ns from either,
#: so the model carries one fuseless edge per site rather than one exclusive
#: edge from `PLL_R[0]`.
PLL_SITES = {'PLL_L[0]': (27, 1), 'PLL_R[0]': (27, 177)}

#: `ttyp` 224 sits in rows 10, 28 and 46, `ttyp` 228 in rows 64, 82 and 100,
#: both spanning columns 145-180 of the 109x182 die.
CONFIG_ROWS = (10, 28, 46, 64, 82, 100)
CONFIG_COLS = range(145, 181)


@pytest.fixture(autouse=True)
def _wire_table():
    """Every test here resolves wire indices through the 138C table."""
    chipdb.wire2node.clear()
    wnames.select_wires(DEVICE)


def datfile():
    home = os.getenv('GOWINHOME')
    if not home:
        pytest.skip('GOWINHOME is not set')
    path = Path(home) / 'IDE' / 'share' / 'device' / DEVICE / f'{DEVICE}.dat'
    if not path.is_file():
        pytest.skip(f'{path} is absent')
    return dat_parser.Datfile(path)


def bare_device():
    """A device with the 138C's grid shape and nothing built into it yet.

    The two top PLL sites are the one exception: `CORE_CLK` does not come off
    the fabric, so the builder wires it from whichever of them the device data
    offers, and a fixture without them would exercise a device the 138C is not
    (`evidence/ae350/core-clock.md`). They carry only what
    `chipdb._ae350_pll_sites` reads.
    """
    grid = [[0] * 182 for _ in range(109)]
    for row in CONFIG_ROWS:
        for col in CONFIG_COLS:
            grid[row][col] = 224 if row < 64 else 228
    dev = chipdb.Device(grid=grid, tiles={0: chipdb.Tile(1, 1, 0)})
    for macro, (row, col) in PLL_SITES.items():
        dev.extra_func.setdefault((row, col), {})['pll'] = {
            'macro': macro, 'outputs': {'CLKOUT1': 'MPLLCLKOUT1'}}
    return dev


def built_device():
    dev = bare_device()
    chipdb.fse_create_ae350(dev, DEVICE, datfile())
    return dev


def ae350(dev):
    return dev.extra_func[chipdb._AE350_SOC_ANCHOR]['ae350']


class _ExplodingDev:
    """Any access at all is a failure: other devices must be left untouched."""

    def __getattr__(self, name):
        raise AssertionError(f'the AE350 builder touched dev.{name}')


def test_fse_create_ae350_is_noop_for_gw5a_25a():
    """The block exists on one device; `S3` forbids disturbing the others."""
    for device in ('GW5A-25A', 'GW5AT-60B', 'GW1NS-4', 'GW1N-9C'):
        chipdb.fse_create_ae350(_ExplodingDev(), device, None)


def test_fse_create_ae350_registers_extra_func_for_138c():
    """Exactly one `ae350` entry, in the row-0 tile at the band's first column."""
    dev = built_device()
    entries = [loc for loc, funcs in dev.extra_func.items() if 'ae350' in funcs]
    assert entries == [(0, 159)]


def test_from_fse_calls_ae350_exactly_once():
    """One registration, on its own line, beside the EMCU's."""
    source = Path(chipdb.__file__).read_text()
    body = source.split('\ndef from_fse(')[1]
    assert body.count('fse_create_ae350(') == 1


def test_ae350_portmap_covers_every_port_bit_of_the_primitive():
    """149 ports, 911 bits: every bit is either bound or explicitly unmapped."""
    block = ae350(built_device())
    assert len(block['ins']) == INPUT_BITS
    assert len(block['outs']) == OUTPUT_BITS
    bound = {port for port in block['ins'] if port not in block['unmapped']}
    assert len(bound) == BOUND_INPUT_BITS
    bound = {port for port in block['outs'] if port not in block['unmapped']}
    assert len(bound) == BOUND_OUTPUT_BITS


def test_ae350_clock_ports_are_tile_clk():
    """The fabric clock inputs enter the clock network, not the logic network.

    `CORE_CLK` is not one of them and is checked separately below: it takes a
    dedicated PLL hop and never a fabric line.
    """
    dev = built_device()
    block = ae350(dev)
    types = {wire_type for wire_type, _wires in dev.nodes.values()}
    assert 'TILE_CLK' in types
    for port in chipdb._AE350_SOC_CLOCK_PORTS - {chipdb._AE350_CORE_CLK_PORT}:
        wire = block['ins'][port]
        assert not wire.startswith(chipdb._AE350_UNMAPPED_PREFIX)
        node = dev.nodes[chipdb.wire2node[(0, 159, wire)]]
        assert node[0] == 'TILE_CLK', f'{port} entered the fabric as {node[0]}'


def test_core_clk_takes_a_dedicated_pll_hop_from_every_site():
    """`CORE_CLK` is bound to its own wire, one fuseless pip per PLL site.

    The port is an input like any other -- it must not be left a placeholder --
    but the wire it binds to belongs to no fabric line, so the only way into it
    is a dedicated hop from a PLL the device data names.
    """
    dev = built_device()
    block = ae350(dev)
    core_clk = block['core_clk']
    assert core_clk['routable'] is False
    assert block['ins'][chipdb._AE350_CORE_CLK_PORT] == core_clk['wire']
    assert sorted(core_clk['sources']) == sorted(PLL_SITES)
    pips = dev[0, 159].pips[core_clk['wire']]
    assert set(pips) == {s['alias'] for s in core_clk['sources'].values()}
    assert all(bits == set() for bits in pips.values())


def test_ae350_no_port_maps_to_negative_coordinate():
    """`0xffff`, not `-1`, is the sentinel of these unsigned tables.

    A record read as a coordinate of -1 would mean the reader lost its signedness
    somewhere; a record read as 65535 and taken for a coordinate would place a
    port off the die. Neither may reach `make_port`.
    """
    dat = datfile()
    for table in ('Ae350SocIns', 'Ae350SocOuts'):
        rows = dat.gw5aStuff[table]
        assert rows, table
        assert not [r for r in rows if any(v < 0 for v in r)]
    dev = built_device()
    for _wire_type, wires in dev.nodes.values():
        for row, col, _wire in wires:
            assert 0 <= row < 109 and 0 <= col < 182


def test_ae350_unmapped_bits_get_unroutable_placeholder_wires():
    """A bit the device data does not map is named, not silently dropped.

    The placeholder wire name is in no wire table, so nextpnr cannot alias it to
    a real wire: a design that drives such a port fails naming the port instead
    of being routed somewhere plausible and wrong.
    """
    block = ae350(built_device())
    assert block['unmapped']
    for port, reason in block['unmapped'].items():
        wire = (block['ins'] if port in block['ins'] else block['outs'])[port]
        assert wire == f'{chipdb._AE350_UNMAPPED_PREFIX}{port}'
        assert wire not in wnames.wirenumbers
        assert reason in {'unbound', 'off-grid', 'no-record',
                          'unknown-wire-index'}
    assert not [port for port in block['unmapped'] if port in block['ins']]
    unmapped_outs = [port for port in block['unmapped'] if port in block['outs']]
    assert len(unmapped_outs) == OUTPUT_BITS - BOUND_OUTPUT_BITS


def test_ae350_config_tiles_are_marked_as_the_blocks_own():
    """The interface bands carry the block's configuration, and no ports."""
    dev = built_device()
    block = ae350(dev)
    marked = {loc for loc, funcs in dev.extra_func.items()
              if 'ae350_config' in funcs}
    assert marked == {(row, col)
                      for row in CONFIG_ROWS for col in CONFIG_COLS}
    assert sorted(block['config_tiles']) == sorted(marked)
    assert block['config_ttyps'] == [224, 228]
    assert chipdb._AE350_SOC_ANCHOR not in marked
