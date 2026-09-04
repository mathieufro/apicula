"""`P0.T27` -- fuse attribution: which bits moved, in which tile, for which
attribute.

Three tests, named by the blueprint. None needs a Gowin install or a real
bitstream: the core diff (`diff_tile_bitmaps`) and its two helpers are
exercised with synthetic numpy bitmaps, so the algebra is testable in
isolation (the real `.fs` pair is the Done-when command's job, via
`attribute_fs`).
"""
import numpy as np

from fuzz.gw5ast138c.harness.attribute import (
    FuseDelta,
    diff_tile_bitmaps,
    presence_diff,
)


def test_attribute_single_bit_localised():
    """Flip exactly 1 bit in a synthetic bitmap -> exactly 1 `FuseDelta`,
    all 4 tuple fields populated."""
    base = np.zeros((4, 6), dtype=np.uint8)
    flipped = base.copy()
    flipped[2, 3] = 1

    tiles_a = {(0, 0): ("longfuse", base)}
    tiles_b = {(0, 0): ("longfuse", flipped)}

    moved = diff_tile_bitmaps(tiles_a, tiles_b)

    assert len(moved) == 1
    fd = moved[0]
    assert isinstance(fd, FuseDelta)
    assert fd.tile_x == 0
    assert fd.tile_y == 0
    assert fd.table == "longfuse"
    assert fd.bit == 2 * base.shape[1] + 3
    # All 4 fields populated (none `None`).
    assert all(field is not None for field in fd)


def _gray_sequence(n_bits):
    """The standard binary-reflected Gray code for `n_bits`, as ints."""
    count = 1 << n_bits
    return [i ^ (i >> 1) for i in range(count)]


def _gray_bitmap(value, n_bits, shape=(1, 8)):
    """One synthetic tile bitmap: `value`'s `n_bits` written 1:1 into the
    first `n_bits` cells of a flattened `shape` bitmap -- a direct encoding
    where each Gray-code bit is exactly one physical fuse bit, so an adjacent
    pair (which differs in exactly one Gray-code bit, by construction of the
    Gray code) moves exactly one fuse."""
    flat = np.zeros(shape[0] * shape[1], dtype=np.uint8)
    for i in range(n_bits):
        flat[i] = (value >> i) & 1
    return flat.reshape(shape)


def test_attribute_gray_sweep_isolates_one_bit():
    """Over a 16-point Gray-coded sweep, every adjacent pair yields
    <= 2 moved fuse groups and >= 1 -- the property `P0.T20`'s Gray-coded
    sweeps rely on to make attribution unambiguous."""
    n_bits = 4  # 16 points
    values = _gray_sequence(n_bits)
    assert len(values) == 16

    bitmaps = [_gray_bitmap(v, n_bits) for v in values]

    for i in range(len(bitmaps) - 1):
        tiles_a = {(0, 0): ("shortval", bitmaps[i])}
        tiles_b = {(0, 0): ("shortval", bitmaps[i + 1])}
        moved = diff_tile_bitmaps(tiles_a, tiles_b)
        assert 1 <= len(moved) <= 2, (
            f"adjacent Gray pair {values[i]}->{values[i + 1]} moved "
            f"{len(moved)} fuse groups, expected 1-2")


def test_attribute_presence_diff_nonempty():
    """The empty-vs-one-instance diff (`presence_diff`) returns >= 1 moved
    fuse -- the block-affiliation method of `apycula/chipdb.py:1509-1515`."""
    empty = np.zeros((3, 5), dtype=np.uint8)
    one_instance = empty.copy()
    one_instance[0, 0] = 1
    one_instance[1, 4] = 1

    baseline_tiles = {(1, 2): ("const", empty)}
    instance_tiles = {(1, 2): ("const", one_instance)}

    moved = presence_diff(baseline_tiles, instance_tiles)

    assert len(moved) >= 1
    assert all(isinstance(fd, FuseDelta) for fd in moved)
