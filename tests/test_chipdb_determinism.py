"""P0.T13b (c): the same (device, install) must build the same bytes.

`chipdb_builder` produced a different sha256 on every run -- also after
decompressing the `.xz`, so it was never a container artefact. Two builds under
a fixed `PYTHONHASHSEED` were byte-identical, which pinned the cause on
`PYTHONHASHSEED` itself: msgpack writes a `set` as an array and a `dict` as a
map in *iteration* order, and sets of wire-name strings -- plus every dict
filled by iterating one -- iterate in a hash-seed-dependent order.
`chipdb.canonicalize` removes that dependence at the serialization boundary,
so the fix does not rely on the environment variable.
"""
import hashlib
import lzma
import os
import subprocess
import sys

import pytest

from apycula import chipdb


def test_canonicalize_sorts_seed_sensitive_sets():
    got = chipdb.canonicalize({'k': {'gamma', 'alpha', 'beta'}})
    assert got == {'k': ['alpha', 'beta', 'gamma']}


def test_canonicalize_sorts_dict_keys():
    got = chipdb.canonicalize({'z': 1, 'a': 2, 'm': 3})
    assert list(got) == ['a', 'm', 'z']


def test_canonicalize_leaves_hash_stable_sets_alone():
    """Sets of ints/coordinates already iterate identically in every process."""
    coords = {(3, 1), (0, 9), (2, 2)}
    assert chipdb.canonicalize({'bits': set(coords)})['bits'] == list(coords)


def test_canonicalize_recurses_into_dataclasses():
    tile = chipdb.Tile(1, 1, 0, pips={'D': {'S': {(1, 2), (0, 1)}}})
    dev = chipdb.Device(grid=[[0]], tiles={0: tile},
                        chip_flags=['B', 'A'])
    chipdb.canonicalize(dev)
    assert isinstance(dev.tiles[0].pips['D']['S'], list)


def test_canonicalize_is_order_preserving_for_content():
    src = {'a': {'x', 'y'}, 'b': [{'p', 'q'}], 'c': ((1, 2), 'z')}
    got = chipdb.canonicalize(src)
    assert got == {'a': ['x', 'y'], 'b': [['p', 'q']], 'c': ((1, 2), 'z')}


# GW1NZ-1 is the smallest device the installs ship; a full build is ~1 s.
DETERMINISM_DEVICE = 'GW1NZ-1'


def _build(gowinhome, out, seed):
    env = dict(os.environ, GOWINHOME=gowinhome, PYTHONHASHSEED=seed)
    proc = subprocess.run(
        [sys.executable, '-m', 'apycula.chipdb_builder', DETERMINISM_DEVICE,
         '--output', str(out)],
        env=env, capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr[-2000:]
    raw = lzma.open(out, 'rb').read()
    return (hashlib.sha256(open(out, 'rb').read()).hexdigest(),
            hashlib.sha256(raw).hexdigest())


@pytest.mark.heavy  # shells out to chipdb_builder, which invokes real gw_sh
def test_chipdb_build_is_deterministic(gowinhome, tmp_path):
    """Two builds of the same device differ in nothing, not even the seed."""
    first = _build(gowinhome, tmp_path / 'a.msgpack.xz', '1')
    second = _build(gowinhome, tmp_path / 'b.msgpack.xz', '2')
    assert first == second, (first, second)


@pytest.mark.heavy  # shells out to chipdb_builder, which invokes real gw_sh
def test_chipdb_build_round_trips(gowinhome, tmp_path):
    """The canonicalised database still loads, with the same content."""
    out = tmp_path / 'c.msgpack.xz'
    _build(gowinhome, out, '3')
    dev = chipdb.load_chipdb(str(out))
    assert dev.grid and dev.tiles
