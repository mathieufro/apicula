"""P0.T13b (a): the `drpfuse` table row width is version-keyed data, not 10.

Gowin IDE 1.9.12.03 widened the `drpfuse` table (type `0x8b`) row from 10 to
30 u16. Only `GW5A-25A` and `GW5AT-60B` ship such a table (`GW5AST-138C` ships
none), which is why the 138C builds never saw it and the 25A/60B builds died
with `FseShapeError ... table=drpfuse expected=10 found=30`.
"""
import io
import os
import struct

import pytest

from apycula import fse_parser


def _u32(v):
    return struct.pack('<i', v)


def _drpfuse_stream(width, rows=2, trailer=0x02):
    """One 0x8b table `width` u16 wide, followed by a known table tag."""
    body = _u32(1) + _u32(1) + _u32(1) + _u32(0x8b) + _u32(rows)
    body += b''.join(struct.pack('<H', 0x0101 + i) for i in range(width * rows))
    body += _u32(trailer)
    return io.BytesIO(body)


@pytest.mark.parametrize('version,shape_set,width', [
    ('1.9.10.03', 'v1_9_10', 10),
    ('1.9.11.03', 'v1_9_11plus', 10),
    ('1.9.12.03', 'v1_9_12plus', 30),
    ('1.9.13.01', 'v1_9_12plus', 30),
])
def test_fse_drpfuse_width_is_selected_by_ide_version(version, shape_set, width):
    name, shapes = fse_parser.select_shapes(version)
    assert name == shape_set
    assert shapes['drpfuse'] == width


def test_fse_drpfuse_width_is_not_per_subtype_or_per_device():
    """0x8b is the only drpfuse subtype and carries no per-series override."""
    for shape_set, shapes in fse_parser.TABLE_SHAPES.items():
        for series in (fse_parser.SERIES_GW5A, fse_parser.SERIES_DEFAULT):
            assert fse_parser.row_width(shape_set, shapes, 'drpfuse',
                                        0x8b, series) == shapes['drpfuse']


@pytest.mark.parametrize('version,width', [('1.9.11.03', 10),
                                           ('1.9.12.03', 30)])
def test_fse_drpfuse_reads_the_selected_width(monkeypatch, version, width):
    monkeypatch.setenv('GOWIN_IDE_VERSION', version)
    tmap = fse_parser.read_one_file(_drpfuse_stream(width), 0, 'GW5A-25A')
    assert all(len(row) == width for row in tmap['drpfuse'][0x8b])


def test_fse_drpfuse_mismatch_raises_named_error(monkeypatch):
    """A width the file contradicts is a loud, named error, not a desync."""
    monkeypatch.setenv('GOWIN_IDE_VERSION', '1.9.11.03')   # selects width 10
    with pytest.raises(fse_parser.FseShapeError) as exc:
        fse_parser.read_one_file(_drpfuse_stream(30), 0, 'GW5A-25A')
    message = str(exc.value)
    for needle in ('ide_version=1.9.11.03', 'shape_set=v1_9_11plus',
                   'table=drpfuse', 'expected_row_width=10',
                   'found_row_width=30'):
        assert needle in message, message


@pytest.mark.parametrize('device', ['GW5A-25A', 'GW5AT-60B'])
def test_fse_drpfuse_devices_parse_to_eof(device, device_file, gowinhome,
                                          monkeypatch):
    """The two devices that carry a drpfuse table parse to EOF (V2's S3)."""
    monkeypatch.setenv('GOWINHOME', gowinhome)
    path = device_file(device, 'fse')
    with open(path, 'rb') as fh:
        tmap = fse_parser.read_fse(fh, device)
        assert fh.tell() == os.path.getsize(path)
    assert any('drpfuse' in tile for tile in tmap.values()
               if isinstance(tile, dict))
