"""`P0.T26` -- levels `E1` (placement identity) and `E2` (the pip-set bonus).

Four tests, named by the blueprint.  None needs a Gowin install or a real
bitstream: what is pinned here is (a) that every `INS_LOC` line the exporter
writes is one nextpnr's own reader regex accepts, (b) the `cls/[AB] -> z`
mapping `gowin_arch_gen.py:1330,1342` fixes, (c) that a vendor `.tr` showing a
constrained cell somewhere else drops the row to `E0` with a reason (`EC9`),
and (d) that an `E2` fraction is never a verdict term (`D32`).
"""
import re

from fuzz.gw5ast138c.harness import equiv
from fuzz.gw5ast138c.shapes import ScopeSpec

# nextpnr's own reader regex, copied verbatim from
# `himbaechel/uarch/gowin/cst.cc:94-96` and transliterated to Python only by
# unescaping C++ string escapes.  The test asserts against THIS, not against
# the exporter's own copy of it.
NEXTPNR_INSLOCRE = re.compile(
    r'INS_LOC +"([^"]+)" +R([0-9]+)C([0-9]+)\[([0-9])\]\[([AB])\] *;.*[\s\S]*')


def _pnr_cell(name, x, y, bel, typ):
    return {"name": name, "type": typ, "bel": bel, "site": (x, y),
            "attrs": {}, "params": {}}


def test_e1_insloc_syntax_matches_nextpnr_regex():
    """8 LUTs + 8 DFFs -> 16 lines, all 16 accepted by nextpnr's regex."""
    cells = ([_pnr_cell(f"lut{i}", 2, 1, f"LUT{i}", "LUT4") for i in range(8)]
             + [_pnr_cell(f"dff{i}", 2, 1, f"DFF{i}", "DFF") for i in range(8)])
    lines = equiv.insloc_lines(cells)["lines"]
    assert len(lines) == 16
    assert all(NEXTPNR_INSLOCRE.match(line) for line in lines)


def test_e1_z_mapping():
    """The five exact values `gowin_arch_gen.py:1330,1342` fixes."""
    assert equiv.z_lut(0, "A") == 0
    assert equiv.z_dff(0, "A") == 1
    assert equiv.z_lut(0, "B") == 2
    assert equiv.z_lut(3, "B") == 14
    assert equiv.z_dff(3, "B") == 15


def test_e1_drops_to_e0_when_placement_ignored(tmp_path):
    """A vendor `.tr` placing the constrained cell elsewhere -> `E0` + reason."""
    exported = equiv.insloc_lines(
        [_pnr_cell("dut_dff", 2, 1, "DFF0", "DFF")])["exported"]
    tr = tmp_path / "run.tr"
    tr.write_text(
        "   AT     DELAY   TYPE   RF   FANOUT       LOC                NODE\n"
        "  6.582   5.968   tNET   RR   1        R12C5[0][A]   dut_dff/CLK\n"
        "  6.927   0.344   tC2Q   RR   1        R12C5[0][A]   dut_dff/Q\n")
    realised = equiv.parse_vendor_placement(tr_path=str(tr))
    out = equiv.level_e1(exported, realised, scope=ScopeSpec(tiles=[(2, 1)]))
    assert out["level"] == "E0"
    assert out["notes"]


def test_e2_fraction_is_never_a_verdict():
    """An `E2` fraction of 0.0 leaves the verdict at `EQUIV E1 ok`."""
    result = equiv.E0Result(verdict="EQUIV E0 ok", level="E0")
    result.e1 = {"level": "E1", "checked": 1, "matched": 1,
                 "mismatched": [], "unobserved": [], "notes": ""}
    result.e2 = {"candidates": 0, "identical": 0, "fraction": 0.0, "nets": [],
                 "note": "no single-legal-path net in scope"}
    equiv.apply_level(result, "E2")
    assert result.e2["fraction"] == 0.0
    assert result.verdict == "EQUIV E1 ok"
    assert equiv.verdict_line(result) == "EQUIV E1 ok"


def test_e1_export_skips_instances_the_vendor_renamed(tmp_path):
    """Measured on the smoke design: a constraint naming an instance
    GowinSynthesis renamed makes `gw_sh` abort with
    `ERROR (CT1135) : Can't find object named ...`, which loses the whole run.
    So a name the vendor netlist does not carry is skipped, with the reason.
    """
    cells = [_pnr_cell("dut_dff", 2, 1, "DFF0", "DFF"),
             _pnr_cell("dut_dff_passthrough_lut$", 2, 1, "LUT0", "LUT4")]
    out = equiv.insloc_lines(cells, known_instances={"dut_dff", "ctx_0_s0"})
    assert out["lines"] == ['INS_LOC "dut_dff" R2C3[0][A];']
    assert [s["name"] for s in out["skipped"]] == ["dut_dff_passthrough_lut$"]
    assert "CT1135" in out["skipped"][0]["why"]
