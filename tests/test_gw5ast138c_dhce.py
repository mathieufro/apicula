"""Phase 1 (clocking) DHCE unit tests for GW5AST-138C -- `P1.T26`.

Owned by `blueprints/P1-clocking.md`.  Every fact asserted here is the MEASURED
one recorded in `$OTC/evidence/dhcen/ce-wires-138c.md` and `trace-138c.md`
(`P1.T25`), not the blueprint's assumption.  The blueprint was refuted twice
(decision `D97`):

* the primitive is **`DHCE`** with enable port **`CEN`**; `DHCEN` does not
  exist on the GW5A family (`ERROR (EX3937)`), so apicula's internal name
  (`dhcen`, `_dhcen_ce`) is the only place the old spelling survives;
* the table is **6 HCLK blocks x 4 sites**, not 4 sides x 6 -- eight entries
  on each of `L`, `R`, `B`, no `'T'` key, and no interbank (`HCLK_BANK_OUT`)
  entry, because the vendor allocates exactly four per block and refuses the
  25th instance (`ERROR (PA2017) ... limit(24)`).
"""
import os
from pathlib import Path

import pytest

from apycula import chipdb
from apycula import wirenames as wnames


#: Vendor-stated capacity, `Clock Resource Usage Summary`: `DHCE 24/24`.
DHCE_COUNT_138C = 24

#: The six measured HCLK block cells (`P1.T04`), `(row, col)`.
HCLK_CELLS_138C = {(27, 0), (27, 181), (81, 0), (81, 181), (108, 64), (108, 117)}

#: `_dhcen_ce['GW1N-9']` exactly as it stood at the base commit -- the
#: regression guard the blueprint asks for.
GW1N9_DHCEN_CE = {
    'R': [(18, 46, 'C6'), (18, 46, 'D7'), (18, 46, 'C7'), (18, 46, 'D6'),
          (18, 46, 'B6'), (18, 46, 'B7')],
    'B': [(28, 46, 'A2'), (28, 46, 'A4'), (28, 46, 'A3'), (28, 46, 'A5'),
          (28, 0, 'B2'), (28, 0, 'B3')],
    'L': [(18, 0, 'C6'), (18, 0, 'D7'), (18, 0, 'C7'), (18, 0, 'D6'),
          (18, 0, 'B6'), (18, 0, 'B7')],
    'T': [(9, 0, 'C6'), (9, 0, 'D7'), (9, 0, 'C7'), (9, 0, 'D6'),
          (9, 0, 'B6'), (9, 0, 'B7')],
}

#: `P1.T25`'s table, `(side, row, col, wire)` per block in allocation order.
CE_WIRES_138C = {
    (27, 0): ('L', ['C2', 'C5', 'C7', 'D2']),
    (81, 0): ('L', ['C2', 'A5', 'C7', 'A4']),
    (27, 181): ('R', ['C2', 'C5', 'C7', 'D2']),
    (81, 181): ('R', ['C2', 'C5', 'C7', 'D2']),
    (108, 64): ('B', ['C2', 'C5', 'C7', 'D2']),
    (108, 117): ('B', ['C2', 'C5', 'C7', 'D2']),
}

OTC = os.environ.get(
    'OTC',
    '/Users/alex/fine-line/.atelier/worktrees/'
    '2026-09-03-open-toolchain-gw5ast-7e84/open-toolchain')
CE_WIRES_MD = Path(OTC) / 'evidence' / 'dhcen' / 'ce-wires-138c.md'


_BUILT = {}


def _build(device, gowinhome):
    """`chipdb.from_fse` for `device`, cached for the whole test session.

    Same recipe as `tests/test_gw5ast138c_plla.py::_build` (P1.T18); kept local
    so the two task files stay independently runnable, per the `tests/`
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


def _dhcen_sites(dev):
    """`{(row, col): [site, ...]}` for every `extra_func` entry with DHCEs."""
    return {rc: extra['dhcen'] for rc, extra in dev.extra_func.items()
            if 'dhcen' in extra}


# ---------------------------------------------------------------- P1.T26

@pytest.mark.heavy  # parses a real multi-MB vendor .fse via _build()
def test_dhcen_bels_created_138c(gowinhome, capsys):
    dev = _build('GW5AST-138C', gowinhome)
    sites = _dhcen_sites(dev)

    # 24 sites, the vendor's own stated capacity, over the six HCLK blocks
    assert set(sites) == HCLK_CELLS_138C
    total = sum(len(v) for v in sites.values())
    assert total == DHCE_COUNT_138C, f'{total} DHCE sites, expected 24'
    for rc, block in sites.items():
        assert len(block) == 4, f'block {rc} has {len(block)} DHCE, expected 4'

    # four distinct `side` values would be wrong here: this die has no
    # top-edge HCLK block, so exactly three sides carry DHCE.
    sides = {site['pip'][3] for block in sites.values() for site in block}
    assert sides == {'L', 'R', 'B'}, f'sides {sorted(sides)}, expected L/R/B'

    # every site names its measured CEN wire, in the measured order, and that
    # wire resolves in the device's own wire-name table
    for rc, block in sites.items():
        side, wires = CE_WIRES_138C[rc]
        assert [s['ce'] for s in block] == wires, f'block {rc}'
        assert {s['pip'][3] for s in block} == {side}, f'block {rc} side'
        for site in block:
            assert site['ce'] in wnames.wirenames_5ast138c.values(), site['ce']

    # no (row, col, wire) triple repeats anywhere on the die
    triples = [(rc[0], rc[1], s['ce'])
               for rc, block in sites.items() for s in block]
    assert len(set(triples)) == len(triples) == DHCE_COUNT_138C

    # every site is inside the grid
    for row, col in sites:
        assert 0 <= row < dev.rows and 0 <= col < dev.cols


@pytest.mark.heavy
def test_dhcen_absent_for_25a(gowinhome, capsys):
    """DHCEN/DHCE is greenfield for the family; the 25A is out of scope."""
    dev = _build('GW5A-25A', gowinhome)
    assert _dhcen_sites(dev) == {}
    assert 'GW5A-25A' not in chipdb._dhcen_ce


def test_dhcen_gw1n9_table_unchanged():
    """The pre-5A tables are frozen: the 138C entry is additive only."""
    assert chipdb._dhcen_ce['GW1N-9'] == GW1N9_DHCEN_CE
    assert chipdb._dhcen_ce['GW1N-9C'] == GW1N9_DHCEN_CE
    # the pre-5A devices keep their 4-side / 6-entry shape
    for device in ('GW1N-1', 'GW1NZ-1', 'GW1NS-2', 'GW1N-4', 'GW1NS-4',
                   'GW1N-9', 'GW1N-9C', 'GW2A-18', 'GW2A-18C'):
        for side, ces in chipdb._dhcen_ce[device].items():
            assert len(ces) == 6, f'{device}/{side} has {len(ces)} entries'


def test_dhcen_138c_table_matches_the_measured_artefact():
    """The literal is the artefact, not a re-derivation of it."""
    table = chipdb._dhcen_ce['GW5AST-138C']
    assert set(table) == {'L', 'R', 'B'}, 'no top-edge HCLK block on this die'
    for side, ces in table.items():
        assert len(ces) == 8, f'{side} has {len(ces)} entries, expected 8'
    flat = {}
    for side, ces in table.items():
        for row, col, wire in ces:
            flat.setdefault((row, col), []).append(wire)
    assert {rc: (None, ws) for rc, ws in flat.items()}.keys() == CE_WIRES_138C.keys()
    for rc, wires in flat.items():
        assert wires == CE_WIRES_138C[rc][1], rc
    if CE_WIRES_MD.is_file():
        text = CE_WIRES_MD.read_text()
        assert '`DHCE`, not `DHCEN`' in text
        assert 'DHCE 24/24' in text


#: MEASURED (`P1.T26`, batch `p1-dhce-fuse`, four vendor compiles): the fuse a
#: DHCE sets in block `(108, 64)`, per site index, read off the incremental
#: `n_dhce = 0 -> 1 -> 2 -> 3` diff of the block tile at a constant four
#: `CLKDIV`.  Index 3 is not in the sweep; it is the same-shaped bit of the
#: fourth multiplexer and is derived, not measured.
GATE_FUSES_108_64 = [(20, 2), (20, 48), (21, 32), (20, 99)]

#: The four HCLK input multiplexers of block `(108, 64)`, in site order.
GATE_MUXES_108_64 = ['HCLK_UNK812', 'HCLK_UNK813', 'HCLK_UNK814', 'HCLK_UNK815']


@pytest.mark.heavy
def test_dhce_gate_pip_is_real_138c(gowinhome):
    """Every site names a pip that actually exists in its block."""
    dev = _build('GW5AST-138C', gowinhome)
    sites = _dhcen_sites(dev)
    for (row, col), block in sites.items():
        pips = dev.hclk_pips[row, col]
        dests = []
        for site in block:
            tile, dest, src, side = site['pip']
            assert tile == f'X{col}Y{row}'
            assert dest in pips, f'{dest} is not a pip of block {(row, col)}'
            assert src in pips[dest], f'{src} does not drive {dest}'
            dests.append(dest)
        assert len(set(dests)) == 4, f'block {(row, col)} reuses a multiplexer'


@pytest.mark.heavy
def test_dhce_gate_fuses_match_the_vendor_138c(gowinhome):
    """The gate fuse is the vendor's, bit for bit, in the measured block."""
    dev = _build('GW5AST-138C', gowinhome)
    block = dev.extra_func[(108, 64)]['dhcen']
    pips = dev.hclk_pips[108, 64]
    assert [s['gate'] for s in block] == GATE_MUXES_108_64
    for idx, site in enumerate(block):
        fuses = chipdb.gw5a_dhce_gate_fuses(pips, site['gate'])
        assert fuses == {GATE_FUSES_108_64[idx]}, (
            f'site {idx}: {sorted(fuses)} != {GATE_FUSES_108_64[idx]}')
    # every block has exactly one gate fuse per site, nowhere zero or two
    for rc, blk in _dhcen_sites(dev).items():
        for site in blk:
            f = chipdb.gw5a_dhce_gate_fuses(dev.hclk_pips[rc], site['gate'])
            assert len(f) == 1, f'{rc} {site["pip"][1]}: {sorted(f)}'


def test_dhce_gowin_pack_emits_the_gate_fuse_138c():
    """`gowin_pack`'s own view of the chipdb carries the gate fuse.

    Exercises the two accessors `GW5AST_138C.get_DHCEN_fuses` calls, against
    the built `.msgpack.xz` rather than a freshly parsed `.fse`, so a chipdb
    that serialises the DHCE entries wrongly fails here and not only in a
    bitstream diff.
    """
    from apycula import gowin_pack
    try:
        db = gowin_pack.ChipDB('GW5AST-138C')
    except Exception as exc:                       # chipdb not built yet
        pytest.skip(f'GW5AST-138C.msgpack.xz unavailable: {exc}')
    x, y = 64, 108                                 # block (108, 64), (x, y)
    sites = db.db.extra_func[y, x]['dhcen']
    assert len(sites) == 4
    for idx in range(4):
        assert db.is_gw5a_dhcen(x, y, idx)
        wire, side = db.get_dhcen_wire_side(x, y, idx)
        assert wire == f'HCLK_MUX_BETA4{idx}'      # the routed lane wire
        assert sites[idx]['gate'] == GATE_MUXES_108_64[idx]
        assert side == 'B'
        assert db.get_gw5a_dhce_gate_fuses(x, y, idx) == {GATE_FUSES_108_64[idx]}
    # and the pre-5A devices keep the attribute-driven path
    try:
        db9 = gowin_pack.ChipDB('GW1N-9')
    except Exception:
        return
    for rc, extra in db9.db.extra_func.items():
        for idx in range(len(extra.get('dhcen', []))):
            assert not db9.is_gw5a_dhcen(rc[1], rc[0], idx)


def test_dhce_gowin_pack_get_DHCEN_fuses_138c():
    """`GW5AST_138C.get_DHCEN_fuses` emits the gate fuse, in the block cell.

    Driven with a stub `self`/`bel` rather than a full `Device`: the override
    reads nothing but `self.chipdb` and the bel's `(x, y, idx_int, cell.attrs)`,
    and building a real `Device` needs a placed-and-routed netlist, which this
    device cannot yet produce for an HCLK design (`D98`, `P1.T08c`).
    """
    from apycula import gowin_pack
    try:
        db = gowin_pack.ChipDB('GW5AST-138C')
    except Exception as exc:
        pytest.skip(f'GW5AST-138C.msgpack.xz unavailable: {exc}')

    class _Cell:
        def __init__(self, attrs):
            self.attrs = attrs

    class _Bel:
        def __init__(self, x, y, idx, attrs):
            self.x, self.y, self.idx_int = x, y, idx
            self.cell = _Cell(attrs)

    class _Self:
        chipdb = db

    x, y = 64, 108
    for idx in range(4):
        bel = _Bel(x, y, idx, {'DHCEN_USED': 1})
        fuses = gowin_pack.GW5AST_138C.get_DHCEN_fuses(_Self(), bel)
        assert len(fuses) == 1, f'site {idx}: {fuses}'
        cfb = fuses[0]
        assert (cfb.x, cfb.y) == (x, y), 'the fuse belongs to the block cell'
        assert set(cfb.bits) == {GATE_FUSES_108_64[idx]}
    # an unused site emits nothing at all
    assert gowin_pack.GW5AST_138C.get_DHCEN_fuses(
        _Self(), _Bel(x, y, 0, {})) == []
    # and the fuse is not written along the whole die edge, as it is pre-5A:
    # only one cell is touched, so the neighbouring block is not gated too
    bel = _Bel(x, y, 0, {'DHCEN_USED': 1})
    cells = {(f.x, f.y)
             for f in gowin_pack.GW5AST_138C.get_DHCEN_fuses(_Self(), bel)}
    assert cells == {(64, 108)}


# ---------------------------------------------------------------- P1.T27

#: MEASURED (`P1.T27`, batch `p1t27-dhce-lane` + `p1t38b-e2e`, six vendor
#: compiles): the gate fuse a *single* DHCE sets when the clock it gates is on
#: HCLK lane `i` of the named block.  It is the fuse of input multiplexer `i`
#: in every one of the six points and in both blocks, which is what settles
#: the question `P1.T26`'s allocation-order sweep could not: a DHCE site index
#: **is** the lane index, not the order the vendor happened to allocate in.
GATE_FUSE_BY_LANE = {
    (108, 117): {0: (21, 7), 1: (20, 31), 2: (20, 94), 3: (20, 50)},
    (108, 64): {0: (20, 2), 2: (21, 32)},
}


def _lane_mux(dev, device, row, col, idx):
    return 'HCLK_MUX_BETA%d%d' % (
        chipdb.gw5_hclk_idx(dev, device, row, col), idx)


@pytest.mark.heavy
def test_dhce_gate_pip_is_the_routed_lane_wire_138c(gowinhome):
    """The wire->bel handle is a wire an HCLK route actually lands on.

    `nextpnr` picks the hardware DHCE by comparing the destination wire of the
    recorded pip against every wire on the routed clock path
    (`globals.cc route_dhcen_net` / `get_dhcen_bel`).  The gate multiplexer
    itself cannot serve: its sources are dangling in table 48, so no route
    ever reaches it.  The lane's own entry multiplexer can, and does.
    """
    device = 'GW5AST-138C'
    dev = _build(device, gowinhome)
    for (row, col), block in _dhcen_sites(dev).items():
        pips = dev.hclk_pips[row, col]
        for idx, site in enumerate(block):
            tile, dest, src, _side = site['pip']
            assert tile == f'X{col}Y{row}'
            assert dest == _lane_mux(dev, device, row, col, idx)
            assert dest in pips, f'{dest} is not a pip of block {(row, col)}'
            assert src in pips[dest], f'{src} does not drive {dest}'
            # the gate multiplexer is kept, separately, for the fuse
            assert site['gate'] in pips
            assert len(chipdb.gw5a_dhce_gate_fuses(pips, site['gate'])) == 1


@pytest.mark.heavy
def test_dhce_gate_fuse_follows_the_lane_138c(gowinhome):
    """The fuse of site `i` is the one the vendor sets for a DHCE on lane `i`."""
    dev = _build('GW5AST-138C', gowinhome)
    for block, by_lane in GATE_FUSE_BY_LANE.items():
        sites = dev.extra_func[block]['dhcen']
        for idx, expected in by_lane.items():
            fuses = chipdb.gw5a_dhce_gate_fuses(dev.hclk_pips[block],
                                                sites[idx]['gate'])
            assert fuses == {expected}, f'{block} lane {idx}: {sorted(fuses)}'


def test_dhce_gowin_pack_gate_fuse_comes_from_the_gate_mux_138c():
    """`gowin_pack` reads the fuse from `gate`, not from the routing handle."""
    from apycula import gowin_pack
    try:
        db = gowin_pack.ChipDB('GW5AST-138C')
    except Exception as exc:                       # chipdb not built yet
        pytest.skip(f'GW5AST-138C.msgpack.xz unavailable: {exc}')
    for (row, col), by_lane in GATE_FUSE_BY_LANE.items():
        x, y = col, row
        for idx, expected in by_lane.items():
            assert db.is_gw5a_dhcen(x, y, idx)
            wire, side = db.get_dhcen_wire_side(x, y, idx)
            assert wire.startswith('HCLK_MUX_BETA') and wire.endswith(str(idx))
            assert side == 'B'
            assert db.get_gw5a_dhce_gate_fuses(x, y, idx) == {expected}


#: MEASURED (`P1.T27`, same six compiles): the CIB wire the vendor drives each
#: HCLK lane's `CLKDIV.RESETN` and `CLKDIV.CALIB` over.  `RESETN` refutes the
#: value carried over from the GW5A-25A (`C4..C7`), which collided with the
#: `CEN` wires of DHCE sites 1 and 2; `CALIB` confirms it.
CLKDIV_CTRL_WIRES_138C = {'clkdiv_resetn': ['D4', 'D5', 'D6', 'D7'],
                          'clkdiv_calib': ['B6', 'B7', 'C0', 'C1']}


def test_clkdiv_control_wires_do_not_collide_with_dhce_cen_138c():
    """No lane's CLKDIV control wire is a DHCE enable wire of the same block.

    A collision is not cosmetic: both are bel pin wires, so a design holding a
    CLKDIV and a DHCE on the affected lanes cannot be routed at all
    (`ERROR: Found two arcs with same sink wire`).
    """
    ctrl = chipdb._gw5a_hclk_ctrl_wires['GW5AST-138C']
    for key, wires in CLKDIV_CTRL_WIRES_138C.items():
        assert ctrl[key] == wires, key
    cen = {w for _side, ws in CE_WIRES_138C.values() for w in ws}
    for key in ('clkdiv_resetn', 'clkdiv_calib', 'clkdiv2_resetn'):
        assert not set(ctrl[key]) & cen, f'{key} collides with a CEN wire'
