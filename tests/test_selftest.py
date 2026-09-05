"""`P0.T29` -- the two head-of-batch self-tests (`spec-harness.md` §9).

Test names are the blueprint's.  The two "detects" tests drive the verdict
logic through a substituted checker rather than by really widening the
checked-in mask or really renumbering nets: `equiv.py`'s mask is frozen for
this task (a widened mask is the exact failure the self-test exists to catch,
so it may not be edited to make a test pass), and the substituted checker
reproduces what an over-masking checker and an unstable canonicaliser do --
report 0 and report more than 1.
"""
import os

import pytest

from fuzz.gw5ast138c.harness import equiv, selftest


SMOKE = os.path.join(equiv.DATASTORE, "oracle-smoke")
SMOKE_OPEN_FS = os.path.join(SMOKE, "top.fs")
SMOKE_PNR = os.path.join(SMOKE, "top_pnr.json")

needs_smoke = pytest.mark.skipif(
    not (os.path.isfile(SMOKE_OPEN_FS) and os.path.isfile(SMOKE_PNR)),
    reason=f"no open-flow smoke artefacts under {SMOKE} (P0.T21 builds them)")


@pytest.fixture(scope="module")
def smoke_db():
    return equiv.load_db()


@pytest.fixture(scope="module")
def smoke_netlist(smoke_db):
    return equiv.unpack_netlist(SMOKE_OPEN_FS, db=smoke_db, noalu=True)


def _fake_compare(differences):
    """A checker that reports `differences` on any non-identical pair."""
    def compare(vendor, open_, scope=None, mask=None, residual=None):
        result = equiv.E0Result()
        if vendor is not open_:
            result.diff_count = {"cells": differences, "attrs": 0,
                                 "conns": 0, "pips": 0}
            result.verdict = "DIFF" if differences else "EQUIV E0 ok"
        result.residual = residual or {}
        return result
    return compare


# --------------------------------------------------------------------------
# S5 -- the injected fuse
# --------------------------------------------------------------------------
@needs_smoke
@pytest.mark.heavy
def test_selftest_inject_one_fuse_reports_exactly_one(capsys):
    """`V6` line 1: exact stdout, exit status 0."""
    status = selftest.main(["--design-dir", SMOKE, "--inject-one-fuse"])
    out = capsys.readouterr().out
    assert out == selftest.SELFTEST_OK + "\n"
    assert status == 0


@needs_smoke
@pytest.mark.heavy
def test_selftest_detects_over_masking(smoke_db, capsys):
    """A checker that reports nothing is a harness defect, not a pass."""
    with pytest.raises(selftest.SelftestError) as err:
        selftest.inject_one_fuse(SMOKE, db=smoke_db,
                                 compare=_fake_compare(0))
    assert "0 differences" in str(err.value)

    status = selftest.main(["--design-dir", SMOKE, "--inject-one-fuse",
                            "--open-fs", os.path.join(SMOKE, "missing.fs")])
    assert status != 0
    assert capsys.readouterr().out == ""


@needs_smoke
@pytest.mark.heavy
def test_selftest_detects_unstable_canonicalisation(smoke_db):
    """More than one difference for one fuse means the canonicalisation moved."""
    with pytest.raises(selftest.SelftestError) as err:
        selftest.inject_one_fuse(SMOKE, db=smoke_db,
                                 compare=_fake_compare(3))
    message = str(err.value)
    assert "3 differences" in message
    assert "canonicalisation is unstable" in message


@needs_smoke
@pytest.mark.heavy
def test_selftest_injects_exactly_one_fuse(smoke_db, smoke_netlist, tmp_path):
    """The injected bitstream differs from the original by one bit, no more."""
    from apycula import chipdb as _chipdb
    from apycula.bslib import read_bitstream

    out = str(tmp_path / "injected.fs")
    selftest.inject_fuse(SMOKE_OPEN_FS, smoke_db, out, netlist=smoke_netlist)
    before, _, _, _ = read_bitstream(SMOKE_OPEN_FS)
    after, _, _, _ = read_bitstream(out)
    flipped = sum(1 for r, row in enumerate(before)
                  for c, bit in enumerate(row) if bit != after[r][c])
    assert flipped == 1
    assert _chipdb.tile_bitmap(smoke_db, after) is not None


# --------------------------------------------------------------------------
# S6b -- unpacker completeness
# --------------------------------------------------------------------------
@needs_smoke
@pytest.mark.heavy
def test_completeness_zero_unattributed(capsys):
    """`V6` line 2: exact stdout, exit status 0."""
    status = selftest.main(["--design-dir", SMOKE, "--unpacker-completeness"])
    out = capsys.readouterr().out
    assert out == selftest.COMPLETENESS_OK + "\n"
    assert status == 0


@needs_smoke
@pytest.mark.heavy
def test_completeness_fails_on_unattributed_tile(monkeypatch, smoke_db,
                                                 smoke_netlist, capsys):
    """One tile with set fuses and nothing decoded from it blocks the batch."""
    from apycula import chipdb as _chipdb
    from apycula.bslib import read_bitstream

    bits, _, _, _ = read_bitstream(SMOKE_OPEN_FS)
    tiles = _chipdb.tile_bitmap(smoke_db, bits)
    blinded = next((row, col) for (row, col), tile in sorted(tiles.items())
                   if any(any(line) for line in tile)
                   and ((row, col) in {(c.y, c.x) for c in smoke_netlist.cells}
                        or smoke_netlist.raw_pips.get((row, col))))

    stripped = equiv.Netlist(
        cells={c: a for c, a in smoke_netlist.cells.items()
               if (c.y, c.x) != blinded},
        conns=smoke_netlist.conns, nets=smoke_netlist.nets,
        raw_pips={k: v for k, v in smoke_netlist.raw_pips.items()
                  if k != blinded},
        source=smoke_netlist.source)
    monkeypatch.setattr(equiv, "unpack_netlist",
                        lambda *a, **k: stripped)

    with pytest.raises(selftest.SelftestError) as err:
        selftest.unpacker_completeness(SMOKE, db=smoke_db)
    message = str(err.value)
    assert "1 unattributed tile," in message
    assert f"({blinded[1]},{blinded[0]})" in message

    status = selftest.main(["--design-dir", SMOKE, "--unpacker-completeness"])
    assert status != 0
    assert capsys.readouterr().out == ""


def test_unattributed_tiles_counts_only_undecoded_tiles():
    """A tile with a pip and no cell is still attributed; an empty one is not."""
    cell = equiv.Cell(3, 4, 0, "LUT")
    netlist = equiv.Netlist(cells={cell: frozenset()},
                            raw_pips={(9, 9): {"A": "B"}})
    tiles = {
        (4, 3): [[1, 0], [0, 0]],   # has a decoded cell
        (9, 9): [[0, 1], [0, 0]],   # has a decoded pip
        (7, 7): [[1, 1], [1, 0]],   # nothing decoded: a blind spot
        (8, 8): [[0, 0], [0, 0]],   # no set fuse at all
    }
    orphans = selftest.unattributed_tiles(tiles, netlist)
    assert orphans == [{"tile": "(7,7)", "bits": 3}]


# --------------------------------------------------------------------------
# Every masked class, probed (gestalt G3/G5)
# --------------------------------------------------------------------------
def test_mask_probe_reports_every_masked_class(smoke_db, capsys):
    """One bit flipped inside each of the five classes comes back named.

    `--inject-one-fuse` picks a LUT flag in a modelled tile, so it proves the
    checker sees a fuse there and nothing about the mask. This probe walks the
    real chipdb's own fuse tables for each class §5.3 can put a bit in.
    """
    report = selftest.probe_mask_classes(db=smoke_db)
    assert [c["category"] for c in report["classes"]] == \
        list(selftest.MASK_PROBE_CLASSES)
    assert all(c["bits"] for c in report["classes"])
    assert [n["category"] for n in report["negatives"]] == \
        ["net_route_endpoint_diff", "io_used_pin_config", "io_nondefault_config"]

    status = selftest.main(["--design-dir", ".", "--probe-mask-classes"])
    assert capsys.readouterr().out == selftest.MASK_PROBE_OK + "\n"
    assert status == 0


def test_mask_probe_detects_a_mask_applied_without_its_conditions(smoke_db,
                                                                  monkeypatch):
    """Red control: drop §5.3's conditions and the probe must fail.

    This is the pre-fix checker exactly -- a fuse-group name decided the
    category on its own -- and it is the state in which a differing IO fuse on
    a used pin and a flipped routing bit were both silently absorbed.
    """
    monkeypatch.setattr(
        equiv, "refine_group_category",
        lambda category, name, coord, db, ttyp, **kw: category)
    with pytest.raises(selftest.SelftestError) as err:
        selftest.probe_mask_classes(db=smoke_db)
    assert "MASKPROBE FAILED" in str(err.value)


def test_mask_probe_detects_open_only_fill_being_masked(smoke_db, monkeypatch):
    """Red control: re-map `open_only_fill` to the fill entry and it fails."""
    widened = dict(equiv.ACCOUNTED_CATEGORIES)
    widened["open_only_fill"] = "unused_tile_fill"
    monkeypatch.setattr(equiv, "ACCOUNTED_CATEGORIES", widened)
    with pytest.raises(selftest.SelftestError) as err:
        selftest.probe_mask_classes(db=smoke_db)
    assert "open_only_fill" in str(err.value)
