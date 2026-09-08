"""The Phase-3 adjudication shapes render and stay inside the board envelope.

`_io_base.IoShape.spec()` refuses a ball outside `SAFE_PINS`, an `IO_TYPE` the
vendor does not emit for this device and a `BANK_VCCIO` the board does not
carry, so constructing each `SPEC` is itself the envelope check. What is left
to guard is that the rendered Verilog names the primitive under test -- a
sweep point that silently renders the wrong module would produce a row about
something else.
"""
import pytest

from fuzz.gw5ast138c.shapes import (adc_osc, io_des16, io_ser16,
                                    iodelay_a_clocked, osc)


@pytest.mark.parametrize("module,point,primitive", [
    (io_ser16, "oser16-default", "OSER16"),
    (io_des16, "ides16-default", "IDES16"),
    (adc_osc, "adclrc-temp", "ADCLRC"),
    (adc_osc, "adculc-temp", "ADCULC"),
    (osc, "osca-div100", "OSCA"),
    (osc, "oscb-div10", "OSCB"),
    (iodelay_a_clocked, "c-static-dly-128", "IODELAY"),
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
