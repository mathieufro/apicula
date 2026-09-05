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


# ---------------------------------------------------------------- P1.T09

# The pre-change flag list for GW5AST-138C (chipdb.set_chip_flags), recorded
# before this task appended HAS_5A_HCLK. The task must grow it by exactly one.
_FLAGS_138C_BASELINE = ['HAS_SP32', 'HAS_PINCFG', 'HAS_DFF67', 'HAS_CIN_MUX',
                        'NEED_BSRAM_RESET_FIX', 'NEED_CFGPINS_INVERSION',
                        'HAS_5A_DSP']


def _chip_flags(device):
    dev = chipdb.Device()
    chipdb.set_chip_flags(dev, device)
    return dev.chip_flags


def test_chip_flags_138c_has_5a_hclk():
    flags = _chip_flags('GW5AST-138C')
    assert 'HAS_5A_HCLK' in flags
    # 138C is in the HAS_PLL_HCLK exclusion set
    assert 'HAS_PLL_HCLK' not in flags
    # grew by exactly one against the recorded pre-change baseline
    assert flags == _FLAGS_138C_BASELINE + ['HAS_5A_HCLK']
    # neighbouring devices untouched
    assert 'HAS_5A_HCLK' in _chip_flags('GW5A-25A')
    assert 'HAS_5A_HCLK' not in _chip_flags('GW5AT-60B')


def test_chip_flags_138c_maps_to_nextpnr_bit():
    """The flag crosses to nextpnr as CHIP_HAS_5A_HCLK = 0x10000.

    Read the bit out of the generator itself rather than restating it, so a
    rename upstream fails here instead of silently dropping the flag.
    """
    gen = None
    for root in (Path(__file__).resolve().parents[2],
                 Path('/Users/alex/fine-line/.atelier/worktrees/'
                      '2026-09-03-open-toolchain-gw5ast-7e84')):
        cand = root / 'nextpnr' / 'himbaechel' / 'uarch' / 'gowin' / 'gowin_arch_gen.py'
        if cand.is_file():
            gen = cand
            break
    if gen is None:
        pytest.skip('nextpnr checkout absent')
    src = gen.read_text()
    m = re.search(r'^CHIP_HAS_5A_HCLK\s*=\s*(0x[0-9a-fA-F]+|\d+)', src, re.M)
    assert m, 'CHIP_HAS_5A_HCLK not defined in gowin_arch_gen.py'
    assert int(m.group(1), 0) == 0x10000
    # and the generator must set that bit from the chipdb flag name
    flags = _chip_flags('GW5AST-138C')
    computed = 0
    for name, value in re.findall(r'^CHIP_(\w+)\s*=\s*(0x[0-9a-fA-F]+|\d+)',
                                  src, re.M):
        if name in flags:
            computed |= int(value, 0)
    assert computed & 0x10000 != 0


# --------------------------------------------------------------- P1.T08b
#
# The HCLK *network* completion the P1.T05-T09 verification pass raised as a
# finding ($OTC/evidence/hclk/port-138c.md, "FINDINGS"): a six-block bel model
# was sitting on a four-block routing model, and `gw5_hclk_idx` returned -1 for
# every 138C cell so not one fuse-bearing HCLK pip existed.

def test_hclk_idx_covers_six_blocks(gowinhome):
    """Every measured 138C block cell resolves to its own block index."""
    dev, _dat = _build('GW5AST-138C', gowinhome)
    locs = chipdb._gw5a_hclk_locs['GW5AST-138C']
    for hclk_idx, (row, col) in locs.items():
        assert chipdb.gw5_hclk_idx(dev, 'GW5AST-138C', row, col) == hclk_idx
    # the block count the pip builder iterates is the table's, not a literal 4
    assert chipdb.gw5_get_num_of_hclks('GW5AST-138C') == len(locs) == 6
    assert chipdb.gw5_get_num_of_hclks('GW5A-25A') == 4
    # the five inter-HCLK bridge cells carry table 48 but are not blocks
    # (topology-138c.md section 4); they must not claim a block index
    for bridge in ((63, 0), (63, 181), (108, 0), (108, 118), (108, 181)):
        assert chipdb.gw5_hclk_idx(dev, 'GW5AST-138C', *bridge) == -1


def test_hclk_pip_nodes_equal_across_blocks(gowinhome):
    """Blocks 4 and 5 get the same HCLK node population as blocks 0-3."""
    dev, _dat = _build('GW5AST-138C', gowinhome)
    per_block = {i: len([n for n in dev.nodes if n.startswith(f'HCLK{i}_')])
                 for i in range(6)}
    assert len(set(per_block.values())) == 1, per_block
    # the four-block default-PIP section used to leave blocks 4/5 at 26
    assert min(per_block.values()) > 26
    # and the per-block wire families the default PIPs create must all be there
    for i in range(6):
        suffixes = {n.split('_', 1)[1] for n in dev.nodes
                    if n.startswith(f'HCLK{i}_')}
        for j in range(4):
            assert f'HCLK{i}{j}' in suffixes
            assert f'HCLK_BUF_AO{i}{j}' in suffixes
            assert f'HCLK_HUB{i}0' in suffixes
            assert f'HCLK_MUX_DELTA{i}{j}' in suffixes
            assert f'HCLK_TO_IHCLK{i}{j}' in suffixes


def test_hclk_pips_carry_fuses_138c(gowinhome):
    """The 138C HCLK pips are fuse-bearing, and evenly so across the six blocks."""
    dev, _dat = _build('GW5AST-138C', gowinhome)
    locs = chipdb._gw5a_hclk_locs['GW5AST-138C']
    fused = {}
    for (row, col), dests in dev.hclk_pips.items():
        n = sum(1 for srcs in dests.values() for f in srcs.values() if f)
        if n:
            fused[(row, col)] = n
    # every fuse-bearing tile is a measured block cell, and every block has some
    assert set(fused) == set(locs.values()), fused
    assert len(set(fused.values())) == 1, fused
    assert min(fused.values()) > 100
    # spot-check the shape of a fuse: a set of (row, col) bit coordinates
    for srcs in dev.hclk_pips[locs[5]].values():
        for f in srcs.values():
            if f:
                assert all(isinstance(b, tuple) and len(b) == 2 for b in f)


# ---------------------------------------------------------------- P1.T11
#
# Structural proof that the built 138C chipdb yields placeable CLKDIV and
# CLKDIV2 bels through the real nextpnr. The blueprint's "Done when" also asks
# for a routed .fs; that half is NOT met and is not pretended here -- full PnR
# exits 125 on "Failed to find a route for arc N of net div_clk" because
# `clknames_5ast138c` defines none of the 16 `{T,B,R,L}BDHCLK{0..3}` names, so
# `gw5_make_hclk_to_clk_gates` never fires and the CLKDIV output has no path to
# a global clock spine. Measured, with the run logs, in
# `$OTC/evidence/hclk/clkdiv-138c.md`. These tests therefore assert exactly the
# placement, via `--no-route`, and will start failing the day routing is fixed
# only if the placement itself regresses.

_DATASTORE = Path('/Users/alex/fine-line-data/open-toolchain-gw5ast')
_NEXTPNR = _DATASTORE / 'toolchains/nextpnr/bin/nextpnr-himbaechel'
_CHIPDB = _DATASTORE / 'chipdb/std/chipdb-GW5AST-138C.bin'
_YOSYS = Path('/opt/homebrew/bin/yosys')


def _place_only(tmp_path, design, bel_attr=None):
    """yosys + `nextpnr-himbaechel --no-route`; returns the placed cells."""
    import json
    import shutil
    import subprocess
    for tool in (_NEXTPNR, _CHIPDB, _YOSYS):
        if not tool.exists():
            pytest.skip(f'{tool} absent')
    src = Path(__file__).resolve().parents[1] / 'examples' / 'gw5a' / design
    text = src.read_text()
    if bel_attr:
        text = text.replace('\tCLKDIV div2 (',
                            f'\t(* BEL = "{bel_attr}" *)\n\tCLKDIV div2 (')
    (tmp_path / 'top.v').write_text(text)
    shutil.copy(src.parent / 'tangmega138k.cst', tmp_path / 'top.cst')
    subprocess.run(
        [str(_YOSYS), '-p',
         'read_verilog top.v; synth_gowin -family gw5a -setundef -json top.json'],
        cwd=tmp_path, check=True, capture_output=True)
    proc = subprocess.run(
        [str(_NEXTPNR), '--device', 'GW5AST-LV138PG484AC1/I0',
         '--chipdb', str(_CHIPDB), '--vopt', 'cst=top.cst', '--json', 'top.json',
         '--write', 'top_pnr_placed.json', '--top', 'top', '--no-route',
         '--timing-allow-fail'],
        cwd=tmp_path, capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr[-2000:]
    design_json = json.loads((tmp_path / 'top_pnr_placed.json').read_text())
    cells = {}
    for module in design_json['modules'].values():
        for name, cell in module['cells'].items():
            cells[name] = (cell['type'], cell['attributes'].get('NEXTPNR_BEL'))
    return cells, proc.stderr


_BEL_RE = re.compile(r'^X(\d+)Y(\d+)/(CLKDIV2?)_([0-3])$')


def _block_of(bel):
    m = _BEL_RE.match(bel)
    assert m, f'bel {bel!r} is not X<n>Y<n>/CLKDIV[2]_<0-3>'
    col, row = int(m.group(1)), int(m.group(2))
    locs = chipdb._gw5a_hclk_locs['GW5AST-138C']
    for idx, loc in locs.items():
        if loc == (row, col):
            return idx
    raise AssertionError(f'bel {bel} is at ({row},{col}), not an HCLK block')


@pytest.mark.heavy  # runs the real yosys + nextpnr against the installed chipdb
def test_nextpnr_places_clkdiv_138c(tmp_path):
    cells, _ = _place_only(tmp_path, 'clkdiv_chain-tangmega138k.v')
    divs = [(n, b) for n, (t, b) in cells.items() if t == 'CLKDIV']
    assert len(divs) == 1, divs
    assert _block_of(divs[0][1]) in range(6)


@pytest.mark.heavy
def test_nextpnr_places_clkdiv_138c_in_block_5(tmp_path):
    """A CLKDIV constrained to block 5 lands there -- blocks 4 and 5 are real."""
    row, col = chipdb._gw5a_hclk_locs['GW5AST-138C'][5]
    cells, _ = _place_only(tmp_path, 'clkdiv_chain-tangmega138k.v',
                           bel_attr=f'X{col}Y{row}/CLKDIV_2')
    divs = [(n, b) for n, (t, b) in cells.items() if t == 'CLKDIV']
    assert len(divs) == 1, divs
    assert _block_of(divs[0][1]) == 5


@pytest.mark.heavy
def test_nextpnr_places_clkdiv2_138c(tmp_path):
    cells, _ = _place_only(tmp_path, 'clkdiv2_chain-tangmega138k.v')
    div2 = [(n, b) for n, (t, b) in cells.items() if t == 'CLKDIV2']
    divs = [(n, b) for n, (t, b) in cells.items() if t == 'CLKDIV']
    assert len(div2) == 1 and len(divs) == 1, (div2, divs)
    assert _block_of(div2[0][1]) in range(6)
    assert _block_of(divs[0][1]) in range(6)
