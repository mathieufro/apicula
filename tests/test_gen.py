"""Tests for `fuzz.gw5ast138c.harness.gen` and the `ShapeSpec` type (P0.T20).

`gen.run(spec, design_dir)` renders exactly three files -- `top.v`, `top.cst`,
`top.sdc` -- and applies the unconditional generation-time `.cst` assertion
(`spec.md` 7.10(5)-(6), `D20a`-`D20c`, `spec-harness.md` 7) before writing a
single byte.  The generated `top.v` is checked through yosys so a generator
that emits invalid Verilog fails here rather than in a batch.
"""
import dataclasses
import importlib
import shutil
import subprocess

import pytest

gen = importlib.import_module("fuzz.gw5ast138c.harness.gen")
shapes = importlib.import_module("fuzz.gw5ast138c.shapes")
smoke = importlib.import_module("fuzz.gw5ast138c.shapes.smoke")

YOSYS = "/opt/homebrew/bin/yosys"


def _yosys_reads(path):
    """True iff yosys parses `path` as Verilog (the generator's own gate)."""
    if not shutil.which(YOSYS):
        pytest.skip("yosys not present at " + YOSYS)
    proc = subprocess.run(
        [YOSYS, "-q", "-p", "read_verilog " + str(path)],
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stderr
    return True


@pytest.mark.heavy  # invokes the real yosys binary via _yosys_reads
def test_gen_emits_three_files(tmp_path):
    written = gen.run(smoke.SPEC, tmp_path)
    names = sorted(p.name for p in tmp_path.iterdir())
    assert names == ["top.cst", "top.sdc", "top.v"]
    assert len(names) == 3
    for name in names:
        assert (tmp_path / name).stat().st_size > 0
    assert sorted(p.name for p in written) == names
    # a generator that emits invalid Verilog fails here
    assert _yosys_reads(tmp_path / "top.v")


def test_gen_cst_defaults_asserted(tmp_path):
    # (1) a used pin with no IO_TYPE -> CstDefaultError naming that pin
    bad_pins = dict(smoke.SPEC.pins)
    bad_pins["dout"] = dataclasses.replace(bad_pins["dout"], io_type=None)
    no_io_type = dataclasses.replace(smoke.SPEC, pins=bad_pins)
    with pytest.raises(gen.CstDefaultError) as exc_io:
        gen.run(no_io_type, tmp_path / "a")
    assert "dout" in str(exc_io.value)

    # (2) an LVCMOS33 pin placed in bank 6 -> BankPolicyError (thermal, F73/PR #423)
    ddr_pins = dict(smoke.SPEC.pins)
    ddr_pins["dout"] = dataclasses.replace(ddr_pins["dout"], bank=6)
    in_bank6 = dataclasses.replace(
        smoke.SPEC,
        pins=ddr_pins,
        bank_vccio={**smoke.SPEC.bank_vccio, 6: "1.5"},
    )
    with pytest.raises(gen.BankPolicyError) as exc_bank:
        gen.run(in_bank6, tmp_path / "b")
    assert "dout" in str(exc_bank.value)
    assert "6" in str(exc_bank.value)

    # exactly 2 distinct error types exercised, both refusing to write anything
    assert len({gen.CstDefaultError, gen.BankPolicyError}) == 2
    assert not (tmp_path / "a").exists()
    assert not (tmp_path / "b").exists()


def test_gen_gray_code_single_bit():
    spec = dataclasses.replace(
        smoke.SPEC,
        sweep_axis="C_STATIC_DLY",
        sweep_values=list(range(256)),
        baseline_value=0,
    )
    ordered = gen.sweep_order(spec)
    assert len(ordered) == 256
    assert sorted(ordered) == list(range(256))
    pairs = list(zip(ordered, ordered[1:]))
    assert len(pairs) == 255
    assert sum(1 for a, b in pairs if bin(a ^ b).count("1") == 1) == 255


def test_gen_smoke_has_primitive_and_scope(tmp_path):
    assert smoke.SPEC.primitive == "DFF"
    assert smoke.SPEC.scope.tiles == [(2, 1)]
    assert isinstance(smoke.SPEC.scope, shapes.ScopeSpec)
    gen.run(smoke.SPEC, tmp_path)
    cst = (tmp_path / "top.cst").read_text()
    ins_loc = [ln for ln in cst.splitlines() if ln.strip().startswith("INS_LOC")]
    assert len(ins_loc) == 1
    # P0.T20 states `top.dut_dff`; measured, the vendor resolves only the flat
    # instance name and raises `CT1135 Can't find object named 'top.dut_dff'`
    # on the qualified one (P0.T19's V4 run). Deviation recorded.
    assert '"dut_dff"' in ins_loc[0]
    assert "R2C3[0][A]" in ins_loc[0]


def test_gen_drive_outputs_only(tmp_path):
    # DRIVE on an input pin -> DriveDirectionError (CT1108, measured P0.T19).
    bad_pins = dict(smoke.SPEC.pins)
    bad_pins["din"] = dataclasses.replace(bad_pins["din"], drive=8, direction="input")
    drive_on_input = dataclasses.replace(smoke.SPEC, pins=bad_pins)
    with pytest.raises(gen.DriveDirectionError) as exc:
        gen.run(drive_on_input, tmp_path / "a")
    assert "din" in str(exc.value)
    assert not (tmp_path / "a").exists()

    # DRIVE on the output pin is fine, and is the only pin that gets emitted.
    cst = gen.render_cst(smoke.SPEC)
    drive_lines = [ln for ln in cst.splitlines() if "DRIVE=" in ln]
    assert len(drive_lines) == 1
    assert '"dout"' in drive_lines[0]
    for port in ("clk", "rst_n", "din"):
        port_lines = [ln for ln in cst.splitlines() if ('"%s"' % port) in ln]
        assert not any("DRIVE=" in ln for ln in port_lines)


def test_gen_ins_loc_flat(tmp_path):
    # a module-qualified INS_LOC instance path -> InsLocError (CT1135).
    qualified = dataclasses.replace(
        smoke.SPEC, ins_loc={"top.dut_dff": "R2C3[0][A]"}
    )
    with pytest.raises(gen.InsLocError) as exc:
        gen.run(qualified, tmp_path / "a")
    assert "top.dut_dff" in str(exc.value)
    assert not (tmp_path / "a").exists()

    # the flat name renders exactly 1 INS_LOC line naming it.
    cst = gen.render_cst(smoke.SPEC)
    ins_loc = [ln for ln in cst.splitlines() if ln.strip().startswith("INS_LOC")]
    assert len(ins_loc) == 1
    assert '"dut_dff"' in ins_loc[0]


def test_gen_rejects_config_pin(tmp_path):
    # a pin at a known config-role location (EMCCLK, measured P0.T19) ->
    # ConfigPinError, whether or not the rest of the pin is otherwise clean.
    bad_pins = dict(smoke.SPEC.pins)
    bad_pins["din"] = dataclasses.replace(bad_pins["din"], loc="V22")
    on_emcclk = dataclasses.replace(smoke.SPEC, pins=bad_pins)
    with pytest.raises(gen.ConfigPinError) as exc:
        gen.run(on_emcclk, tmp_path / "a")
    assert "din" in str(exc.value)
    assert "EMCCLK" in str(exc.value)
    assert not (tmp_path / "a").exists()

    # the smoke shape's real pins are all clear of the denylist.
    for port, pin in smoke.SPEC.pins.items():
        assert gen.config_role_of_loc(pin.loc) is None, port


@pytest.mark.heavy  # invokes the real yosys binary via _yosys_reads
def test_gen_regenerated_oracle_smoke_passes_cst_assertion(tmp_path):
    reference = gen.run(smoke.SPEC, tmp_path)
    errors = gen.assert_cst_defaults(smoke.SPEC)
    assert errors == []

    target = gen.datastore_root() / "oracle-smoke"
    regenerated = gen.run(smoke.SPEC, target)
    assert sorted(p.name for p in regenerated) == ["top.cst", "top.sdc", "top.v"]
    for name in ("top.v", "top.cst", "top.sdc"):
        assert (target / name).read_bytes() == (tmp_path / name).read_bytes()
    assert len(reference) == 3
    assert _yosys_reads(target / "top.v")
