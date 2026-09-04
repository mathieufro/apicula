"""Fuse attribution: which bits moved, in which tile, for which attribute.

`P0.T27` (`spec-harness.md` §6, field `fuses_moved`). Module rooting is
fixed: this module is always addressed as
`fuzz.gw5ast138c.harness.attribute` and run from `$FL/apicula`; it never
depends on cwd -- the design directory is always passed explicitly via
`--design-dir`.

What this module does, and does not, do:

* It numpy-diffs two fuse bitmaps, tile by tile, and reports every bit that
  moved as `(tile_x, tile_y, table, bit)` -- the in-tree precedent is
  `legacy/fuzzer.py`'s `find_bits:79` (read-only: a symmetric-difference over
  a stack of configuration words). `equiv.py`'s raw residual (`D35`, §5.1b)
  answers "do these two `.fs` differ anywhere"; this module answers "where,
  in tile terms" -- the two are complementary, not a duplicate (`equiv.py` is
  frozen for this task and is only ever imported here, never edited).
* `table` identifies the fuse table shape a tile uses -- apicula's `Tile.ttyp`
  (`apycula/chipdb.py` `class Tile`) for a real bitstream, or whatever token
  the caller supplies for a synthetic one. It is a classifier, not a decode:
  this module does not resolve a bit to an attribute *name* (`gowin_unpack`
  and `equiv.py`'s `canon_attr` already do that at the netlist level); it
  only localises *where* the fuse lives, which is what a sweep needs to
  isolate which parameter moved which bits (`P0.T20`'s Gray-coded sweeps
  exist precisely so this localisation is unambiguous).
* The presence-diff helper (`presence_diff`) is the same core diff, applied
  to a baseline build with the primitive absent and a build with exactly one
  instance placed -- the maintainer's documented method for establishing
  block affiliation (`apycula/chipdb.py:1509-1515`, read-only reference; that
  file is frozen for this phase and not edited here).
"""
import argparse
import collections
import json
import os
import sys

import numpy as np

DEVICE = "GW5AST-138C"

#: One moved fuse: which tile, which fuse table the tile uses, and the flat
#: bit index (`row * tile_width + col`) within that tile's bitmap.
FuseDelta = collections.namedtuple("FuseDelta", "tile_x tile_y table bit")


# --------------------------------------------------------------------------
# 1. The core diff -- precedent: legacy/fuzzer.py find_bits:79 (read-only)
# --------------------------------------------------------------------------
def _as_bitmap(arr):
    """Coerce anything array-like (list-of-lists, numpy array, `None`) into a
    2-D `uint8` numpy array, `(0, 0)` for `None`/empty."""
    if arr is None:
        return np.zeros((0, 0), dtype=np.uint8)
    a = np.asarray(arr, dtype=np.uint8)
    if a.ndim == 1:
        a = a.reshape(1, -1)
    return a


def diff_tile_bitmaps(tiles_a, tiles_b):
    """Numpy-diff two `{(tile_x, tile_y): (table, bitmap)}` dicts.

    Every tile present on either side is compared; a tile absent on one side
    diffs against an all-zero bitmap of the other side's shape (so a whole
    tile appearing/disappearing is reported bit-by-bit, not swallowed). Two
    bitmaps of differing shape for the same tile are compared over their
    zero-padded union, so a genuine shape drift shows up as extra moved bits
    rather than raising.

    Returns a list of `FuseDelta`, sorted by `(tile_x, tile_y, bit)` so the
    output is deterministic run to run.
    """
    moved = []
    for key in sorted(set(tiles_a) | set(tiles_b)):
        table_a, arr_a = tiles_a.get(key, (None, None))
        table_b, arr_b = tiles_b.get(key, (None, None))
        table = table_a if table_a is not None else table_b

        a = _as_bitmap(arr_a)
        b = _as_bitmap(arr_b)
        h = max(a.shape[0], b.shape[0])
        w = max(a.shape[1], b.shape[1])
        if h == 0 or w == 0:
            continue
        pa = np.zeros((h, w), dtype=np.uint8)
        pb = np.zeros((h, w), dtype=np.uint8)
        pa[: a.shape[0], : a.shape[1]] = a
        pb[: b.shape[0], : b.shape[1]] = b

        rows, cols = np.where(pa != pb)
        tile_x, tile_y = key
        for r, c in zip(rows.tolist(), cols.tolist()):
            moved.append(FuseDelta(tile_x, tile_y, table, r * w + c))
    moved.sort(key=lambda fd: (fd.tile_x, fd.tile_y, fd.bit))
    return moved


# --------------------------------------------------------------------------
# 2. Bridging a real `.fs` into the same `{tile: (table, bitmap)}` shape
# --------------------------------------------------------------------------
def load_tile_bitmaps(fs_path, device=DEVICE, db=None):
    """Read one `.fs` and return `{(tile_x, tile_y): (table, bitmap)}`.

    `table` is `db[row, col].ttyp` -- the same fuse-table identifier
    `apycula/chipdb.py`'s `Tile` dataclass carries, so a `fuses_moved` row is
    traceable back to the vendor `.fse`/`.dat` table it came from. Uses
    `bslib.read_bitstream` (`apycula/bslib.py`, read-only) and
    `chipdb.tile_bitmap` (`apycula/chipdb.py`, read-only) -- the same two
    calls `equiv.py.unpack_netlist` makes, so the tile grid lines up with the
    one `equiv.py` diffs at the netlist level.
    """
    from apycula.bslib import read_bitstream
    from apycula import chipdb as _chipdb

    if db is None:
        from .equiv import load_db
        db = load_db(device)

    bitmap, _hdr, _ftr, _slots = read_bitstream(fs_path)
    bm = _chipdb.tile_bitmap(db, bitmap, empty=True)

    tiles = {}
    for (row, col), tile in bm.items():
        try:
            ttyp = db[row, col].ttyp
        except Exception:
            ttyp = None
        tiles[(col, row)] = (ttyp, tile)
    return tiles


def attribute_fs(vendor_fs, open_fs, device=DEVICE, db=None):
    """`fuses_moved` for one pair of `.fs` files: the real production path.

    `db` may be passed in (and shared across a sweep, `equiv.py.load_db`) to
    avoid reloading the chipdb per pair.
    """
    if db is None:
        from .equiv import load_db
        db = load_db(device)
    tiles_v = load_tile_bitmaps(vendor_fs, device=device, db=db)
    tiles_o = load_tile_bitmaps(open_fs, device=device, db=db)
    return diff_tile_bitmaps(tiles_v, tiles_o)


def presence_diff(baseline, instance, device=DEVICE, db=None):
    """The presence-diff helper: baseline (primitive absent) vs one instance.

    Establishes block affiliation -- the maintainer's documented method
    (`apycula/chipdb.py:1509-1515`, read-only reference) -- by reusing the
    exact same diff as `attribute_fs`/`diff_tile_bitmaps`; only the semantics
    of the two inputs differ (an empty-design build vs a one-instance build),
    not the mechanism.

    Accepts either two `{tile: (table, bitmap)}` dicts (the synthetic-test
    path -- no Gowin install needed) or two `.fs` paths (the production
    path, bridged through `load_tile_bitmaps`).
    """
    if isinstance(baseline, dict) and isinstance(instance, dict):
        return diff_tile_bitmaps(baseline, instance)
    return attribute_fs(baseline, instance, device=device, db=db)


# --------------------------------------------------------------------------
# 3. CLI
# --------------------------------------------------------------------------
def build_parser():
    """Return this module's argparse parser.

    Every harness module parser carries a required `--design-dir` so no
    harness command depends on the current working directory
    (`spec-harness.md` §1, `spec.md` V5/V6).
    """
    parser = argparse.ArgumentParser(prog="fuzz.gw5ast138c.harness.attribute")
    parser.add_argument(
        "--design-dir",
        required=True,
        help="Directory holding the test design for this run (never inferred from cwd).",
    )
    parser.add_argument("--device", default=DEVICE)
    parser.add_argument("--vendor-fs", default=None,
                        help="Override the vendor .fs path (default: equiv.VENDOR_FS "
                             "under --design-dir).")
    parser.add_argument("--open-fs", default=None,
                        help="Override the open-flow .fs path (default: equiv.OPEN_FS "
                             "under --design-dir).")
    parser.add_argument("--json", action="store_true")
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    from .equiv import VENDOR_FS, OPEN_FS

    design_dir = os.path.abspath(args.design_dir)
    vendor_fs = args.vendor_fs or os.path.join(design_dir, VENDOR_FS)
    open_fs = args.open_fs or os.path.join(design_dir, OPEN_FS)

    fuses_moved = attribute_fs(vendor_fs, open_fs, device=args.device)

    print(f"FUSES_MOVED {len(fuses_moved)}")
    for fd in fuses_moved[:32]:
        print(f"  tile=({fd.tile_x},{fd.tile_y}) table={fd.table} bit={fd.bit}")
    if len(fuses_moved) > 32:
        print(f"  ... and {len(fuses_moved) - 32} more")
    if args.json:
        print(json.dumps({"fuses_moved": [list(fd) for fd in fuses_moved]},
                         sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
