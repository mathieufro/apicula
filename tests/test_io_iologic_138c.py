"""Phase 3 (IO and IOLOGIC) unit tests for GW5AST-138C.

`D39`'s three ordered states end here: Phase 1 corrected the misspelled
exclusion so it fired, Phase 1 set `HAS_5A_HCLK`, and `P3.T03` deletes the
exclusion so IOLOGIC on this die is deliberate rather than accidental. What
replaces it is a **ttyp-qualified** gate (`P3.T04`) derived from the device
data, not a blanket device gate.

The bel-surface test reads the built `apycula/GW5AST-138C.msgpack.xz` -- the
canonical chipdb the whole open flow consumes (`F7`) -- rather than rebuilding
it, so the phase pays for that build once and every test still asserts against
the artefact that ships.
"""
import os
import re

import pytest

from apycula import chipdb
from apycula.gowin_pack import ChipDB

DEVICE = "GW5AST-138C"

#: The 25A ttyp gate `P3.T03` must leave standing (`F10`, `F11`).
GW5A_25A_IOLOGIC_EXCLUSIONS = {48, 51, 263, 392, 399}


def _fse_iologic_source():
    """The text of `fse_iologic` alone -- a guard elsewhere is not this guard."""
    path = os.path.join(os.path.dirname(chipdb.__file__), "chipdb.py")
    text = open(path, encoding="utf-8").read()
    match = re.search(r"^def fse_iologic\(.*?^(?=def )", text, re.S | re.M)
    assert match, "fse_iologic not found in chipdb.py"
    return match.group(0)


def _iologic_bel_counts(db):
    """`{bel name: cell count}` over the whole grid."""
    counts = {"IOLOGICA": 0, "IOLOGICB": 0}
    for row in db.grid:
        for ttyp in row:
            for name in db.tiles[ttyp].bels:
                if name in counts:
                    counts[name] += 1
    return counts


#: Each of the three IOLOGIC sweeps carries the shape's six points...
SWEEP_POINTS = 6

#: ...plus one point on the **B** half of a pad pair (`P3.F3`).  The sweeps
#: were confined to `A`-half balls by a conclusion that has since been
#: retracted -- see `shapes/io_basic_b.py` -- so each slug now also carries the
#: measurement that settles the other half of the column.
B_HALF_POINTS = 1


@pytest.fixture(scope="module")
def db_138c():
    try:
        return ChipDB(DEVICE).db
    except FileNotFoundError:  # pragma: no cover - build it first
        pytest.skip(f"{DEVICE}.msgpack.xz absent; run apycula.chipdb_builder")


def test_iologic_bels_created_on_138c(db_138c):
    """IOLOGIC exists on 138C, and it exists next to a real clock (`D39` state 2)."""
    counts = _iologic_bel_counts(db_138c)
    assert counts["IOLOGICA"] >= 1
    assert counts["IOLOGICA"] + counts["IOLOGICB"] > 0
    assert "HAS_5A_HCLK" in db_138c.chip_flags


def test_iologic_bare_138c_guard_absent():
    """No misspelling anywhere, and no *blanket* 138C exclusion in `fse_iologic`.

    The ttyp-qualified form `P3.T04` adds is deliberately still legal.
    """
    path = os.path.join(os.path.dirname(chipdb.__file__), "chipdb.py")
    assert open(path, encoding="utf-8").read().count("GW5AST-138AC") == 0
    assert _fse_iologic_source().count("if device in {'GW5AST-138C'}:") == 0


def test_iologic_25a_ttyp_gate_intact():
    """The 25A exclusion is untouched -- Phase 3 must not regress a shipped family."""
    source = _fse_iologic_source()
    match = re.search(
        r"if device in \{'GW5A-25A'\} and ttyp in \{([^}]*)\}:\s*\n\s*return bels",
        source)
    assert match, "the GW5A-25A ttyp gate is gone from fse_iologic"
    assert {int(x) for x in match.group(1).split(",")} == \
        GW5A_25A_IOLOGIC_EXCLUSIONS


# ---------------------------------------------------------------- P3.T04

#: The adjudication `P3.T04` derived, relative to this checkout's siblings.
_ADJUDICATION = os.path.join("open-toolchain", "evidence", "oddr-iddr",
                             "ttyp-adjudication.tsv")


def _adjudication_path():
    """`$OTC/evidence/oddr-iddr/ttyp-adjudication.tsv`, from the worktree layout."""
    here = os.path.dirname(os.path.dirname(os.path.abspath(chipdb.__file__)))
    candidates = [os.environ.get("P3_TTYP_ADJUDICATION"),
                  os.path.join(os.path.dirname(here), _ADJUDICATION),
                  os.path.join(os.path.dirname(os.path.dirname(here)),
                               _ADJUDICATION)]
    for candidate in candidates:
        if candidate and os.path.isfile(candidate):
            return candidate
    return None


def _ttyp_gate_literal():
    """The 138C ttyp set `fse_iologic` excludes, as written in the source."""
    match = re.search(
        r"if device in \{'GW5AST-138C'\} and ttyp in \{([^}]*)\}:",
        _fse_iologic_source(), re.S)
    return {int(x) for x in match.group(1).replace("\n", " ").split(",")
            if x.strip()} if match else set()


def test_iologic_ttyp_exclusion_138c_matches_evidence():
    """The literal in the source is the set the evidence rejected -- no more, no less."""
    path = _adjudication_path()
    if path is None:
        pytest.skip("ttyp-adjudication.tsv not reachable from this checkout")
    rows = [line.split("\t") for line in
            open(path, encoding="utf-8").read().splitlines()[1:] if line]
    rejected = {int(r[0]) for r in rows if r[1] == "reject"}
    accepted = {int(r[0]) for r in rows if r[1] == "accept"}
    assert rejected | accepted == {int(r[0]) for r in rows}, "a row has no verdict"
    assert _ttyp_gate_literal() == rejected
    assert len(rejected) == sum(1 for r in rows if r[1] == "reject")
    assert len(rejected) >= 0


# --------------------------------------------------------------------------
# ODDR / IDDR against the vendor (`P3.T11`, `P3.T12`)
# --------------------------------------------------------------------------
_ODDR_IDDR = "oddr-iddr"

#: The IOLOGIC fuses the vendor sets at `IOLOGICA` of tile type 247, measured
#: on the GW5AST-138C by `P3.T11`'s two oracle runs
#: (`$OTC/evidence/oddr-iddr/fuse-delta.json`).  A handler that writes more
#: than this over-emits and a handler that writes less under-configures; both
#: are a `DIFF`, so the set is pinned here rather than recomputed.
VENDOR_IOLOGIC_FUSES_247A = {
    "ODDR": {(20, 59), (21, 54), (21, 112), (21, 113)},
    "IDDR": {(21, 15), (21, 104)},
    "IDDRC": {(21, 15), (21, 49), (21, 56), (21, 104)},
}

#: `GW5A_25A.common_iologic_handler`'s output for a cell carrying no
#: parameters, as it stood before Phase 3 (`S3`, `F1`).  The 138C work adds an
#: override on its own class and must not move this.
GW5A_25A_DEFAULT_ATTRS = [("TXCLK_POL", "0"), ("GSR", "ENGSR")]


def _otc_path(*parts):
    """A file under `$OTC/evidence`, or `None` when the tree is not reachable.

    `$OTC_EVIDENCE` is the harness's own spelling of that root and is what a
    worktree checkout sets, so it is consulted first; the sibling-submodule
    layout is the fallback for a plain clone.
    """
    roots = [os.environ.get("OTC_EVIDENCE")]
    here = os.path.dirname(os.path.dirname(os.path.abspath(chipdb.__file__)))
    for base in (os.path.dirname(here), os.path.dirname(os.path.dirname(here))):
        roots.append(os.path.join(base, "open-toolchain", "evidence"))
    for root in roots:
        if not root:
            continue
        candidate = os.path.join(root, *parts)
        if os.path.exists(candidate):
            return candidate
    return None


def _iologic_bel(typ, parms, fclk="UNKNOWN"):
    """A bare `IologicBelDesc` -- the handlers read the cell and `fclk`.

    `fclk` is the HCLK lane spelling `set_iologic_bel_fclk` would have put
    there (`SPINE10`..`SPINE13`); `UNKNOWN` is a cell with no fast clock.
    """
    from apycula.gowin_pack import IologicBelDesc

    class _Cell:
        pass

    cell = _Cell()
    cell.typ = typ
    cell.parms = dict(parms)
    cell.attrs = {}
    return IologicBelDesc(0, 0, "0", cell, fclk,
                          parms.get("OUTMODE"), parms.get("INMODE"))


def _emitted_attrs(device_cls, typ, parms, fclk="UNKNOWN"):
    """`[(attr, val)]` the device's IOLOGIC handlers emit for one cell."""
    from apycula.gowin_pack import GW5AST_138C

    device = object.__new__(device_cls)
    bel = _iologic_bel(typ, parms, fclk)
    attr_vals = device.common_iologic_handler(bel)
    if device_cls is GW5AST_138C:
        attr_vals += (device.get_out_iologic_attrs(bel) if "OUTMODE" in parms
                      else device.get_in_iologic_attrs(bel))
    return [(av.attr, str(av.val)) for av in attr_vals]


def _fuses_for(device_cls, typ, parms, ttyp=247, idx="A"):
    """The fuse set those attributes reach through the `IOLOGIC` table."""
    from apycula import attrids
    from apycula.chipdb import add_attr_val, get_shortval_fuses

    db = chipdb.load_chipdb(os.path.join(os.path.dirname(chipdb.__file__),
                                         f"{DEVICE}.msgpack.xz"))
    av = set()
    for attr, val in _emitted_attrs(device_cls, typ, parms):
        attr_id = attrids.iologic_attrids.get(attr)
        val_id = attrids.iologic_attrvals.get(val)
        if attr_id is not None and val_id is not None:
            add_attr_val(db, "IOLOGIC", av, attr_id, val_id)
    return {tuple(bit) for bit in get_shortval_fuses(db, ttyp, av,
                                                     f"IOLOGIC{idx}")}


def test_oddr_iddr_attr_gap_recorded():
    """`P3.T11` recorded a disposition for every attribute either side sets."""
    path = _otc_path(_ODDR_IDDR, "attr-gap.tsv")
    if path is None:
        pytest.skip("attr-gap.tsv not reachable from this checkout")
    lines = [l for l in open(path, encoding="utf-8").read().splitlines() if l]
    header = lines[0].split("\t")
    assert header[0] == "primitive" and "disposition" in header
    rows = [dict(zip(header, l.split("\t"))) for l in lines[1:]]
    assert rows, "an audit that measured nothing is not an audit"
    assert {r["disposition"] for r in rows} <= {"handler",
                                                "unexplained-justified"}
    assert all(r["justification"] for r in rows)


@pytest.mark.parametrize("primitive,parms", [
    ("ODDR", {"OUTMODE": "ODDRX1"}),
    ("IDDR", {"INMODE": "IDDRX1"}),
    ("IDDRC", {"INMODE": "IDDRX1"}),
])
def test_gw5ast138c_iologic_fuses_are_exactly_the_vendors(primitive, parms):
    """The 138C handler writes the measured vendor fuse set, and no more."""
    from apycula.gowin_pack import GW5AST_138C

    assert (_fuses_for(GW5AST_138C, primitive, parms)
            == VENDOR_IOLOGIC_FUSES_247A[primitive])


def test_gw5ast138c_iologic_emits_gsr_only_on_opt_in():
    """`GSR` is one fuse on this die and the vendor leaves it clear."""
    from apycula.gowin_pack import GW5AST_138C

    default = dict(_emitted_attrs(GW5AST_138C, "IDDR", {"INMODE": "IDDRX1"}))
    assert "GSR" not in default
    opted_in = dict(_emitted_attrs(GW5AST_138C, "IDDR",
                                   {"INMODE": "IDDRX1", "GSREN": "TRUE"}))
    assert opted_in["GSR"] == "ENGSR"


def test_gw5ast138c_iologic_carries_txclk_pol_as_its_own_attribute():
    """MEASURED (`P3.T13`): two vendor `OSER4` bitstreams differing in nothing
    but `TXCLK_POL` differ by exactly one fuse, `(8,125)`, decoded as the
    IOLOGIC attribute `TXCLK_POL=1`.  The pre-5A handler moved the parameter
    to `TSHX`, which this die's table does not spend a bit on, so the
    polarity never reached the bitstream at all."""
    from apycula.gowin_pack import GW5AST_138C

    default = dict(_emitted_attrs(GW5AST_138C, "OSER4", {"OUTMODE": "ODDRX2"}))
    assert "TXCLK_POL" not in default and "TSHX" not in default
    inverted = dict(_emitted_attrs(GW5AST_138C, "OSER4",
                                   {"OUTMODE": "ODDRX2", "TXCLK_POL": "1"}))
    assert inverted["TXCLK_POL"] == "1"
    assert "TSHX" not in inverted


def test_gw5ast138c_iologic_carries_hwl_as_its_own_attribute():
    """`HWL` is attribute 117 on the Arora V families, not the pre-5A
    `UPDATE=SAME`."""
    from apycula.gowin_pack import GW5AST_138C

    default = dict(_emitted_attrs(GW5AST_138C, "OSER4", {"OUTMODE": "ODDRX2"}))
    assert "HWL" not in default and "UPDATE" not in default
    held = dict(_emitted_attrs(GW5AST_138C, "OSER4",
                               {"OUTMODE": "ODDRX2", "HWL": "true"}))
    assert held["HWL"] == "TRUE"
    assert "UPDATE" not in held


def test_gw5a_25a_iologic_handler_untouched():
    """`S3`: the 25A handler's output is what it was before Phase 3."""
    from apycula.gowin_pack import GW5A_25A

    device = object.__new__(GW5A_25A)
    bel = _iologic_bel("ODDR", {"OUTMODE": "ODDRX1"})
    assert [(av.attr, str(av.val)) for av in device.common_iologic_handler(bel)] \
        == GW5A_25A_DEFAULT_ATTRS


def _oddr_iddr_rows():
    path = _otc_path(_ODDR_IDDR, "runs.jsonl")
    if path is None or not os.path.getsize(path):
        return None
    import json
    return [json.loads(l) for l in open(path, encoding="utf-8") if l.strip()]


def test_oddr_iddr_sweep_is_complete_at_e1():
    """Every point of the sweep is measured and reaches `E1`."""
    rows = _oddr_iddr_rows()
    if rows is None:
        pytest.skip("evidence/oddr-iddr/runs.jsonl not written yet")
    assert len(rows) == SWEEP_POINTS + B_HALF_POINTS
    assert len([r for r in rows if r["level"] == "E1"]) == len(rows)


def test_oddr_iddr_rows_e1():
    """The row is closed at `E1` over the shape's whole sweep.

    This carried a strict `xfail` until the item it named was settled: the
    three `IDDR` points differed on four `conns` because the two flows took
    the deserialiser's output out of the tile on different fabric wires (the
    vendor from `IOLOGIC.Q14` = `F7`, `nextpnr` from `IOLOGIC.Q8` = `F0`).
    `P3.T14`'s bitstreams decoded the vendor's whole wire-to-`Q_i` map, the
    rename landed, and the `EW10`/`W11` IO-tile wire alias closed the last
    two. All six points are `ok` at `E1` with `conns` 0.
    """
    rows = _oddr_iddr_rows()
    if rows is None:
        pytest.skip("evidence/oddr-iddr/runs.jsonl not written yet")
    assert len(rows) == SWEEP_POINTS + B_HALF_POINTS
    good = [r for r in rows if r["level"] == "E1" and r["verdict"] == "ok"]
    assert len(good) == len(rows)
    assert all(r["diff_count"]["conns"] == 0 for r in rows)


def test_oddr_iddr_decode_check_ok():
    """Every measured row round-trips through the unpacker (`C1` and `C2`)."""
    rows = _oddr_iddr_rows()
    if rows is None:
        pytest.skip("evidence/oddr-iddr/runs.jsonl not written yet")
    measured = [r for r in rows if r["verdict"] in ("ok", "diff")]
    assert measured
    for row in measured:
        assert row["decode_check"]["c1"] == "ok", row["run_id"]
        assert row["decode_check"]["c2"] == "ok", row["run_id"]


def test_oddr_iddr_no_raw_residual():
    """No row carries an unjustified leftover bit (`D35`)."""
    rows = _oddr_iddr_rows()
    if rows is None:
        pytest.skip("evidence/oddr-iddr/runs.jsonl not written yet")
    for row in rows:
        leftovers = row.get("unexplained_bits") or []
        assert all(isinstance(entry, dict) and entry.get("justification")
                   for entry in leftovers), row["run_id"]


# --------------------------------------------------------------------------
# The serialiser and deserialiser rows (`P3.T13`, `P3.T14`)
# --------------------------------------------------------------------------
_OSER = "oser"
_IDES = "ides"


def _rows(slug):
    path = _otc_path(slug, "runs.jsonl")
    if path is None or not os.path.exists(path) or not os.path.getsize(path):
        return None
    import json
    return [json.loads(l) for l in open(path, encoding="utf-8") if l.strip()]


def test_oser_rows_e1():
    """The output-serialiser row is closed at `E1` (`P3.T13`).

    Five of the six points are `E1` `verdict: ok`; `ovideo-default` is the
    one exception and has its own test, because "one point short" must not be
    something the suite can drift into silently.
    """
    rows = _rows(_OSER)
    if rows is None:
        pytest.skip("evidence/oser/runs.jsonl not written yet")
    assert len(rows) == SWEEP_POINTS + B_HALF_POINTS
    good = [r for r in rows if r["level"] == "E1" and r["verdict"] == "ok"]
    assert len(good) == len(rows) - 1
    assert {r["sweep"]["POINT"] for r in rows} - {
        r["sweep"]["POINT"] for r in good} == {"ovideo-default"}


def test_oser_rows_have_no_set_level_difference():
    """Every point matches the vendor on cells, attributes and connections --
    including the one that does not reach `E1`."""
    rows = _rows(_OSER)
    if rows is None:
        pytest.skip("evidence/oser/runs.jsonl not written yet")
    for row in rows:
        counts = row["diff_count"]
        assert (counts["cells"], counts["attrs"], counts["conns"]) == (0, 0, 0), \
            row["run_id"]
        assert not row["unexplained_bits"], row["run_id"]


def test_oser_ovideo_decode_check_is_closed_by_an_output_path_alias():
    """MEASURED: an `OVIDEO`'s `OUTMODE` fuses decode back as value id 74,
    `LVDSOUT` -- which is what `gowin_pack` itself writes for a `VIDEOTX`, so
    `c1` reported the `OVIDEO` missing from a bitstream that carried it. The
    alias is safe because it is applied on the **output** path only: the same
    id in `INMODE` is a different mode and must keep failing to resolve, which
    is why the row could be closed without renaming a genuine differential
    output on the GW5A-25A."""
    rows = _rows(_OSER)
    if rows is None:
        pytest.skip("evidence/oser/runs.jsonl not written yet")
    row = next(r for r in rows if r["sweep"]["POINT"] == "ovideo-default")
    assert row["decode_check"] == {"c1": "ok", "c2": "ok"}
    from apycula import gowin_unpack
    assert gowin_unpack._iologic_outmode_alias["LVDSOUT"] == "OVIDEO"


def test_oser_lane_is_pinned_in_both_flows():
    """`D107`: the HCLK lane is a matched term, so no point may carry a
    `§5.3` mask entry for the fast-clock selection."""
    rows = _rows(_OSER)
    if rows is None:
        pytest.skip("evidence/oser/runs.jsonl not written yet")
    for row in rows:
        assert not any("FCLKSEL" in str(b) for b in row["unexplained_bits"]), \
            row["run_id"]


def test_oser_widths_covered():
    """All four widths of the family are measured, not just the two the
    parameter sweep can move."""
    rows = _rows(_OSER)
    if rows is None:
        pytest.skip("evidence/oser/runs.jsonl not written yet")
    from fuzz.gw5ast138c.shapes import io_ser
    measured = {io_ser.PRIMITIVE_OF_WIDTH[io_ser.POINTS[
        r["sweep"]["POINT"]][0]] for r in rows}
    assert measured == {"OSER4", "OSER8", "OSER10", "OVIDEO"}


def test_oser_no_mem_variants_touched():
    """`OSER4_MEM`/`OSER8_MEM` belong to Phase 5b; this row must not have
    measured one by accident."""
    rows = _rows(_OSER)
    if rows is None:
        pytest.skip("evidence/oser/runs.jsonl not written yet")
    for row in rows:
        assert "_MEM" not in row["primitive"], row["run_id"]
        assert "_MEM" not in row["sweep"]["POINT"], row["run_id"]


def test_ides_rows_e1():
    """The input-deserialiser row reaches `E1` on its whole sweep (`P3.T14`).

    Every point matches the vendor on cells, attributes **and** connections
    and passes both decode checks. The `conns` residual this row was opened
    with -- the `Q0`/`Q1` fabric-wire question the `ODDR`/`IDDR` row left open
    -- was settled here at three widths (`IDES4` -> `Q8`-`Q11`, `IDES8` ->
    `Q8`-`Q15`, `IDES10` -> `Q6`-`Q15`) and then taken to zero by the
    `EW10`/`W11` IO-tile wire alias.
    """
    rows = _rows(_IDES)
    if rows is None:
        pytest.skip("evidence/ides/runs.jsonl not written yet")
    assert len(rows) == SWEEP_POINTS + B_HALF_POINTS
    assert all(r["level"] == "E1" for r in rows)
    for row in rows:
        counts = row["diff_count"]
        assert (counts["cells"], counts["attrs"], counts["conns"]) == (0, 0, 0), \
            row["run_id"]
        assert row["decode_check"] == {"c1": "ok", "c2": "ok"}, row["run_id"]


def test_ides_input_fclk_selection_is_not_fuse_backed():
    """MEASURED (`P3.T14`): no vendor input bitstream sets `FCLKSEL*` or
    `WRFCLKSEL`, where the output path sets three on the same tile type -- so
    the GW5A-25A's `FCLKSEL5`/`6`/`7` emission is correctly absent here."""
    from apycula.gowin_pack import GW5AST_138C

    attrs = dict(_emitted_attrs(GW5AST_138C, "IDES4", {"INMODE": "IDDRX2"},
                                fclk="SPINE12"))
    assert not [a for a in attrs if a.startswith("FCLKSEL")]
    assert "WRFCLKSEL" not in attrs


def _generated_periods(shape_module, point, tmp_path):
    """`(fclk period, pclk period)` of one point's **generated design**.

    The slow clock is stated by the `CLKDIV` the design carries, not by a
    `create_clock` line: `gen.render_sdc` is Phase 0's and emits one
    `create_clock` per **port**, and `PCLK` is internal to the design and
    divides differently at every point, so a per-point period cannot reach
    the `.sdc` through `ShapeSpec.clocks` at all.  The ratio is therefore
    asserted where the design really carries it.
    """
    import re as _re
    from fuzz.gw5ast138c.harness import gen
    spec = shape_module.SPEC
    design = tmp_path / point
    gen.run(spec, str(design), point)
    sdc = (design / "top.sdc").read_text()
    verilog = (design / "top.v").read_text()
    fclk = float(_re.search(r"-name fclk -period ([0-9.]+)", sdc).group(1))
    div = float(_re.search(r'DIV_MODE = "([0-9.]+)"', verilog).group(1))
    return fclk, fclk * div


def test_ides_pclk_ratio_ides4(tmp_path):
    """`IDES4`'s `PCLK` period is exactly twice its `FCLK`'s (UG304E p.62)."""
    from fuzz.gw5ast138c.shapes import io_des
    fclk, pclk = _generated_periods(io_des, "ides4-reset-pad", tmp_path)
    assert pclk == 2 * fclk


def test_ides_pclk_ratio_ides8(tmp_path):
    """`IDES8`'s `PCLK` period is exactly four times its `FCLK`'s."""
    from fuzz.gw5ast138c.shapes import io_des
    fclk, pclk = _generated_periods(io_des, "ides8-reset-pad", tmp_path)
    assert pclk == 4 * fclk


def test_gearbox_shapes_hold_no_fabric_cell(tmp_path):
    """`D105`: neither gearbox shape puts a cell between a package ball and
    the primitive under test, at any point of its sweep."""
    from fuzz.gw5ast138c.shapes import io_des, io_ser
    for module in (io_ser, io_des):
        for point in module.POINTS:
            rtl = module.SPEC.rtl(module.SPEC, point)
            assert "always @" not in rtl, (module.__name__, point)
            assert " reg " not in rtl, (module.__name__, point)


def test_gearbox_shapes_pin_their_divider_in_both_flows(tmp_path):
    """One `INS_LOC` line reaches both `.cst` files (`D107`).

    The `PCLK` net ends on the scoped tile, so a freely placed `CLKDIV` would
    give it two identities -- and the divider consumes its lane's HCLK wire,
    so the same line is what pins the lane the gearbox's `FCLK` lands on.  It
    therefore has to survive into the **open-flow** copy of the constraints,
    which is exactly what it did not do while the reader took `SIDE[0|1]`
    only."""
    from fuzz.gw5ast138c.harness import gen
    from fuzz.gw5ast138c.shapes import _io_base, io_des, io_ser
    line = 'INS_LOC "pclk_div" %s;' % _io_base.GEARBOX_CLKDIV_INS_LOC
    for module in (io_ser, io_des):
        spec = module.SPEC
        point = spec.baseline_value
        assert gen.ins_loc_of(spec, point)["pclk_div"] == \
            _io_base.GEARBOX_CLKDIV_INS_LOC
        assert line in gen.render_cst(spec, point)
        assert line in gen.render_cst(spec, point, with_ins_loc=False)
        # no second, flow-private placement: a `BEL` attribute here would let
        # the two flows be pinned to different lanes without anyone noticing
        assert "(* BEL" not in spec.rtl(spec, point)


def test_gearbox_shapes_sit_in_the_block_they_pin(db_138c):
    """A `CLKDIV` pins the lane of *its own* block, so a gearbox served by a
    different block would be unpinned however the divider is placed."""
    from apycula.chipdb import _gw5a_hclk_locs
    from fuzz.gw5ast138c.shapes import _io_base, io_des, io_ser

    block_cell = (_io_base.GEARBOX_HCLK_BLOCK_XY[1],
                  _io_base.GEARBOX_HCLK_BLOCK_XY[0])
    blocks = _gw5a_hclk_locs[DEVICE]
    idx = [i for i, cell in blocks.items() if tuple(cell) == block_cell]
    assert len(idx) == 1, "the pinned CLKDIV names no HCLK block of this die"
    served = {tuple(c) for c in db_138c.io2hclk[idx[0]]}
    for module in (io_ser, io_des):
        # a ScopeSpec tile is (x, y) = (col, row); io2hclk is keyed (row, col)
        x, y = module.SCOPE_TILES[0]
        assert (y, x) in served, (module.__name__, (y, x))


def test_gearbox_scope_is_the_pad_cell_in_himbaechel_order(db_138c):
    """A scope tile is `(x, y)`, and a shape that wrote `(row, col)` scopes a
    different tile entirely -- MEASURED here as `cell vendor=DFF
    open=<absent>` on a tile neither design's gearbox is in."""
    import json
    from fuzz.gw5ast138c.shapes import io_des, io_ser

    path = _otc_path("iologic", "pin-hclk-138c.json")
    if path is None:
        pytest.skip("pin-hclk-138c.json not reachable from this checkout")
    pins = {p["ball"]: p for p in json.load(open(path, encoding="utf-8"))["pins"]}
    for module, ball in ((io_ser, io_ser.OSER_BALL), (io_des, io_des.IDES_BALL)):
        pin = pins[ball]
        assert module.SCOPE_TILES == ((pin["col"], pin["row"]),), ball
        assert pin["half"] == "A", ball


def test_gearbox_shapes_place_the_iologic_on_an_a_half_ball():
    """An IOLOGIC is configurable on the A half only -- the B half's fuse
    table holds 3 coordinates against the A half's 100 -- so a gearbox on a
    `B` ball would have nothing to compare (`P3.T11`'s named gap)."""
    from fuzz.gw5ast138c.shapes import _io_base, io_des, io_ser
    for ball in (io_ser.OSER_BALL, io_des.IDES_BALL):
        assert _io_base.SAFE_PINS[ball].site.endswith("A"), ball


# ---------------------------------------------------------------- P3.F1
# The HCLK -> IOLOGIC FCLK wiring (`D106`).  Every assertion below is about
# the *derivation*: the arcs come from the shipped tables, so a test that
# restated the table would prove nothing.

def _iologic_cells(db):
    """Every cell of the grid that carries an IOLOGIC bel."""
    return {(row, col)
            for row, ttyps in enumerate(db.grid)
            for col, ttyp in enumerate(ttyps)
            if any(name.startswith("IOLOGIC") for name in db.tiles[ttyp].bels)}


def test_io2hclk_serves_every_iologic_cell_and_nothing_else(db_138c):
    """An IOLOGIC without an HCLK block has no fast clock at all, and a cell
    without an IOLOGIC has nothing to clock."""
    served = {cell for cells in db_138c.io2hclk.values() for cell in cells}
    assert served == _iologic_cells(db_138c)


def test_io2hclk_gives_each_cell_exactly_one_block(db_138c):
    """The arcs partition the periphery: two blocks over one cell would let
    the placer pick a block the fuse set cannot express."""
    served = [cell for cells in db_138c.io2hclk.values() for cell in cells]
    assert len(served) == len(set(served))


def test_io2hclk_arc_contains_its_own_block_cell(db_138c):
    """The property that fixes the bottom side's boundary: a block serves the
    run of its own side that it sits in.  The GW5A-25A's hand-traced arcs have
    it, and it is what rules out reading the (108,118) bridge as a boundary."""
    from apycula.chipdb import _gw5a_hclk_locs, gw5_die_side

    for hclk_idx, (block_row, block_col) in _gw5a_hclk_locs[DEVICE].items():
        side, pos = gw5_die_side(db_138c, block_row, block_col)
        arc = [gw5_die_side(db_138c, row, col)
               for row, col in db_138c.io2hclk[hclk_idx]]
        assert {s for s, _ in arc} == {side}, hclk_idx
        positions = [p for _, p in arc]
        assert min(positions) < pos < max(positions), hclk_idx


def test_io2hclk_places_the_vendor_oser4_cell_in_block_one(db_138c):
    """The cross-check the derivation is calibrated against: the vendor's
    `OSER4` (`$OTC/evidence/oser/attr-audit.json`) sits at `IOR51A`, cell
    (50, 181), and set `FCLKSEL1=HCLK2` -- lane 2 of the block that serves it,
    which this walk has to name."""
    assert (50, 181) in db_138c.io2hclk[1]
    assert sorted(db_138c.hclk_pips[(50, 181)]["FCLKA"]) == [
            "HCLK10", "HCLK11", "HCLK12", "HCLK13"]


def test_gw5ast138c_out_iologic_selects_the_measured_fclk_fuses():
    """`FCLKSEL1`/`FCLKSEL2` are the two bits the packer used to miss."""
    from apycula.gowin_pack import GW5AST_138C

    device = object.__new__(GW5AST_138C)
    bel = _iologic_bel("OSER4", {"OUTMODE": "ODDRX2"})
    bel = type(bel)(bel.x, bel.y, bel.idx_str, bel.cell, "SPINE12",
                    "ODDRX2", None)
    emitted = {(av.attr, str(av.val))
               for av in device.get_out_iologic_attrs(bel)}
    assert ("WRFCLKSEL", "UNK102") in emitted
    assert ("FCLKSEL1", "HCLK2") in emitted
    assert ("FCLKSEL2", "HCLK2_") in emitted


def test_gw5ast138c_out_iologic_selects_nothing_without_an_hclk():
    """A gearbox whose `FCLK` the router did not bring off an HCLK must not
    get a selection fuse invented for it."""
    from apycula.gowin_pack import GW5AST_138C

    device = object.__new__(GW5AST_138C)
    bel = _iologic_bel("OSER4", {"OUTMODE": "ODDRX2"})
    emitted = {av.attr for av in device.get_out_iologic_attrs(bel)}
    assert not emitted & {"WRFCLKSEL", "FCLKSEL1", "FCLKSEL2"}


def _dummy_bel(outmode):
    """The `IOLOGIC_DUMMY` cell `nextpnr` places on the aux half of a gearbox."""
    class _Cell:
        pass

    class _Bel:
        pass

    cell = _Cell()
    cell.typ = "IOLOGIC_DUMMY"
    cell.parms = {"OUTMODE": outmode}
    cell.attrs = {}
    bel = _Bel()
    bel.cell = cell
    return bel


def test_narrow_output_gearbox_aux_half_costs_no_fuse_on_138c():
    """`OSER8`/`OSER10`/`OVIDEO` leave the aux cell clear, as the vendor does.

    MEASURED (`P3.F3`): the vendor's `OSER8` at the pad pair (108, 52) writes
    nothing into the aux cell's `IOLOGICB`, while the pre-5A model wrote five
    fuses there.
    """
    from apycula.gowin_pack import GW5AST_138C

    device = object.__new__(GW5AST_138C)
    assert device.get_IOLOGIC_DUMMY_fuses(_dummy_bel("DDRENABLE")) == []


def test_io16_aux_half_still_configures_on_138c():
    """The 16:1 gearbox is the exception: its aux half is really configured.

    MEASURED (`P3.T16a`): the vendor's `OSER16` sets six bits in the aux
    cell, so `DDRENABLE16` must keep reaching the base handler.
    """
    from apycula.gowin_pack import GW5A, GW5AST_138C

    sentinel = object()
    device = object.__new__(GW5AST_138C)
    own = "get_IOLOGIC_DUMMY_fuses" in vars(GW5A)
    original = vars(GW5A).get("get_IOLOGIC_DUMMY_fuses")
    GW5A.get_IOLOGIC_DUMMY_fuses = lambda self, bel: sentinel
    try:
        reached = device.get_IOLOGIC_DUMMY_fuses(_dummy_bel("DDRENABLE16"))
    finally:
        if own:
            GW5A.get_IOLOGIC_DUMMY_fuses = original
        else:
            del GW5A.get_IOLOGIC_DUMMY_fuses
    assert reached is sentinel
