"""Tests for the gw_sh oracle driver (P0.T19).

Test names are fixed by `blueprints/P0-foundation.md` P0.T19 "Tests first".
"""
import os

import pytest

from fuzz.gw5ast138c.harness import oracle


SMOKE_FILES = (
    ('verilog', 'top.v'),
    ('cst', 'top.cst'),
    ('sdc', 'top.sdc'),
)


def test_oracle_tcl_template_exact():
    tcl = oracle.render_tcl(SMOKE_FILES, top_module='top')
    lines = tcl.splitlines()

    create = [ln for ln in lines if ln.startswith('create_project')]
    assert len(create) == 1, create
    assert '-device_version C' in create[0]
    # P0.T19 states `0` occurrences of `-pn`, on F57's reading of the
    # libGWTE option table. Measured on the install of record, that reading is
    # wrong: `create_project` without `-pn` aborts with `No target device in
    # this project`, so exactly one `-pn` -- on `create_project`, naming the
    # part -- is the only form that runs. Recorded as a deviation.
    assert tcl.count('-pn') == 1
    assert f'-pn {oracle.PART}' in create[0]

    set_device = [ln for ln in lines if ln.startswith('set_device')]
    assert len(set_device) == 1, set_device
    assert 'GW5AST-LV138PG484AC1/I0' in set_device[0]
    assert 'GW5AST-138C' in set_device[0]

    # F34: the gw_sh namespace is `-use_*_as_gpio`; `--*_as_gpio` is the
    # gowin_pack CLI namespace and never appears here.
    assert tcl.count('-use_cpu_as_gpio 1') == 1
    assert tcl.count('-cpu_as_gpio') == 0
    assert '--cpu_as_gpio' not in tcl


    assert 'run all' in lines[-1]


def test_oracle_preflight_fails_on_unknown_option():
    log = (
        'GowinSynthesis start\n'
        'unknown option: -cpu_as_gpio\n'
        'GowinSynthesis finish\n'
    )
    result = oracle.preflight(log, returncode=0)
    assert result.returncode == 0
    assert result.ok is False
    assert result.unknown_option_lines == ['unknown option: -cpu_as_gpio']
    assert 'unknown option:' in result.reason

    clean = oracle.preflight('GowinSynthesis finish\n', returncode=0)
    assert clean.ok is True


def _make_run_tree(root, basename):
    pnr = os.path.join(root, 'run', 'impl', 'pnr')
    os.makedirs(pnr)
    for ext in oracle.ARTIFACT_CLASSES:
        with open(os.path.join(pnr, f'{basename}.{ext}'), 'w') as fh:
            fh.write('x')
    gws = os.path.join(root, 'run', 'impl', 'gwsynthesis')
    os.makedirs(gws)
    with open(os.path.join(gws, f'{basename}.vg'), 'w') as fh:
        fh.write('x')
    return pnr


def test_oracle_collects_four_artifact_classes(tmp_path):
    root = str(tmp_path)
    pnr = _make_run_tree(root, 'top')
    got = oracle.collect_artifacts(root)
    assert sorted(got) == ['fs', 'sdf', 'tr', 'vg', 'vo']
    for cls in oracle.ARTIFACT_CLASSES:
        assert len(got[cls]) == 1, cls
        assert got[cls]
        assert os.path.dirname(got[cls][0]) == pnr
    assert len([c for c in oracle.ARTIFACT_CLASSES if got[c]]) == 4


def test_oracle_smoke_cst_defaults_asserted():
    cst = os.path.join(oracle.SMOKE_DIR, 'top.cst')
    if not os.path.isfile(cst):
        pytest.skip(f'{cst} is absent (P0.T19 smoke project not materialised)')
    banks = oracle.load_pin_banks()
    with open(cst) as fh:
        text = fh.read()
    ports = oracle.parse_cst(text)
    assert ports, 'no IO_LOC/IO_PORT pairs parsed from the smoke .cst'

    # 1. every used pin carries IO_TYPE
    missing_io_type = [p.port for p in ports.values() if 'IO_TYPE' not in p.attrs]
    assert missing_io_type == []

    # 2. every bank named carries a BANK_VCCIO
    used_banks = {banks[p.pin] for p in ports.values()}
    with_vccio = {banks[p.pin] for p in ports.values() if 'BANK_VCCIO' in p.attrs}
    assert used_banks - with_vccio == set()

    # 3. zero LVCMOS* assignments on any bank 6 or 7 pin (F73, PR #423)
    hazard = [
        p.port for p in ports.values()
        if banks[p.pin] in (6, 7)
        and str(p.attrs.get('IO_TYPE', '')).upper().startswith('LVCMOS')
    ]
    assert len(hazard) == 0

    assert oracle.check_cst_defaults(text, banks) == []


def test_oracle_collector_globs_never_assumes_basename(tmp_path):
    root = str(tmp_path)
    _make_run_tree(root, 'attosoc')
    got = oracle.collect_artifacts(root)
    resolved = [c for c in oracle.ARTIFACT_CLASSES if got[c]]
    assert len(resolved) == 4
    for cls in oracle.ARTIFACT_CLASSES:
        assert os.path.basename(got[cls][0]) == f'attosoc.{cls}'

    import inspect
    src = inspect.getsource(oracle)
    assert src.count('top.sdf') == 0
