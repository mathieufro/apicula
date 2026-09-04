"""`P0.T23` -- the `E0` core of the equivalence checker.

Six tests, named by the blueprint.  None of them needs a Gowin install or a
real bitstream: the unpack step is exercised separately by the `Done when`
command, while the algebra of the three sets is what these tests pin down.
"""
import pytest

from fuzz.gw5ast138c.harness import equiv
from fuzz.gw5ast138c.harness.equiv import Cell, Netlist, ScopeUndefinedError
from fuzz.gw5ast138c.shapes import ScopeSpec, ShapeSpec


# --------------------------------------------------------------------------
# helpers -- a tiny hand-built netlist, so the set algebra is testable without
# a bitstream (the real pair is the Done-when command's job).
# --------------------------------------------------------------------------
def dut(x=2, y=1, z=0, typ="DFF"):
    return Cell(x, y, z, typ)


def tiny(net_label="n0", cell_type="DFF", extra_cells=()):
    """One DFF in tile (2,1) with a D/CLK/Q port map, plus optional extras."""
    d = Cell(2, 1, 0, cell_type)
    driver = Cell(0, 0, 0, "IBUF")
    cells = {d: frozenset({("FF_TYPE", "DFF")}),
             driver: frozenset({("IO_TYPE", "LVCMOS33")})}
    conns = {d: {"D": net_label, "CLK": "clk", "Q": "q"},
             driver: {"O": net_label}}
    nets = {
        net_label: frozenset({(d, "D"), (driver, "O")}),
        "clk": frozenset({(d, "CLK")}),
        "q": frozenset({(d, "Q")}),
    }
    for cell, attrs, cconns in extra_cells:
        cells[cell] = attrs
        conns[cell] = cconns
    return Netlist(cells=cells, conns=conns, nets=nets, pip_count=7)


SCOPE = ScopeSpec(tiles=[(2, 1)])


# --------------------------------------------------------------------------
def test_equiv_e0_identical_is_ok():
    a = tiny()
    b = tiny()
    result = equiv.compare_e0(a, b, scope=SCOPE, mask=equiv.load_mask(None))
    assert result.verdict == "EQUIV E0 ok"
    assert equiv.verdict_line(result).startswith("EQUIV E0 ok")
    assert result.diff_count["cells"] == 0
    assert result.diff_count["attrs"] == 0
    assert result.diff_count["conns"] == 0


def test_equiv_e0_reports_first_diff_shape():
    import re

    a = tiny(cell_type="DFF")
    b = tiny(cell_type="DFFR")
    result = equiv.compare_e0(a, b, scope=SCOPE, mask=equiv.load_mask(None))
    assert result.verdict == "DIFF"
    assert re.match(
        r"^tile \(\d+,\d+\) bel \d+: (cell|attr|port) vendor=.* open=.*$",
        result.first_diff), result.first_diff
    assert result.diff_count["cells"] == 1


def test_equiv_net_identity_is_endpoint_set():
    a = tiny(net_label="net_17")
    b = tiny(net_label="$auto$4711")
    result = equiv.compare_e0(a, b, scope=SCOPE, mask=equiv.load_mask(None))
    assert result.diff_count["conns"] == 0


def test_equiv_abort_on_failed_build(tmp_path):
    design = tmp_path / "oracle-smoke"
    (design / "run" / "impl" / "pnr").mkdir(parents=True)
    (design / "run" / "impl" / "pnr" / "run.fs").write_text("//vendor\n")
    # no top.fs: the open flow failed.
    (design / "yosys.log").write_text("ERROR\n")
    result = equiv.compare_design(str(design), level="E0", mask_path=None)
    assert result.verdict == "ABORT"
    assert result.log_path is not None
    rows = equiv.evidence_rows(result)
    assert [r for r in rows if r["verdict"] == "ok"] == []


def test_equiv_scope_is_shapespec_tiles():
    from fuzz.gw5ast138c.shapes.smoke import SPEC

    scope = equiv.scope_of(SPEC)
    assert scope.tiles == [(2, 1)]

    # A cell planted in another tile is not compared at all ...
    elsewhere = (Cell(9, 9, 0, "LUT4"), frozenset({("INIT", "0xdead")}), {})
    a = tiny()
    b = tiny(extra_cells=[elsewhere])
    cells_a, _, _ = equiv.canonicalise(a, scope)
    assert {(c.x, c.y) for c in cells_a} == {(2, 1)}
    result = equiv.compare_e0(a, b, scope=scope, mask=equiv.load_mask(None))
    assert result.diff_count["cells"] == 0


def test_equiv_null_primitive_requires_calibration():
    null_spec = ShapeSpec(
        name="nullprim", primitive=None, sweep_axis="none", sweep_values=[None],
        baseline_value=None, pins={}, bank_vccio={}, scope=ScopeSpec(tiles=[]),
        rtl=lambda spec, v=None: "")
    with pytest.raises(ScopeUndefinedError):
        equiv.scope_of(null_spec, calibration=False)
    assert equiv.scope_of(null_spec, calibration=True) is None
