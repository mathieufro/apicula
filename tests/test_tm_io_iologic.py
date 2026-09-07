"""IO / IOLOGIC timing groups of the `.tm` file (`P3.T32`).

The claim under test is the one `doc/timing-io-iologic.md` records: both
blocks decode with a determinate shape, both are inherited GW2A bytes, and
neither can be published as a GW5AST-138C timing model.
"""
import hashlib
import os

import pytest

from apycula import tm_parser

CHUNK = tm_parser.chunklen
IREGOREG_OFF = 0x306c
IO_OFF = 0x3278
IODELAY_OFF = 0x3728

# The exact source line `read_tm` uses to stop before the device-specific
# payload. Phase 6 owns it; this phase must leave it byte-for-byte alone.
BREAK_LINE = (
    "        if i >= 3 and device in {'GW5A-25A', 'GW5AT-60B', 'GW5AST-138C'}:")


@pytest.fixture
def chunk0(device_file):
    with open(device_file('GW5AST-138C', 'tm'), 'rb') as fh:
        return fh.read(CHUNK)


def _block(path, offset, end, chunk=0):
    with open(path, 'rb') as fh:
        data = fh.read(CHUNK * (chunk + 1))[CHUNK * chunk:]
    return data[offset:end]


def test_parse_io_returns_dict_or_nodata(chunk0):
    """`parse_io` publishes arcs, or says in writing why it publishes none."""
    result = tm_parser.parse_io(chunk0[IO_OFF:])
    assert isinstance(result, dict)
    if isinstance(result, tm_parser.NoData):
        assert result.group == 'io'
        assert result.reason.strip()
        assert not result, 'a NoData group must be falsy so read_tm skips it'
    else:
        assert len(result) >= 1


def test_parse_iregoreg_returns_dict_or_nodata(chunk0):
    """`parse_iregoreg` publishes arcs, or says why it publishes none."""
    result = tm_parser.parse_iregoreg(chunk0[IREGOREG_OFF:])
    assert isinstance(result, dict)
    if isinstance(result, tm_parser.NoData):
        assert result.group == 'iregoreg'
        assert result.reason.strip()
        assert not result, 'a NoData group must be falsy so read_tm skips it'
    else:
        assert len(result) >= 1


def test_tm_parser_break_line_unchanged():
    """The chunk-3 break stays byte-for-byte as Phase 6 will find it."""
    src = os.path.join(os.path.dirname(tm_parser.__file__), 'tm_parser.py')
    with open(src) as fh:
        lines = fh.read().splitlines()
    assert lines.count(BREAK_LINE) == 1


def test_io_block_decodes_five_records_one_path_each(chunk0):
    """The 0x3278 block round-trips as five 240-byte records, one path each."""
    block = tm_parser.io_block(chunk0[IO_OFF:])
    assert len(block) == 5
    assert all(len(v) == 4 for v in block.values())
    assert [round(max(v), 4) for v in block.values()] == [
        0.6875, 0.5865, 0.5385, 0.819, 0.663]


def test_iregoreg_block_decodes_thirty_two_paths(chunk0):
    """The 0x306c block round-trips as 2 + 30 four-float paths."""
    block = tm_parser.iregoreg_block(chunk0[IREGOREG_OFF:])
    assert len(block) == 32
    assert all(len(v) == 4 for v in block.values())
    assert round(block['path_0'][0], 4) == 0.341
    assert round(block['path_31'][0], 4) == 1.289


def test_io_blocks_are_inherited_gw2a_bytes(gowinhome):
    """Both blocks are byte-identical across GW2A and GW5A -- not re-characterised."""
    def digest(device, offset, end):
        path = f'{gowinhome}/IDE/share/device/{device}/{device}.tm'
        if not os.path.isfile(path):
            pytest.skip(f'{device}.tm is not in this install')
        return hashlib.sha256(_block(path, offset, end)).hexdigest()[:12]

    for offset, end in ((IREGOREG_OFF, IO_OFF), (IO_OFF, IODELAY_OFF)):
        ours = digest('GW5AST-138C', offset, end)
        assert ours == digest('GW2A-18', offset, end)
        assert ours != digest('GW1N-9', offset, end)


def test_no_io_group_reaches_the_chipdb(device_file):
    """`read_tm` publishes no `io`/`iregoreg` group for this die."""
    with open(device_file('GW5AST-138C', 'tm'), 'rb') as fh:
        tmdat = tm_parser.read_tm(fh, 'GW5AST-138C')
    assert tmdat
    for grade, groups in tmdat.items():
        assert 'io' not in groups, grade
        assert 'iregoreg' not in groups, grade
