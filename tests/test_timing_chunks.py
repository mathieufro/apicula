"""P0.T36 / D49b -- chunks 0, 1 and 2 of `GW5AST-138C.tm` dumped and identified.

The first `W-TIMING` measurement.  `P0.T35` labelled chunk 0 `C2/I1` and left
chunks 1 and 2 as `unidentified_1` / `unidentified_2`; this task measures what
they actually contain and records the result in the pipeline's
`evidence/timing-l0-cfu/chunks.md`.  The measurement did **not** identify either
chunk as a published speed grade -- DS1239E Table 3-13 publishes only C2/I1 and
C1/I0 for GW5AST-138, chunk 2 is a uniform `0.862 x` derate of chunk 0 (faster
than the fastest grade the part ships) and chunk 1 shares chunk 0's whole
sequential model while collapsing the combinational min/max spread.  So the
`unidentified_*` labels stand and `C1/I0` stays derived (`1.25 x`, P0.T35).

These tests re-derive the evidence file's claims from the shipped `.tm`, so the
dump cannot rot away from the device data.
"""
import os
import re

import pytest

from apycula import tm_parser

DEVICE = 'GW5AST-138C'

# The two speed grades DS1239E (`DS1239-1.0.3E`) Table 3-13 publishes for
# GW5AST-138.  There is no A0, no ES and no "A" grade column in that sheet, and
# the sibling GW5AT (DS981E T3-34) / GW5AS (DS1105E T3-21) sheets publish the
# same two columns with identical numbers.
DS1239E_COLUMNS = ('C2/I1', 'C1/I0')
# tSR_CFU / tCO_CFU, C2/I1 column, in ns.
DS_TSR_C2I1 = (1.075, 1.148)
DS_TCO_C2I1 = (0.200, 0.230)
# ...and the ratio between the two published columns, which is what makes
# `tm_parser.C1_I0_FROM_C2_I1` legitimate rather than a guess.
DS_C1I0_OVER_C2I1 = 1.25
# The measured scaling of chunk 2 relative to chunk 0.
CHUNK2_OVER_CHUNK0 = 0.862

_PIPE_CANDIDATES = (
    '/Users/alex/fine-line/.atelier/worktrees/'
    '2026-09-03-open-toolchain-gw5ast-7e84/.atelier/pipelines/'
    '2026-09-03-open-toolchain-gw5ast-7e84',
    '/Users/alex/fine-line/.atelier/pipelines/'
    '2026-09-03-open-toolchain-gw5ast-7e84',
)
_CHUNKS_MD = os.path.join('evidence', 'timing-l0-cfu', 'chunks.md')


def _chunks_md():
    for pipe in _PIPE_CANDIDATES:
        path = os.path.join(pipe, _CHUNKS_MD)
        if os.path.isfile(path):
            return path
    pytest.skip(f'{_CHUNKS_MD} not found in any pipeline candidate')


@pytest.fixture
def chunks(device_file):
    """The first three 15,552-byte chunks, parsed but unlabelled."""
    with open(device_file(DEVICE, 'tm'), 'rb') as fh:
        raw = [fh.read(tm_parser.chunklen) for _ in range(3)]
    assert all(len(c) == tm_parser.chunklen for c in raw)
    return [{name: tm for name, tm in tm_parser.parse_chunk(c) if tm}
            for c in raw]


def _floats(parsed):
    """Flatten one parsed chunk to {(group, path, slot): value} floats only."""
    out = {}
    for group, paths in parsed.items():
        for path, values in paths.items():
            if isinstance(values, list):
                for i, v in enumerate(values):
                    out[(group, path, i)] = v
    return out


# --------------------------------------------------------------------------
# The three tests P0.T36 names.
# --------------------------------------------------------------------------

def test_timing_c1i0_chunks_dumped():
    """`chunks.md` has exactly 3 chunk rows, each identified or `unidentified`."""
    with open(_chunks_md()) as fh:
        body = fh.read()

    rows = [line for line in body.splitlines()
            if re.match(r'^\|\s*[0-9]+\s*\|', line)
            and '15,552' in line]
    assert len(rows) == 3, f'expected 3 chunk rows, got {len(rows)}: {rows}'

    for want_index, row in enumerate(rows):
        cells = [c.strip() for c in row.strip().strip('|').split('|')]
        assert int(cells[0]) == want_index, f'chunk rows out of order: {row}'
        ident = cells[3]
        named = [col for col in DS1239E_COLUMNS if col in ident]
        assert bool(named) ^ ('unidentified' in ident), (
            f'chunk {want_index} identification cell {ident!r} is neither a '
            f'DS1239E column {DS1239E_COLUMNS} nor the literal "unidentified"')

    # ...and the file must not silently drop the structural facts it exists to
    # record: no chunk is C1/I0, so C1/I0 stays derived.
    assert 'C1/I0' in body and 'derived' in body


def test_timing_chunk0_matches_c2i1_to_three_decimals(chunks):
    """Chunk 0's `dff.lsr_q` rounds to DS1239E's C2/I1 tSR_CFU Min/Max."""
    lsr_q = chunks[0]['dff']['lsr_q']
    assert (round(min(lsr_q), 3), round(max(lsr_q), 3)) == DS_TSR_C2I1

    # The same two literals appear nowhere in chunk 2, which is what rules chunk
    # 2 out as the C2/I1 source; chunk 1 does carry them (it shares chunk 0's
    # whole DFF group), so the LUT column is what separates 0 from 1: DS1239E
    # tLUT4_CFU C2/I1 Max is 0.539, which chunk 1's LUT4 arcs never reach.
    assert (round(min(chunks[2]['dff']['lsr_q']), 3),
            round(max(chunks[2]['dff']['lsr_q']), 3)) != DS_TSR_C2I1
    lut4 = lambda p: [v for k in ('a_f', 'b_f', 'c_f', 'd_f') for v in p['lut'][k]]
    assert max(lut4(chunks[1])) < 0.539 <= max(lut4(chunks[0]))

    # tCO_CFU agrees to the datasheet's own rounding (0.002 ns), two orders of
    # magnitude tighter than the 25 % gap to the C1/I0 column.
    clk_qpos = chunks[0]['dff']['clk_qpos']
    assert min(clk_qpos) == pytest.approx(DS_TCO_C2I1[0], abs=0.002)
    assert max(clk_qpos) == pytest.approx(DS_TCO_C2I1[1], abs=0.002)


def test_timing_unidentified_never_under_speed_grade_key(device_file):
    """Grade-shaped keys are exactly {C1/I0, C2/I1}; the rest are `unidentified_N`."""
    with open(device_file(DEVICE, 'tm'), 'rb') as fh:
        tm = tm_parser.read_tm(fh, DEVICE)

    grade = re.compile(r'^[A-Z][0-9]/[A-Z][0-9]$')
    grades = {k for k in tm if grade.match(k)}
    assert grades == {'C1/I0', 'C2/I1'}
    for key in set(tm) - grades:
        assert re.match(r'^unidentified_[0-9]+$', key), (
            f'{key!r} is neither a speed grade nor an `unidentified_N` key')


# --------------------------------------------------------------------------
# The measurements those three rest on, asserted so the dump cannot rot.
# --------------------------------------------------------------------------

def test_timing_chunk2_is_a_uniform_derate_of_chunk0(chunks):
    """Chunk 2 == 0.862 x chunk 0 everywhere but `fanout` -- derived, not a grade.

    A uniformly scaled table is a derived table, and no DS1239E column sits at
    0.862 x C2/I1 (the only published ratio is C1/I0 = 1.25 x, and 0.862 x would
    be *faster* than the fastest grade the part ships).  Hence `unidentified_2`.
    """
    c0, c2 = _floats(chunks[0]), _floats(chunks[2])
    scaled = unscaled = 0
    for key, v0 in c0.items():
        if key[0] == 'fanout':
            continue
        if v0 == 0.0:
            assert c2[key] == 0.0
            continue
        if c2[key] == pytest.approx(CHUNK2_OVER_CHUNK0 * v0, rel=1e-6):
            scaled += 1
        else:
            unscaled += 1
            # the one exception is a tap constant, not a delay
            assert key == ('iodelay', 'SDTAP_DO', 0), f'{key} = {c2[key]} vs {v0}'
    assert scaled >= 600 and unscaled <= 1
    # and it is not the published C1/I0 ratio under a different sign
    assert CHUNK2_OVER_CHUNK0 != pytest.approx(DS_C1I0_OVER_C2I1, rel=0.05)


def test_timing_chunk1_shares_chunk0_sequential_model(chunks):
    """Chunk 1 differs from chunk 0 only on combinational/routing groups.

    `dff`, `bram`, `glbsrc`, `hclk`, `iodelay` and `fanout` are byte-equal to
    chunk 0; only `lut`, `alu`, `sram.rad*_do` and `wire` move, and every tuple
    it moves collapses (slot[2] == slot[0], slot[3] == slot[1]) -- no min/max
    spread.  A speed grade or a PVT corner moves the sequential arcs too, so
    chunk 1 is a different *model*, not a grade.  Hence `unidentified_1`.
    """
    c0, c1 = _floats(chunks[0]), _floats(chunks[1])
    changed = {k for k in c0 if c1[k] != c0[k]}
    assert {k[0] for k in changed} == {'lut', 'alu', 'sram', 'wire'}
    for group in ('dff', 'bram', 'glbsrc', 'hclk', 'iodelay', 'fanout'):
        assert not [k for k in changed if k[0] == group], f'{group} moved'

    tuples = {(g, p) for (g, p, _) in changed}
    for group, path in tuples:
        v = [c1[(group, path, i)] for i in range(4)]
        assert v[2] == v[0] and v[3] == v[1], f'{group}.{path} = {v} not collapsed'
    assert len(tuples) == 27
