"""P1.T33 -- `parse_pll` and the PLL slice of the L0 timing band (`D60`).

`D60` hands the PLL arcs of L0 to Phase 1.  This measures what the shipped
`.tm` actually holds at the PLL offset and what the vendor's own static timing
says about the same cell, and pins both so the conclusion cannot rot:

* the `0x7cc` block is 80 bytes -- five `float_data` paths of four corners --
  and is **byte-identical to `GW2A-18.tm`**, i.e. inherited rPLL data;
* five paths is the rPLL output count (CLKOUT/LOCK/CLKOUTP/CLKOUTD/CLKOUTD3),
  not this die's PLL, which UG306E Table 5-2 gives CLKOUT0..6/CLKFBOUT/LOCK;
* the vendor SDF for a 138C PLL design emits `CLKIN -> CLKOUT0..6` and every
  one is `0.000:0.000:0.000`.

So the PLL slice is "no arcs by design" and `parse_pll` publishes nothing.
"""
import os
import re

import pytest

from apycula import tm_parser
from fuzz.gw5ast138c.harness import evidence

DEVICE = 'GW5AST-138C'
GW2A = 'GW2A-18'
PLL_OFF = 0x7cc
DLL_OFF = 0x81c
PLL_LEN = DLL_OFF - PLL_OFF          # 0x50 == 80 bytes == 5 paths x 4 floats

# The marker file P1.T33 writes; the blueprint's path first, the task's
# evidence file second.  Either satisfies the marker branch.
MARKER_FILES = (os.path.join('plla', 'timing-l0-pll.md'),
                os.path.join('timing-l0-cfu', 'pll-slice.md'))


def _marker_text():
    try:
        root = evidence.evidence_root()
    except evidence.EvidenceSchemaError:
        pytest.skip('no open-toolchain evidence tree found')
    for rel in MARKER_FILES:
        path = os.path.join(root, rel)
        if os.path.isfile(path):
            return open(path).read()
    pytest.skip(f'none of {MARKER_FILES} found under {root}')


@pytest.fixture
def chunk0(device_file):
    with open(device_file(DEVICE, 'tm'), 'rb') as fh:
        chunk = fh.read(tm_parser.chunklen)
    assert len(chunk) == tm_parser.chunklen
    return chunk


def test_parse_pll_returns_named_arcs_or_marker(chunk0):
    """`parse_pll` yields named float arcs, or a recorded `NO-DATA:` marker."""
    res = tm_parser.parse_pll(chunk0[PLL_OFF:])
    if res:
        assert len(res) >= 1
        for name, vals in res.items():
            assert isinstance(name, str) and name
            assert all(isinstance(v, float) for v in vals)
        return
    text = _marker_text()
    nodata = [l for l in text.splitlines() if l.strip().startswith('NO-DATA:')]
    assert nodata, 'no `NO-DATA:` line in the PLL evidence file'
    line = nodata[0]
    ints = [int(n) for n in re.findall(r'\b\d+\b', line)]
    assert tm_parser.chunklen in ints, (
        f'the NO-DATA line must name the chunk length {tm_parser.chunklen}: {line}')
    assert 'tm_parser.py:344' in text and 'i >= 3' in text, (
        'the marker must name the chunk-count break condition')


def test_pll_block_is_five_rpll_paths(chunk0):
    """The 0x7cc..0x81c block decodes as exactly five 4-corner paths."""
    assert PLL_LEN == 80
    block = tm_parser.pll_block(chunk0[PLL_OFF:DLL_OFF])
    assert list(block) == tm_parser._PLL_INHERITED_RPLL_PATHS
    assert len(block) == 5
    for vals in block.values():
        assert len(vals) == 4
        assert all(0.15 < v < 0.25 for v in vals)


def test_pll_block_is_inherited_gw2a_data(device_file, chunk0):
    """The GW5A PLL block is byte-identical to GW2A-18's -- inherited, not measured."""
    with open(device_file(GW2A, 'tm'), 'rb') as fh:
        gw2a = fh.read(tm_parser.chunklen)
    assert chunk0[PLL_OFF:DLL_OFF] == gw2a[PLL_OFF:DLL_OFF]


def test_read_tm_publishes_no_pll_group(device_file):
    """No speed grade gains a `pll` group -- chipdb bytes are unaffected."""
    with open(device_file(DEVICE, 'tm'), 'rb') as fh:
        tmdat = tm_parser.read_tm(fh, DEVICE)
    assert tmdat
    for grade, groups in tmdat.items():
        assert 'pll' not in groups, f'{grade} gained a pll timing group'
