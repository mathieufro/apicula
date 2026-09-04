"""P0.T13 -- `.dat` header layout drift between Gowin IDE 1.9.11 and 1.9.12.

`pytest -k "dat_version"` must select exactly the tests in this module and
`pytest -k "dat_gw5a_stuff"` exactly those in `tests/test_dat_gw5a_stuff.py`.

Root cause under test: 1.9.12.03 grew a three-u16 field in front of `partType`
at the 0x7b4a4 anchor and dropped the pad word behind it, so `partType` moved
+6 and the 5-series table block moved +4. Reading `partType` at the 1.9.11
offset yields 0xffff on a GW5A* part, the 5-series branch is skipped and the
build dies far away in `chipdb.py:fse_create_5a138_clocks` with
``AttributeError: 'Datfile' object has no attribute 'gw5aStuff'``.
"""
import os
import struct

import pytest

from apycula import dat_parser


ANCHOR = dat_parser.DAT_HEADER_ANCHOR


def _dat_bytes(pre_words, part_type, tail=b''):
    """A synthetic `.dat` whose header sits at the real anchor."""
    buf = bytearray(b'\x00' * ANCHOR)
    for word in pre_words:
        buf += struct.pack('<H', word & 0xffff)
    buf += struct.pack('<H', part_type & 0xffff)
    buf += tail
    return bytes(buf)


def test_dat_version_shape_sets_are_named_not_hardcoded():
    assert set(dat_parser.DAT_HEADER_SHAPES) == {'v1_9_11minus', 'v1_9_12plus'}
    assert dat_parser.DEFAULT_DAT_SHAPE_SET == 'v1_9_11minus'
    old = dat_parser.DAT_HEADER_SHAPES['v1_9_11minus']
    new = dat_parser.DAT_HEADER_SHAPES['v1_9_12plus']
    # the historical layout, transcribed from the literals it replaced
    assert dat_parser.part_type_offset(old) == 0x7b4a4
    assert dat_parser.part_type_offset(old) + old['rs_table_delta'] == 0x7b4a8
    # 1.9.12: partType +6, table block +4 -- the +4 is the whole file's size delta
    assert dat_parser.part_type_offset(new) == 0x7b4aa
    assert dat_parser.part_type_offset(new) + new['rs_table_delta'] == 0x7b4ac


@pytest.mark.parametrize('version,expected', [
    ('1.9.9.01', 'v1_9_11minus'),
    ('1.9.10.03', 'v1_9_11minus'),
    ('1.9.11.03', 'v1_9_11minus'),
    ('1.9.12.03', 'v1_9_12plus'),
    ('1.9.13.00', 'v1_9_12plus'),
    ('1.10.0.00', 'v1_9_12plus'),
    ('unknown', 'v1_9_11minus'),
    ('', 'v1_9_11minus'),
])
def test_dat_version_selects_layout(version, expected):
    name, shape = dat_parser.select_dat_header(version)
    assert name == expected
    assert shape is dat_parser.DAT_HEADER_SHAPES[expected]


def test_dat_version_part_types_by_layout_reads_both_offsets():
    data = _dat_bytes([0xffff, 0xffff, 0xffff], 2, tail=b'\x00' * 0x30000)
    by_layout = dat_parser.part_types_by_layout(data)
    assert by_layout == {'v1_9_11minus': 0xffff, 'v1_9_12plus': 2}


def _headered(data, version):
    """A `Datfile` with only its header state initialised.

    The synthetic buffers here carry a header and nothing else, so the full
    constructor would die in `read_primitives` long before reaching the code
    under test; the confirmations are what these tests are about.
    """
    dat = dat_parser.Datfile.__new__(dat_parser.Datfile)
    dat.data = data
    dat.ide_version = version
    dat.dat_shape_set, dat._dat_header = dat_parser.select_dat_header(version)
    dat._part_type_offset = dat_parser.part_type_offset(dat._dat_header)
    dat._rs_table_offset = (dat._part_type_offset
                            + dat._dat_header['rs_table_delta'])
    return dat


def test_dat_version_drift_raises_named_error():
    """A 1.9.12-shaped file read with the 1.9.11 layout must not go quiet."""
    data = _dat_bytes([0xffff, 0xffff, 0xffff], 2, tail=b'\x00' * 0x30000)
    dat = _headered(data, '1.9.11.03')
    with pytest.raises(dat_parser.DatLayoutError) as excinfo:
        dat._confirm_dat_header('GW5AST-138C.dat')
    msg = str(excinfo.value)
    for needle in ('1.9.11.03', 'v1_9_11minus', '0x7b4a4', '0xffff',
                   'v1_9_12plus', 'gw5aStuff'):
        assert needle in msg, msg


def test_dat_version_correct_layout_confirms_silently():
    data = _dat_bytes([0xffff, 0xffff, 0xffff], 2, tail=b'\x00' * 0x30000)
    assert _headered(data, '1.9.12.03')._confirm_dat_header('x.dat') is None
    old = _dat_bytes([], 2, tail=b'\x00' * 0x30000)
    assert _headered(old, '1.9.11.03')._confirm_dat_header('x.dat') is None


def test_dat_version_unknown_part_type_without_5a_alternative_is_tolerated():
    """Upstream tolerance is preserved: GW1NS-4C declares partType 0x20."""
    data = _dat_bytes([1, 0x26, 7], 0x20, tail=b'\x00' * 0x10)
    dat = _headered(data, '1.9.12.03')
    assert dat._confirm_dat_header('GW1NS-4C.dat') is None
    assert dat_parser.part_types_by_layout(data)['v1_9_12plus'] == 0x20


def test_dat_version_rs_table_contradicted_by_grid_raises():
    """The block start is confirmed against the grid the same file yielded."""
    data = _dat_bytes([0xffff, 0xffff, 0xffff], 2, tail=b'\x00' * 0x30000)
    dat = _headered(data, '1.9.12.03')
    # a grid whose bounds the all-zero hiq/viq quad cannot sit inside
    dat.grid = dat_parser.Grid(num_rows=0, num_cols=0, center_x=0,
                               center_y=0, rows=[])
    with pytest.raises(dat_parser.DatLayoutError) as excinfo:
        dat._confirm_rs_table('GW5AST-138C.dat')
    msg = str(excinfo.value)
    for needle in ('v1_9_12plus', 'TopHiq', 'grid'):
        assert needle in msg, msg


def test_dat_version_rs_table_past_eof_raises():
    dat = _headered(_dat_bytes([0xffff, 0xffff, 0xffff], 2), '1.9.12.03')
    dat.grid = dat_parser.Grid(num_rows=1, num_cols=1, center_x=0,
                               center_y=0, rows=[['C']])
    with pytest.raises(dat_parser.DatLayoutError) as excinfo:
        dat._confirm_rs_table('GW5AST-138C.dat')
    assert 'the file ends at' in str(excinfo.value)
