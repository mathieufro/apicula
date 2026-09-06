"""P1.T14 / P1.T15 -- the CLKDIV and CLKDIV2 evidence rows, and the three
harness gaps writing them exposed.

The four row tests are the blueprint's, by name.  They read the committed
evidence tree ($OTC/evidence/<slug>/runs.jsonl and summary.md) and the
pipeline's spec-primitives.md, and skip -- never lie -- when a tree that is
not part of this checkout is absent.
"""
import json
import os
import re

import pytest

from fuzz.gw5ast138c.harness import equiv, evidence, gen
from fuzz.gw5ast138c.shapes import PinSpec

DEVICE = "GW5AST-138C"
PART = "GW5AST-LV138PG484AC1/I0"
STATUS_RE = re.compile(r"^(E1|E0\+hw|E0\+hw-pending|refused:.+)$")
HEADINGS = ("## Row", "## Sweep", "## Verdict", "## Artefacts")

#: The pipeline document whose section-1 status cells these rows set.
SPEC_PRIMITIVES = os.path.join(
    os.path.expanduser("~"), "fine-line", ".atelier", "pipelines",
    "2026-09-03-open-toolchain-gw5ast-7e84", "spec-primitives.md")


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------
def _rows(slug):
    try:
        path = evidence.rows_path(slug)
    except evidence.EvidenceSchemaError as exc:
        pytest.skip(f"no evidence tree: {exc}")
    if not os.path.isfile(path):
        pytest.skip(f"{path} absent (the batch has not landed its rows yet)")
    return path, evidence.read_rows(path)


def _summary(slug):
    """The slug's `summary.md`, once its rows exist.

    A slug whose `runs.jsonl` has not landed yet is skipped, not failed: every
    slug already carries the `P1.T03` skeleton `summary.md`, so its presence
    alone says nothing about whether the owning task has run.
    """
    _rows(slug)
    root = evidence.evidence_root()
    path = os.path.join(root, slug, "summary.md")
    if not os.path.isfile(path):
        pytest.skip(f"{path} absent")
    return path, open(path).read()


#: The section-1 column the DEL-b status vocabulary belongs to.  Located by
#: its header text, never by a bare index, so a column inserted upstream of it
#: fails the lookup instead of silently reading the neighbour.
STATUS_COLUMN = "138C status"


def _status_cell(primitive):
    """The `138C status` cell of the section-1 row naming `primitive`.

    That column, not the `Done` one, is what `S25`/`DEL-b` reads: `Done` holds
    the row's done-when *criteria* and stays `DONE-STD, plus: ...` for life.
    """
    if not os.path.isfile(SPEC_PRIMITIVES):
        pytest.skip(f"{SPEC_PRIMITIVES} absent")
    index = None
    for line in open(SPEC_PRIMITIVES):
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if index is None and STATUS_COLUMN in cells:
            index = cells.index(STATUS_COLUMN)
            continue
        if index is None or not line.startswith("| **%s**" % primitive):
            continue
        assert len(cells) == 7, (primitive, len(cells))
        return cells[index]
    pytest.fail(f"no section-1 row for {primitive!r} in {SPEC_PRIMITIVES}")


def _check_rows(path, rows, expected):
    assert len(rows) == expected, f"{path}: {len(rows)} rows, expected {expected}"
    masks = set()
    for row in rows:
        evidence.validate_row(row)
        assert row["device"] == DEVICE, row["run_id"]
        assert row["part"].startswith(PART), row["run_id"]
        assert row["verdict"] in ("ok", "refused"), (row["run_id"], row["verdict"])
        masks.add(row["mask_sha256"])
        if row["level"] == "E1":
            for key in ("cells", "attrs", "conns"):
                assert row["diff_count"][key] == 0, (row["run_id"], key,
                                                     row["diff_count"])
        if row["level"] == "E0":
            assert row["notes"].strip(), row["run_id"]
        unexplained = row["unexplained_bits"]
        assert unexplained == [] or all(
            "justification" in entry for entry in unexplained), row["run_id"]
    assert sum(1 for r in rows if r["verdict"] == "aborted") == 0
    assert len(masks) == 1, f"{path}: mask_sha256 differs across rows: {masks}"


# --------------------------------------------------------------------------
# P1.T14
# --------------------------------------------------------------------------
def test_clkdiv_sweep_rows_complete():
    path, rows = _rows("clkdiv")
    _check_rows(path, rows, 10)
    modes = {r["sweep"].get("DIV_MODE") for r in rows
             if r["shape"] == "clocking_clkdiv"}
    from fuzz.gw5ast138c.shapes.clocking_clkdiv import (DEFAULT_DIV_MODE,
                                                        DIV_MODES)
    assert modes == set(DIV_MODES), modes
    baseline = [r for r in rows if r["shape"] == "clocking_clkdiv_baseline"]
    assert len(baseline) == 1, [r["shape"] for r in rows]
    assert baseline[0]["sweep"]["DIV_MODE"] == DEFAULT_DIV_MODE


def test_clkdiv_free_control_differs_by_placement_alone():
    """The unpinned control is a measurement, not a row of the sweep.

    It is the one point that is `diff` **by construction** -- neither placer is
    told anything, so they choose different HCLK blocks -- which is why it is
    recorded as its own batch beside the sweep rather than inside the ten rows
    whose verdicts the sweep is read from.
    """
    try:
        root = evidence.evidence_root()
    except evidence.EvidenceSchemaError as exc:
        pytest.skip(f"no evidence tree: {exc}")
    path = os.path.join(root, "_runs", "p1t14-clkdiv-e0.rows.jsonl")
    if not os.path.isfile(path):
        pytest.skip(f"{path} absent")
    rows = evidence.read_rows(path)
    assert len(rows) == 1
    row = rows[0]
    assert row["shape"] == "clocking_clkdiv_free"
    assert row["level"] == "E0" and row["verdict"] == "diff"
    assert row["diff_count"]["cells"] > 0
    assert "CLKDIV" in (row["first_diff"] or "")


def test_clkdiv_row_closes():
    path, text = _summary("clkdiv")
    assert len(text.splitlines()) <= 200, path
    for heading in HEADINGS:
        assert heading in text, (path, heading)
    cell = _status_cell("CLKDIV")
    assert cell and cell not in ("", "pending") and not cell.startswith("blocked:")
    assert STATUS_RE.match(cell), cell


# --------------------------------------------------------------------------
# P1.T15
# --------------------------------------------------------------------------
def test_clkdiv2_sweep_rows_complete():
    path, rows = _rows("clkdiv2")
    _check_rows(path, rows, 8)
    swept = [r["sweep"] for r in rows if r["shape"] == "clocking_clkdiv2"]
    paths = {s.get("input_path") for s in swept}
    assert "HCLK_BUF_BO" in paths, paths   # even lane: the fuseless node
    assert "CLKDIV2_I" in paths, paths     # odd lane: the pip
    assert len({json.dumps(s, sort_keys=True) for s in swept}) == len(swept)
    assert sum(1 for r in rows if r["shape"] == "clocking_clkdiv2_free") == 1


def test_clkdiv2_row_closes():
    path, text = _summary("clkdiv2")
    assert len(text.splitlines()) <= 200, path
    for heading in HEADINGS:
        assert heading in text, (path, heading)
    cell = _status_cell("CLKDIV2")
    assert cell and cell not in ("", "pending") and not cell.startswith("blocked:")
    assert STATUS_RE.match(cell), cell


# --------------------------------------------------------------------------
# The three harness gaps P1.T14/T15 had to fix, each with its own test
# --------------------------------------------------------------------------
def test_gen_ins_loc_may_be_a_callable(tmp_path):
    """A shape whose swept parameter IS the placement (`P1.T15`)."""
    spec = gen.load_shape("clocking_clkdiv2")
    assert callable(spec.ins_loc)
    assert gen.ins_loc_of(spec, (0, "pin")) == {"div0": "BOTTOMSIDE[4]"}
    assert gen.ins_loc_of(spec, (3, "pin")) == {"div0": "BOTTOMSIDE[7]"}
    gen.run(spec, tmp_path / "p3", (3, "pin"))
    assert 'INS_LOC "div0" BOTTOMSIDE[7];' in (tmp_path / "p3" / "top.cst").read_text()
    # and a plain dict still works
    assert gen.ins_loc_of(gen.load_shape("clocking_clkdiv")) == {
        "div0": "BOTTOMSIDE[4]"}


def test_gen_open_cst_has_no_ins_loc(tmp_path):
    """nextpnr's reader cannot parse `SIDE[0~7]`, so it gets its own `.cst`."""
    spec = gen.load_shape("clocking_clkdiv")
    gen.run(spec, tmp_path / "d", "4")
    vendor = (tmp_path / "d" / "top.cst").read_text()
    open_cst = (tmp_path / "d" / "top-open.cst").read_text()
    assert "INS_LOC" in vendor and "BOTTOMSIDE[4]" in vendor
    assert "INS_LOC" not in open_cst
    for line in vendor.splitlines():
        if line.startswith(("IO_LOC", "IO_PORT")):
            assert line in open_cst


def test_gen_config_role_pin_needs_a_measured_ack(tmp_path):
    """The config-pin refusal stands; only a MEASURED string lifts it."""
    spec = gen.load_shape("clocking_clkdiv")
    assert gen.config_role_of_loc("V22") == "EMCCLK"
    assert spec.pins["clk"].config_role_ack
    assert gen.assert_cst_defaults(spec) == []
    naked = PinSpec(loc="V22", bank=4, drive=None, direction="input")
    import dataclasses
    bad = dataclasses.replace(spec, pins=dict(spec.pins, clk=naked))
    with pytest.raises(gen.ConfigPinError):
        gen.assert_cst_defaults(bad)


def test_level_e1_hclk_reads_the_vendor_bitstream_not_its_reports():
    """`E1` for a CLKDIV: the vendor's `.tr` never names one (measured)."""
    exported = {"div0": {"x": 117, "y": 108, "z": 0, "type": "CLKDIV",
                         "bel": "CLKDIV_0"}}
    scope = type("S", (), {"tiles": [(117, 108)]})()
    ok = equiv.level_e1_hclk(exported, {(117, 108, 0): "CLKDIV"}, scope=scope)
    assert ok["level"] == "E1" and len(ok["matched"]) == 1
    moved = equiv.level_e1_hclk(exported, {(64, 108, 0): "CLKDIV"}, scope=scope)
    assert moved["level"] == "E0" and len(moved["mismatched"]) == 1
    # and the merge: a CLS half that saw nothing in scope must not veto it
    silent = {"level": "E0", "checked": 3, "matched": [], "mismatched": [],
              "unobserved": [], "notes": "nothing in scope"}
    assert equiv.merge_e1(silent, ok)["level"] == "E1"
    assert equiv.merge_e1(silent, moved)["level"] == "E0"


def test_hclk_exported_reads_clkdiv_and_clkdiv2_bels():
    cells = [
        {"name": "div0", "type": "CLKDIV", "bel": "CLKDIV_2", "site": (117, 108)},
        {"name": "div2", "type": "CLKDIV2", "bel": "CLKDIV2_2", "site": (117, 108)},
        {"name": "ctr", "type": "DFF", "bel": "DFF3", "site": (10, 10)},
        {"name": "un", "type": "CLKDIV", "bel": None, "site": None},
    ]
    got = equiv.hclk_exported(cells)
    assert set(got) == {"div0", "div2"}
    assert got["div0"]["type"] == "CLKDIV" and got["div0"]["z"] == 2
    assert got["div2"]["type"] == "CLKDIV2"
