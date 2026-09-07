"""The dual-purpose-pin sweep shape (`P2.T28`).

What these guard is the sweep's *isolation*: nine points, one option each
(three at the last one), and two tool namespaces that never cross.  A point
that quietly set two options would attribute one option's fuses to the other,
and a `-use_...` string handed to `gowin_pack` would be accepted as a netlist
path rather than refused (`F34`).
"""
import re

import pytest

from fuzz.gw5ast138c.harness import gen
from fuzz.gw5ast138c.shapes import dualpin

SPEC = dualpin.SPEC

GWSH_FORM = re.compile(r"^-use_[a-z0-9]+_as_gpio 1$")
PACK_FORM = re.compile(r"^--[a-z0-9]+_as_gpio$")
VOPT_FORM = re.compile(r"^[a-z0-9]+_as_gpio$")


def test_dualpin_shape_emits_nine_sweep_points():
    assert len(dualpin.SWEEP_POINTS) == 9
    assert SPEC.sweep_values == [dualpin.BASELINE] + dualpin.SWEEP_POINTS
    assert SPEC.baseline_value == dualpin.BASELINE


def test_dualpin_shape_one_option_per_point():
    counts = [len(dualpin.options_of(p)) for p in dualpin.SWEEP_POINTS]
    assert counts[:8] == [1] * 8
    assert counts[8] == 3
    assert dualpin.options_of(dualpin.BASELINE) == ()


def test_dualpin_shape_namespaces_never_cross():
    for point in [dualpin.BASELINE] + dualpin.SWEEP_POINTS:
        for opt in gen.gwsh_options_of(SPEC, point):
            assert GWSH_FORM.match(opt), opt
        for flag in gen.pack_flags_of(SPEC, point):
            assert PACK_FORM.match(flag), flag
        for vopt in gen.nextpnr_vopts_of(SPEC, point):
            assert VOPT_FORM.match(vopt), vopt


def test_dualpin_shape_vopts_only_for_options_nextpnr_knows():
    """`gowin_pack` raises when a packer flag and the netlist disagree."""
    assert gen.nextpnr_vopts_of(SPEC, "sspi") == ["sspi_as_gpio"]
    assert gen.nextpnr_vopts_of(SPEC, "i2c") == ["i2c_as_gpio"]
    assert gen.nextpnr_vopts_of(SPEC, "mspi") == []
    assert gen.nextpnr_vopts_of(SPEC, "ae350_triple") == ["sspi_as_gpio"]


def test_dualpin_shape_design_is_constant_across_the_sweep():
    """Only the option set moves; a moved bit is therefore the option's."""
    bodies = {re.sub(r"//.*", "", gen.render_verilog(SPEC, p))
              for p in [dualpin.BASELINE] + dualpin.SWEEP_POINTS}
    assert len(bodies) == 1


def test_dualpin_shape_stays_out_of_the_ddr_banks():
    assert all(pin.bank not in (6, 7) for pin in SPEC.pins.values())


def test_dualpin_shape_rejects_an_unknown_point():
    with pytest.raises(ValueError):
        dualpin.options_of("mode")


def test_dualpin_shape_owns_its_packer_flag_set():
    """No inherited `--cpu_as_gpio`: the all-off baseline must really be off."""
    from fuzz.gw5ast138c.harness import openflow

    assert gen.pack_flags_are_complete(SPEC)
    cmd = openflow.pack_command(["gowin_pack"], extra_gpio=[],
                                base_gpio=())
    assert "--cpu_as_gpio" not in cmd
    cmd = openflow.pack_command(["gowin_pack"],
                                extra_gpio=gen.pack_flags_of(SPEC, "cpu"),
                                base_gpio=())
    assert cmd.count("--cpu_as_gpio") == 1


def test_landed_shapes_keep_the_inherited_packer_flag():
    """A shape with a plain flag list still packs exactly as it did before."""
    from fuzz.gw5ast138c.harness import openflow
    from fuzz.gw5ast138c.shapes import ae350_soc, smoke

    assert not gen.pack_flags_are_complete(smoke.SPEC)
    assert not gen.pack_flags_are_complete(ae350_soc.SPEC)
    cmd = openflow.pack_command(
        ["gowin_pack"], extra_gpio=gen.pack_flags_of(ae350_soc.SPEC))
    assert cmd == ["gowin_pack", "-d", openflow.DEVICE, "--cpu_as_gpio",
                   "--sspi_as_gpio", "--mspi_as_gpio",
                   "-o", "top.fs", "top_pnr.json"]
