"""The harness self-tests that run at the head of every batch (`P0.T29`).

Two of them, and a batch's evidence rows are worth nothing without both
(`spec-harness.md` §9, `spec.md` `S5`/`S6b`):

* ``--inject-one-fuse`` flips **exactly one** fuse bit in the open-flow
  bitstream of a *passing* pair and runs the checker over it.  Expected
  stdout, exactly::

      SELFTEST ok: 1 difference reported, 0 spurious

  0 differences means the checker masks too much; more than 1 means the
  canonicalisation is unstable.  Either is a harness defect and blocks every
  evidence row produced after it.

  The passing pair is the open-flow ``.fs`` against **itself**: that is the
  only pair guaranteed to compare clean before any primitive has been closed,
  and the property under test -- can the checker see one flipped fuse? -- is
  the same either way.  The unmodified pair is compared first and must report
  nothing, so a checker that already reports differences on identical inputs
  fails here rather than swallowing the injected one.

* ``--unpacker-completeness`` implements §5.1c / `S6b`: unpacking the
  open-flow bitstream must recover **every** cell the nextpnr placement
  contains (`c1` of §5.4) and **no** tile may carry set fuses the unpacker
  cannot attribute to something it decoded.  Expected stdout, exactly::

      COMPLETENESS ok: 0 unattributed tiles, 0 missing cells

  A failure blocks the batch, because without it both sides of every diff are
  decoded through the same blind spot.

Module rooting is fixed: this module is always addressed as
`fuzz.gw5ast138c.harness.selftest` and run from `$FL/apicula`; it never
depends on cwd -- the design directory is always passed explicitly via
`--design-dir`.
"""
import argparse
import os
import sys
import tempfile

from fuzz.gw5ast138c.harness import equiv


#: Exact stdout of a passing `--inject-one-fuse` (§9).
SELFTEST_OK = "SELFTEST ok: 1 difference reported, 0 spurious"
#: Exact stdout of a passing `--unpacker-completeness` (§9).
COMPLETENESS_OK = "COMPLETENESS ok: 0 unattributed tiles, 0 missing cells"


class SelftestError(Exception):
    """A harness defect the self-test refuses to let a batch run past."""


# --------------------------------------------------------------------------
# 1. Injecting one fuse (`S5`, §9)
# --------------------------------------------------------------------------
def tile_origin(db, row, col):
    """The `(y, x)` origin of tile `(row, col)` in the whole-device bitmap.

    `chipdb.tile_bitmap()` walks the grid accumulating tile widths and
    heights; this is the same walk stopped at one tile, so a tile-local fuse
    coordinate can be turned back into a bitmap coordinate.
    """
    y = 0
    for idx in range(db.rows):
        x = 0
        height = 0
        for jdx in range(db.cols):
            td = db[idx, jdx]
            height = td.height
            if (idx, jdx) == (row, col):
                return y, x
            x += td.width
        y += height
    raise SelftestError(
        f"tile ({row},{col}) is not on the {db.rows}x{db.cols} grid")


def choose_fuse(db, tiles, netlist):
    """Pick the one fuse to flip: a clear single-bit LUT flag of a used LUT.

    Deterministic (first in sorted order), so two runs flip the same bit, and
    chosen inside a tile the unpacker already decodes a cell from, so the flip
    lands in *modelled* configuration and must show up as one attribute
    difference rather than as an unattributable residual bit.  A flag of
    exactly one bit is required -- a multi-bit flag would be more than one
    flipped fuse.
    """
    for cell in sorted(netlist.cells, key=lambda c: (c.y, c.x, c.z, c.type)):
        if cell.type != "LUT":
            continue
        tile = tiles.get((cell.y, cell.x))
        if tile is None:
            continue
        bel = db[cell.y, cell.x].bels.get(f"LUT{cell.z}")
        if bel is None:
            continue
        for flag, bits in sorted(bel.flags.items()):
            if len(bits) != 1:
                continue
            (r, c), = bits
            if tile[r][c] == 0:
                return {"tile": (cell.y, cell.x), "bit": (r, c),
                        "cell": cell, "flag": flag}
    raise SelftestError(
        "no clear single-bit LUT flag in any decoded tile: there is no fuse to "
        "inject that the unpacker models, so the self-test cannot run")


def inject_fuse(fs_path, db, out_path, netlist=None):
    """Write `fs_path` back out with exactly one extra fuse bit set."""
    from apycula import bitmatrix, chipdb as _chipdb
    from apycula.bslib import read_bitstream, write_bitstream

    bits, hdr, ftr, slots = read_bitstream(fs_path)
    tiles = _chipdb.tile_bitmap(db, bits)
    if netlist is None:
        netlist = equiv.unpack_netlist(fs_path, db=db, noalu=True)
    chosen = choose_fuse(db, tiles, netlist)

    (row, col), (r, c) = chosen["tile"], chosen["bit"]
    y, x = tile_origin(db, row, col)
    if bits[y + r][x + c] != 0:
        raise SelftestError("the chosen fuse is not clear in the bitmap")
    bits[y + r][x + c] = 1
    # `read_bitstream` returns `transpose(fliplr(lines))` for the 5A series and
    # `write_bitstream` writes `fliplr(bs)` as its lines, so the inverse of the
    # read is a single transpose -- the dance `equiv.decode_check_c2` documents.
    write_bitstream(out_path, bitmatrix.transpose(bits),
                    [bytearray(h) for h in hdr], [bytearray(f) for f in ftr],
                    False, slots)
    chosen["path"] = out_path
    return chosen


def reported_differences(result):
    """The differences the checker enumerates: the three `E0` sets plus §5.1b.

    Pips are excluded on purpose -- routing is never a verdict term (`D32`).
    An unexplained residual bit counts, because a fuse no cell explains is
    exactly the difference §5.1b exists to catch.
    """
    sets = sum(result.diff_count.get(k, 0) for k in ("cells", "attrs", "conns"))
    residual = result.residual or {}
    return sets + (residual.get("unexplained_total_bits", 0) or 0)


def inject_one_fuse(design_dir, open_fs=None, device=equiv.DEVICE, db=None,
                    mask_path=None, compare=None, out_path=None):
    """`S5`'s injected-fuse self-test.  Returns the report; raises on defect."""
    design_dir = os.path.abspath(design_dir)
    open_fs = open_fs or os.path.join(design_dir, equiv.OPEN_FS)
    if not os.path.isfile(open_fs):
        raise SelftestError(
            f"no open-flow bitstream at {open_fs}: the self-test needs a "
            "passing pair before it can inject anything")

    db = db if db is not None else equiv.load_db(device)
    mask = equiv.load_mask(mask_path)
    compare = compare or equiv.compare_e0

    base = equiv.unpack_netlist(open_fs, device=device, db=db, noalu=True)
    baseline = compare(base, base, scope=None, mask=mask, residual={})
    if reported_differences(baseline):
        raise SelftestError(
            "SELFTEST FAILED: the pair given is not a passing pair -- the "
            f"checker reports {reported_differences(baseline)} differences "
            "before any fuse is injected, so an injected one cannot be told "
            "apart from them")

    tmp = out_path or os.path.join(
        tempfile.mkdtemp(prefix="selftest-inject-"), "injected.fs")
    chosen = inject_fuse(open_fs, db, tmp, netlist=base)
    hurt = equiv.unpack_netlist(tmp, device=device, db=db, noalu=True)
    res = equiv.residual(open_fs, tmp, db=db, nl_v=base, nl_o=hurt, mask=mask)
    result = compare(base, hurt, scope=None, mask=mask, residual=res)

    reported = reported_differences(result)
    report = {
        "reported": reported,
        "spurious": max(reported - 1, 0),
        "tile": f"({chosen['tile'][1]},{chosen['tile'][0]})",
        "bit": list(chosen["bit"]),
        "flag": chosen["flag"],
        "first_diff": result.first_diff,
        "injected_fs": tmp,
        "mask_sha256": mask.sha256,
    }
    if reported == 0:
        raise SelftestError(
            "SELFTEST FAILED: 0 differences reported for one fuse injected at "
            f"tile {report['tile']} bit {report['bit']} -- the checker masks "
            f"too much (mask {mask.sha256[:8]}, spec-harness.md 9)")
    if reported > 1:
        raise SelftestError(
            f"SELFTEST FAILED: {reported} differences reported for one fuse "
            f"injected at tile {report['tile']} bit {report['bit']} -- the "
            "canonicalisation is unstable (spec-harness.md 9)")
    return report


# --------------------------------------------------------------------------
# 2. Unpacker completeness (§5.1c, `S6b`)
# --------------------------------------------------------------------------
def unattributed_tiles(bitmap_tiles, netlist):
    """Tiles carrying set fuses the unpacker decoded nothing from.

    "Attributed" is deliberately literal: the unpacker produced a bel **or** a
    pip for that tile.  A tile with set bits and neither is a blind spot --
    both sides of every diff would be decoded through it.
    """
    with_cells = {(cell.y, cell.x) for cell in netlist.cells}
    out = []
    for (row, col), tile in sorted(bitmap_tiles.items()):
        bits = sum(sum(line) for line in tile)
        if not bits:
            continue
        if (row, col) in with_cells or netlist.raw_pips.get((row, col)):
            continue
        out.append({"tile": f"({col},{row})", "bits": bits})
    return out


def unpacker_completeness(design_dir, open_fs=None, pnr_json=None,
                          device=equiv.DEVICE, db=None):
    """§5.1c / `S6b`.  Returns the report; raises on a blind spot."""
    from apycula import chipdb as _chipdb
    from apycula.bslib import read_bitstream

    design_dir = os.path.abspath(design_dir)
    open_fs = open_fs or os.path.join(design_dir, equiv.OPEN_FS)
    pnr_json = pnr_json or os.path.join(design_dir, "top_pnr.json")
    for path, what in ((open_fs, "open-flow bitstream"),
                       (pnr_json, "nextpnr post-PnR netlist")):
        if not os.path.isfile(path):
            raise SelftestError(
                f"no {what} at {path}: unpacker completeness cannot be "
                "asserted, so no evidence row from this batch is admissible "
                "(spec.md S6b)")

    db = db if db is not None else equiv.load_db(device)
    netlist = equiv.unpack_netlist(open_fs, device=device, db=db, noalu=True)
    bits, _hdr, _ftr, _slots = read_bitstream(open_fs)
    tiles = _chipdb.tile_bitmap(db, bits)

    orphans = unattributed_tiles(tiles, netlist)
    c1 = equiv.decode_check_c1(equiv.read_pnr_cells(pnr_json), netlist)
    report = {
        "unattributed_tiles": len(orphans),
        "unattributed_sample": orphans[:16],
        "missing_cells": len(c1["missing"]),
        "missing": c1["missing"],
        "attr_mismatch": c1["attr_mismatch"],
        "required_cells": c1["required_cells"],
        "recovered_cells": c1["recovered_cells"],
        "c1": c1["c1"],
    }
    if orphans or c1["missing"] or c1["attr_mismatch"]:
        n_tiles, n_cells = len(orphans), len(c1["missing"])
        detail = []
        if orphans:
            detail.append(f"first unattributed tile: {orphans[0]['tile']} "
                          f"with {orphans[0]['bits']} set fuses")
        if c1["missing"]:
            detail.append(f"first missing cell: {c1['missing'][0]}")
        if c1["attr_mismatch"]:
            detail.append(f"first attribute mismatch: {c1['attr_mismatch'][0]}")
        raise SelftestError(
            "COMPLETENESS FAILED: "
            f"{n_tiles} unattributed tile{'' if n_tiles == 1 else 's'}, "
            f"{n_cells} missing cell{'' if n_cells == 1 else 's'} "
            "(spec.md S6b, spec-harness.md 5.1c); " + "; ".join(detail))
    return report


# --------------------------------------------------------------------------
# 3. Probing every masked class (`S5`/`S6b` generalised, gestalt G3/G5)
# --------------------------------------------------------------------------
#: Exact stdout of a passing `--probe-mask-classes`.
MASK_PROBE_OK = "MASKPROBE ok: 6 classes probed, 6 reported"

#: The residual classes a differing *tile* bit can land in under
#: `spec-harness.md` §5.3.  `--inject-one-fuse` deliberately picks "a clear
#: single-bit LUT flag inside a tile the unpacker already decodes a cell
#: from", so it proves the checker sees a fuse in a **modelled** tile and
#: proves nothing about these.  This probe flips one bit inside each of
#: them, on the real chipdb's own fuse tables, and asserts the disposition
#: §5.3 requires -- including, for the two rows that carry conditions, that
#: the condition-violating variant comes back as a difference, and (`D92`)
#: that the SAME net routed over a different wire is still a route.
MASK_PROBE_CLASSES = ("set_level_diff", "vendor_only_fill", "open_only_fill",
                      "net_route", "net_route_rerouted",
                      "io_default_unused_pins")


def _probe_cells(tile, typ="LUT", z=0, attrs=()):
    cell = equiv.Cell(tile[1], tile[0], z, typ)
    return equiv.cells_by_tile(equiv.Netlist(cells={cell: frozenset(attrs)}))


def io_probe_site(db):
    """A real IO tile with both a defaulted and a `DRIVE`/`PULLMODE` fuse."""
    for row in range(db.rows):
        for col in range(db.cols):
            ttyp = db.grid[row][col]
            owned = equiv.fuse_groups(db, ttyp).get("longval:IOBA") or set()
            if not owned:
                continue
            hot = owned & equiv.iob_nondefault_coords(db, ttyp)
            plain = owned - hot
            if plain and hot:
                return (row, col), sorted(plain)[0], sorted(hot)[0]
    raise SelftestError(
        "no IO tile on this device carries both a defaulted and a "
        "DRIVE/PULLMODE IOBA fuse, so spec-harness.md 5.3 row 6's two "
        "conditions cannot be probed")


def pip_probe_site(db):
    """A real routing fuse and the global wire the pip it belongs to drives."""
    for row in range(db.rows):
        for col in range(db.cols):
            owners = equiv.pip_owners(db, db.grid[row][col])
            for coord in sorted(owners):
                for dest in sorted(owners[coord]):
                    try:
                        wire = equiv.db_wire2global(db, row, col, dest)
                    except Exception:
                        continue
                    return (row, col), coord, wire
    raise SelftestError(
        "no pip fuse on this device resolves to a global wire, so "
        "spec-harness.md 5.3 row 5's endpoint condition cannot be probed")


def _routed_netlist(tile, wire, port):
    cell = equiv.Cell(tile[1], tile[0], 0, "LUT")
    netlist = equiv.Netlist(cells={cell: frozenset()})
    netlist.nets = {wire: frozenset([(cell, port)])}
    netlist.wire_net = {wire: wire}
    return netlist


def probe_mask_classes(db=None, device=equiv.DEVICE, mask=None,
                       level="E0", shape_class=None):
    """Flip one bit inside each masked class and assert it is reported.

    "Reported" is per class what §5.3 says it is: a masked class must come
    back **named, with its mask entry and its bit count** (never silently
    dropped), and the two rows that carry conditions must additionally send
    the condition-violating variant to `unexplained_bits`.  Returns the
    report; raises `SelftestError` on the first class that does not.
    """
    db = db if db is not None else equiv.load_db(device)
    mask = mask if mask is not None else equiv.load_mask(None)
    io_tile, io_default, io_drive = io_probe_site(db)
    pip_tile, pip_coord, pip_wire = pip_probe_site(db)
    fill_tile = (1, 1)

    def classify(tile, cells_v, cells_o, coords=(), **kw):
        return equiv.classify_residual(
            {tile: max(len(coords), 1)}, cells_v, cells_o,
            outside_every_tile=0, outside={},
            tile_coords={tile: set(coords)} if coords else {},
            db=db, mask=mask, level=level, shape_class=shape_class, **kw)

    def named(res, key, category):
        for row in res[key]:
            if row["category"] == category:
                return row
        return None

    routed = _routed_netlist(pip_tile, pip_wire, "F")
    #: `D92`'s positive: the SAME net -- same canonical endpoint set -- routed
    #: over a different wire, which is what two independent routers actually
    #: produce.  Round 1's per-fuse reading called this a difference.
    rerouted = _routed_netlist(pip_tile, pip_wire + "#rerouted", "F")
    probes = [
        ("set_level_diff", "explained", None, "set_level_diff",
         classify(fill_tile, _probe_cells(fill_tile, "LUT"),
                  _probe_cells(fill_tile, "DFF"))),
        ("vendor_only_fill", "explained", "unused_tile_fill",
         "vendor_only_fill",
         classify(fill_tile, _probe_cells(fill_tile), {})),
        ("open_only_fill", "unexplained_bits", None, "open_only_fill",
         classify(fill_tile, {}, _probe_cells(fill_tile))),
        ("net_route", "explained", "net_route", "net_route",
         classify(pip_tile, {}, {}, coords=[pip_coord], nl_v=routed,
                  nl_o=_routed_netlist(pip_tile, pip_wire, "F"))),
        ("net_route_rerouted", "explained", "net_route", "net_route",
         classify(pip_tile, {}, {}, coords=[pip_coord], nl_v=routed,
                  nl_o=rerouted)),
        ("io_default_unused_pins", "explained", "io_default_unused_pins",
         "io_default_unused_pins",
         classify(io_tile, {}, {}, coords=[io_default])),
    ]
    #: The condition-violating variant of each conditioned row: §5.3 row 5's
    #: net whose endpoints changed, row 6's used pin, and row 6's
    #: non-defaulted value.  Each must be a difference, not a don't-care.
    negatives = [
        ("net_route_endpoint_diff",
         classify(pip_tile, {}, {}, coords=[pip_coord], nl_v=routed,
                  nl_o=_routed_netlist(pip_tile, pip_wire, "Q"))),
        ("io_used_pin_config",
         classify(io_tile, _probe_cells(io_tile, "IOB"),
                  _probe_cells(io_tile, "IOB"), coords=[io_default])),
        ("io_nondefault_config",
         classify(io_tile, {}, {}, coords=[io_drive])),
    ]

    report = {"classes": [], "negatives": [], "mask_sha256": mask.sha256,
              "io_tile": f"({io_tile[1]},{io_tile[0]})",
              "pip_tile": f"({pip_tile[1]},{pip_tile[0]})"}
    for label, key, entry, category, res in probes:
        row = named(res, key, category)
        if row is None or not row.get("bits"):
            raise SelftestError(
                f"MASKPROBE FAILED: one fuse flipped inside {label} is not "
                f"reported in `{key}` -- the checker drops it silently "
                f"(mask {mask.sha256[:8]}, spec-harness.md 5.3)")
        if entry and row.get("mask_entry") != entry:
            raise SelftestError(
                f"MASKPROBE FAILED: {label} came back with mask entry "
                f"{row.get('mask_entry')!r}, not {entry!r} "
                "(spec-harness.md 5.3)")
        report["classes"].append({"category": label, "bits": row["bits"],
                                  "mask_entry": row.get("mask_entry"),
                                  "reported_in": key})
    for category, res in negatives:
        row = named(res, "unexplained_bits", category)
        if row is None or not row.get("bits"):
            raise SelftestError(
                f"MASKPROBE FAILED: {category} is masked away -- a mask entry "
                "is being applied outside the conditions its spec-harness.md "
                "5.3 row states, which is the PR #423 defect class")
        report["negatives"].append({"category": category, "bits": row["bits"]})
    return report


# --------------------------------------------------------------------------
# 4. CLI
# --------------------------------------------------------------------------
def build_parser():
    """Return this module's argparse parser.

    Every harness module parser carries a required `--design-dir` so no
    harness command depends on the current working directory
    (`spec-harness.md` §1, `spec.md` V5/V6).
    """
    parser = argparse.ArgumentParser(prog="fuzz.gw5ast138c.harness.selftest")
    parser.add_argument(
        "--design-dir",
        required=True,
        help="Directory holding the test design for this run (never inferred from cwd).",
    )
    parser.add_argument("--inject-one-fuse", action="store_true",
                        help="S5: flip one fuse and assert the checker reports it.")
    parser.add_argument("--unpacker-completeness", action="store_true",
                        help="S6b: assert the unpacker has no blind spot here.")
    parser.add_argument("--probe-mask-classes", action="store_true",
                        help="Flip one bit inside each masked class and assert "
                             "each is reported (spec-harness.md 5.3).")
    parser.add_argument("--device", default=equiv.DEVICE)
    parser.add_argument("--mask", default=None,
                        help="Mask file; the checked-in dontcare.mask by default.")
    parser.add_argument("--open-fs", default=None)
    parser.add_argument("--pnr-json", default=None)
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    if not (args.inject_one_fuse or args.unpacker_completeness
            or args.probe_mask_classes):
        print("selftest: pass --inject-one-fuse, --unpacker-completeness "
              "and/or --probe-mask-classes", file=sys.stderr)
        return 2

    db = None
    status = 0
    if args.unpacker_completeness:
        try:
            db = equiv.load_db(args.device)
            unpacker_completeness(args.design_dir, open_fs=args.open_fs,
                                  pnr_json=args.pnr_json, device=args.device,
                                  db=db)
            print(COMPLETENESS_OK)
        except SelftestError as err:
            print(str(err), file=sys.stderr)
            status = 1
    if args.inject_one_fuse:
        try:
            if db is None:
                db = equiv.load_db(args.device)
            inject_one_fuse(args.design_dir, open_fs=args.open_fs,
                            device=args.device, db=db, mask_path=args.mask)
            print(SELFTEST_OK)
        except SelftestError as err:
            print(str(err), file=sys.stderr)
            status = 1
    if args.probe_mask_classes:
        try:
            if db is None:
                db = equiv.load_db(args.device)
            probe_mask_classes(db=db, device=args.device,
                               mask=equiv.load_mask(args.mask))
            print(MASK_PROBE_OK)
        except SelftestError as err:
            print(str(err), file=sys.stderr)
            status = 1
    return status


if __name__ == "__main__":
    sys.exit(main())
