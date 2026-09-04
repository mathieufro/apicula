"""P0.T14 -- proof that `conftest.py`'s fixtures actually resolve.

`test_conftest_fixtures_available`: `device_file('GW5AST-138C', 'fse')` must
name a file that exists on disk and is > 30_000_000 bytes (F62 records the
138C `.fse` at 30.8 MB). Skips (does not fail) when no Gowin install is
selected, same as every other fixture-dependent test in this suite.
"""
import os


def test_conftest_fixtures_available(device_file):
    path = device_file('GW5AST-138C', 'fse')
    assert os.path.isfile(path), path
    assert os.path.getsize(path) > 30_000_000, os.path.getsize(path)
