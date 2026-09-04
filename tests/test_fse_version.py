"""P0.T11 — version detection and the named `.fse` parser error.

`pytest -k "fse_version"` must select exactly the tests in this module, so no
other test may live here (the no-regression suite is
`tests/test_fse_shapes_regression.py`). P0.T12 added the two longfuse
width tests below.
"""
import io
import os
import re
import struct

import pytest

from apycula import fse_parser


def _u32(v):
    return struct.pack('<i', v)


def _u16(v):
    return struct.pack('<H', v)


def _mutated_longfuse_stream():
    """A minimal `read_one_file` body whose longfuse rows are 14 u16 wide.

    The parser reads them at the 1.9.10 width of 17, overruns into the following
    `const` table header and ends up reading a mutated 4-byte type whose high
    bytes are 0xFF -> an unknown table type, i.e. the real desync shape.
    """
    body = b''
    body += _u32(1)          # height
    body += _u32(1)          # width
    body += _u32(2)          # tables
    body += _u32(0x12)       # table 1: longfuse
    body += _u32(1)          # ... 1 row
    body += b''.join(_u16(0x0101 + i) for i in range(14))   # 14 u16, not 17
    body += _u32(0x04)       # table 2: const
    body += _u32(1)          # ... 1 row
    body += _u16(0xFFFF)     # the byte pair that becomes the mutated type
    return io.BytesIO(body)


# The pipeline records which of the two installed editions is the oracle of
# record. `P0.T14`'s conftest will own this lookup; until it lands the test
# resolves the install itself so `pytest -k fse_version` needs no environment.
# P0.T12: the live pipeline tree is the umbrella *worktree* copy; the main
# checkout carries only `impl/`. Both are tried, worktree first.
SELECTED = (
    '/Users/alex/fine-line/.atelier/worktrees/'
    '2026-09-03-open-toolchain-gw5ast-7e84/.atelier/pipelines/'
    '2026-09-03-open-toolchain-gw5ast-7e84/evidence/_runs/gowinhome.selected',
    '/Users/alex/fine-line/.atelier/pipelines/'
    '2026-09-03-open-toolchain-gw5ast-7e84/evidence/_runs/gowinhome.selected',
)


def _selected_gowinhome():
    gowinhome = os.environ.get('GOWINHOME')
    if gowinhome:
        return gowinhome
    for path in SELECTED:
        try:
            with open(path) as fh:
                return fh.read().strip()
        except OSError:
            continue
    return ''


def test_fse_version_detect_names_installed_ide():
    gowinhome = _selected_gowinhome()
    if not os.path.isdir(gowinhome):
        pytest.skip('no Gowin install selected (GOWINHOME unset, '
                    'gowinhome.selected absent)')
    version = fse_parser.detect_ide_version(gowinhome)
    assert isinstance(version, str)
    assert re.match(r'^1\.9\.1[12]\.03$', version), version


def test_fse_version_mismatch_message():
    with pytest.raises(fse_parser.FseShapeError) as excinfo:
        fse_parser.read_one_file(_mutated_longfuse_stream(), 0, 'GW5AST-138C')
    msg = str(excinfo.value)
    for needle in ('ide_version=', 'shape_set=',
                   'expected_row_width=', 'found_row_width='):
        assert needle in msg, msg
    assert len(msg.split()) >= 6, msg
    # the diagnostic must name the table that actually desynced, and the two
    # widths that disagree (17 configured vs 14 in the data).
    assert 'table=longfuse' in msg, msg
    assert 'expected_row_width=17' in msg, msg
    assert 'found_row_width=14' in msg, msg


# --- P0.T12: the longfuse 17 -> 14 u16 desync -------------------------------

FSE_REL = 'IDE/share/device/GW5AST-138C/GW5AST-138C.fse'
# The two offsets the parser used to die at, Education and Standard (F13).
FIRST_DESYNC_EDU = 0xe30db0
FIRST_DESYNC_STD = 0xe30fc2
# longfuse subtypes that are 14 u16 wide from IDE 1.9.11 on.
NARROW_LONGFUSE = (0x35, 0x36)


def _selected_fse():
    gowinhome = _selected_gowinhome()
    if not gowinhome:
        return None
    path = os.path.join(gowinhome, FSE_REL)
    return path if os.path.isfile(path) else None


def _parse_selected_fse(monkeypatch):
    """Parse the installed `.fse`, recording every longfuse width decision.

    Returns (tiles, end_offset, [(typ, data_start, rows, derived, used)]).
    """
    path = _selected_fse()
    if path is None:
        pytest.skip('no GW5AST-138C.fse in the selected Gowin install')
    seen = []
    real = fse_parser._confirm_row_width

    def spy(f, rows, data_start, expected, table, ide_version, shape_set):
        derived = fse_parser.derive_row_width(f, rows, data_start)
        used = real(f, rows, data_start, expected, table,
                    ide_version, shape_set)
        seen.append((None, data_start, rows, derived, used))
        return used

    monkeypatch.setattr(fse_parser, '_confirm_row_width', spy)
    with open(path, 'rb') as fh:
        tiles = fse_parser.read_fse(fh, 'GW5AST-138C')
        end = fh.tell()
    return tiles, end, seen


def test_fse_version_longfuse_width_is_derived(monkeypatch):
    """The narrow longfuse width comes from the file, not from a constant."""
    _ver, shape_set, shapes = fse_parser._active_shapes()
    assert shape_set == 'v1_9_11plus', shape_set
    # the flat descriptor is still the historical 17; 14 is a subtype override
    assert shapes['longfuse'] == 17, shapes['longfuse']
    # the 14-wide override is scoped to the 5-series (P0.T13b); a pre-5-series
    # device on the same install keeps the flat 17
    gw5a = fse_parser.device_series('GW5AST-138C')
    for typ in NARROW_LONGFUSE:
        assert fse_parser.row_width(shape_set, shapes, 'longfuse', typ,
                                    gw5a) == 14
        assert fse_parser.row_width(shape_set, shapes, 'longfuse', typ,
                                    fse_parser.device_series('GW1N-9C')) == 17
        assert fse_parser.row_width('v1_9_10', TABLE_SHAPES_V1_9_10,
                                    'longfuse', typ, gw5a) == 17

    _tiles, _end, seen = _parse_selected_fse(monkeypatch)
    assert seen, 'no longfuse table was read at all'
    narrow = [row for row in seen if row[4] == 14]
    assert len(narrow) >= 1, [(hex(r[1]), r[3], r[4]) for r in seen]
    # at least one 14-wide read is confirmed by the file's own layout (a table
    # that is the last of its tile is followed by a tile type, not a table
    # type, so its probe is legitimately inconclusive)
    confirmed = [r for r in narrow if r[3] and r[3][0] == 14]
    assert confirmed, [(hex(r[1]), r[3], r[4]) for r in narrow]
    # and no read used a width the data positively contradicts
    for _typ, data_start, _rows, derived, used in seen:
        assert not derived or used in derived, (hex(data_start), derived, used)


def test_fse_version_first_desync_offset_passed(monkeypatch):
    """Parsing runs past the historical desync without an `FseShapeError`."""
    tiles, end, _seen = _parse_selected_fse(monkeypatch)
    assert tiles
    assert end > FIRST_DESYNC_STD > FIRST_DESYNC_EDU, hex(end)


TABLE_SHAPES_V1_9_10 = fse_parser.TABLE_SHAPES['v1_9_10']
