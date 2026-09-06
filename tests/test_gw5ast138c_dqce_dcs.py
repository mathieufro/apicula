"""Phase 1 (clocking) DQCE and DCS unit tests for GW5AST-138C -- `P1.T29`/`P1.T31`.

Owned by `blueprints/P1-clocking.md`.  Every fact asserted here is the MEASURED
one recorded in `$OTC/evidence/dqce/quadrants-138c.md` and
`$OTC/evidence/dcs/ports-138c.md`, not the blueprint's assumption.  The
blueprint was refuted twice:

* the 138C did not build "two of four quadrants" -- it built **none**.
  `fse_create_clocks` hands `GW5AST-138C` to `fse_create_5a138_clocks` and
  returns before ever reaching the DQCE and DCS builders, so the shipped
  chipdb carried zero `extra_func['dqce']` and zero `extra_func['dcs']`
  entries;
* the die does not have four quadrants to fill.  Only two of its six
  clock-bridge cells carry a spine multiplexer at all, and they are quadrants
  1 and 2 of the pre-5A numbering -- the top and bottom halves of this die's
  1x4-per-half clock plane.
"""
import os
from pathlib import Path

import pytest

from apycula import chipdb


#: MEASURED (`P1.T29`, batch `p1t29-dce`, three vendor compiles): twelve DQCE,
#: six in each of the two clock-bridge cells that carry a spine multiplexer.
#: `{(row, col): (quadrant, [spine, ...])}`.
DQCE_138C = {
    (54, 93): (1, [f'SPINE{8 + j}' for j in range(6)]),
    (54, 88): (2, [f'SPINE{16 + j}' for j in range(6)]),
}

#: The enable wire of slot `j`, unchanged from the pre-5A model.
DQCE_CE_WIRES = ['A0', 'B0', 'C0', 'D0', 'A1', 'B1']

#: MEASURED (`P1.T31`, batch `p1t31-dcs`, two vendor compiles): four DCS, two
#: in each of the same two cells.  `{(row, col): {dcs_idx: (clkout, prefix)}}`.
DCS_138C = {
    (54, 93): {0: ('SPINE14', 'P26'), 1: ('SPINE15', 'P27')},
    (54, 88): {0: ('SPINE22', 'P36'), 1: ('SPINE23', 'P37')},
}

#: `gw5_dcs_inputs` exactly as it stood at the base commit -- the 25A table is
#: frozen; the 138C gets its own entry, never a mutation of this one.
GW5_DCS_INPUTS_BASE = {
    (0, 0): [(48, 'D7'), (44, 'D4'), (45, 'D7'), (46, 'D7'), (47, 'D7')],
    (0, 1): [(47, 'D2'), (47, 'D3'), (47, 'C3'), (47, 'B3'), (47, 'A3')],
    (1, 0): [(48, 'D6'), (44, 'C3'), (45, 'D6'), (46, 'D6'), (47, 'D6')],
    (1, 1): [(47, 'C1'), (47, 'C2'), (47, 'B2'), (47, 'A2'), (47, 'D1')],
    (2, 0): [(48, 'C6'), (44, 'A1'), (45, 'C6'), (46, 'C6'), (47, 'C6')],
    (2, 1): [(44, 'A5'), (47, 'A0'), (44, 'D5'), (44, 'C5'), (44, 'B5')],
    (3, 0): [(48, 'C7'), (44, 'B2'), (45, 'C7'), (46, 'C7'), (47, 'C7')],
    (3, 1): [(47, 'B0'), (47, 'B1'), (47, 'A1'), (47, 'D0'), (47, 'C0')],
}

#: The four-quadrant pre-5A devices, and the two-quadrant rule for the rest.
_PRE5A_FOUR_QUADRANT = {'GW1N-9', 'GW1N-9C', 'GW2A-18', 'GW2A-18C'}

OTC = os.environ.get(
    'OTC',
    '/Users/alex/fine-line/.atelier/worktrees/'
    '2026-09-03-open-toolchain-gw5ast-7e84/open-toolchain')

_BUILT = {}


def _build(device, gowinhome):
    """`chipdb.from_fse` for `device`, cached for the whole test session.

    Same recipe as `tests/test_gw5ast138c_dhce.py::_build`; kept local so the
    two task files stay independently runnable, per the `tests/`
    file-ownership rule.
    """
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


def _sites(dev, func):
    return {rc: extra[func] for rc, extra in dev.extra_func.items()
            if func in extra}


# ---------------------------------------------------------------- P1.T29

@pytest.mark.heavy  # parses a real multi-MB vendor .fse via _build()
def test_dqce_quadrants_138c_are_the_two_measured_ones(gowinhome):
    dev = _build('GW5AST-138C', gowinhome)
    sites = _sites(dev, 'dqce')

    assert set(sites) == set(DQCE_138C), (
        'the 138C hosts DQCE in exactly the two clock-bridge cells that carry '
        'a spine multiplexer')
    assert sum(len(v) for v in sites.values()) == 12

    for rc, block in sites.items():
        _quadrant, spines = DQCE_138C[rc]
        assert sorted(block) == list(range(6)), f'{rc} has {len(block)} slots'
        assert [block[j]['clkin'] for j in range(6)] == spines, rc
        assert [block[j]['ce'] for j in range(6)] == DQCE_CE_WIRES, rc
        # every wire the model names is a real wire of that cell
        tile = dev[rc[0], rc[1]]
        cell_wires = set(tile.clock_pips) | {
            w for srcs in tile.pips.values() for w in srcs} | set(tile.pips)
        for j in range(6):
            assert block[j]['clkin'] in tile.clock_pips, (rc, j)
            assert block[j]['ce'] in cell_wires, (rc, j)


def test_dqce_quadrant_table_is_the_pre5a_one_for_pre5a_devices():
    """The per-device lookup reproduces the rule it replaced, exactly."""
    for device in ('GW1N-1', 'GW1NZ-1', 'GW1NS-2', 'GW1N-4', 'GW1NS-4',
                   'GW1N-9', 'GW1N-9C', 'GW2A-18', 'GW2A-18C'):
        expected = {q: ttyp for q, ttyp in enumerate([85, 80, 81, 84])
                    if q >= 2 or device in _PRE5A_FOUR_QUADRANT}
        assert chipdb.dqce_quadrant_types(device) == expected, device
    assert chipdb.dqce_quadrant_types('GW5AST-138C') == {1: 85, 2: 80}


# ---------------------------------------------------------------- P1.T31

@pytest.mark.heavy
def test_dcs_quadrants_138c_are_the_two_measured_ones(gowinhome):
    dev = _build('GW5AST-138C', gowinhome)
    sites = _sites(dev, 'dcs')

    assert set(sites) == set(DCS_138C)
    assert sum(len(v) for v in sites.values()) == 4

    clkouts = set()
    for rc, block in sites.items():
        tile = dev[rc[0], rc[1]]
        for idx, (clkout, prefix) in DCS_138C[rc].items():
            dcs = block[idx]
            assert dcs['clkout'] == clkout, (rc, idx)
            assert dcs['clk'] == [f'{prefix}{p}' for p in 'ABCD'], (rc, idx)
            # the four clock inputs are real multiplexers of that very cell
            for wire in dcs['clk']:
                assert wire in tile.clock_pips, (rc, idx, wire)
            clkouts.add(clkout)
    assert len(clkouts) == 4, 'two DCS may not share an output spine'


def test_dcs_quadrant_table_is_the_pre5a_one_for_pre5a_devices():
    pre5a_four = _PRE5A_FOUR_QUADRANT | {'GW5A-25A'}
    for device in ('GW1N-1', 'GW1NZ-1', 'GW1NS-2', 'GW1N-4', 'GW1NS-4',
                   'GW1N-9', 'GW1N-9C', 'GW2A-18', 'GW2A-18C', 'GW5A-25A'):
        expected = {q: types
                    for q, types in enumerate([(85, 84), (80, 81),
                                               (80, 81), (85, 84)])
                    if q >= 2 or device in pre5a_four}
        assert chipdb.dcs_quadrant_types(device) == expected, device
    assert chipdb.dcs_quadrant_types('GW5AST-138C') == {1: (85, 85),
                                                        2: (80, 80)}


def test_dcs_25a_input_table_unchanged():
    """The hand-traced 25A table is frozen; the 138C never mutates it."""
    assert chipdb.gw5_dcs_inputs == GW5_DCS_INPUTS_BASE


@pytest.mark.heavy
def test_dcs_prefix_is_clkin_on_gw5a(gowinhome):
    """`DCS` clock inputs are `CLKIN<n>` on this family, not `CLK<n>`."""
    dev = _build('GW5AST-138C', gowinhome)
    assert dev.dcs_prefix == 'CLKIN'
