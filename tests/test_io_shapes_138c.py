"""The Phase-3 IO/IOLOGIC shape base and its five shapes (`P3.T10`).

What these guard is the *safety envelope*, not the Verilog: a shape that
reaches a ball nobody has checked, or lands one in a DDR bank, or names an
`IO_TYPE` the vendor does not emit, is the failure mode `PR #423` made real
on this die (unconstrained banks defaulting to 1.2 V, unfused pull strengths,
an overheating part).  One test per property, and each is derived from the
shapes rather than restated from them.
"""
import dataclasses
import re

import pytest

from fuzz.gw5ast138c.harness import gen
from fuzz.gw5ast138c.shapes import (DDR_BANKS, PinSpec, diff_io, io_basic,
                                    io_des, io_ser, iodelay_a)
from fuzz.gw5ast138c.shapes._io_base import (SAFE_PINS, VENDOR_IO_TYPES,
                                             EnvelopeError, IoShape)

#: The three shapes `P3.T10`'s Done-when names, plus the two this phase's
#: later tasks run from the same base.
SHAPES = {
    "io_basic": io_basic,
    "io_ser": io_ser,
    "io_des": io_des,
    "iodelay_a": iodelay_a,
    "diff_io": diff_io,
}

#: Shapes whose pins are all single-ended, so `gen`'s `.cst` assertion (which
#: has no differential exemption yet) applies to them unchanged.
SINGLE_ENDED = ("io_basic", "io_ser", "io_des", "iodelay_a")

IO_LOC = re.compile(r'^IO_LOC\s+"([^"]+)"\s+(\S+);', re.M)
IO_PORT = re.compile(r'^IO_PORT\s+"([^"]+)"\s+(.*);', re.M)


def _cst(module, sweep_value=None):
    spec = module.SPEC
    return gen.render_cst(spec, sweep_value or spec.baseline_value)


# -- the base ---------------------------------------------------------------
def test_io_base_bank_constants_are_33v():
    assert IoShape.BANK_CONSTANTS["BANK_VCCIO"] == "3.3"
    assert IoShape.BANK_CONSTANTS["IO_TYPE"] == "LVCMOS33"


def test_io_base_reserves_the_phase5b_marker():
    """Phase 5b adds the bank-6 constants beside the 3.3 V set (`D54`); the
    marker is the seam, so it must survive edits to this file."""
    from fuzz.gw5ast138c.shapes import _io_base
    source = open(_io_base.__file__).read()
    assert source.count("# Phase 5b (D54): bank-6 constants") == 1


def test_io_base_refuses_a_ball_outside_the_board_allowlist():
    class Reaching(IoShape):
        name = "reaching"
        primitive = "IOB"
        sweep_axis = "POINT"
        sweep_values = ["x"]
        baseline_value = "x"
        ports = {"d": ("A1", "input")}   # bank 7: a DDR3 ball

        def rtl(self, sweep_value):
            return ""

    with pytest.raises(EnvelopeError):
        Reaching().spec()


def test_io_base_refuses_a_ddr_bank_even_from_a_listed_ball():
    """The bank rule does not depend on the allowlist being right."""
    spec = io_basic.SPEC
    hijacked = dict(spec.pins)
    hijacked["din"] = PinSpec(loc="N15", bank=6, direction="input", drive=None)
    with pytest.raises(EnvelopeError):
        IoShape().assert_envelope(
            dataclasses.replace(spec, pins=hijacked))


# -- every shape ------------------------------------------------------------
@pytest.mark.parametrize("name", sorted(SHAPES))
def test_io_shape_pins_are_all_board_balls(name):
    for port, pin in SHAPES[name].SPEC.pins.items():
        assert pin.loc in SAFE_PINS, (name, port, pin.loc)
        assert pin.bank == SAFE_PINS[pin.loc].bank, (name, port, pin.loc)


@pytest.mark.parametrize("name", sorted(SHAPES))
def test_io_shape_no_bank6_or_7_pins(name):
    spec = SHAPES[name].SPEC
    assert [p.loc for p in spec.pins.values() if p.bank in DDR_BANKS] == []
    assert [b for b in spec.bank_vccio if b in DDR_BANKS] == []


@pytest.mark.parametrize("name", sorted(SHAPES))
def test_io_shape_io_types_are_ones_the_vendor_emits(name):
    """A pin either names an `IO_TYPE` the vendor emits, or is a declared
    differential pad, whose standard comes from the buffer primitive."""
    module = SHAPES[name]
    diff_pads = set(getattr(module, "DiffIoShape", IoShape).diff_pads)
    for port, pin in module.SPEC.pins.items():
        if pin.io_type is None:
            assert port in diff_pads, (name, port)
            continue
        assert pin.io_type in VENDOR_IO_TYPES, (name, port, pin.io_type)


@pytest.mark.parametrize("name", sorted(SHAPES))
def test_io_shape_every_bank_in_use_declares_vccio(name):
    spec = SHAPES[name].SPEC
    assert {p.bank for p in spec.pins.values()} == set(spec.bank_vccio)
    assert set(spec.bank_vccio.values()) == {"3.3"}


@pytest.mark.parametrize("name", sorted(SHAPES))
def test_io_shape_renders_every_sweep_point(name):
    spec = SHAPES[name].SPEC
    for point in spec.sweep_values:
        rtl = spec.rtl(spec, point)
        assert "module top" in rtl, (name, point)
        assert "endmodule" in rtl, (name, point)


@pytest.mark.parametrize("name", sorted(SHAPES))
def test_io_shape_sweep_moves_one_axis_per_run(name):
    """A point that changed two things at once would attribute one
    parameter's fuses to another (`F12`)."""
    spec = SHAPES[name].SPEC
    for point in spec.sweep_values:
        defparams = re.findall(r"^\s*defparam dut\.", spec.rtl(spec, point),
                               re.M)
        assert len(defparams) <= 1, (name, point, defparams)


# -- the .cst ---------------------------------------------------------------
@pytest.mark.parametrize("name", sorted(SINGLE_ENDED))
def test_io_shape_cst_has_iotype_on_every_pin(name):
    cst = _cst(SHAPES[name])
    locs = IO_LOC.findall(cst)
    ports = [attrs for _port, attrs in IO_PORT.findall(cst)]
    assert len(locs) == len(ports) > 0
    assert len(ports) == len([a for a in ports if "IO_TYPE=" in a])


@pytest.mark.parametrize("name", sorted(SINGLE_ENDED))
def test_io_shape_cst_declares_bank_vccio_on_every_pin(name):
    ports = [attrs for _port, attrs in IO_PORT.findall(_cst(SHAPES[name]))]
    assert ports
    assert all("BANK_VCCIO=3.3" in attrs for attrs in ports)


@pytest.mark.parametrize("name", sorted(SINGLE_ENDED))
def test_io_shape_passes_the_harness_cst_assertion(name):
    spec = SHAPES[name].SPEC
    for point in spec.sweep_values:
        assert gen.assert_cst_defaults(spec, point) == []


def test_diff_io_pads_have_no_iotype_and_the_harness_refuses_them():
    """The named gap `P3.T23` opens with.

    `gen.assert_cst_defaults` rule (a) demands an `IO_TYPE` on every used pin
    and rule (b) admits only `LVCMOS33` on a non-DDR pin.  Neither has a
    differential exemption, and `harness/**` is frozen for this phase, so the
    differential shape -- spelled the way the vendor's own board constraints
    spell a TMDS pair, with no `IO_TYPE` -- is refused today.  This test
    fails the moment the exemption lands, which is the reminder to delete it.
    """
    spec = diff_io.SPEC
    assert spec.pins["pad_p"].io_type is None
    assert spec.pins["pad_n"].io_type is None
    with pytest.raises(gen.CstDefaultError):
        gen.assert_cst_defaults(spec, spec.baseline_value)


# -- per-shape properties ---------------------------------------------------
def test_iodelay_sweep_is_gray_coded():
    assert set(iodelay_a.gray_adjacent_bit_changes()) == {1}
    assert len(iodelay_a.C_STATIC_DLY_POINTS) == 24
    assert len(set(iodelay_a.C_STATIC_DLY_POINTS)) == 24


def test_iodelay_sweep_touches_every_delay_bit():
    seen = set()
    points = iodelay_a.C_STATIC_DLY_POINTS
    for first, second in zip(points, points[1:]):
        seen.add((first ^ second).bit_length() - 1)
    assert seen == set(range(8))


def test_iodelay_sweep_has_the_budgeted_28_points():
    assert len(iodelay_a.SPEC.sweep_values) == 28


def test_gearbox_pclk_divider_is_half_the_width():
    """`PCLK = FCLK / (width / 2)` (UG304E p.62-69) -- the one number a
    deserialiser shape silently gets wrong."""
    from fuzz.gw5ast138c.shapes._io_base import GEARBOX_DIV_MODE
    for width, div_mode in GEARBOX_DIV_MODE.items():
        assert float(div_mode) == width / 2


@pytest.mark.parametrize("module", [io_ser, io_des])
def test_gearbox_shape_divides_its_own_width(module):
    from fuzz.gw5ast138c.shapes._io_base import GEARBOX_DIV_MODE
    spec = module.SPEC
    for point, entry in module.POINTS.items():
        width = entry[0]
        rtl = spec.rtl(spec, point)
        assert 'DIV_MODE = "%s"' % GEARBOX_DIV_MODE[width] in rtl, point
        assert module.PRIMITIVE_OF_WIDTH[width] + " dut" in rtl, point


def test_diff_io_omits_tlvds_iobuf_until_it_is_adjudicated():
    """`P3.T24` adjudicates the 138C removal against the oracle; a shape must
    not presume the answer."""
    assert "TLVDS_IOBUF" not in set(diff_io.POINTS.values())
    assert "ELVDS_IBUF" not in set(diff_io.POINTS.values())


def test_io_basic_covers_both_primitives_and_their_parameters():
    primitives = {p for p, _ in io_basic.POINTS.values()}
    assert primitives == {"ODDR", "IDDR"}
    parameters = {key for _p, params in io_basic.POINTS.values()
                  for key in params}
    assert parameters == {"TXCLK_POL", "INIT", "Q0_INIT", "Q1_INIT"}


# -- the allowlist against the vendor pinout --------------------------------
def test_safe_pins_agree_with_the_vendor_pinout():
    """The banks in `SAFE_PINS` are the vendor's; re-read them when an IDE is
    present so a typo cannot survive a run of the suite on this box."""
    import os
    if not os.environ.get("GOWINHOME"):
        pytest.skip("no GOWINHOME; SAFE_PINS banks re-checked only with an IDE")
    from apycula import pindef
    pindef.all_packages("GW5AST-138C")
    pins = {str(p["INDEX"]): p
            for p in pindef.get_package("GW5AST-138C", "PBGA484A",
                                        pindef.VeryTrue)}
    for loc, safe in SAFE_PINS.items():
        assert loc in pins, loc
        assert int(pins[loc]["BANK"]) == safe.bank, loc
        assert str(pins[loc]["NAME"]) == safe.site, loc
