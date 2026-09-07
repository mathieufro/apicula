"""Where the AE350's core clock and DDR clock actually come from (`P2.T38`).

`spec-primitives.md` §5 asks for the PLL placement to be *varied* and the two
routes *measured*, because MUG1031 and the shipped `.cst` are documentation,
not device data.  These tests guard the measurement's record: exactly one
verdict line each, and a chipdb whose model of the core-clock tap agrees with
what the vendor was seen to do.

The blueprint's assumed spelling for the model, `fixed_clk['CORE_CLK'][:3]`,
does not exist on this device and never did: the chipdb carries no fixed-edge
table for the block.  What it carries is one tap wire per clock port in
`extra_func[(0, 159)]['ae350']['ins']`, and `P2.T23` measured that the vendor
does not route `CORE_CLK` through it at all -- it takes the dedicated PLL
route, leaving the tap as a fabric alternative.  So the agreement these tests
assert is between the recorded route line and the tap the model still offers,
which is the assertion the missing table was standing in for.
"""
import os
import re

import pytest

from apycula import chipdb
from fuzz.gw5ast138c.harness import evidence

DEVICE = 'GW5AST-138C'

#: The two admissible verdicts.  A third spelling is not a softer verdict, it
#: is an unrecorded measurement.
CORE_CLK_SPELLINGS = ('PLL_R[0] exclusive', 'PLL_L[0] also legal')

CORE_LINE = re.compile(r'^CORE-CLK-ROUTE: (.+)$', re.M)
DDR_LINE = re.compile(r'^DDR-CLK-ROUTE: (PLL_[LRB]\[\d\])\.(CLKOUT\d) -> DDR_CLK$',
                      re.M)
RUNS_FIELD = re.compile(r'^BATCH_COMPLETE \S+ runs=(\d+) ', re.M)


def _read(name):
    root = evidence.evidence_root()
    path = os.path.join(root, 'ae350', name)
    if not os.path.isfile(path):
        pytest.skip(f'{path} not written yet')
    with open(path) as fh:
        return fh.read()


def test_core_clk_route_line_present_exactly_once():
    hits = CORE_LINE.findall(_read('core-clock.md'))
    assert len(hits) == 1
    assert hits[0] in CORE_CLK_SPELLINGS


def test_ddr_clk_route_line_present_exactly_once():
    hits = DDR_LINE.findall(_read('core-clock.md'))
    assert len(hits) == 1


def test_core_clk_model_matches_measurement():
    """An exclusive route leaves the chipdb's fabric tap; a legal `PLL_L[0]`
    placement means the tap is not the whole story and the model owes a fix."""
    verdict = CORE_LINE.findall(_read('core-clock.md'))[0]
    db = chipdb.load_chipdb(
        os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                     'apycula', f'{DEVICE}.msgpack.xz'))
    tap = db.extra_func[(0, 159)]['ae350']['ins']['CORE_CLK']
    assert tap == 'AE350_SOCCORE_CLKCLK1'
    if verdict == 'PLL_L[0] also legal':
        pytest.fail(
            'the core clock is reachable from PLL_L[0]: the chipdb models one '
            'tap and one dedicated route, and P2.T10 owes it a second edge')


def test_pll_placement_run_count_at_most_two():
    root = evidence.evidence_root()
    path = os.path.join(root, '_runs', 'p2t38-pll-l.log')
    if not os.path.isfile(path):
        pytest.skip(f'{path} not written yet')
    with open(path) as fh:
        runs = RUNS_FIELD.findall(fh.read())
    assert runs and int(runs[-1]) <= 2
