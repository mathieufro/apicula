"""The 138C's IOB and bank defaults, asserted on the unpacked bitstream.

`D53` fixes the defaults an omitted bank must fall back to: `LVCMOS33` with
`PULL_STRENGTH=MEDIUM`. PR #423 is the reason they matter — a wrong bank
default on this die is a thermal hazard, not a cosmetic diff — so they are
read back out of a real `.fs` rather than taken from the packer that wrote it.
"""

import os

import pytest

from apycula import attrids, chipdb
from apycula import gowin_unpack as gu
from apycula.bslib import read_bitstream

DATASTORE = "/Users/alex/fine-line-data/open-toolchain-gw5ast"
OPEN_FS = f"{DATASTORE}/p3t13/p3-oser-io_ser-0000/top.fs"
VENDOR_FS = f"{DATASTORE}/p3t13/p3-oser-io_ser-0000/run/impl/pnr/run.fs"
def _chipdb_path():
    """The built 138C database, wherever this checkout can see one."""
    here = os.path.dirname(os.path.abspath(__file__))
    root = os.path.dirname(here)
    candidates = [os.path.join(root, "apycula/GW5AST-138C.msgpack.xz")]
    for _ in range(4):
        root = os.path.dirname(root)
        candidates.append(
            os.path.join(root, "apicula/apycula/GW5AST-138C.msgpack.xz"))
    return next((c for c in candidates if os.path.exists(c)), candidates[0])


CHIPDB = _chipdb_path()

#: What `GW5A.get_unused_io_attrvals` emits for an unused pin on this device.
UNUSED_IO_ATTRVALS = (
    ("OPENDRAIN", "OFF"), ("IO_TYPE", "LVCMOS33"), ("DRIVE", "8"),
    ("DRIVE_LEVEL", "8"), ("PADDI", "PADDI"), ("PULLMODE", "NONE"),
)
DRIVE_ATTRS = ("DRIVE", "DRIVE_LEVEL")


@pytest.fixture(scope="module")
def unpacked():
    """The chipdb and both tile bitmaps of one real 138C design."""
    for path in (CHIPDB, OPEN_FS, VENDOR_FS):
        if not os.path.exists(path):
            pytest.skip(f"{path} is not on this host")
    db = gu.load_chipdb(CHIPDB)
    gu._device = "GW5AST-138C"
    return (db,
            chipdb.tile_bitmap(db, read_bitstream(VENDOR_FS)[0]),
            chipdb.tile_bitmap(db, read_bitstream(OPEN_FS)[0]))


def _bank_cells(db):
    for row in range(db.rows):
        for col in range(db.cols):
            for name in sorted(db[row, col].bels):
                if name.startswith("BANK"):
                    yield row, col, name


def _bank_tables(db):
    tables = {}
    for ttyp, groups in db.longval.items():
        for key, val in (groups.get("BANK") or {}).items():
            tables.setdefault(ttyp, {}).setdefault(
                f"BANK{key[0]}", {})[key[1:]] = val
    return tables


def _bank_attrs(db, bitmap, tables, row, col, name):
    table = (tables.get(db[row, col].ttyp) or {}).get(name)
    tile = bitmap.get((row, col))
    if not table or tile is None:
        return {}
    raw = gu.parse_attrvals(tile, db.rev_logicinfo("IOB"), table,
                            attrids.iob_attrids, "IOB")
    return {a: attrids.iob_num2val.get(v, str(v)) for a, v in raw.items()}


def _programmed_banks(db, bitmap):
    tables = _bank_tables(db)
    return {name: attrs
            for row, col, name in _bank_cells(db)
            if (attrs := _bank_attrs(db, bitmap, tables, row, col, name))}


def test_iob_bank_default_io_type_is_lvcmos33(unpacked):
    db, _vendor, opened = unpacked
    vccio = {name: attrs["BANK_VCCIO"]
             for name, attrs in _programmed_banks(db, opened).items()
             if "BANK_VCCIO" in attrs}
    assert vccio, "no bank in the open bitstream carries a VCCIO at all"
    assert set(vccio.values()) == {"3.3"}, vccio


def test_iob_bank_default_pull_strength_is_medium(unpacked):
    db, _vendor, opened = unpacked
    strengths = {name: attrs["PULL_STRENGTH"]
                 for name, attrs in _programmed_banks(db, opened).items()
                 if "PULL_STRENGTH" in attrs}
    assert strengths, "no bank carries PR #423's PULL_STRENGTH fuse"
    assert set(strengths.values()) == {"MEDIUM"}, strengths


def test_iob_bank_no_lvcmos12_emitted(unpacked):
    db, _vendor, opened = unpacked
    tables = _bank_tables(db)
    for row, col, name in _bank_cells(db):
        attrs = _bank_attrs(db, opened, tables, row, col, name)
        assert "LVCMOS12" not in attrs.values(), (name, attrs)


def test_bank_pull_strength_matches_the_vendor_bit_for_bit(unpacked):
    """PR #423's own fuse is the one thing this row may not get wrong."""
    db, vendor, opened = unpacked
    tables = _bank_tables(db)
    for row, col, name in _bank_cells(db):
        want = _bank_attrs(db, vendor, tables, row, col, name)
        got = _bank_attrs(db, opened, tables, row, col, name)
        if "PULL_STRENGTH" in want or "PULL_STRENGTH" in got:
            assert want.get("PULL_STRENGTH") == got.get("PULL_STRENGTH"), name


@pytest.mark.xfail(
    strict=True,
    reason="P3.T26 refused:unused_pin_drive_default -- the packer programs "
           "DRIVE/DRIVE_LEVEL on every unused pin and the vendor programs "
           "neither. Fixing it changes a default on class GW5A and is an "
           "owner-visible thermal decision, so this test states the defect "
           "and flips the day it is fixed.")
def test_unused_pin_carries_no_drive_the_vendor_does_not(unpacked):
    db, vendor, opened = unpacked
    offenders = []
    for row in range(db.rows):
        for col in range(db.cols):
            for name in ("IOBA", "IOBB"):
                bel = db[row, col].bels.get(name)
                if bel is None:
                    continue
                cell = (row, col)
                if name == "IOBB" and bel.fuse_cell_offset:
                    cell = (row + bel.fuse_cell_offset[0],
                            col + bel.fuse_cell_offset[1])
                ttyp = db[cell].ttyp
                if not (db.longval.get(ttyp, {}) or {}).get(name):
                    continue
                if cell not in vendor:
                    continue
                full = _fuses(db, ttyp, name[-1], UNUSED_IO_ATTRVALS)
                nodrive = _fuses(db, ttyp, name[-1],
                                 tuple(p for p in UNUSED_IO_ATTRVALS
                                       if p[0] not in DRIVE_ATTRS))
                drive_only = full - nodrive
                for fr, fc in drive_only:
                    if opened[cell][fr][fc] and not vendor[cell][fr][fc]:
                        offenders.append((cell, name, (fr, fc)))
    assert offenders == []


def _fuses(db, ttyp, idx, pairs):
    av = set()
    for attr, val in pairs:
        chipdb.add_attr_val(db, "IOB", av, attrids.iob_attrids[attr],
                            attrids.iob_attrvals[val])
    return {tuple(c)
            for c in chipdb.get_longval_fuses(db, ttyp, av, f"IOB{idx}")}
