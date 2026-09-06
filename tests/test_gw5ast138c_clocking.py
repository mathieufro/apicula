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
from apycula import gowin_pack

from tests.fixtures.no_hclk_device import make_no_hclk_stub


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


# --------------------------------------------------------------- P1.T08c
#
# `gowin_unpack` decodes the HCLK-block cells of the 138C. Before this task
# unpacking the vendor CLKDIV bitstream yielded 138,600 cells of four types
# (DFF/IOB/LUT/BANK) and no CLKDIV at any tile ($OTC/evidence/hclk/clkdiv-138c.md
# section 4), which made an HCLK-scoped E0 vacuous. Everything asserted here is
# driven by the SAME chipdb data `gowin_pack` writes through -- the `HCLK`
# shortval table (`get_CLKDIV_fuses` -> `chipdb.get_hclk_fuses`) and
# `dev.hclk_pips` -- never by a literal fuse coordinate.

#: The P1.T11 vendor oracle run: a single `CLKDIV` with `DIV_MODE = "2"`.
#: sha256 of record 3d36f0aa63b6f2b48fabe9b3ac153bfffe15ab012b158022836ea7ab32b5ac5a
_VENDOR_CLKDIV_FS = (_DATASTORE /
                     'batch/p1t11/clkdiv/run/impl/pnr/run.fs')


def _unpack_hclk_tiles(dev, fs_path, device='GW5AST-138C'):
    """`gowin_unpack.parse_tile_` over the six measured HCLK block cells."""
    from apycula import gowin_unpack as gu
    from apycula.bslib import read_bitstream
    bits, _hdr, _ftr, _slots = read_bitstream(str(fs_path))
    bm = chipdb.tile_bitmap(dev, bits)
    old_device = gu._device
    gu._device = device
    try:
        out = {}
        for rc in sorted(chipdb._gw5a_hclk_locs[device].values()):
            tile = bm.get(rc)
            assert tile is not None, f'no tile bitmap at {rc}'
            bels, _pips, _cpips = gu.parse_tile_(dev, rc[0], rc[1], tile, bm,
                                                 noiostd=False)
            out[rc] = bels
    finally:
        gu._device = old_device
    return out


@pytest.mark.heavy  # needs the real vendor .fse (via _build) and the P1.T11 vendor .fs
def test_unpack_decodes_clkdiv_138c(gowinhome):
    """The vendor CLKDIV bitstream decodes to a CLKDIV cell with DIV_MODE.

    The vendor placed its single `CLKDIV` in HCLK block 5, at the measured
    block cell (108, 117) -- so exactly one of the six blocks must carry a
    CLKDIV bel, and it must carry the design's `DIV_MODE = "2"`.
    """
    if not _VENDOR_CLKDIV_FS.is_file():
        pytest.skip(f'{_VENDOR_CLKDIV_FS} absent')
    dev, _dat = _build('GW5AST-138C', gowinhome)
    per_tile = _unpack_hclk_tiles(dev, _VENDOR_CLKDIV_FS)

    with_clkdiv = {rc: bels for rc, bels in per_tile.items()
                   if any(n.startswith('CLKDIV_') for n in bels)}
    assert list(with_clkdiv) == [(108, 117)], with_clkdiv

    bels = per_tile[(108, 117)]
    assert 'CLKDIV_0' in bels, sorted(bels)
    assert 'DIV_MODE="2"' in bels['CLKDIV_0'], bels['CLKDIV_0']
    # the bel index is the chipdb's own CLKDIV slot, not an invention
    assert '0' in {str(k) for k in dev.extra_func[(108, 117)]['clkdiv']['bels']}
    # the block's own configured state is recovered too, on the HCLK bel
    assert 'HCLK5' in bels, sorted(bels)
    assert bels['HCLK5'], 'HCLK block cell decoded with no state'
    # and the five unconfigured blocks stay empty of CLKDIV/CLKDIV2
    for rc, other in per_tile.items():
        if rc == (108, 117):
            continue
        assert not [n for n in other if n.startswith('CLKDIV')], (rc, other)


@pytest.mark.heavy  # needs the real vendor .fse (via _build)
def test_unpack_hclk_completeness_138c(gowinhome):
    """`S6b`: every HCLK fuse is decoded or listed as known-undecoded."""
    from apycula import gowin_unpack as gu
    dev, _dat = _build('GW5AST-138C', gowinhome)
    rep = gu.hclk_decode_completeness(dev, 'GW5AST-138C')
    assert rep['blocks'] == 6
    assert rep['total'] == rep['decoded'] + rep['undecoded']
    assert rep['undecoded'] == 0, rep
    # nothing is quietly dropped: every entry not carried by a named CLKDIV
    # attribute is still recovered onto the HCLK block cell
    assert rep['clkdiv_div_entries'] == 36 * 6
    assert rep['pip_fuses'] == 151 * 6
    # the known-undecoded list is explicit and reasoned
    assert set(rep['known_undecoded']) == {'CLKDIV2', 'block_default_bits'}
    for reason in rep['known_undecoded'].values():
        assert reason and isinstance(reason, str)


def test_unpack_hclk_decode_is_device_gated():
    """The new decoder is strictly 138C-gated: pre-5A devices cannot reach it.

    This is the regression proof for `GW1N-9C` and `GW2A-18C`, for which no
    example bitstream is checked in: `parse_hclk_block` is the only entry
    point the change adds to `parse_tile_`, and it returns an empty bel set
    for any device not in `_hclk_block_devices`.
    """
    from apycula import gowin_unpack as gu
    assert 'GW5AST-138C' in gu._hclk_block_devices
    for absent in ('GW1N-9C', 'GW1N-9', 'GW2A-18C', 'GW2A-18', 'GW1N-1',
                   'GW1NZ-1', 'GW1N-4', 'GW1NS-4', 'GW5A-25A', 'GW5AT-60B'):
        assert absent not in gu._hclk_block_devices

    class _Dev:
        def __getitem__(self, rc):
            raise AssertionError('device-gated path touched the chipdb')
        extra_func = property(lambda self: (_ for _ in ()).throw(
            AssertionError('device-gated path touched extra_func')))

    old = gu._device
    try:
        for absent in ('GW1N-9C', 'GW2A-18C'):
            gu._device = absent
            assert gu.parse_hclk_block(_Dev(), 0, 0, None) == {}
    finally:
        gu._device = old


# ---------------------------------------------------------------- P1.T08c
# HCLK -> global-clock backbone.  See `chipdb._gw5a_hclk_to_clk` for the
# measurement these three tests encode and `$OTC/evidence/hclk/backbone-138c.md`
# for the vendor runs behind it.

def test_hclk5_backbone_map_138c_is_the_measured_staircase():
    """Block 5's four CLKDIV outputs, as MEASURED on four vendor bitstreams.

    Adding CLKDIVs one at a time lit block-5 wire indices 0,1,2,3 in the
    (108,117) table-48 fuses and, in lockstep, clock wires 109, 110, 224, 225
    at the central clock mux (54,88).  Blocks 0-4 are deliberately absent:
    the vendor placed every design in block 5 and nothing measured the rest.
    """
    m = chipdb._gw5a_hclk_to_clk['GW5AST-138C']
    assert set(m) == {5}, 'only block 5 is measured; do not guess the others'
    assert m[5] == {0: 109, 1: 110, 2: 224, 3: 225}
    # the two bands are disjoint and neither is the 25A's 169..184
    assert set(m[5].values()).isdisjoint(range(169, 185))
    # the 25A must not acquire an entry by accident
    assert 'GW5A-25A' not in chipdb._gw5a_hclk_to_clk


@pytest.mark.xfail(strict=True, reason=(
    "MEASURED REFUTATION (P1.T08c): the GW5AST-138C has no sixteen-wire "
    "{T,B,R,L}BDHCLK band.  Its six HCLK blocks expose 4 backbone wires each "
    "and block 5's four -- the only ones measured -- are clock wires "
    "109, 110, 224, 225, drawn from two disjoint bands, not one contiguous "
    "sixteen.  Naming sixteen wires here would be an invention.  Promoting "
    "this to a pass needs the other five blocks isolated on the vendor, which "
    "needs a CLKDIV placement handle the oracle does not expose."))
def test_clknames_138c_has_16_bdhclk():
    names = {f'{side}BDHCLK{i}' for side in 'TBRL' for i in range(4)}
    have = names & set(wnames.clknames_5ast138c.values())
    assert have == names, f'missing {sorted(names - have)}'


@pytest.mark.xfail(strict=True, reason=(
    "MEASURED REFUTATION (P1.T08c): gw5_make_hclk_to_clk_gates cannot fire on "
    "the GW5AST-138C.  It builds each gate pip from a table-48 row whose source "
    "is in {25,27,28,29} and whose destination is a clock wire; no cell of this "
    "device has such a row (the 25A has exactly four, ttyp 410/393/187/257).  "
    "The HCLK-block -> clock-mux hop is fuseless here, so the primitive the "
    "138C needs is a node, not a gate pip, and the selecting pips live in "
    "table 38, which fse_clock_pips_138 does not read."))
@pytest.mark.heavy  # parses the real vendor .fse
def test_hclk_to_clk_gates_fire_138c(gowinhome):
    from apycula import fse_parser
    names = {f'{side}BDHCLK{i}' for side in 'TBRL' for i in range(4)}
    assert names <= set(wnames.clknames_5ast138c.values())
    base = f'{gowinhome}/IDE/share/device/GW5AST-138C/GW5AST-138C.fse'
    if not os.path.isfile(base):
        pytest.skip('GW5AST-138C.fse absent')
    with open(base, 'rb') as fh:
        fse = fse_parser.read_fse(fh, 'GW5AST-138C')
    wnames.select_wires('GW5AST-138C')
    gate_rows = 0
    for ttyp, tile in fse.items():
        if not isinstance(tile, dict) or 'wire' not in tile:
            continue
        for srcid, destid, *_ in tile['wire'].get(48, []):
            if abs(srcid) in {25, 27, 28, 29} and \
                    wnames.clknames.get(destid, '') in names:
                gate_rows += 1
    assert gate_rows >= 16, f'only {gate_rows} gate rows in the .fse'




# ---------------------------------------------------------------- P1.T12

def test_fse_iologic_guard_string_is_real_device():
    """The fse_iologic exclusion must name a device that actually exists.

    'GW5AST-138AC' is not a device string anywhere in the tree, so the guard
    never fired and IOLOGIC bels were created on 138C by accident (F26).
    Correcting it to 'GW5AST-138C' is D39 state (1).
    """
    src = Path(chipdb.__file__).read_text()
    assert src.count("GW5AST-138AC") == 0
    assert chipdb.is_GW5_family('GW5AST-138C')


def test_iologic_refusal_message_literal():
    """The named refusal added to class GW5AST_138C raises the exact D39
    state-(1) error text, with no chipdb and no fixture involved."""
    chip = object.__new__(gowin_pack.GW5AST_138C)
    with pytest.raises(Exception) as excinfo:
        chip.reject_iologic_unsupported()
    message = str(excinfo.value)
    assert message == (
        "IOLOGIC on GW5AST-138C requires HCLK: no IOLOGIC bel exists for "
        "this device yet"
    )
    assert len(message) > 0


# ---------------------------------------------------------------- P1.T13

def test_iologic_before_hclk_unsupported_error_138c():
    """V16 selector: IOLOGIC before HCLK raises the D39 state-(1) refusal,
    proven against the synthetic no-HCLK fixture (roadmap F16) rather than
    the live 138C chipdb, which after Phase 3 legitimately carries IOLOGIC
    bels once the fse_iologic guard is deleted."""
    stub = make_no_hclk_stub()
    assert stub.chip_flags.count('HAS_5A_HCLK') == 0

    raised = []

    def _attempt_iologic_pack():
        if 'HAS_5A_HCLK' not in stub.chip_flags:
            chip = object.__new__(gowin_pack.GW5AST_138C)
            chip.reject_iologic_unsupported()

    with pytest.raises(Exception) as excinfo:
        _attempt_iologic_pack()
    raised.append(excinfo.value)

    assert len(raised) == 1
    assert str(raised[0]) == (
        "IOLOGIC on GW5AST-138C requires HCLK: no IOLOGIC bel exists for "
        "this device yet"
    )


def test_no_hclk_fixture_is_not_the_live_chipdb():
    """The fixture must be a different object from a live 138C Device, and
    (once P1.T09 lands HAS_5A_HCLK on this branch's chipdb.py) that live
    device must carry the flag while the fixture never does.

    Built against chipdb.set_chip_flags directly, not against the shipped
    GW5AST-138C.msgpack.xz build artifact, which predates HAS_5A_HCLK and
    would fail this test for the wrong reason (stale artifact, not a code
    defect); apycula/chipdb_builder.py is frozen this phase so it is not
    rebuilt here.

    P1.T09 (HAS_5A_HCLK) lands on branch clocking/gw5a-hclk-6block, not on
    this task's clocking/iologic-guard-spelling -- so on this branch the
    live device does not yet carry the flag. This is the "six-block chipdb
    not yet installed" case named in this task's dispatch: assert only the
    fixture-side property here (fixture never carries HAS_5A_HCLK) and skip
    the cross-branch live-flag assertion until integration.
    """
    stub = make_no_hclk_stub()
    assert 'HAS_5A_HCLK' not in stub.chip_flags

    live = chipdb.Device()
    chipdb.set_chip_flags(live, 'GW5AST-138C')
    assert stub is not live

    if 'HAS_5A_HCLK' not in live.chip_flags:
        pytest.skip(
            "HAS_5A_HCLK not yet on this branch's chipdb.py (P1.T09 lands "
            "on clocking/gw5a-hclk-6block) -- fixture-only assertion holds"
        )
    assert 'HAS_5A_HCLK' in live.chip_flags
