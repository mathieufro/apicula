"""Phase 1 (clocking) PLLA unit tests for GW5AST-138C -- `P1.T18`/`T19`/`T20`.

Owned by `blueprints/P1-clocking.md`. Every fact asserted here is the MEASURED
one recorded in `$OTC/evidence/plla/sites-138c.md` (`P1.T17`) and
`$OTC/evidence/plla/trace-138c.md` (`P1.T19`), not the blueprint's assumption:

* the 138C has **no PLL slots at all** -- no pseudo-ttyp >= 1024, no `drpfuse`
  header table -- so `slot_idx` on this device is a *site index*, not a DRP
  slot number, and `_gw5a_pll_slots['GW5AST-138C']` is a site table that
  happens to reuse the 25A table's 4-tuple shape;
* the 138C `.dat` names **zero** sites, so every entry is `old_style`;
* the MDIO/DRP ports (`MDCLK`, `MDOPC*`, `MDAINC`, `MDWDI*`, `MDRDO*`) are
  filled with `-1` in the 138C `.dat` and must be skipped, not looked up --
  `wirenames[-1]` is a bare `KeyError`.
"""
import os
import re
from pathlib import Path

import pytest

from apycula import chipdb
from apycula import gowin_pack
from apycula import wirenames as wnames


# --------------------------------------------------------------- constants

#: DS1239E Table 1-1 `Phase Locked Loop (PLLs) 12`, confirmed against the
#: shipped `.fse` by `P1.T17`.
PLL_COUNT_138C = 12

#: The six 25A entries exactly as they stood before `P1.T18` moved them into
#: `_gw5a_pll_slots`. `(row, col, slot_idx, io_table)`.
GW5A_25A_SLOT_PLLS = {
    (27, 0, 6, 'PllLB'),
    (27, 91, 2, 'PllRB'),
    (0, 0, 5, 'PllLT'),
    (0, 91, 3, 'PllRT'),
    (0, 45, 4, 'old_style'),
    (36, 45, 8, 'old_style'),
}

#: `P1.T17` anchors (`sites-138c.md` §3): the lowest-column tile of each
#: three-tile `shortval[35]` run. 4 left / 4 right / 4 bottom.
SITE_ANCHORS_138C = {
    (27, 1), (45, 0), (63, 0), (81, 1),
    (27, 177), (45, 178), (63, 178), (81, 177),
    (108, 28), (108, 32), (108, 146), (108, 150),
}

#: DS1239E Table 3-18, `GW5AST-138`, speed grade C1/I0, read verbatim:
#: FINMAX 800, FOUTMAX 1000, FOUTMIN 5.079, FVCOMAX 1300, FVCOMIN 650.
#: Docstring order at `gowin_pack.py` `GW5A_25A.get_permitted_pll_freqs` is
#: `(max_in, max_out, min_out, max_vco, min_vco)`.
PERMITTED_FREQS_138C = (800., 1000., 5.079, 1300., 650.)
PERMITTED_FREQS_25A = (800., 1600., 6.25, 1600., 800.)

OTC = os.environ.get(
    'OTC',
    '/Users/alex/fine-line/.atelier/worktrees/'
    '2026-09-03-open-toolchain-gw5ast-7e84/open-toolchain')
SITES_MD = Path(OTC) / 'evidence' / 'plla' / 'sites-138c.md'


# --------------------------------------------------- shared build fixture

_BUILT = {}


def _build(device, gowinhome):
    """`chipdb.from_fse` for `device`, cached for the whole test session.

    Same recipe as `tests/test_gw5ast138c_clocking.py::_build` (P1.T07); kept
    local rather than shared so the two task files stay independently
    runnable, per the `tests/` file-ownership rule.
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
    _BUILT[device] = (dev, dat)
    return _BUILT[device]


def _pll_entries(dev):
    """`{(row, col): pll_dict}` for every `extra_func` entry carrying a PLL."""
    return {rc: extra['pll'] for rc, extra in dev.extra_func.items()
            if 'pll' in extra}


# ---------------------------------------------------------------- P1.T18

@pytest.mark.heavy  # parses a real multi-MB vendor .fse via _build()
def test_plla_bel_count_138c_is_12(gowinhome):
    dev, _dat = _build('GW5AST-138C', gowinhome)
    plls = _pll_entries(dev)
    assert len(plls) == PLL_COUNT_138C, (
        f'{len(plls)} PLL extra_func entries, expected {PLL_COUNT_138C}')
    slot_idxs = [p['slot_idx'] for p in plls.values()]
    assert len(set(slot_idxs)) == PLL_COUNT_138C, (
        f'slot_idx values are not distinct: {sorted(slot_idxs)}')
    for row, col in plls:
        assert 0 <= row < dev.rows, f'PLL row {row} outside 0..{dev.rows - 1}'
        assert 0 <= col < dev.cols, f'PLL col {col} outside 0..{dev.cols - 1}'
    # the anchors are exactly P1.T17's measured ones, not a re-derivation
    assert set(plls) == SITE_ANCHORS_138C
    # every site is really wired: a PLL with an empty portmap is a bel that
    # nextpnr can create and never connect.
    for rc, pll in plls.items():
        assert pll['inputs'], f'PLL at {rc} has no inputs'
        assert pll['outputs'], f'PLL at {rc} has no outputs'
        assert 'CLKIN' in pll['inputs'], f'PLL at {rc} has no CLKIN'
        assert 'CLKOUT0' in pll['outputs'], f'PLL at {rc} has no CLKOUT0'


@pytest.mark.heavy
def test_plla_25a_slot_table_unchanged(gowinhome):
    # the literal itself, byte-for-byte after the move into the per-device table
    assert chipdb._gw5a_pll_slots['GW5A-25A'] == GW5A_25A_SLOT_PLLS
    dev, _dat = _build('GW5A-25A', gowinhome)
    plls = _pll_entries(dev)
    assert len(plls) == 6, f'{len(plls)} PLL entries on the 25A, expected 6'
    assert {p['slot_idx'] for p in plls.values()} == {2, 3, 4, 5, 6, 8}
    assert set(plls) == {(r, c) for r, c, _s, _t in GW5A_25A_SLOT_PLLS}


def test_plla_gate_is_the_device_table_not_a_literal():
    """The gate must be data-driven: a device is admitted iff it has a table."""
    assert set(chipdb._gw5a_pll_slots) >= {'GW5A-25A', 'GW5AST-138C'}
    src = Path(chipdb.__file__).read_text()
    body = src.split('def fse_create_slot_plls(')[1].split('\ndef ')[0]
    assert 'if device not in _gw5a_pll_slots' in body, (
        'fse_create_slot_plls still carries a hardcoded device set')
    assert '{(27, 0, 6,' not in body, (
        'the 25A slot literal is still inline in fse_create_slot_plls')


@pytest.mark.heavy
def test_plla_138c_has_no_drp_ports(gowinhome):
    """The 138C `.dat` fills every MDIO/DRP row with -1; they must be skipped.

    Before `P1.T18` guarded the `old_style` lookup this was not a cosmetic
    gap: `wirenames[-1]` raises a bare `KeyError` and kills the whole build.
    """
    dev, _dat = _build('GW5AST-138C', gowinhome)
    drp_in = {'MDCLK', 'MDOPC0', 'MDOPC1', 'MDAINC'} | {f'MDWDI{i}' for i in range(8)}
    drp_out = {f'MDRDO{i}' for i in range(8)}
    for rc, pll in _pll_entries(dev).items():
        assert not (drp_in & set(pll['inputs'])), f'DRP inputs at {rc}'
        assert not (drp_out & set(pll['outputs'])), f'DRP outputs at {rc}'


# ---------------------------------------------------------------- P1.T20


def test_permitted_pll_freqs_138c_five_tuple():
    got = gowin_pack.GW5AST_138C.get_permitted_pll_freqs(
        gowin_pack.GW5AST_138C)
    assert isinstance(got, tuple) and len(got) == 5, (
        f'expected a 5-tuple (max_in, max_out, min_out, max_vco, min_vco), '
        f'got {got!r}')
    for name, g, w in zip(('max_in', 'max_out', 'min_out', 'max_vco', 'min_vco'),
                          got, PERMITTED_FREQS_138C):
        assert g == w, f'{name}: {g} != {w}'


def test_permitted_pll_freqs_25a_unchanged():
    got = gowin_pack.GW5A_25A.get_permitted_pll_freqs(gowin_pack.GW5A_25A)
    assert tuple(got) == PERMITTED_FREQS_25A


def test_permitted_pll_freqs_138c_does_not_hit_the_base_stub():
    """`GW5AST_138C` must carry its own override, not inherit `GW5A`'s."""
    assert 'get_permitted_pll_freqs' in vars(gowin_pack.GW5AST_138C), (
        'GW5AST_138C inherits get_permitted_pll_freqs; instantiating a PLLA '
        'reaches the base stub raise')
