"""P0.T11 no-regression guard: GW1N/GW2A parsing is untouched.

Deliberately named so `pytest -k "fse_version"` does NOT select it.
"""
import io
import struct

import pytest

from apycula import fse_parser


def _u32(v):
    return struct.pack('<i', v)


def _u16(v):
    return struct.pack('<H', v)


def _one_table_stream(typ, width, rows=2):
    body = _u32(1) + _u32(1) + _u32(1) + _u32(typ) + _u32(rows)
    body += b''.join(_u16(0x0101 + i) for i in range(width * rows))
    return io.BytesIO(body)


# (table type, expected typn, expected row width) for the non-5-series widths
# that existed before P0.T11 as bare literals in the dispatch.
LEGACY_WIDTHS = [
    (0x01, 'fuse', 150),
    (0x02, 'wire', 8),
    (0x03, 'wiresearch', 3),
    (0x04, 'const', 1),
    (0x05, 'shortval', 14),
    (0x06, 'alonenode', 15),
    (0x07, 'logicinfo', 3),
    (0x12, 'longfuse', 17),
    (0x17, 'longval', 28),
    (0x43, 'logicinfo', 3),
    (0x86, 'signedlogicinfo', 3),
    (0x8b, 'drpfuse', 10),
    (0x9a, 'logicinfo', 3),
]


# The IDE version each shape set stands for, for an explicit `shape_ctx`. The
# widths below are a property of the shape set, not of whichever install
# happens to be on the box, so the test passes one in rather than inheriting
# the ambient `GOWINHOME` (Standard 1.9.12.03 since 2026-09-04, C9/D79).
SHAPE_SET_VERSIONS = {
    'v1_9_10': '1.9.10.03',
    'v1_9_11plus': '1.9.11.03',
    'v1_9_12plus': '1.9.12.03',
}


@pytest.mark.parametrize('device', ['GW1N-9C', 'GW2A-18C'])
@pytest.mark.parametrize('shape_set', sorted(SHAPE_SET_VERSIONS))
@pytest.mark.parametrize('typ,typn,width', LEGACY_WIDTHS)
def test_legacy_device_row_widths_unchanged(device, shape_set, typ, typn,
                                            width):
    """Pre-5-series row widths, per shape set.

    `width` is the pre-1.9.11 width; a set that measured a different one is
    listed in `RECORDED_SET_DIFFERENCES` (P0.T13b measured `drpfuse` 10 -> 30
    u16 in 1.9.12.03) and that measured width is what is asserted there.
    """
    expected = RECORDED_SET_DIFFERENCES[shape_set].get(typn, width)
    shape_ctx = (SHAPE_SET_VERSIONS[shape_set], shape_set,
                 fse_parser.TABLE_SHAPES[shape_set])
    tmap = fse_parser.read_one_file(_one_table_stream(typ, expected), 0,
                                    device, shape_ctx=shape_ctx)
    assert typn in tmap, tmap.keys()
    table = tmap[typn][typ]
    assert len(table) == 2
    assert all(len(row) == expected for row in table)


def test_five_series_fuse_and_wire_widths_unchanged():
    tmap = fse_parser.read_one_file(_one_table_stream(0x01, 512, rows=1),
                                    0, 'GW5AST-138C')
    assert len(tmap['fuse'][0x01][0]) == 512
    tmap = fse_parser.read_one_file(_one_table_stream(0x02, 9), 0, 'GW5AST-138C')
    assert all(len(row) == 9 for row in tmap['wire'][0x02])


# The only flat widths that differ between shape sets, and why. Anything else
# differing means a width changed without a recorded measurement behind it.
RECORDED_SET_DIFFERENCES = {
    'v1_9_10': {},
    'v1_9_11plus': {},
    # P0.T13b: `drpfuse` rows grew 10 -> 30 u16 in Gowin IDE 1.9.12.03.
    'v1_9_12plus': {'drpfuse': 30},
}


def test_shape_sets_differ_only_where_measured():
    """Every flat-width difference between shape sets is a recorded one.

    P0.T11 shipped descriptors only. P0.T12 made `longfuse` per-subtype (in
    `TABLE_SUBTYPE_SHAPES`, not here) and P0.T13b widened `drpfuse` for
    1.9.12. Any other divergence would silently change GW1N/GW2A parsing on a
    1.9.11/1.9.12 install.
    """
    base = fse_parser.TABLE_SHAPES['v1_9_10']
    for name, shapes in fse_parser.TABLE_SHAPES.items():
        expected = dict(base, **RECORDED_SET_DIFFERENCES[name])
        assert shapes == expected, (name, shapes)


def test_pre_5series_keeps_flat_longfuse_width_on_every_shape_set():
    """P0.T13b: the 0x35/0x36 -> 14 override is 5-series only.

    P0.T12 keyed it on the IDE version alone, so every pre-5-series `.fse`
    desynced at its first 0x35 table on a 1.9.11+ install.
    """
    for name, shapes in fse_parser.TABLE_SHAPES.items():
        for typ in (0x12, 0x13, 0x35, 0x36, 0x3a):
            assert fse_parser.row_width(
                name, shapes, 'longfuse', typ,
                fse_parser.device_series('GW1N-9C')) == 17
        assert fse_parser.row_width(
            name, shapes, 'longfuse', 0x35,
            fse_parser.device_series('GW5AST-138C')) == (
                14 if name != 'v1_9_10' else 17)


def test_gw5ast_138c_still_routes_to_logicinfo_for_0x43():
    tmap = fse_parser.read_one_file(_one_table_stream(0x43, 3), 0, 'GW5AST-138C')
    assert 'logicinfo' in tmap and 'signedlogicinfo' not in tmap
    tmap = fse_parser.read_one_file(_one_table_stream(0x43, 3), 0, 'GW5AT-138')
    assert 'signedlogicinfo' in tmap and 'logicinfo' not in tmap


def test_known_table_types_all_dispatch():
    """`_KNOWN_TABLE_TYPES` feeds the desync realignment probe.

    A type listed there but absent from the dispatch would make the probe
    accept a bogus realignment and report a wrong `found_row_width`, so every
    listed type must really be understood by `read_one_file`.
    """
    for typ in sorted(fse_parser._KNOWN_TABLE_TYPES):
        stream = io.BytesIO(_u32(1) + _u32(1) + _u32(1)
                            + _u32(typ) + _u32(1) + b'\0' * 8192)
        fse_parser.read_one_file(stream, 0, 'GW1N-9C')
