"""V7 -- S17a: the C1/I0 speed grade is derived, not aliased (P0.T35).

`tm_parser` used to publish `C1/I0` as a copy of chunk 0 under the label `ES`
(`_aliases = {"gw5a": {"ES": ["C1/I0", "A0"]}}`).  Chunk 0's numbers are the
**C2/I1** column of DS1239E Table 3-13, so every C1/I0 arc nextpnr used for
`GW5AST-LV138PG484AC1/I0` was ~25 % optimistic.  Chunk 0 is now labelled
`C2/I1` and `C1/I0` is derived from it as `1.25 x C2/I1`; see
`doc/timing-c1i0.md`.
"""
import pytest

from apycula import tm_parser

DEVICE = 'GW5AST-138C'

# DS1239E Table 3-13, CFU rows, in ns.  Each .tm path carries four corner
# values whose min/max are compared against the datasheet's Min/Max columns.
DS1239E = {
    'C1/I0': {'lsr_q': (1.344, 1.435), 'clk_qpos': (0.250, 0.288)},
    'C2/I1': {'lsr_q': (1.075, 1.148), 'clk_qpos': (0.200, 0.230)},
}
# The datasheet quotes three decimals and the .tm chunk itself agrees with the
# C2/I1 column only to ~0.002 ns (chunk 0 clk_qpos maxes at 0.232 against a
# published 0.230).  The derivation scales that same 0.002 by 1.25, so the band
# check carries a 0.005 ns tolerance -- large enough for the inherited rounding,
# far smaller than the 25 % gap between the two grade columns it must separate.
TOL = 0.005


@pytest.fixture
def tm(device_file):
    with open(device_file(DEVICE, 'tm'), 'rb') as fh:
        return tm_parser.read_tm(fh, DEVICE)


def _in_band(values, band):
    lo, hi = band
    return min(values) >= lo - TOL and max(values) <= hi + TOL


def test_timing_c1i0_in_ds1239e_band(tm):
    """The derived C1/I0 DFF arcs sit in Table 3-13's C1/I0 band, not C2/I1's."""
    dff = tm['C1/I0']['dff']
    for path in ('lsr_q', 'clk_qpos'):
        assert _in_band(dff[path], DS1239E['C1/I0'][path]), (
            f'{path}={dff[path]} outside the C1/I0 band '
            f'{DS1239E["C1/I0"][path]}')
        assert not _in_band(dff[path], DS1239E['C2/I1'][path]), (
            f'{path}={dff[path]} still sits in the C2/I1 band '
            f'{DS1239E["C2/I1"][path]} -- C1/I0 is still the mislabelled '
            'chunk 0')
    # ...and the source chunk still matches the C2/I1 column, which is what
    # makes the 1.25x derivation legitimate rather than a fudge.
    c2 = tm['C2/I1']['dff']
    for path in ('lsr_q', 'clk_qpos'):
        assert _in_band(c2[path], DS1239E['C2/I1'][path])


def test_timing_c1i0_is_derived_not_aliased(tm, device_file):
    """C1/I0 == 1.25 x chunk 0, to within 1e-9, arc by arc."""
    with open(device_file(DEVICE, 'tm'), 'rb') as fh:
        chunk0 = fh.read(tm_parser.chunklen)
    parsed0 = {name: t for name, t in tm_parser.parse_chunk(chunk0) if t}

    assert tm['C1/I0']['dff']['lsr_q'] == pytest.approx(
        [1.25 * v for v in parsed0['dff']['lsr_q']], abs=1e-9)

    # ...and not merely that one path: every parsed delay is the scaled chunk 0,
    # while `parse_fanout`'s integer fanout counts are carried through as-is.
    assert set(tm['C1/I0']) == set(parsed0)
    for group, paths in parsed0.items():
        for path, values in paths.items():
            got = tm['C1/I0'][group][path]
            if isinstance(values, list):
                assert got == pytest.approx(
                    [1.25 * v for v in values], abs=1e-9), f'{group}.{path}'
            else:
                assert got == values, f'{group}.{path} is not a delay'
    # chunk 0 itself is published unscaled, as C2/I1.
    assert tm['C2/I1'] == parsed0


def test_timing_orphan_aliases_removed(tm):
    """No `ES`/`A0` keys survive, because chunk 0 is relabelled at the source."""
    assert 'gw5a' not in tm_parser._aliases
    assert 'A0' not in tm
    assert 'ES' not in tm
    order = tm_parser._gw5a_chunk_order
    assert order[0] == 'C2/I1'
    assert order[1] == 'unidentified_1'
    assert set(tm) == {'C2/I1', 'C1/I0', 'unidentified_1', 'unidentified_2'}
