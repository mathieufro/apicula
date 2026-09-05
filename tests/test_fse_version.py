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
from fuzz.gw5ast138c.harness import paths


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
#: The recorded selection lives in the evidence tree, wherever that is
#: checked out (`$OTC_EVIDENCE`, else the sibling `open-toolchain` checkout).
SELECTED = (
    os.path.join(paths.otc_evidence(), '_runs', 'gowinhome.selected'),
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


def _parse_selected_fse(monkeypatch, path=None):
    """Parse a GW5AST-138C `.fse`, recording every longfuse width decision.

    `path` defaults to the selected install's copy; a 1.9.11 test passes the
    archived Education file instead (see `tests/conftest.py`).
    Returns (tiles, end_offset, [(typ, data_start, rows, derived, used)]).
    """
    if path is None:
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


# (IDE version, shape set) pairs the 14-u16 longfuse rule covers. 1.9.11.03 is
# read from the archived Education device tree: that install was removed from
# disk on 2026-09-04 (C9/D79), so the file, not the install, is the reference.
NARROW_LONGFUSE_VERSIONS = [
    ('1.9.11.03', 'v1_9_11plus'),
    ('1.9.12.03', 'v1_9_12plus'),
]


@pytest.mark.parametrize('ide_version,shape_set', NARROW_LONGFUSE_VERSIONS)
def test_fse_version_longfuse_width_is_derived(monkeypatch, archived_device_file,
                                               ide_version, shape_set):
    """The narrow longfuse width comes from the file, not from a constant.

    Run for both shape sets that carry the rule. The 1.9.11 case parses the
    archived Education `.fse` with `GOWIN_IDE_VERSION` forced; the 1.9.12 case
    parses the selected (Standard) install's own copy.
    """
    if ide_version == '1.9.11.03':
        path = archived_device_file('GW5AST-138C', 'fse')
    else:
        path = _selected_fse()
    monkeypatch.setenv('GOWIN_IDE_VERSION', ide_version)
    ver, active_set, shapes = fse_parser._active_shapes()
    assert (ver, active_set) == (ide_version, shape_set), (ver, active_set)
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

    _tiles, _end, seen = _parse_selected_fse(monkeypatch, path)
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


# --- P0.T13c: select_shapes must compare version tuples, not prefix-match ---

@pytest.mark.parametrize('version,shape_set', [
    ('1.8.06', 'v1_9_10'),
    ('1.9.9', 'v1_9_10'),
    ('1.9.10.03', 'v1_9_10'),
    ('1.9.11.03', 'v1_9_11plus'),
    ('1.9.12.03', 'v1_9_12plus'),
    ('1.9.13', 'v1_9_12plus'),
])
def test_fse_version_select_shapes_ordering(version, shape_set):
    """Pre-1.9.11 versions (e.g. 1.9.9, 1.8.06) must not fall through to
    v1_9_11plus just because they don't literally start with "1.9.10.".
    """
    name, shapes = fse_parser.select_shapes(version)
    assert name == shape_set
    assert shapes is fse_parser.TABLE_SHAPES[shape_set]


def test_fse_version_select_shapes_four_part_vs_three_part_threshold():
    """A 4-part version compares correctly against the 3-part thresholds."""
    # 1.9.11.03 has a non-empty 4th field but is still >= (1, 9, 11)
    assert fse_parser._version_tuple('1.9.11.03') == (1, 9, 11, 3)
    name, _shapes = fse_parser.select_shapes('1.9.11.03')
    assert name == 'v1_9_11plus'
    # a 4-part version just below the 1.9.11 threshold stays on the old set
    assert fse_parser._version_tuple('1.9.10.99') == (1, 9, 10, 99)
    name, _shapes = fse_parser.select_shapes('1.9.10.99')
    assert name == 'v1_9_10'


def test_fse_version_undetectable_raises_instead_of_falling_back(monkeypatch,
                                                                 tmp_path):
    """An undetectable IDE version is loud, never a silent shape-set default.

    `_active_shapes()` used to swallow `FseVersionError` and parse on with the
    pre-1.9.11 widths under `ide_version="unknown"` -- so a 5-series `.fse`
    from an install whose release notes are missing was read through the wrong
    row widths, and the error that eventually surfaced named the version as
    the one thing it could not name.
    """
    monkeypatch.delenv("GOWIN_IDE_VERSION", raising=False)
    monkeypatch.setenv("GOWINHOME", str(tmp_path))
    with pytest.raises(fse_parser.FseVersionError) as err:
        fse_parser._active_shapes()
    assert "GOWIN_IDE_VERSION" in str(err.value)
    assert str(tmp_path) in str(err.value)

    monkeypatch.delenv("GOWINHOME", raising=False)
    with pytest.raises(fse_parser.FseVersionError):
        fse_parser._active_shapes()


def test_fse_version_override_is_still_honoured(monkeypatch, tmp_path):
    """`GOWIN_IDE_VERSION` remains the documented way past a missing install."""
    monkeypatch.setenv("GOWINHOME", str(tmp_path))
    monkeypatch.setenv("GOWIN_IDE_VERSION", "1.9.11.03")
    ide_version, shape_set, shapes = fse_parser._active_shapes()
    assert (ide_version, shape_set) == ("1.9.11.03", "v1_9_11plus")
    assert shapes is fse_parser.TABLE_SHAPES["v1_9_11plus"]
