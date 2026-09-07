"""The DCS clock-input side of the GW5AST-138C clock plane -- `P1.F2`.

`P1.T31` closed the DCS *output* side and left the input side a named gap:
the DCS input multiplexers `P26A-D` / `P36A-D` are fed only by the bridge
cells' bare `*MDCLK*` / `*BDCLK*` / `PCLK*` wires, and nothing in the model
drove any of them, because `get_logic_clock_ins` returned a single hardcoded
gate for this die.  Both halves now come from the `.dat` CMux tables, and the
bare gate wire of the central multiplexer is aliased onto the half the vendor
was measured to use.

Every fact asserted here is MEASURED -- five vendor bitstreams, recorded in
`$OTC/evidence/dcs/input-side-138c.md`.
"""
import os
from pathlib import Path

import pytest

from apycula import chipdb, wirenames as wnames


#: MEASURED (batch `p1f2-dcsin`, runs a/b/c/d and the `P1.T31` baseline): the
#: bare gate a DCS input multiplexer selects, and the coordinate whose `CLK1`
#: the vendor drives to feed it.  `{cell: {gate: gate cell}}`.
DCS_INPUT_GATES = {
    (54, 93): {'BLMDCLK1': (108, 90)},
    (54, 88): {'TLMDCLK1': (81, 90), 'TRMDCLK1': (81, 91)},
}

_BUILT = {}


def _build(device, gowinhome):
    if device in _BUILT:
        return _BUILT[device]
    from apycula import fse_parser, dat_parser
    from apycula.chipdb_builder import DEVICE_PARAMS
    os.environ.setdefault('GOWINHOME', gowinhome)
    vendor = DEVICE_PARAMS[device]['device']
    base = f'{gowinhome}/IDE/share/device/{vendor}/{vendor}'
    if not os.path.isfile(base + '.fse'):
        pytest.skip(f'{base}.fse absent')
    with open(base + '.fse', 'rb') as fh:
        fse = fse_parser.read_fse(fh, device)
    dat = dat_parser.Datfile(Path(base + '.dat'))
    if vendor in {'GW5AT-60B', 'GW5AST-138C'}:
        dat.patch_grid_bram_138()
    chipdb.wire2node.clear()
    dev = chipdb.from_fse(device, fse, dat)
    _BUILT[device] = dev
    return dev


def _dat(device, gowinhome):
    from apycula import dat_parser
    from apycula.chipdb_builder import DEVICE_PARAMS
    vendor = DEVICE_PARAMS[device]['device']
    base = f'{gowinhome}/IDE/share/device/{vendor}/{vendor}'
    if not os.path.isfile(base + '.dat'):
        pytest.skip(f'{base}.dat absent')
    return dat_parser.Datfile(Path(base + '.dat'))


def test_logic_clock_gates_of_both_halves_come_from_the_dat(gowinhome):
    """Both halves are read from the CMux tables, not named in the source."""
    wnames.select_wires('GW5AST-138C')
    dat = _dat('GW5AST-138C', gowinhome)
    halves = chipdb.get_logic_clock_ins('GW5AST-138C', dat)

    assert len(halves) == 2
    gate_ids = set(range(wnames.clknumbers['TRBDCLK0'],
                         wnames.clknumbers['TRMDCLK1'] + 1))
    for half, table in enumerate(('CMuxTopIns', 'CMuxBotIns')):
        assert halves[half] == chipdb.gw5_logic_clock_gates(dat, table)
        assert {entry[0] for entry in halves[half]} == gate_ids
        assert len(halves[half]) == 24
    # the two halves are disjoint sets of cells, one per half of the die
    top = {(r, c) for _, r, c, _ in halves[0]}
    bot = {(r, c) for _, r, c, _ in halves[1]}
    assert not top & bot
    assert max(r for r, _ in top) < min(r for r, _ in bot)


def test_dcs_input_multiplexer_sources_have_a_driver(gowinhome):
    """Every gate a DCS input multiplexer selects reaches the fabric.

    The bare wire the central multiplexer names and the fabric `CLK1` the
    vendor drives to feed it must be the same Himbaechel node; that node is
    what the router walks back through to reach the clock source.
    """
    dev = _build('GW5AST-138C', gowinhome)

    for (row, col), gates in DCS_INPUT_GATES.items():
        tile = dev[row, col]
        dcs_inputs = {dest: srcs for dest, srcs in tile.clock_pips.items()
                      if dest[0] == 'P' and dest[1:3].isdigit()}
        assert dcs_inputs, f'({row}, {col}) hosts no DCS input multiplexer'
        for gate, gate_cell in gates.items():
            assert any(gate in srcs for srcs in dcs_inputs.values()), (
                f'{gate} is not a DCS input source at ({row}, {col})')
            node = chipdb.wire2node.get((row, col, gate))
            assert node is not None, f'{gate} at ({row}, {col}) is in no node'
            members = dev.nodes[node][1]
            assert (gate_cell[0], gate_cell[1], 'CLK1') in members, (
                f'{node} does not reach the measured gate cell {gate_cell}')


def test_used_dcs_is_required_to_drive_the_clock_plane():
    """`c1` asks a used DCS for its output node, not for a cell.

    `DCS_MODE` is a `longfuses` attribute and `gowin_unpack` decodes no
    `longfuses` table on any device, so demanding a `DCS` cell back makes
    `c1` assert something the format cannot carry.  What it can carry -- and
    what a route through the mux is worth asserting -- is the DCS output
    driving the clock plane.
    """
    from types import SimpleNamespace

    from fuzz.gw5ast138c.harness import equiv

    assert equiv.dcs_clkout_node(14) == 'CBRIDGEOUT_TOP6'
    assert equiv.dcs_clkout_node(22) == 'CBRIDGEOUT_BOTTOM6'
    assert equiv.dcs_clkout_node(3) is None

    cell = {'name': '$PACKER_DCS_SPINE14', 'bel': 'DCS0', 'site': [93, 54],
            'type': 'DCS'}
    routed = SimpleNamespace(raw_pips={
        (81, 87): {'R82C88_SPINE4': 'R82C88_CBRIDGEOUT_TOP6'}})
    assert equiv.dcs_recovered_via_clkout(cell, routed) is None

    unrouted = SimpleNamespace(raw_pips={
        (81, 87): {'R82C88_SPINE4': 'R82C88_CBRIDGEOUT_TOP7'}})
    why = equiv.dcs_recovered_via_clkout(cell, unrouted)
    assert why and 'CBRIDGEOUT_TOP6' in why


def test_sel4_point_drives_the_four_clkin_from_four_clocks():
    """The `sel4` sweep point is the one where `CLKSEL` really selects."""
    from fuzz.gw5ast138c.shapes import clocking_dcs

    spec = clocking_dcs.SPEC
    assert spec.sweep_values[-1] == clocking_dcs.SEL_POINT

    sel4 = clocking_dcs.e1_rtl(spec, clocking_dcs.SEL_POINT)
    for port, net in (('CLKIN0', 'clk'), ('CLKIN1', 'd1'),
                      ('CLKIN2', 'd2'), ('CLKIN3', 'd3')):
        assert f'.{port}   ({net})' in sel4, port
    assert 'always @(posedge d2)  d3 <= ~d3;' in sel4

    # the quadrant points are untouched: one clock on all four inputs
    for point in ('q1', 'q2'):
        rtl = clocking_dcs.e1_rtl(spec, point)
        assert rtl.count('(clk),') == 4, point
        assert 'd1' not in rtl, point
