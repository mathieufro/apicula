"""`P1.T40` -- the phase's end-to-end clock-tree design and its row.

The design is the one place every Phase-1 clocking primitive that the open
flow can build appears in a single bitstream, so what these tests assert is
its *shape*: which primitives, how many, and on which sites -- a design that
quietly loses one of them would otherwise still pass the `E1` comparison.
"""
import json
import os
import re
from pathlib import Path

import pytest

from fuzz.gw5ast138c.harness import gen
from fuzz.gw5ast138c.shapes import clocking_e2e

OTC = os.environ.get(
    'OTC',
    '/Users/alex/fine-line/.atelier/worktrees/'
    '2026-09-03-open-toolchain-gw5ast-7e84/open-toolchain')

BATCH_ID = 'p1t40-e2e'

#: The primitive under test -> how many instances the design carries.
#: `DCS` is 0 on purpose and its reason is measured
#: (`$OTC/evidence/dcs/openflow-gap-138c.md`); `CLKDIV2` is 0 per `D103`.
EXPECTED_INSTANCES = {'PLL': 1, 'DHCE': 1, 'CLKDIV': 1, 'DCE': 1,
                      'DCS': 0, 'CLKDIV2': 0}

PLL_HEADER = Path(__file__).resolve().parents[1] / 'examples' / 'pll' / 'GW5AST-138C.vh'


def design():
    return gen.render_verilog(clocking_e2e.SPEC)


def instances(rtl, primitive):
    """Instantiations of `primitive` in `rtl`, comments excluded."""
    body = re.sub(r'//[^\n]*', '', rtl)
    return re.findall(r'(?<![A-Za-z0-9_.])%s(?![A-Za-z0-9_])'
                      r'\s*(?:#\s*\(|[A-Za-z_][A-Za-z0-9_]*\s*\()' % primitive,
                      body)


def test_clocktree_e2e_carries_every_open_flow_clocking_primitive():
    rtl = design()
    for primitive, count in EXPECTED_INSTANCES.items():
        assert len(instances(rtl, primitive)) == count, primitive


def test_clocktree_e2e_chains_the_primitives_it_instantiates():
    """Pin -> DHCE -> HCLK lane -> CLKDIV -> DCE is one path, not four islands."""
    rtl = re.sub(r'//[^\n]*', '', design())
    assert '.CLKIN  (clk)' in rtl                      # DHCE from the pin
    assert '.HCLKIN (gated_hclk)' in rtl               # lane from the gate
    assert '.CLKIN  (div_clk)' in rtl                  # DCE from the divider
    assert 'defparam div0.DIV_MODE = "%s"' % clocking_e2e.DIV_MODE in rtl


def test_clocktree_e2e_pins_both_placeable_primitives():
    """`E1` is placement identity, so both sites are pinned on both sides."""
    bel = 'X%dY%d/CLKDIV_%d' % (clocking_e2e.BLOCK5_XY[0],
                                clocking_e2e.BLOCK5_XY[1], clocking_e2e.LANE)
    assert bel in design()
    ins_loc = clocking_e2e.SPEC.ins_loc
    assert ins_loc['dut_pll'] == clocking_e2e.PLL_SITE
    assert ins_loc['div0'] == 'BOTTOMSIDE%s' % f'[{clocking_e2e.INS_LOC_BASE + clocking_e2e.LANE}]'
    # the open flow reads the macro form and not the SIDE[0~7] one (P1.T14)
    assert gen.open_flow_reads_ins_loc(clocking_e2e.PLL_SITE)
    assert not gen.open_flow_reads_ins_loc(ins_loc['div0'])


def test_clocktree_e2e_uses_the_p1t39_pll_operating_point():
    """The design must not invent a PLL operating point of its own."""
    header = PLL_HEADER.read_text()
    params = dict(clocking_e2e.PLL_PARAMS)
    for name, define in (('FCLKIN', 'FCLKIN_MHZ'), ('IDIV_SEL', 'IDIV_SEL'),
                         ('FBDIV_SEL', 'FBDIV_SEL'), ('MDIV_SEL', 'MDIV_SEL'),
                         ('ODIV0_SEL', 'ODIV0_SEL')):
        want = re.search(r'`define GW5AST_138C_PLL_%s\s+(\S+)' % define,
                         header).group(1)
        assert params[name].strip('"') == want, name


def test_clocktree_e2e_row_is_e1():
    """Done-when: the one E2E run closes `E1` with nothing unexplained."""
    path = Path(OTC) / 'evidence' / 'clocking' / 'runs.jsonl'
    if not path.is_file():
        pytest.skip(f'{path} absent (set $OTC)')
    rows = [json.loads(l) for l in path.read_text().splitlines() if l.strip()]
    rows = [r for r in rows if str(r.get('run_id', '')).startswith(BATCH_ID)]
    if not rows:
        pytest.skip(f'batch {BATCH_ID} has not been merged into runs.jsonl')
    assert len(rows) == 1
    row = rows[0]
    assert row['verdict'] == 'ok'
    assert row['level'] == 'E1'
    assert row['diff_count']['cells'] == 0
    assert row['diff_count']['attrs'] == 0
    assert row['diff_count']['conns'] == 0
    assert row['decode_check'] == {'c1': 'ok', 'c2': 'ok'}
    assert row['unexplained_bits'] == []
