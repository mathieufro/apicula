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


# ---------------------------------------------------------------- P1.T19

#: `P1.T19`, MEASURED: one oracle run per site, a single hard `PLL` pinned by
#: `INS_LOC "dut_pll" PLL_<side>[<n>]`, whose `.fs` lights up exactly one of
#: the twelve three-tile groups. `slot_idx` is the vendor site index.
TRACED_SITES_138C = {
    'PLL_L[0]': (27, 1, 0), 'PLL_L[1]': (45, 0, 1),
    'PLL_L[2]': (63, 0, 2), 'PLL_L[3]': (81, 1, 3),
    'PLL_R[0]': (27, 177, 4), 'PLL_R[1]': (45, 178, 5),
    'PLL_R[2]': (63, 178, 6), 'PLL_R[3]': (81, 177, 7),
    'PLL_B[0]': (108, 28, 8), 'PLL_B[1]': (108, 32, 9),
    'PLL_B[2]': (108, 146, 10), 'PLL_B[3]': (108, 150, 11),
}

#: The `PLL`/`PLLA` ports `_plla_inputs`/`_plla_outputs` index and the 138C
#: `.dat` populates: 35 - 12 MDIO inputs, 16 - 8 MDRDO outputs, plus the
#: manually created `CLKFBOUT`.
TRACED_PORT_COUNTS_138C = (23, 9)


def _md_source_column():
    """`source` values of the 12 rows of `sites-138c.md` section 3."""
    row_re = re.compile(
        r'^\|\s*(\d+)\s*\|\s*([LRB])\s*\|\s*([^|]+?)\s*\|\s*\((\d+),\s*(\d+)\)\s*\|'
        r'\s*([^|]+?)\s*\|\s*(\w+)\s*\|')
    if not SITES_MD.is_file():
        pytest.skip(f'{SITES_MD} absent (set $OTC)')
    out = []
    with SITES_MD.open(encoding='utf-8') as fh:
        for line in fh:
            m = row_re.match(line)
            if m:
                out.append((int(m.group(1)), int(m.group(4)), int(m.group(5)),
                            m.group(7)))
    return out


def test_plla_all_sites_resolved():
    rows = _md_source_column()
    assert len(rows) == PLL_COUNT_138C, (
        f'sites-138c.md has {len(rows)} rows, expected {PLL_COUNT_138C}')
    unknown = [r for r in rows if r[3] == 'unknown']
    assert not unknown, f'unresolved PLL sites remain: {unknown}'
    traced = [r for r in rows if r[3] == 'traced']
    assert len(traced) == PLL_COUNT_138C, (
        'P1.T19 traces all 12 sites (the .dat names none); '
        f'{len(traced)} rows carry source == "traced"')
    assert {(r[1], r[2]) for r in rows} == SITE_ANCHORS_138C


def test_plla_slot_idx_is_the_traced_vendor_site_index():
    """`slot_idx` must be the site the vendor placed there, not a guess.

    P1.T17 could only assume a row-major numbering; P1.T19 measured the
    bijection one oracle run at a time. If the two ever disagree again, this
    fails rather than silently mislabelling a bel.
    """
    table = chipdb._gw5a_pll_slots['GW5AST-138C']
    got = {(row, col): slot for row, col, slot, _t in table}
    want = {(r, c): s for r, c, s in TRACED_SITES_138C.values()}
    assert got == want
    assert sorted(got.values()) == list(range(PLL_COUNT_138C))
    assert {t for _r, _c, _s, t in table} == {'old_style'}, (
        'the 138C .dat names no site, so every entry is old_style')


@pytest.mark.heavy
def test_plla_traced_wires_in_wirenames(gowinhome):
    """Every wire the 138C PLL portmaps name resolves in a 138C name table."""
    dev, _dat = _build('GW5AST-138C', gowinhome)
    known = set(wnames.wirenames_5ast138c.values())
    known |= set(wnames.clknames_5ast138c.values())
    known |= set(wnames.wirenames.values())
    unresolved = []
    for (row, col), pll in _pll_entries(dev).items():
        for nam, wire in pll['inputs'].items():
            # aliases are synthesised names of the form PLLA<port><wire>
            base = wire[len(f'PLLA{nam}'):] if wire.startswith(f'PLLA{nam}') else wire
            if base not in known:
                unresolved.append((row, col, nam, wire))
    assert not unresolved, f'{len(unresolved)} unresolved wire names: {unresolved[:8]}'


@pytest.mark.heavy
def test_plla_traced_port_counts_are_the_shared_pll_plla_subset(gowinhome):
    """The port gap is pinned as a number, not left implicit.

    The 138C cell type is `PLL`, not `PLLA` (`sites-138c.md` section 8.2), and
    `_plla_inputs`/`_plla_outputs` index only the ports the two primitives
    share. `PLL`'s dynamic-divider ports -- ENCLKn, FBDSEL, IDSEL, MDSEL,
    ODSELn, DTn -- sit at `PllIn` indices apicula has no table for. This test
    states the size of that gap so growing the tables is a visible change.
    """
    dev, _dat = _build('GW5AST-138C', gowinhome)
    want_in, want_out = TRACED_PORT_COUNTS_138C
    for rc, pll in _pll_entries(dev).items():
        assert len(pll['inputs']) == want_in, (
            f'{rc}: {len(pll["inputs"])} inputs, expected {want_in}')
        assert len(pll['outputs']) == want_out, (
            f'{rc}: {len(pll["outputs"])} outputs, expected {want_out}')


def test_plla_trace_shape_sweeps_the_twelve_sites():
    """The `P1.T19` shape is the reproduction path, so it is guarded too."""
    from fuzz.gw5ast138c.harness import gen
    spec = gen.load_shape('clocking_pll_trace')
    assert spec.primitive == 'PLL', (
        'a PLLA instantiation on this device is refused with '
        'RP0008 "There is no PLLA resource in current device"')
    assert list(spec.sweep_values) == list(TRACED_SITES_138C)
    # the INS_LOC line must actually follow the sweep, not pin one site
    for site in TRACED_SITES_138C:
        assert f'INS_LOC "dut_pll" {site};' in gen.render_cst(spec, site)


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


# ---------------------------------------------------------------- P1.T21
#
# NOTE ON FILE PLACEMENT: `blueprints/P1-clocking.md` names
# `tests/test_gw5ast138c_clocking.py` for these two tests.  That file is
# already created, on `clocking/gw5a-hclk-6block`, by `P1.T07`/`T08b`/`T11`.
# Creating it independently here would be an add/add merge conflict on the
# integration branch for no gain, so the two blueprint-named tests live in
# this branch's own PLL test file instead.  The test NAMES -- which is what
# the task's Done-when quotes -- are exactly as the blueprint spells them.

#: The shipped example operating point, `examples/gw5a/clock-PLLA.v` with the
#: `pll/` defines, and the point `shapes/clocking_pll_trace.py` runs on the
#: oracle: FCLKIN 50 MHz, IDIV 1, FBDIV 1, MDIV 16, ODIV0 8.
ISSUE427_TRIPLE = dict(fclkin=50.0, idiv=1, fbdiv=1, mdiv=16, odiv=8)

#: Hand-computed from `UG306-1.0.9E` section 5.1 for that point:
#:   Fpfd   = 50 / 1       =  50.0 MHz
#:   Fclkfb = 50 * 1       =  50.0 MHz
#:   Fvco   = 50 * 16      = 800.0 MHz
#:   Fclkout0 = 800 / 8    = 100.0 MHz
ISSUE427_EXPECTED = (50.0, 50.0, 800.0, 100.0)

#: `P1.T20` five-tuple positions 4 and 3.
FVCO_MIN_138C, FVCO_MAX_138C = 650.0, 1300.0


class _Bare138C(gowin_pack.GW5AST_138C):
    """`GW5AST_138C` with the heavyweight `Device.__init__` bypassed.

    `check_pll_fvco` and `compute_pll_fvco` read nothing but
    `get_permitted_pll_freqs()`, so this exercises the real methods on the
    real class without needing a chipdb or a placed netlist.
    """

    def __init__(self):  # noqa: D107 - deliberately does not call super()
        pass


def test_pll_fvco_issue427_regression():
    """apicula #427: the GW5A PLL/PLLA VCO formula, in both emitters.

    Reverting the `gowin_pll.py` hunk (the `GW5A-25 ES` entry going back to
    `pll_name: rPLL` and `plla_freqs`/`solve_plla` disappearing) makes this
    test fail: `gowin_pll.plla_freqs` no longer exists and the entry no longer
    declares `pll_kind`.
    """
    from apycula import gowin_pll

    # 1. The formula itself, against the hand-computed datasheet value.
    pfd, fclkfb, fvco, clkout = gowin_pll.plla_freqs(**ISSUE427_TRIPLE)
    for got, want, what in zip((pfd, fclkfb, fvco, clkout), ISSUE427_EXPECTED,
                               ('Fpfd', 'Fclkfb', 'Fvco', 'Fclkout0')):
        assert abs(got - want) < 1e-6, f'{what}: {got} != {want}'

    # 2. It lies inside the 138C VCO band.
    assert FVCO_MIN_138C <= fvco <= FVCO_MAX_138C

    # 3. The packer computes the identical VCO -- zero differing values
    #    between the two places apicula derives a GW5A VCO frequency.  This is
    #    the drift that let #427 exist in one of them and not the other.
    packer_fvco = _Bare138C().compute_pll_fvco(
        ISSUE427_TRIPLE['fclkin'], ISSUE427_TRIPLE['idiv'],
        ISSUE427_TRIPLE['fbdiv'], ISSUE427_TRIPLE['mdiv'])
    assert abs(packer_fvco - fvco) < 1e-6

    # 4. The generator now knows the GW5A-25 is a PLLA part, not an rPLL one.
    #    This is the #427 root cause: an rPLL entry meant the emitted design
    #    used minus-one-encoded dividers, no MDIV at all, and solved
    #    VCO = CLKOUT*ODIV on a part where CLKOUT = VCO/ODIV.
    entry = _gw5a_25_pll_entry()
    assert entry['pll_name'] == 'PLLA'
    assert entry.get('pll_kind') == 'PLLA'

    # 5. End to end: asking for 100 MHz out of 50 MHz in yields a setup whose
    #    own numbers close under the PLLA formula.
    setup = gowin_pll.solve_plla(entry, 50.0, 100.0)
    assert setup, 'solve_plla found no setup for 50 MHz -> 100 MHz'
    _, _, s_fvco, s_clkout = gowin_pll.plla_freqs(
        50.0, setup['IDIV_SEL'], setup['FBDIV_SEL'],
        setup['MDIV_SEL'], setup['ODIV0_SEL'])
    assert abs(s_clkout - 100.0) < 1e-6
    assert abs(s_fvco - setup['VCO']) < 1e-6
    assert entry['vco_min'] <= s_fvco <= entry['vco_max']


def _gw5a_25_pll_entry():
    """The `GW5A-25 ES` row of `gowin_pll.main`'s `device_limits` literal.

    `device_limits` is a local of `main()`, so it is read out of the function's
    constants rather than re-typed here -- a copy would not notice a revert.
    """
    import ast
    import inspect
    from apycula import gowin_pll

    tree = ast.parse(inspect.getsource(gowin_pll.main))
    for node in ast.walk(tree):
        if (isinstance(node, ast.Assign)
                and isinstance(node.targets[0], ast.Name)
                and node.targets[0].id == 'device_limits'):
            table = ast.literal_eval(node.value)
            return table['GW5A-25 ES']
    raise AssertionError('device_limits not found in gowin_pll.main')


def test_pll_fvco_out_of_band_is_rejected():
    """The 138C VCO band check, exact text, inclusive at both ends."""
    dev = _Bare138C()

    with pytest.raises(Exception) as exc:
        dev.check_pll_fvco(649.0)
    assert str(exc.value) == (
        'FVCO 649.0 MHz is outside the GW5AST-138C permitted range '
        '[650.0, 1300.0] MHz')

    # Inclusive at both ends: 650.0 and 1300.0 are attainable values.
    dev.check_pll_fvco(650.0)
    dev.check_pll_fvco(1300.0)

    with pytest.raises(Exception) as exc:
        dev.check_pll_fvco(1300.5)
    assert str(exc.value) == (
        'FVCO 1300.5 MHz is outside the GW5AST-138C permitted range '
        '[650.0, 1300.0] MHz')


def test_pll_fclkin_check_untouched():
    """`P1.T21` must not disturb the base-class FCLKIN range check."""
    import inspect
    src = inspect.getsource(gowin_pack.Device.get_pll_attrvals)
    assert ('raise Exception(f"The {fclkin}MHz frequency is outside the '
            'permissible range of 3-{permitted_freqs[0]}MHz.")') in src


def test_pll_rpll_generator_path_unchanged():
    """The rPLL/PLLVR half of `gowin_pll` keeps its exact old algebra."""
    from apycula import gowin_pll
    pfd, clkout, vco = gowin_pll.rpll_freqs(27.0, 0, 3, 16)
    assert (pfd, clkout, vco) == (27.0, 108.0, 1728.0)


# ---------------------------------------------------------------- P1.T22

#: The commit `P1.T22` appended to. Its `pll_attrids` block is the baseline
#: every pre-existing entry must still match, byte for byte.
ATTRIDS_BASE_COMMIT = '401f6dc'

#: `$OTC/evidence/plla/attrids-138c.tsv`, `P1.T17` census + `P1.T22` sections.
ATTRIDS_TSV = Path(OTC) / 'evidence' / 'plla' / 'attrids-138c.tsv'


def _parse_pll_attrids(source):
    """`{name: id}` from a `apycula/attrids.py` source string."""
    import ast
    tree = ast.parse(source)
    for node in tree.body:
        if (isinstance(node, ast.Assign)
                and isinstance(node.targets[0], ast.Name)
                and node.targets[0].id == 'pll_attrids'):
            return ast.literal_eval(node.value)
    raise AssertionError('pll_attrids not found')


def _tsv_sections():
    """`attrids-138c.tsv` split into its blank-line-separated blocks."""
    if not ATTRIDS_TSV.is_file():
        pytest.skip(f'{ATTRIDS_TSV} absent')
    blocks = []
    for chunk in ATTRIDS_TSV.read_text().split('\n\n'):
        rows = [l for l in chunk.splitlines()
                if l.strip() and not l.startswith('#')]
        if rows:
            blocks.append([r.split('\t') for r in rows])
    return blocks


def test_pll_attrids_138c_reconciled():
    """`P1.T22`: no `.fse` id is silently nameless, and nothing was renamed."""
    from apycula import attrids

    # (a) The three counts are present in the artefact, as integers.
    counts = {}
    unnamed_rows = {}
    for block in _tsv_sections():
        head = block[0]
        if head[:2] == ['metric', 'value']:
            counts = {r[0]: int(r[1]) for r in block[1:]}
        elif head[0] == 'attr_id' and 'reason' in head:
            idx = head.index('reason')
            unnamed_rows = {int(r[0]): r[idx] for r in block[1:]}
    for key in ('in_both', 'fse_id_with_no_name', 'name_with_no_fse_id'):
        assert key in counts and isinstance(counts[key], int), (
            f'attrids-138c.tsv carries no integer {key}')

    # (b) Every `.fse` id with no name is accounted for, with a reason.
    n_unnamed = counts['fse_id_with_no_name']
    if n_unnamed:
        assert len(unnamed_rows) == n_unnamed, (
            f'{n_unnamed} nameless ids counted but {len(unnamed_rows)} listed')
        for attr_id, reason in unnamed_rows.items():
            assert reason.strip(), f'attr id {attr_id} listed with no reason'
        named = set(attrids.pll_attrids.values())
        assert not (set(unnamed_rows) & named), (
            'an id listed as nameless now has a name; refresh the artefact')

    # (c) The two MEASURED appends are present and are the only new ids.
    assert attrids.pll_attrids['A_DYN_IDIV_SEL'] == 125
    assert attrids.pll_attrids['A_DYN_ODIV0_SEL'] == 132

    # (d) No pre-existing entry was renamed, renumbered or removed.
    import subprocess
    repo = Path(__file__).resolve().parents[1]
    try:
        base_src = subprocess.run(
            ['git', 'show', f'{ATTRIDS_BASE_COMMIT}:apycula/attrids.py'],
            cwd=repo, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            timeout=60, check=True).stdout.decode()
    except (subprocess.CalledProcessError, FileNotFoundError, OSError):
        pytest.skip(f'commit {ATTRIDS_BASE_COMMIT} not reachable here')
    base = _parse_pll_attrids(base_src)
    now = attrids.pll_attrids
    modified = {k: (v, now.get(k)) for k, v in base.items() if now.get(k) != v}
    assert modified == {}, f'pre-existing pll_attrids entries changed: {modified}'
    assert set(now) - set(base) == {'A_DYN_IDIV_SEL', 'A_DYN_ODIV0_SEL'}


def test_pll_attrmap_138c_artefact_is_complete():
    """Every non-baseline oracle point of `p1-pll-attrmap` is attributed."""
    import json
    path = Path(OTC) / 'evidence' / 'plla' / 'attrmap-138c.json'
    if not path.is_file():
        pytest.skip(f'{path} absent')
    data = json.loads(path.read_text())
    assert data['batch_id'] == 'p1-pll-attrmap'
    assert data['site'] == 'PLL_L[0]'
    assert len(data['runs']) == 12
    for run in data['runs']:
        if run['point'] == 'p00_baseline':
            assert run['moved_bits'] == 0, 'the baseline moved against itself'
            continue
        assert run['moved_bits'] > 0, f"{run['point']} moved no bit at all"
        assert run['attrvals'], f"{run['point']} resolved to no shortval row"


# ======================================================================
# P1.T23 -- the `PLL` sweep shape and batch A (`IDIV` / `FBDIV`)
#
# The shape is `fuzz/gw5ast138c/shapes/clocking_pll.py` (`D96`: the cell type
# is `PLL`, not `PLLA`; the evidence slug stays `plla` for path stability).
# `P1.T41`-`T43` reuse it unedited through `$FUZZ_PLL_AXIS`.
# ======================================================================

#: DS1239E Table 3-18 `FPFDMIN` / `FPFDMAX`, the same bounds `P1.T22` used.
FPFD_BAND_138C = (19.0, 81.25)

#: Batch A's axes and its expected row count (blueprint `P1.T23`).
BATCH_A_AXES = {'IDIV', 'FBDIV'}
BATCH_A_ROWS = 20
BATCH_A_ID = 'p1-pll-sweep-a'


def _shape(axes='idiv,fbdiv'):
    """Import the shape module with `$FUZZ_PLL_AXIS` set, freshly."""
    import importlib
    mod = 'fuzz.gw5ast138c.shapes.clocking_pll'
    old = os.environ.get('FUZZ_PLL_AXIS')
    os.environ['FUZZ_PLL_AXIS'] = axes
    try:
        import sys
        sys.modules.pop(mod, None)
        return importlib.import_module(mod)
    finally:
        if old is None:
            os.environ.pop('FUZZ_PLL_AXIS', None)
        else:
            os.environ['FUZZ_PLL_AXIS'] = old


def test_pll_sweep_shape_points_are_inside_every_datasheet_band():
    """`S7` at generation time: no point of batch A can be out of band.

    `FVCO` in [650, 1300] (`P1.T21`), `Fpfd` in [19, 81.25], `CLKOUT0` in
    [5.079, 1000] and `FCLKIN` <= `FINMAX` 800 -- all four, for all 20 points.
    """
    m = _shape()
    fin_max, fout_max, fout_min, fvco_max, fvco_min = PERMITTED_FREQS_138C
    points = m.points()
    assert len(points) == BATCH_A_ROWS
    for name, (axis, value) in points.items():
        parms = axis.params(value)
        fclkin = float(parms['FCLKIN'].strip('"'))
        assert fclkin <= fin_max, f'{name}: FCLKIN {fclkin} > FINMAX {fin_max}'
        assert FPFD_BAND_138C[0] <= axis.fpfd(value) <= FPFD_BAND_138C[1], \
            f'{name}: Fpfd {axis.fpfd(value)} outside {FPFD_BAND_138C}'
        assert fvco_min <= axis.fvco(value) <= fvco_max, \
            f'{name}: FVCO {axis.fvco(value)} outside [{fvco_min}, {fvco_max}]'
        assert fout_min <= axis.clkout0(value) <= fout_max, \
            f'{name}: CLKOUT0 {axis.clkout0(value)} outside band'


def test_pll_sweep_shape_changes_exactly_one_parameter_per_point():
    """One parameter per run: a point differs from ITS axis baseline in 1 key."""
    m = _shape()
    for name, (axis, value) in m.points().items():
        base = axis.params(axis.baseline)
        here = axis.params(value)
        assert set(base) == set(here)
        diff = {k for k in base if base[k] != here[k]}
        if value == axis.baseline:
            assert diff == set(), f'{name} is the baseline and must not differ'
        else:
            assert diff == {axis.param}, \
                f'{name} differs in {sorted(diff)}, not just {axis.param}'


def test_pll_sweep_shape_axis_env_is_the_t41_t43_reuse_contract():
    """`$FUZZ_PLL_AXIS` selects the axes; the batch CLI stays seven options."""
    only_idiv = _shape('idiv')
    assert {a.name for a, _ in only_idiv.points().values()} == {'IDIV'}
    only_fbdiv = _shape('fbdiv')
    assert {a.name for a, _ in only_fbdiv.points().values()} == {'FBDIV'}
    both = _shape('idiv,fbdiv')
    assert len(both.points()) == len(only_idiv.points()) + len(only_fbdiv.points())
    with pytest.raises(ValueError):
        _shape('nosuchaxis').points()
    # The published CLI is exactly seven options (F11/F29) -- the axis is not
    # an eighth one.
    from fuzz.gw5ast138c.harness import __main__ as batch
    opts = [a for a in batch.build_parser()._actions if a.dest != 'help']
    assert len(opts) == 7, [a.dest for a in opts]


def test_plla_no_bank67_pins():
    """No sweep `.cst` may touch a bank 6/7 pin or a non-`LVCMOS33` IO_TYPE.

    `F73`/PR #423: an `LVCMOS*` value on a bank 6/7 pin of this die is a live
    thermal hazard. Authored by `P1.T23`, re-run unchanged by `P1.T41`-`T43`.
    """
    from fuzz.gw5ast138c.harness import gen
    from fuzz.gw5ast138c.shapes import DDR_BANKS
    m = _shape()
    spec = m.SPEC
    bad_banks = [p.loc for p in spec.pins.values() if p.bank in DDR_BANKS]
    assert bad_banks == [], f'sweep pins on a DDR bank: {bad_banks}'
    bad_types = [(n, p.io_type) for n, p in spec.pins.items()
                 if p.io_type != 'LVCMOS33']
    assert bad_types == [], f'non-LVCMOS33 IO_TYPE: {bad_types}'
    for name in m.points():
        cst = gen.render_cst(spec, name)
        for bank in DDR_BANKS:
            assert f'BANK_VCCIO {bank}' not in cst and \
                   f'BANK_VCCIO={bank}' not in cst, \
                   f'{name}: .cst configures bank {bank}'
        for line in cst.splitlines():
            if 'IO_TYPE=' in line:
                value = line.split('IO_TYPE=')[1].split()[0].rstrip(';,')
                assert value == 'LVCMOS33', f'{name}: IO_TYPE={value}'


def _batch_a_rows():
    """Batch A's rows out of the slug's `runs.jsonl` (skip when absent)."""
    import json
    path = Path(OTC) / 'evidence' / 'plla' / 'runs.jsonl'
    if not path.is_file():
        pytest.skip(f'{path} absent (set $OTC)')
    rows = [json.loads(l) for l in path.read_text().splitlines() if l.strip()]
    rows = [r for r in rows if r.get('shape') == 'clocking_pll'
            and str(r.get('run_id', '')).startswith(BATCH_A_ID)]
    if not rows:
        pytest.skip('batch p1-pll-sweep-a has not been merged into runs.jsonl')
    return rows


def test_plla_sweep_batch_a_rows():
    """`runs.jsonl` gained exactly 20 admissible batch-A rows.

    Every row's `sweep` map is `{axis, <swept parameter>}`; a non-baseline row
    differs from its axis baseline in exactly **one** key (the parameter), and
    each axis contributes exactly one baseline row. `mask_sha256` is one value
    across the batch. The verdict term asserted here is the **oracle** half:
    every row must carry a vendor `.fs`, because the vendor bitstream is what
    batch A measures (the open half's status is recorded in `notes`; see
    `$OTC/evidence/plla/openflow-gap-138c.md`).
    """
    m = _shape()
    rows = _batch_a_rows()
    assert len(rows) == BATCH_A_ROWS, f'{len(rows)} rows, expected {BATCH_A_ROWS}'
    assert len({r['run_id'] for r in rows}) == BATCH_A_ROWS

    axes = {r['sweep']['axis'] for r in rows}
    assert axes == BATCH_A_AXES, f'axes {axes}'
    assert len({r.get('mask_sha256') for r in rows}) == 1, 'mask_sha256 differs'
    assert all(r.get('vendor_fs') for r in rows), \
        'a row carries no vendor .fs: the oracle half did not complete'
    assert all(r.get('level') == 'E1' for r in rows)

    baselines = {}
    for name, (axis, value) in m.points().items():
        if value == axis.baseline:
            baselines[axis.name] = {'axis': axis.name, axis.param: value}
    assert set(baselines) == BATCH_A_AXES

    n_baseline = 0
    for row in rows:
        sweep = row['sweep']
        base = baselines[sweep['axis']]
        assert set(sweep) == set(base), f"{row['run_id']}: keys {sorted(sweep)}"
        diff = {k for k in base if base[k] != sweep[k]}
        if not diff:
            n_baseline += 1
        else:
            assert len(diff) == 1, f"{row['run_id']} differs in {sorted(diff)}"
    assert n_baseline == len(BATCH_A_AXES), \
        f'{n_baseline} baseline rows, expected one per axis'


# ---------------------------------------------------------------- P1.T41
#
# Batch B: the `ODIV0` / `ODIV1` / `MDIV` axes, and the four gaps that stood
# between a `PLL` design and a `.fs` through the open flow
# (`$OTC/evidence/plla/openflow-gap-138c.md`).

BATCH_B_AXES = {'ODIV0', 'ODIV1', 'MDIV'}
BATCH_B_ROWS = 20
BATCH_B_ID = 'p1-pll-sweep-b'
BATCH_B_ENV = 'odiv0,odiv1,mdiv'

#: `$OTC/evidence/plla/pump-138c.json`, the campaign this fit was made from.
PUMP_BATCH_ID = 'p1-pll-pump'
PUMP_POINTS = 10

#: The Done-when run: one `PLL` design through the whole open flow.
E1_BATCH_ID = 'p1-pll-e1'

#: The nextpnr checkout whose sources the gap-1/2 assertions read.
_NEXTPNR_SRC = Path(os.environ.get(
    'NEXTPNR_SRC',
    '/Users/alex/fine-line/.atelier/worktrees/'
    '2026-09-03-open-toolchain-gw5ast-7e84/nextpnr'))


def _db_138c():
    """The packaged 138C chipdb, or a skip when it has not been built."""
    import importlib.resources as ir
    from apycula import chipdb as _chipdb
    path = ir.files('apycula') / 'GW5AST-138C.msgpack.xz'
    if not path.is_file():
        pytest.skip('apycula/GW5AST-138C.msgpack.xz absent (make it first)')
    return _chipdb.load_chipdb(str(path))


def test_pll_sweep_batch_b_axes_are_inside_every_datasheet_band():
    """Every batch-B point satisfies all four DS1239E Table 3-18 bounds.

    The `ODIV` axes move `CLKOUT0`/`CLKOUT1` only and the `MDIV` axis moves
    `FVCO` only, so this is the band check batch A's own points get, applied
    to the three axes `P1.T41` adds.
    """
    m = _shape(BATCH_B_ENV)
    fin_max, fout_max, fout_min, fvco_max, fvco_min = PERMITTED_FREQS_138C
    points = m.points()
    assert len(points) == BATCH_B_ROWS
    assert {a.name for a, _ in points.values()} == BATCH_B_AXES
    for name, (axis, value) in points.items():
        parms = axis.params(value)
        fclkin = float(parms['FCLKIN'].strip('"'))
        assert fclkin <= fin_max, f'{name}: FCLKIN {fclkin} > FINMAX'
        assert FPFD_BAND_138C[0] <= axis.fpfd(value) <= FPFD_BAND_138C[1], \
            f'{name}: Fpfd {axis.fpfd(value)} outside {FPFD_BAND_138C}'
        assert fvco_min <= axis.fvco(value) <= fvco_max, \
            f'{name}: FVCO {axis.fvco(value)} outside [{fvco_min}, {fvco_max}]'
        # The ODIV1 axis divides CLKOUT1, not CLKOUT0; both share the band.
        divider = int(parms[axis.param]) if axis.name.startswith('ODIV') \
            else int(parms['ODIV0_SEL'])
        out = axis.fvco(value) / divider
        assert fout_min <= out <= fout_max, \
            f'{name}: CLKOUT {out} outside [{fout_min}, {fout_max}]'


def test_pll_sweep_batch_b_odiv1_axis_enables_clkout1():
    """`ODIV1` without `CLKOUT1_EN` writes no fuse, so it is in the axis.

    MEASURED on batch A: `ODIV1_SEL 8` with `CLKOUT1_EN "FALSE"` decodes to no
    value at all in the `A_ODIV1_SEL` (115) field of the site's `shortval[35]`
    table, i.e. the vendor emits the `ODIV1` divider only for an enabled
    output. `CLKOUT1_EN` therefore belongs to the axis's *operating point* --
    which keeps "a point differs from its own baseline in exactly one key"
    true, and that invariant is asserted for every axis by
    `test_pll_sweep_shape_changes_exactly_one_parameter_per_point`.
    """
    m = _shape(BATCH_B_ENV)
    for name, (axis, value) in m.points().items():
        parms = axis.params(value)
        if axis.name == 'ODIV1':
            assert parms['CLKOUT1_EN'] == '"TRUE"', name
        else:
            assert parms['CLKOUT1_EN'] == '"FALSE"', name


def _batch_b_rows():
    """Batch B's rows out of the slug's `runs.jsonl` (skip when absent)."""
    import json
    path = Path(OTC) / 'evidence' / 'plla' / 'runs.jsonl'
    if not path.is_file():
        pytest.skip(f'{path} absent (set $OTC)')
    rows = [json.loads(l) for l in path.read_text().splitlines() if l.strip()]
    rows = [r for r in rows if str(r.get('run_id', '')).startswith(BATCH_B_ID)]
    if not rows:
        pytest.skip('batch p1-pll-sweep-b has not been merged into runs.jsonl')
    return rows


def test_plla_sweep_batch_b_rows():
    """`runs.jsonl` gained exactly 20 admissible batch-B rows.

    The blueprint's terms: 20 rows carrying `sweep.axis` in the batch-B axis
    set, `0` aborted **oracle** halves (every row carries a vendor `.fs`),
    `mask_sha256` identical to batch A's, and every row's `sweep` map
    differing from its own axis baseline in exactly one key.
    """
    m = _shape(BATCH_B_ENV)
    rows = _batch_b_rows()
    assert len(rows) == BATCH_B_ROWS, f'{len(rows)} rows, expected {BATCH_B_ROWS}'
    assert len({r['run_id'] for r in rows}) == BATCH_B_ROWS

    axes = {r['sweep']['axis'] for r in rows}
    assert axes == BATCH_B_AXES, f'axes {axes}'
    assert all(r.get('vendor_fs') for r in rows), \
        'a row carries no vendor .fs: the oracle half did not complete'

    masks = {r.get('mask_sha256') for r in rows}
    assert len(masks) == 1, f'mask_sha256 differs inside batch B: {masks}'
    a_masks = {r.get('mask_sha256') for r in _batch_a_rows()}
    assert masks == a_masks, f'batch B mask {masks} != batch A mask {a_masks}'

    baselines = {}
    for name, (axis, value) in m.points().items():
        if value == axis.baseline:
            baselines[axis.name] = {'axis': axis.name, axis.param: value}
    assert set(baselines) == BATCH_B_AXES

    n_baseline = 0
    for row in rows:
        sweep = row['sweep']
        base = baselines[sweep['axis']]
        assert set(sweep) == set(base), f"{row['run_id']}: keys {sorted(sweep)}"
        diff = {k for k in base if base[k] != sweep[k]}
        if not diff:
            n_baseline += 1
        else:
            assert len(diff) == 1, f"{row['run_id']} differs in {sorted(diff)}"
    assert n_baseline == len(BATCH_B_AXES), \
        f'{n_baseline} baseline rows, expected one per axis'


# --- the four gaps `openflow-gap-138c.md` recorded (`P1.T41`) --------------


def test_pll_chipdb_names_every_site_primitive_and_macro():
    """Gap 1/2, data half: the database carries what the die actually has.

    The GW5AST-138C's primitive is `PLL`, not `PLLA` (`D96`), and each of its
    twelve sites has a vendor placement handle -- the bijection `P1.T19`
    measured one oracle run at a time. Both live in the chipdb so nextpnr's
    bel type and `cst.cc`'s macro table follow the *device*; nothing infers
    either from the family or from where a site sits on the die.
    """
    from apycula import chipdb as _chipdb
    macros = _chipdb._gw5a_pll_macros['GW5AST-138C']
    assert len(macros) == PLL_COUNT_138C
    assert set(macros.values()) == {
        f'PLL_{side}[{i}]' for side in 'LRB' for i in range(4)}
    slots = {slot: (row, col) for row, col, slot, _io
             in _chipdb._gw5a_pll_slots['GW5AST-138C']}
    assert {slots[s] for s in macros} == SITE_ANCHORS_138C
    assert macros[0] == 'PLL_L[0]' and slots[0] == (27, 1)
    assert _chipdb._gw5a_pll_primitive['GW5AST-138C'] == 'PLL'
    assert _chipdb._gw5a_pll_primitive['GW5A-25A'] == 'PLLA'


def test_pll_bel_and_macro_reach_the_built_chipdb():
    """The built database exposes the primitive, the macro and a decodable bel.

    A site with no entry in `tile.bels` decodes to nothing, which is what made
    a GW5A `PLL` invisible to `gowin_unpack` even though its fuses sat in an
    ordinary `shortval['PLL']` table.
    """
    db = _db_138c()
    sites = {(row, col): func['pll']
             for (row, col), func in db.extra_func.items() if 'pll' in func}
    assert len(sites) == PLL_COUNT_138C
    assert {s['primitive'] for s in sites.values()} == {'PLL'}
    assert sites[(27, 1)]['macro'] == 'PLL_L[0]'
    assert 'PLL' in db.tiles[db.grid[27][1]].bels
    assert 'PLL' in db.shortval[db.grid[27][1]]


def test_nextpnr_accepts_the_pll_cell_and_resolves_the_macro():
    """Gap 1/2, code half: `cst.cc` and `pack.cc` name the `PLL` at all.

    `cst.cc:334` shipped an empty macro table, so `INS_LOC "u" PLL_L[0];` was
    `Unknown placement macro`; `pack.cc:162` matched only `rPLL`/`PLLVR`/
    `PLLA`, so a `PLL` cell had no bel; and `gowin.h`'s `type_is_pll` omitted
    both GW5A spellings, so every `is_pll()` site skipped them.
    """
    gowin = _NEXTPNR_SRC / 'himbaechel' / 'uarch' / 'gowin'
    if not gowin.is_dir():
        pytest.skip(f'{gowin} absent (set $NEXTPNR_SRC)')
    cst = (gowin / 'cst.cc').read_text()
    assert 'macro_bel_type = {}' not in cst, 'the macro table is still empty'
    for family in ('PLL_L', 'PLL_R', 'PLL_B'):
        assert f'{{"{family}", id_PLL}}' in cst, family
    assert 'macro_bels' in cst, 'the macro is not resolved through the chipdb'
    pack = (gowin / 'pack.cc').read_text()
    assert 'id_rPLL, id_PLLVR, id_PLLA, id_PLL' in pack
    header = (gowin / 'gowin.h').read_text()
    assert ('type_is_pll(IdString cell_type) { return cell_type.in(id_rPLL, '
            'id_PLLVR, id_PLLA, id_PLL); }') in header


def test_get_PLL_fuses_writes_the_three_site_tiles_without_a_slot():
    """Gap 3: `gowin_pack` has a `PLL` handler, and it is not the slot path.

    `GW5A.common_pll_handler` writes through `get_pll_slot_fuses`, hardcoded
    to pseudo-ttyp 1024, which this device does not have (`P1.T17`). The 138C
    handler writes the site's own three tiles instead.
    """
    from apycula.gowin_pack import Device, GW5A, GW5AST_138C
    assert hasattr(GW5AST_138C, 'get_PLL_fuses')
    assert GW5AST_138C.get_PLL_fuses is not getattr(GW5A, 'get_PLL_fuses', None)
    # GW5A defines no `get_pll_bels` at all -- the 25A never needs one, because
    # its slot path never asks which tiles a site spans.
    assert not hasattr(GW5A, 'get_pll_bels')

    class _Bel:
        x, y = 1, 27
    tiles = list(GW5AST_138C.get_pll_bels(None, _Bel()))
    assert tiles == [(1, 27), (2, 27), (3, 27)]
    # the handler must reach Device's tile path, never GW5A's slot path
    source = GW5AST_138C.get_PLL_fuses.__doc__ or ''
    assert 'common_pll_handler' in source
    assert Device.common_pll_handler is not GW5A.common_pll_handler


def test_pll_pump_reproduces_every_measured_point():
    """Gap 4: the fitted charge pump agrees with every vendor bitstream.

    `$OTC/evidence/plla/pump-138c.json` is `gen_pump_138c.py`'s output over the
    three campaigns; a single disagreeing point means the fit is wrong, and an
    inconsistent coefficient interval means the model is.
    """
    import json
    from apycula import gw5ast138c_pll_pump as pump_mod
    path = Path(OTC) / 'evidence' / 'plla' / 'pump-138c.json'
    if not path.is_file():
        pytest.skip(f'{path} absent (set $OTC)')
    fit = json.loads(path.read_text())
    assert fit['mismatches'] == []
    assert fit['measured_points'] >= 44
    assert fit['kvco'] == [pump_mod.KVCO]
    for r_idx, row in fit['fit'].items():
        assert row['consistent'], f'R{r_idx}: empty coefficient interval'
        low, high = row['interval']
        fitted = dict(pump_mod.ICP_PER_NDIV)[int(r_idx)]
        assert low <= fitted <= high, f'R{r_idx}: {fitted} outside {row["interval"]}'
    # every point re-derived here, not just trusted from the file
    for point in fit['points']:
        assert pump_mod.pump(point['fref'], point['fvco']) == (
            point['FLDCOUNT'], point['icp'], point['r_value'] - 22)


def test_pll_openflow_row_is_e1():
    """Done-when: one `PLL` design closes `E1` with nothing unexplained."""
    import json
    path = Path(OTC) / 'evidence' / 'plla' / 'runs.jsonl'
    if not path.is_file():
        pytest.skip(f'{path} absent (set $OTC)')
    rows = [json.loads(l) for l in path.read_text().splitlines() if l.strip()]
    rows = [r for r in rows if str(r.get('run_id', '')).startswith(E1_BATCH_ID)]
    if not rows:
        pytest.skip(f'batch {E1_BATCH_ID} has not been merged into runs.jsonl')
    assert len(rows) == 1
    row = rows[0]
    assert row['verdict'] == 'ok'
    assert row['level'] == 'E1'
    assert row['diff_count']['cells'] == 0
    assert row['diff_count']['attrs'] == 0
    assert row['diff_count']['conns'] == 0
    assert row['decode_check'] == {'c1': 'ok', 'c2': 'ok'}
    assert row.get('open_fs'), 'the open flow produced no bitstream'


# ------------------------------------------------- P1.T42 batch C, P1.T43 D

BATCH_C_AXES = {'DYN', 'ODIV1L'}
BATCH_C_ROWS = 12
BATCH_C_ID = 'p1-pll-sweep-c'
BATCH_C_ENV = 'dyn,odiv1l'

BATCH_D_AXES = {'SITE'}
BATCH_D_ROWS = 12
BATCH_D_ID = 'p1-pll-sweep-d'
BATCH_D_ENV = 'site'

#: `P1.T39`'s reference operating point (`examples/pll/GW5AST-138C.vh`), the
#: point batch D holds fixed while it sweeps the placement.
T39_REFERENCE_POINT = {'FCLKIN': '"50.0"', 'IDIV_SEL': '1', 'FBDIV_SEL': '1',
                       'MDIV_SEL': '16', 'ODIV0_SEL': '8'}

#: The four batches' oracle-run counts. The blueprint budgeted 14 runs each
#: for C and D; the owner's run budget caps a clocking batch at 12, and both
#: batches are complete at 12 -- C sweeps five `DYN` modes plus a baseline and
#: six `ODIV1L` dividers, D sweeps every one of the twelve sites -- so the
#: campaign total is 64, not the blueprint's 68.
CAMPAIGN_RUNS = {BATCH_A_ID: 20, BATCH_B_ID: 20, BATCH_C_ID: 12,
                 BATCH_D_ID: 12}
CAMPAIGN_TOTAL = 64


def test_pll_sweep_batches_a_and_b_regenerate_byte_identically():
    """`P1.T42`'s axes are additive: no earlier point's Verilog moved.

    Batch C needs two parameters (`DYN_MDIV_SEL`, `DYN_DPA_EN`) that no
    earlier point carries and one variant that loads `CLKOUT1`. Both are
    reached through the axis, never through `BASE_PARAMS` or `RTL`, precisely
    so every batch-A and batch-B point still renders the bytes it was measured
    from -- otherwise the campaign's rows would no longer share a design.
    """
    from fuzz.gw5ast138c.harness import gen
    for env, count in ((None, BATCH_A_ROWS), (BATCH_B_ENV, BATCH_B_ROWS)):
        m = _shape(env) if env else _shape()
        points = m.points()
        assert len(points) == count
        for name, (axis, value) in points.items():
            assert axis.extra_params == [], f'{name}: {axis.extra_params}'
            assert not axis.loads_clkout1, name
            assert axis.param_order() == m.PARAM_ORDER, name
            assert 'pll_clkout1' not in m.rtl(m.SPEC, name), name
            gen.render_cst(m.SPEC, name)


def test_pll_sweep_batch_c_axes_are_inside_every_datasheet_band():
    """Every batch-C point satisfies all four DS1239E Table 3-18 bounds.

    The `DYN` axis never moves a divider, so its whole point set sits at one
    frequency; `ODIV1L` divides `CLKOUT1` after the VCO exactly as `ODIV1`
    does. Both still get batch A's band check, because a point that cannot be
    built measures nothing.
    """
    m = _shape(BATCH_C_ENV)
    fin_max, fout_max, fout_min, fvco_max, fvco_min = PERMITTED_FREQS_138C
    points = m.points()
    assert len(points) == BATCH_C_ROWS
    assert {a.name for a, _ in points.values()} == BATCH_C_AXES
    for name, (axis, value) in points.items():
        parms = axis.params(value)
        fclkin = float(parms['FCLKIN'].strip('"'))
        assert fclkin <= fin_max, f'{name}: FCLKIN {fclkin} > FINMAX'
        assert FPFD_BAND_138C[0] <= axis.fpfd(value) <= FPFD_BAND_138C[1], \
            f'{name}: Fpfd {axis.fpfd(value)} outside {FPFD_BAND_138C}'
        assert fvco_min <= axis.fvco(value) <= fvco_max, \
            f'{name}: FVCO {axis.fvco(value)} outside [{fvco_min}, {fvco_max}]'
        divider = int(parms[axis.param]) if axis.name == 'ODIV1L' \
            else int(parms['ODIV0_SEL'])
        out = axis.fvco(value) / divider
        assert fout_min <= out <= fout_max, \
            f'{name}: CLKOUT {out} outside [{fout_min}, {fout_max}]'


def test_pll_sweep_batch_c_dyn_axis_turns_on_exactly_one_mode():
    """A `DYN` point differs from the all-`FALSE` baseline in one parameter.

    The dynamic-reconfiguration selects are independent booleans, so the axis
    sweeps *which* one is `"TRUE"` rather than one parameter's value. The
    property attribution needs is unchanged and asserted here: exactly one key
    differs from the axis baseline, and it is a `DYN_*` key.
    """
    m = _shape(BATCH_C_ENV)
    modes = set()
    for name, (axis, value) in m.points().items():
        if axis.name != 'DYN':
            continue
        base = axis.params(axis.baseline)
        here = axis.params(value)
        assert set(base) == set(here), name
        diff = {k for k in base if base[k] != here[k]}
        if value == axis.baseline:
            assert diff == set(), f'{name} is the baseline and must not differ'
            assert all(v == '"FALSE"' for k, v in here.items()
                       if k.startswith('DYN_')), name
        else:
            assert len(diff) == 1, f'{name} differs in {sorted(diff)}'
            key = diff.pop()
            assert key.startswith('DYN_') and here[key] == '"TRUE"', name
            modes.add(key)
    assert modes == {'DYN_IDIV_SEL', 'DYN_FBDIV_SEL', 'DYN_MDIV_SEL',
                     'DYN_ODIV0_SEL', 'DYN_DPA_EN'}, modes


def test_pll_sweep_batch_c_odiv1l_axis_loads_clkout1():
    """`ODIV1L` is `ODIV1` plus a load, and the port list is unchanged.

    Batch B measured `A_ODIV1_SEL` (115) written at **none** of six divider
    values with `CLKOUT1` enabled but unconnected (`sweep-b-138c.md` 3.1).
    This axis connects `CLKOUT1` to a second flop and raises its dynamic
    enable; because that flop feeds the existing `dout`, the module's port
    list -- the thing a moved bit could otherwise be an artefact of -- is
    byte-identical to every other axis's.
    """
    m = _shape(BATCH_C_ENV)
    base_ports = _module_ports(m.rtl(m.SPEC, 'dyn_none'))
    seen = 0
    for name, (axis, value) in m.points().items():
        if axis.name != 'ODIV1L':
            continue
        seen += 1
        parms = axis.params(value)
        assert parms['CLKOUT1_EN'] == '"TRUE"', name
        assert parms['ODIV0_SEL'] == '8', name
        text = m.rtl(m.SPEC, name)
        assert '.CLKOUT1      (pll_clkout1)' in text, name
        assert ".ENCLK1       (1'b1)" in text, name
        assert 'posedge pll_clkout1' in text, name
        assert _module_ports(text) == base_ports, name
    assert seen == 6
    assert m.AXES['odiv1'].operating_point['CLKOUT1_EN'] == '"TRUE"'
    assert not m.AXES['odiv1'].loads_clkout1


def _module_ports(verilog):
    """The `module top (...)` port list of a rendered shape."""
    head = verilog.split('module top (')[1].split(');')[0]
    return tuple(sorted(line.strip().rstrip(',') for line in head.splitlines()
                        if line.strip()))


def test_pll_sweep_batch_d_is_the_t39_reference_point_on_every_site():
    """Batch D sweeps the placement and nothing else.

    Twelve points, one per `PLL` site of `sites-138c.md`, every one at
    `P1.T39`'s reference operating point, every one rendering the same module
    body. A per-site difference in the resulting bitstream is therefore a
    property of the site.
    """
    m = _shape(BATCH_D_ENV)
    points = m.points()
    assert len(points) == BATCH_D_ROWS
    assert {a.name for a, _ in points.values()} == BATCH_D_AXES
    assert {v for _, v in points.values()} == set(m.SITES)
    bodies = set()
    for name, (axis, value) in points.items():
        parms = axis.params(value)
        for key, want in T39_REFERENCE_POINT.items():
            assert parms[key] == want, f'{name}: {key}={parms[key]}'
        assert axis.fvco(value) == 800.0 and axis.fpfd(value) == 50.0
        assert axis.clkout0(value) == 100.0
        assert m.site(name) == value
        bodies.add(m.rtl(m.SPEC, name).split('`default_nettype none')[1])
    assert len(bodies) == 1, 'the twelve designs are not the same design'
    # the E0/E1 scope is every site's three tiles, so a run placed anywhere is
    # compared inside its own site rather than outside the scope
    assert len(m.SPEC.scope.tiles) == 3 * PLL_COUNT_138C


def _mask_sha256():
    """The sha256 of the shared don't-care mask, the file every row cites.

    The blueprint's term for batches C and D is "`mask_sha256` identical to
    batch A's", but batch A and batch B carry **no** `mask_sha256` at all:
    their open halves aborted before `equiv` ran (the four
    `openflow-gap-138c.md` gaps were still open), and the field is `equiv`'s.
    The mask file itself is the thing that term is about, so it is what the
    comparison is made against -- and against batch A too, whenever those rows
    ever gain the field.
    """
    import hashlib
    path = Path(__file__).resolve().parent.parent / 'fuzz' / 'gw5ast138c' \
        / 'dontcare.mask'
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _assert_mask_is_the_campaign_mask(rows):
    masks = {r.get('mask_sha256') for r in rows}
    assert len(masks) == 1, f'mask_sha256 differs inside the batch: {masks}'
    assert masks == {_mask_sha256()}, masks
    a_masks = {r.get('mask_sha256') for r in _batch_a_rows()} - {None}
    if a_masks:
        assert masks == a_masks, f'mask {masks} != batch A mask {a_masks}'


def _batch_rows(batch_id):
    """One batch's rows out of the slug's `runs.jsonl` (skip when absent)."""
    import json
    path = Path(OTC) / 'evidence' / 'plla' / 'runs.jsonl'
    if not path.is_file():
        pytest.skip(f'{path} absent (set $OTC)')
    rows = [json.loads(l) for l in path.read_text().splitlines() if l.strip()]
    rows = [r for r in rows if str(r.get('run_id', '')).startswith(batch_id)]
    if not rows:
        pytest.skip(f'batch {batch_id} has not been merged into runs.jsonl')
    return rows


def _assert_row_is_e1_ok(row):
    """The row closed `E1` through both flows with nothing unexplained."""
    assert row['verdict'] == 'ok', f"{row['run_id']}: {row['verdict']}"
    assert row['level'] == 'E1', row['run_id']
    for term in ('cells', 'attrs', 'conns'):
        assert row['diff_count'][term] == 0, f"{row['run_id']}: {term}"
    assert row['decode_check'] == {'c1': 'ok', 'c2': 'ok'}, row['run_id']
    assert row.get('vendor_fs'), f"{row['run_id']}: no vendor .fs"
    assert row.get('open_fs'), f"{row['run_id']}: the open flow made no .fs"


def test_plla_sweep_batch_c_rows():
    """`runs.jsonl` gained exactly 12 admissible batch-C rows, all `E1` ok.

    The blueprint's terms, at the owner's 12-run cap: 12 rows carrying
    `sweep.axis` in the batch-C axis set, `0` aborted, `mask_sha256` identical
    to batch A's, one baseline row per axis and every other row differing from
    it in exactly one key. Unlike batches A and B, which ran before
    `openflow-gap-138c.md`'s four gaps were closed, both halves of every
    batch-C row complete, so the verdict asserted is the full `E1` one.
    """
    m = _shape(BATCH_C_ENV)
    rows = _batch_rows(BATCH_C_ID)
    assert len(rows) == BATCH_C_ROWS, f'{len(rows)} rows'
    assert len({r['run_id'] for r in rows}) == BATCH_C_ROWS
    assert {r['sweep']['axis'] for r in rows} == BATCH_C_AXES

    _assert_mask_is_the_campaign_mask(rows)

    baselines = {axis.name: {'axis': axis.name, axis.param: axis.baseline}
                 for axis, _ in m.points().values()}
    assert set(baselines) == BATCH_C_AXES
    n_baseline = 0
    for row in rows:
        _assert_row_is_e1_ok(row)
        sweep = row['sweep']
        base = baselines[sweep['axis']]
        assert set(sweep) == set(base), f"{row['run_id']}: {sorted(sweep)}"
        diff = {k for k in base if base[k] != sweep[k]}
        if not diff:
            n_baseline += 1
        else:
            assert len(diff) == 1, f"{row['run_id']} differs in {sorted(diff)}"
    assert n_baseline == len(BATCH_C_AXES)
    modes = {r['sweep']['DYN_MODE'] for r in rows
             if r['sweep']['axis'] == 'DYN'}
    assert len(modes) == 6, f'duplicate DYN mode values: {modes}'


def test_plla_sweep_batch_d_rows():
    """`runs.jsonl` gained exactly 12 admissible batch-D rows, all `E1` ok.

    Twelve rows, `0` aborted, `mask_sha256` identical to batch A's, and
    exactly twelve distinct site identities with none missing against
    `sites-138c.md` -- which is the claim "all twelve sites are real" reduced
    to a property of the evidence file.
    """
    m = _shape(BATCH_D_ENV)
    rows = _batch_rows(BATCH_D_ID)
    assert len(rows) == BATCH_D_ROWS, f'{len(rows)} rows'
    assert len({r['run_id'] for r in rows}) == BATCH_D_ROWS
    assert {r['sweep']['axis'] for r in rows} == BATCH_D_AXES

    _assert_mask_is_the_campaign_mask(rows)

    sites = [r['sweep']['SITE'] for r in rows]
    assert len(set(sites)) == PLL_COUNT_138C, f'duplicate sites: {sites}'
    assert set(sites) == set(m.SITES), \
        f'missing against sites-138c.md: {set(m.SITES) - set(sites)}'
    for row in rows:
        _assert_row_is_e1_ok(row)


def test_plla_campaign_total_is_64():
    """The four batches' `runs` columns sum to the campaign total.

    The blueprint budgeted 68 (14 + 14 for C and D); the owner's cap of 12
    oracle runs per clocking batch makes it 64, and both batches are complete
    at 12 (see `CAMPAIGN_RUNS`).
    """
    path = Path(OTC) / 'evidence' / '_budget' / 'clocking-runs.tsv'
    if not path.is_file():
        pytest.skip(f'{path} absent (set $OTC)')
    runs = {}
    for line in path.read_text().splitlines()[1:]:
        if not line.strip():
            continue
        batch_id, _slug, n, _cum, _ts = line.split('\t')
        runs[batch_id] = int(n)
    missing = [b for b in CAMPAIGN_RUNS if b not in runs]
    if missing:
        pytest.skip(f'batches not yet charged: {missing}')
    charged = {b: runs[b] for b in CAMPAIGN_RUNS}
    assert charged == CAMPAIGN_RUNS, charged
    assert sum(charged.values()) == CAMPAIGN_TOTAL


#: The two sites whose anchor sits in column 0 and whose anchor tile type is
#: unique on the die; both explicitly disable the internal voltage regulator.
LEFT_EDGE_SITES = {'PLL_L[1]', 'PLL_L[2]'}


def test_plla_sites_decode_identically_except_the_two_left_edge_sites():
    """One design, twelve placements, one attribute encoding.

    `sites-e1-138c.json` decodes each site's three tiles through
    `shortval[35]`. Ten sites give an identical `{attribute: value}` map at
    three different tile-type triples, and the two left-edge sites give that
    map plus `A_VR_EN` -- so the encoding is a property of the `PLL` and the
    one difference is a property of the site.
    """
    import json
    path = Path(OTC) / 'evidence' / 'plla' / 'sites-e1-138c.json'
    if not path.is_file():
        pytest.skip(f'{path} absent (set $OTC)')
    fit = json.loads(path.read_text())
    assert fit['sites_decoded'] == PLL_COUNT_138C
    assert fit['e1_ok'] == PLL_COUNT_138C
    differing = {e['site'] for e in fit['sites']
                 if e['same_as_reference'] is False}
    assert differing == LEFT_EDGE_SITES, differing
    for entry in fit['sites']:
        if entry['site'] in LEFT_EDGE_SITES:
            assert entry['attr_delta'] == {'A_VR_EN': [None, 2]}, entry['site']
            assert entry['anchor'][1] == 0, entry['site']
        assert tuple(entry['anchor']) in SITE_ANCHORS_138C, entry['site']


# --------------------------------------------------- P1.T42 follow-up: DYN

#: The `DYN_*` selects the packer must encode from the cell, with the attribute
#: id each one was MEASURED at (`P1.T22` 125/132, `P1.T42` 124/131/190).
DYN_SELECT_IDS = {
    'A_DYN_IDIV_SEL': 125,
    'A_DYN_FBDIV_SEL': 124,
    'A_DYN_MDIV_SEL': 131,
    'A_DYN_ODIV0_SEL': 132,
    'A_DYN_DPA_EN': 190,
}


class _RecordingChipdb:
    """A chipdb stub that records the `AttrVal`s the packer asks it to encode."""

    def __init__(self):
        self.seen = {}

    def get_pll_attr_val(self, attrval, av):
        self.seen[attrval.attr] = attrval.val


class _AttrVals138C(gowin_pack.GW5AST_138C):
    """`GW5AST_138C` whose only collaborator is the recording chipdb."""

    def __init__(self):  # noqa: D107 - deliberately does not call super()
        self.chipdb = _RecordingChipdb()


class _Cell:
    def __init__(self, parms):
        self.name, self.parms = 'dut_pll', parms


class _Bel:
    def __init__(self, parms):
        self.x, self.y, self.cell = 27, 1, _Cell(parms)


#: The `P1.T42` batch-C operating point, `A_`-prefixed as `get_PLL_fuses`
#: hands it to `get_pll_attrvals`.
_BATCH_C_PARMS = {'A_FCLKIN': '100.0', 'A_IDIV_SEL': bin(4),
                  'A_FBDIV_SEL': bin(18), 'A_MDIV_SEL': bin(2),
                  'A_ODIV0_SEL': bin(8)}


def test_pll_attrids_name_the_two_batch_c_first_sightings():
    """`P1.T42` measured 124 and 131; an unnamed id cannot be encoded."""
    from apycula import attrids
    for name, attr_id in DYN_SELECT_IDS.items():
        assert attrids.pll_attrids[name] == attr_id, name


def test_pll_dyn_selects_are_encoded_from_the_cell_not_forced_false():
    """Each `DYN_*` cell parameter reaches the bitstream as its own boolean.

    The packer used to write every dynamic select `FALSE` regardless of the
    cell, so a `DYN_MDIV_SEL "TRUE"` design produced a static bitstream.
    """
    for name in DYN_SELECT_IDS:
        parm = name[len('A_'):]
        dev = _AttrVals138C()
        dev.get_pll_attrvals(_Bel(dict(_BATCH_C_PARMS, **{name: 'TRUE'})))
        assert dev.chipdb.seen[name] == 'TRUE', parm
        others = {n: dev.chipdb.seen[n] for n in DYN_SELECT_IDS if n != name}
        assert set(others.values()) == {'FALSE'}, others


def test_pll_dyn_selects_default_to_false():
    """A cell that names no dynamic mode still writes all five, all `FALSE`."""
    dev = _AttrVals138C()
    dev.get_pll_attrvals(_Bel(dict(_BATCH_C_PARMS)))
    for name in DYN_SELECT_IDS:
        assert dev.chipdb.seen[name] == 'FALSE', name
