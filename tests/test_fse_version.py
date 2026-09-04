"""P0.T11 — version detection and the named `.fse` parser error.

`pytest -k "fse_version"` must select exactly the two tests in this module, so no
other test may live here (the no-regression suite is
`tests/test_fse_shapes_regression.py`).
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
SELECTED = ('/Users/alex/fine-line/.atelier/pipelines/'
            '2026-09-03-open-toolchain-gw5ast-7e84/evidence/_runs/gowinhome.selected')


def _selected_gowinhome():
    gowinhome = os.environ.get('GOWINHOME')
    if gowinhome:
        return gowinhome
    try:
        with open(SELECTED) as fh:
            return fh.read().strip()
    except OSError:
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
