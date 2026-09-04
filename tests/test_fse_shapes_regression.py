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


@pytest.mark.parametrize('device', ['GW1N-9C', 'GW2A-18C'])
@pytest.mark.parametrize('typ,typn,width', LEGACY_WIDTHS)
def test_legacy_device_row_widths_unchanged(device, typ, typn, width):
    tmap = fse_parser.read_one_file(_one_table_stream(typ, width), 0, device)
    assert typn in tmap, tmap.keys()
    table = tmap[typn][typ]
    assert len(table) == 2
    assert all(len(row) == width for row in table)


def test_five_series_fuse_and_wire_widths_unchanged():
    tmap = fse_parser.read_one_file(_one_table_stream(0x01, 512, rows=1),
                                    0, 'GW5AST-138C')
    assert len(tmap['fuse'][0x01][0]) == 512
    tmap = fse_parser.read_one_file(_one_table_stream(0x02, 9), 0, 'GW5AST-138C')
    assert all(len(row) == 9 for row in tmap['wire'][0x02])


def test_shape_sets_agree_until_p0_t12_discriminates_longfuse():
    """P0.T11 ships descriptors only; no width VALUE changes between sets.

    P0.T12 is the task that makes `longfuse` data-driven. Until then every
    shape set must be identical, or GW1N/GW2A parsing would silently change on
    a 1.9.11/1.9.12 install.
    """
    base = fse_parser.TABLE_SHAPES['v1_9_10']
    for name, shapes in fse_parser.TABLE_SHAPES.items():
        assert shapes == base, (name, shapes)


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
