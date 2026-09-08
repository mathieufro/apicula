"""The Phase-3 adjudication shapes render and stay inside the board envelope.

`_io_base.IoShape.spec()` refuses a ball outside `SAFE_PINS`, an `IO_TYPE` the
vendor does not emit for this device and a `BANK_VCCIO` the board does not
carry, so constructing each `SPEC` is itself the envelope check. What is left
to guard is that the rendered Verilog names the primitive under test -- a
sweep point that silently renders the wrong module would produce a row about
something else.
"""
import pytest

from fuzz.gw5ast138c.shapes import (adc_osc, io_des16, io_des16_balls,
                                    io_ser16, iodelay_a_clocked,
                                    iodelay_a_iddr, osc)


@pytest.mark.parametrize("module,point,primitive", [
    (io_ser16, "oser16-default", "OSER16"),
    (io_des16, "ides16-default", "IDES16"),
    (adc_osc, "adclrc-temp", "ADCLRC"),
    (adc_osc, "adculc-temp", "ADCULC"),
    (osc, "osca-div100", "OSCA"),
    (osc, "oscb-div10", "OSCB"),
    (iodelay_a_clocked, "c-static-dly-128", "IODELAY"),
    (io_des16_balls, "ides16-balls", "IDES16"),
    (iodelay_a_iddr, "c-static-dly-128", "IODELAY"),
])
def test_shape_renders_its_primitive(module, point, primitive):
    spec = module.SPEC
    rtl = spec.rtl(spec, point)
    assert f"{primitive} dut" in rtl


def test_clocked_iodelay_has_a_clocked_endpoint():
    """The whole point of the shape: the delayed net reaches a register."""
    spec = iodelay_a_clocked.SPEC
    rtl = spec.rtl(spec, "c-static-dly-128")
    assert "always @(posedge clk) captured <= delayed;" in rtl
    assert spec.clocks == {"clk": 8.0}


def test_osc_unrun_corners_are_declared_not_dropped():
    """The two `FREQ_DIV` corners this task could not afford stay named."""
    assert "osca-div126" in adc_osc.OSC_POINTS
    assert "osca-div3" in adc_osc.OSC_POINTS


def test_e1_ides16_shape_holds_no_fabric_cell():
    """`P3.T16a`: the `E1` shape drops the XOR fold rather than hiding it.

    `io_des16` reduces `Q10`-`Q15` onto one ball through a fabric LUT, which is
    a freely placed cell and costs `conns` (`D105`). The `E1` shape leaves
    those six outputs unconnected instead, so every net starts or ends on a
    ball.
    """
    spec = io_des16_balls.SPEC
    rtl = spec.rtl(spec, "ides16-balls")
    assert "assign" not in rtl and "^" not in rtl
    for bit in range(10, 16):
        assert ".Q%d" % bit not in rtl
    for bit in range(10):
        assert ".Q%-4d(q%d)," % (bit, bit) in rtl or ".Q%d " % bit in rtl


def test_iddr_iodelay_endpoint_is_the_pads_own_register():
    """The endpoint stays, the fabric goes: no freely placed cell is left."""
    spec = iodelay_a_iddr.SPEC
    rtl = spec.rtl(spec, "c-static-dly-128")
    assert "IDDR cap" in rtl
    assert "always @" not in rtl and "reg " not in rtl
    assert spec.clocks == {"clk": 8.0}
    assert "defparam dut.C_STATIC_DLY = 128;" in rtl
