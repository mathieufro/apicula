"""Phase 1 (clocking) unit tests for GW5AST-138C.

Owned by `blueprints/P1-clocking.md`; one section per task. The HCLK facts
asserted here are the MEASURED ones recorded in
`$OTC/evidence/hclk/topology-138c.md` (P1.T04) -- notably the **2 top / 4
bottom** die-half partition, which refutes the blueprint's assumed 3/3.
"""
import os
import re
from pathlib import Path

import pytest

from apycula import chipdb
from apycula import wirenames as wnames


# ---------------------------------------------------------------- P1.T05

def test_gw5_ihclk_wire_num_has_138c():
    n = chipdb.gw5_ihclk_wire_num('GW5AST-138C')
    assert isinstance(n, int) and n > 0
    # the 25A value is untouched
    assert chipdb.gw5_ihclk_wire_num('GW5A-25A') == 65
    # no `.get(device, ...)` default was introduced
    for absent in ('GW1N-9', 'GW5AT-60B'):
        with pytest.raises(KeyError):
            chipdb.gw5_ihclk_wire_num(absent)


# ---------------------------------------------------------------- P1.T06

def test_gw5a_hclk_locs_138c_six_blocks():
    locs = chipdb._gw5a_hclk_locs['GW5AST-138C']
    assert sorted(locs) == [0, 1, 2, 3, 4, 5]
    assert len(set(locs.values())) == 6
    a25 = chipdb._gw5a_hclk_locs['GW5A-25A']
    assert len(a25) == 4
    assert a25[0] == (0, 64)


# --------------------------------------------------- shared build fixture

_BUILT = {}


def _build(device, gowinhome):
    """`chipdb.from_fse` for `device`, cached for the whole test session."""
    if device in _BUILT:
        return _BUILT[device]
    from pathlib import Path as _P
    from apycula import fse_parser, dat_parser
    from apycula.chipdb_builder import DEVICE_PARAMS
    # the .fse parser reads GOWINHOME from the environment for its version
    # probe; the `gowinhome` fixture is the authority on which install that is
    os.environ.setdefault('GOWINHOME', gowinhome)
    vendor = DEVICE_PARAMS[device]['device']
    base = f'{gowinhome}/IDE/share/device/{vendor}/{vendor}'
    if not os.path.isfile(base + '.fse'):
        pytest.skip(f'{base}.fse absent')
    with open(base + '.fse', 'rb') as fh:
        fse = fse_parser.read_fse(fh, device)
    dat = dat_parser.Datfile(_P(base + '.dat'))
    if vendor in {'GW5AT-60B', 'GW5AST-138C'}:
        dat.patch_grid_bram_138()
    # chipdb.wire2node is module-global and chipdb_builder builds exactly one
    # device per process; building a second one in-process needs it cleared.
    chipdb.wire2node.clear()
    dev = chipdb.from_fse(device, fse, dat)
    # chipdb_builder.main() calls this right after from_fse (:451); the HCLK
    # bels are built there, not inside from_fse.
    chipdb.add_hclk_bels(dat, dev, device)
    _BUILT[device] = (dev, dat)
    return _BUILT[device]


# ---------------------------------------------------------------- P1.T07

@pytest.mark.heavy  # parses a real multi-MB vendor .fse via _build(); slow, not toolchain, but budget-binding
def test_gw5_add_hclk_bels_138c_block_and_wire_counts(gowinhome):
    dev, dat = _build('GW5AST-138C', gowinhome)
    # P1.T07 owns the builder, P1.T08 owns routing 138C into it; drive it
    # directly so this test states T07's contract on its own. The call is
    # idempotent, so it stays correct once T08 has landed.
    if not dev.hclk_div2:
        chipdb.gw5_add_hclk_bels(dat, dev, 'GW5AST-138C')
    assert len(dev.hclk_div2) == 6
    for hclk_idx, slots in dev.hclk_div2.items():
        assert hclk_idx in range(6)
        assert len(slots) == 4, f'block {hclk_idx}: {len(slots)} CLKDIV2 slots'
    assert sum(len(s) for s in dev.hclk_div2.values()) == 24

    halves = {}
    n_clkdiv = 0
    for (row, col), func in dev.extra_func.items():
        if 'clkdiv' not in func:
            continue
        idx = func['clkdiv']['hclk_idx']
        assert idx in range(6)
        assert func['clkdiv2']['hclk_idx'] == idx
        n_clkdiv += len(func['clkdiv']['bels'])
        # the half is derived, never stored: storing it would change the
        # GW5A-25A chipdb, a Phase-0 family-regression baseline (see
        # chipdb.gw5_hclk_half)
        assert 'half' not in func['clkdiv'] and 'half' not in func['clkdiv2']
        halves[idx] = chipdb.gw5_hclk_half(dev, row)
    assert n_clkdiv == 24
    assert set(halves.values()) == {'top', 'bottom'}
    # MEASURED partition (topology-138c.md §1): blocks 0,1 sit at row 27 (top
    # half of a 109-row die), the other four at rows 81/108. The blueprint's
    # assumed 3-top/3-bottom split is REFUTED.
    assert sorted(halves) == [0, 1, 2, 3, 4, 5]
    assert [halves[i] for i in range(6)] == [
        'top', 'top', 'bottom', 'bottom', 'bottom', 'bottom']


@pytest.mark.heavy  # parses a real multi-MB vendor .fse via _build(); slow, not toolchain, but budget-binding
def test_gw5_add_hclk_bels_25a_unchanged(gowinhome):
    dev, _dat = _build('GW5A-25A', gowinhome)
    assert len(dev.hclk_div2) == 4
    assert sum(len(s) for s in dev.hclk_div2.values()) == 16
    for (row, col), func in dev.extra_func.items():
        if 'clkdiv2' not in func:
            continue
        i = func['clkdiv2']['hclk_idx']
        assert i in range(4)
        # the 25A control wires are the in-tree literals
        # nothing new is written into the 25A extra_func: its chipdb must stay
        # byte-identical to the Phase-0 baseline 6311219d...
        assert 'half' not in func['clkdiv2'] and 'half' not in func['clkdiv']
        assert set(func['clkdiv2']) == {'bels', 'hclk_idx'}
        assert func['clkdiv2']['bels'][0]['inputs']['RESETN'] == 'B2'
        assert func['clkdiv']['bels'][0]['inputs']['RESETN'] == 'C4'
        assert func['clkdiv']['bels'][0]['inputs']['CALIB'] == 'B6'


# ---------------------------------------------------------------- P1.T08

@pytest.mark.heavy  # parses a real multi-MB vendor .fse via _build(); slow, not toolchain, but budget-binding
def test_hclk_nodes_138c_not_pre5a_path(gowinhome):
    dev, _dat = _build('GW5AST-138C', gowinhome)
    hclk_nodes = {n for n in dev.nodes if n.startswith('HCLK')}
    per_block = {i for i in range(6)
                 if any(n.startswith(f'HCLK{i}_') for n in hclk_nodes)}
    assert per_block == set(range(6)), f'blocks without a node: {set(range(6)) - per_block}'
    assert len(hclk_nodes) >= 6
    # the pre-5A generic path names its wires HCLK_OUT0..3 -- none may appear
    # (?<!I): HCLK_IHCLK_OUT.. is a GW5A inter-HCLK wire, not a pre-5A one
    pre5a = re.compile(r'(?<!I)HCLK_OUT[0-3]')
    assert not [n for n in dev.nodes if pre5a.search(n)]
    for tile_pips in dev.hclk_pips.values():
        for dest, srcs in tile_pips.items():
            assert not pre5a.search(dest)
            assert not any(pre5a.search(s) for s in srcs)


@pytest.mark.heavy  # forces a real .fse re-parse via _build(); slow, not toolchain, but budget-binding
def test_hclk_138c_takes_gw5a_branch(gowinhome, monkeypatch):
    calls = {'pin': 0, 'gates': 0, 'pips': 0}
    for name, key in (('gw5_make_pin_to_hclk', 'pin'),
                      ('gw5_make_hclk_to_clk_gates', 'gates'),
                      ('gw5_make_hclk_pips', 'pips')):
        orig = getattr(chipdb, name)

        def counted(*a, _orig=orig, _key=key, **kw):
            calls[_key] += 1
            return _orig(*a, **kw)
        monkeypatch.setattr(chipdb, name, counted)

    _BUILT.pop('GW5AST-138C', None)          # force a real build under the counters
    _build('GW5AST-138C', gowinhome)
    assert calls == {'pin': 1, 'gates': 1, 'pips': 1}
    # `_hclk_to_fclk` is not on the GW5A path and this task adds no key to it
    assert 'GW5AST-138C' not in chipdb._hclk_to_fclk
