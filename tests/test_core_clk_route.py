"""Where the AE350's core clock and DDR clock actually come from (`P2.T38`).

`spec-primitives.md` §5 asks for the PLL placement to be *varied* and the two
routes *measured*, because MUG1031 and the shipped `.cst` are documentation,
not device data.  These tests guard the measurement's record: exactly one
verdict line each, and a chipdb whose model of the core-clock tap agrees with
what the vendor was seen to do.

The model of record is `extra_func[(0, 159)]['ae350']['core_clk']`: one
fuseless pip per PLL site into a wire of the anchor tile that belongs to no
fabric line.  The fabric tap the `.dat` record names for the port is kept
beside it, unbound, because the vendor never routes through it -- a port with
a fabric alternative is not a fixed connection.
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


def _db():
    return chipdb.load_chipdb(
        os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                     'apycula', f'{DEVICE}.msgpack.xz'))


def test_core_clk_model_matches_measurement():
    """The model owes one dedicated edge per PLL site the measurement found."""
    verdict = CORE_LINE.findall(_read('core-clock.md'))[0]
    ae350 = _db().extra_func[(0, 159)]['ae350']
    sources = set(ae350['core_clk']['sources'])
    assert 'PLL_R[0]' in sources
    if verdict == 'PLL_L[0] also legal':
        assert 'PLL_L[0]' in sources, (
            'the chipdb models the core clock as PLL_R[0]-only, but the vendor '
            'built it from PLL_L[0] over the same zero-delay route')


def test_core_clk_is_bound_to_the_dedicated_wire_not_the_fabric_tap():
    """The port has no fabric route: the tap is recorded, never offered."""
    db = _db()
    ae350 = db.extra_func[(0, 159)]['ae350']
    edge = ae350['core_clk']
    assert ae350['ins']['CORE_CLK'] == edge['wire']
    assert edge['routable'] is False
    assert edge['fabric_tap'] is not None
    fabric = [name for name, (_kind, wires) in db.nodes.items()
              if (0, 159, edge['wire']) in wires and (0, 87, 'CLK1') in wires]
    assert fabric == []


def test_each_dedicated_hop_is_one_fuseless_pip_from_its_pll():
    """A fixed connection costs no bit and has exactly one source per site."""
    db = _db()
    edge = db.extra_func[(0, 159)]['ae350']['core_clk']
    pips = db.tiles[db.grid[0][159]].pips[edge['wire']]
    assert set(pips) == {src['alias'] for src in edge['sources'].values()}
    for site, source in edge['sources'].items():
        assert pips[source['alias']] == set(), site
        prow, pcol, pwire = source['pll_wire']
        assert any((0, 159, source['alias']) in wires
                   and (prow, pcol, pwire) in wires
                   for _kind, wires in db.nodes.values()), site


def test_pll_placement_run_count_at_most_two():
    root = evidence.evidence_root()
    path = os.path.join(root, '_runs', 'p2t38-pll-l.log')
    if not os.path.isfile(path):
        pytest.skip(f'{path} not written yet')
    with open(path) as fh:
        runs = RUNS_FIELD.findall(fh.read())
    assert runs and int(runs[-1]) <= 2
