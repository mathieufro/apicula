"""`P0.T29` (unpacker half) -- the two `S6b` completeness defects on GW5A.

Both are GW1N-shaped assumptions in `gowin_unpack.parse_tile_` that make the
decoder *lose* real cells on a GW5A bitstream, so the decode check `c1`
(`spec-harness.md` §5.4) reports `mismatch` and no evidence row is admissible:

1. **A zero-fuse `RAM16` mode.**  `chipdb.fse_luts` builds the shadow-SRAM
   mode from the `fse` `shortval(28)` row keyed `(2, 0)`.  That row does not
   exist for the GW5A slice tile types, so the mode's fuse set is **empty**
   and matches every tile whose bits are clear -- a `RAM16` is decoded in all
   16,200+ slice tiles and `ram16_remove_bels()` then deletes `LUT0`-`LUT5`
   and `DFF4`/`DFF5` from each.  GW1N-9C and GW2A-18C carry exactly one real
   fuse there, so the "a zero-fuse mode is not evidence" rule cannot change
   pre-5A decoding.

2. **An aliased `LVDS_OUT=ON` record.**  A longval record's key is a
   *conjunction* and the encoder ORs the fuses of every satisfied record, so
   the decoder's maximal-subset match can report a record that was never
   used.  On GW5A the `LVDS_OUT=ON` record's fuse set is exactly the fuse set
   of the default (negative-key) records that every plain input buffer sets
   (`-ODMUX=TRIMUX, OPENDRAIN=OFF, PADDI=PADDI`), so every used input decodes
   as `TLVDS_IBUF` and its paired `IOBB` is dropped via `skip_bels`.  The
   sibling rule -- "a B bel with `IO_TYPE` and no `DRIVE` is the negative half
   of an ELVDS pair" -- fires on the same attribute set and drops the same
   bel, so both are disabled on an aliased table.  The predicate is a property
   of the fuse table, not of the device name: measured true for all 24
   GW5AST-138C IOB tables and false for every IOB table of GW1N-1, GW1N-9C,
   GW1NZ-1, GW1NS-4 and GW2A-18C.
"""
import os

import pytest

from apycula import gowin_unpack as gu
from fuzz.gw5ast138c.harness import equiv


SMOKE = os.path.join(equiv.DATASTORE, "oracle-smoke")
SMOKE_OPEN_FS = os.path.join(SMOKE, "top.fs")
SMOKE_PNR = os.path.join(SMOKE, "top_pnr.json")

needs_smoke = pytest.mark.skipif(
    not os.path.isfile(SMOKE_OPEN_FS),
    reason=f"no open-flow smoke bitstream at {SMOKE_OPEN_FS} (P0.T21 builds it)")


# --------------------------------------------------------------------------
# 1. the zero-fuse RAM16 mode
# --------------------------------------------------------------------------
def test_ram16_zero_fuse_mode_is_not_evidence():
    """An empty fuse set decodes nothing -- it matches every cleared tile."""
    assert gu.mode_carries_evidence("RAM16", set()) is False


def test_ram16_single_fuse_mode_still_decodes():
    """The GW1N/GW2A shape (one real fuse) is untouched by the rule."""
    assert gu.mode_carries_evidence("RAM16", {(12, 3)}) is True


def test_zero_fuse_mode_of_other_bels_untouched():
    """Only `RAM16` is affected; every other bel keeps its default-mode match."""
    assert gu.mode_carries_evidence("LUT0", set()) is True
    assert gu.mode_carries_evidence("IOBA", set()) is True


# --------------------------------------------------------------------------
# 2. the aliased LVDS_OUT record
# --------------------------------------------------------------------------
#: `rev_logicinfo('IOB')` shape: `idx -> (attr_code, value_code)`.
#: `16` is `attrids.iob_attrids['LVDS_OUT']`, `0` is `IO_TYPE`.
_LOGICINFO = {1: (16, 107), 2: (0, 236), 3: (4, 108), 4: (24, 80)}


def test_lvds_out_alias_detected_in_gw5a_shaped_table():
    """Positive `LVDS_OUT` record whose fuses are a default record's fuses."""
    table = {
        (1, 2): {(20, 51), (20, 79)},          # LVDS_OUT=ON, IO_TYPE=236
        (-1000, 2, 3, 4): {(20, 51), (20, 79)},  # the plain-IBUF default record
    }
    assert gu._table_lvds_out_is_aliased(table, _LOGICINFO) is True


def test_lvds_out_not_aliased_in_gw1n_shaped_table():
    """A `LVDS_OUT` record with a fuse of its own stays evidence."""
    table = {
        (1, 2): {(20, 51), (20, 71)},
        (-1000, 2, 3, 4): {(20, 51), (20, 79)},
    }
    assert gu._table_lvds_out_is_aliased(table, _LOGICINFO) is False


def test_lvds_out_alias_ignores_tables_without_the_attribute():
    table = {(2, 3): {(1, 1)}, (-1000, 4): {(1, 1)}}
    assert gu._table_lvds_out_is_aliased(table, _LOGICINFO) is False


# --------------------------------------------------------------------------
# 3. the two misses, on the real smoke bitstream
# --------------------------------------------------------------------------
@needs_smoke
@pytest.mark.heavy
def test_smoke_unpack_recovers_luts_at_tile_2_1():
    """`LUT0`/`LUT2`/`LUT3` survive: no spurious `RAM16` removes them."""
    nl = equiv.unpack_netlist(SMOKE_OPEN_FS, noalu=True)
    at21 = {(c.type, c.z) for c in nl.cells if (c.x, c.y) == (2, 1)}
    assert ("RAM", 16) not in at21
    for z in (0, 2, 3):
        assert ("LUT", z) in at21, f"LUT{z} lost at tile (2,1): {sorted(at21)}"


@needs_smoke
@pytest.mark.heavy
def test_smoke_unpack_recovers_iobb_at_55_108():
    """The `IOBB` paired with a plain-`IBUF` `IOBA` is not skipped."""
    nl = equiv.unpack_netlist(SMOKE_OPEN_FS, noalu=True)
    at = {(c.type, c.z) for c in nl.cells if (c.x, c.y) == (55, 108)}
    assert ("IOB", 0) in at and ("IOB", 1) in at, sorted(at)


@needs_smoke
@pytest.mark.heavy
def test_smoke_decode_check_c1_ok():
    """`c1` -- every fuse-backed placed cell is recovered (`S6b`)."""
    nl = equiv.unpack_netlist(SMOKE_OPEN_FS, noalu=True)
    res = equiv.decode_check_c1(equiv.read_pnr_cells(SMOKE_PNR), nl)
    assert res["missing"] == [] and res["attr_mismatch"] == []
    assert res["c1"] == "ok"
    assert res["recovered_cells"] == res["required_cells"]


# --------------------------------------------------------------------------
# 4. the pre-5A regression: no GW1N/GW2A IOB table is affected
# --------------------------------------------------------------------------
import glob  # noqa: E402  (kept beside the test that needs it)

_UPSTREAM = ("/Users/alex/fine-line/vendor/venv-upstream/lib/python*/"
             "site-packages/apycula/{dev}.msgpack.xz")


def _upstream_chipdb(dev):
    hits = glob.glob(_UPSTREAM.format(dev=dev))
    if not hits:
        pytest.skip(f"no {dev} chipdb in vendor/venv-upstream (D56 baseline)")
    from apycula.chipdb import load_chipdb
    return load_chipdb(hits[0])


@pytest.mark.parametrize("dev", ("GW1N-9C", "GW2A-18C"))
def test_pre_gw5_iob_tables_keep_differential_decoding(dev):
    """Every pre-5A IOB table stays reliable, so its decoding is unchanged."""
    db = _upstream_chipdb(dev)
    saved = gu._device
    try:
        gu._device = dev
        gu._lvds_out_alias_cache.clear()
        tables = [(ttyp, name) for ttyp, tabs in db.longval.items()
                  for name in tabs if name.startswith("IOB")]
        assert tables, f"{dev} chipdb has no IOB longval table"
        unreliable = [t for t in tables
                      if not gu.differential_decode_is_reliable(db, *t)]
        assert unreliable == []
    finally:
        gu._device = saved
        gu._lvds_out_alias_cache.clear()


def test_gw5ast_iob_tables_are_all_aliased():
    """The GW5AST-138C tables are the ones the rule exists for."""
    db = equiv.load_db()
    saved = gu._device
    try:
        gu._device = equiv.DEVICE
        gu._lvds_out_alias_cache.clear()
        tables = [(ttyp, name) for ttyp, tabs in db.longval.items()
                  for name in tabs if name.startswith("IOB")]
        assert tables
        assert all(not gu.differential_decode_is_reliable(db, *t) for t in tables)
    finally:
        gu._device = saved
        gu._lvds_out_alias_cache.clear()
