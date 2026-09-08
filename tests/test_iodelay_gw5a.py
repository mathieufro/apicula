"""IODELAY packing: the parameter the packer reads, and how far it can count.

Two defects sat in `Device.handle_iodelay` on every device:

* it read ``C_STATIC_DELAY``, a name neither the vendor primitive nor nextpnr
  nor yosys ever writes -- the parameter is ``C_STATIC_DLY`` -- so the delay
  step never arrived and every delay line packed at zero;
* the step is eight bits wide in `UG304-1.3.8E` Table 4-48 but the `IOLOGIC`
  attribute table stops at ``DELAY_DEL6``, so the eighth bit has nowhere to go
  and must be refused rather than dropped.

The GW5AST-138C additionally takes the Arora V delay line
(``DLYSTEP[7:0]``, no ``SETN``, `D23`), which is `handle_iodelay_gw5a`; the
GW5A-25A keeps the inherited path, and this file pins that it is untouched.
"""
import pytest

from apycula.gowin_pack import (
    AttrVal,
    CellDesc,
    Device,
    GW5A_25A,
    GW5AST_138C,
    IologicBelDesc,
    c_static_dly_bits,
)


def _bel(parms, *, iodelay="IN"):
    cell = CellDesc(name="dly", typ="IOLOGICI_EMPTY", parms=dict(parms),
                    attrs={"IODELAY": iodelay}, connections={})
    return IologicBelDesc(0, 0, "A", cell, "SPINE10", None, None)


def _handler(cls):
    """A packer of `cls` with no device state -- these handlers read none."""
    obj = object.__new__(cls)
    object.__setattr__(obj, "device", cls.__name__.replace("_", "-"))
    return obj


def _delays(attr_vals):
    """The pre-5A delay encoding: seven one-bit `DELAY_DEL*` attributes."""
    return [av for av in attr_vals if av.attr.startswith("DELAY_DEL")]


def _gw5a_delay(attr_vals):
    """The Arora V encoding, MEASURED (`P3.T21`, 28 bitstreams).

    `C_STATIC_DLY` is **one** enumerated IOLOGIC attribute, number 118,
    carrying the whole 0-255 step -- value id `2` for step 1 and `1000 + n`
    for `n >= 2` -- and its fuses are eight plain binary weights in row 21,
    columns 3-10. So the die spends a bit on step 7, and the pre-5A window's
    seven `DELAY_DEL0`-`DELAY_DEL6` attributes are simply the wrong encoding
    here, not a missing one.
    """
    return [av for av in attr_vals if av.attr == "C_STATIC_DLY"]


def test_iodelay_param_name_both_spellings():
    """The name nextpnr emits and the name this packer used to read agree."""
    packer = _handler(Device)
    new = packer.handle_iodelay(_bel({"C_STATIC_DLY": "00000101"}))
    old = packer.handle_iodelay(_bel({"C_STATIC_DELAY": "00000101"}))
    assert new == old
    assert _delays(new) == [AttrVal("DELAY_DEL0", "1"), AttrVal("DELAY_DEL2", "1")]


def test_iodelay_param_name_prefers_c_static_dly():
    """With both spellings present the primitive's own name wins."""
    packer = _handler(Device)
    attr_vals = packer.handle_iodelay(
        _bel({"C_STATIC_DLY": "00000001", "C_STATIC_DELAY": "00000010"}))
    assert _delays(attr_vals) == [AttrVal("DELAY_DEL0", "1")]


def test_iodelay_c_static_dly_eight_bits():
    """Seven bits are packable, the eighth is refused, and zero packs nothing."""
    packer = _handler(Device)
    assert _delays(packer.handle_iodelay(_bel({"C_STATIC_DLY": 0}))) == []
    assert len(_delays(packer.handle_iodelay(_bel({"C_STATIC_DLY": 127})))) == 7
    with pytest.raises(Exception, match="DELAY_DEL7"):
        packer.handle_iodelay(_bel({"C_STATIC_DLY": 255}))


def test_c_static_dly_reads_bit_strings_and_integers():
    assert c_static_dly_bits({"C_STATIC_DLY": "00000101"}) == "00000101"
    assert c_static_dly_bits({"C_STATIC_DLY": 5}) == "00000101"
    assert c_static_dly_bits({"C_STATIC_DLY": "255"}) == "11111111"
    assert c_static_dly_bits({}) == "00000000"


def test_iodelay_138c_handler_invoked():
    """The 138C's IOLOGIC handler reaches the Arora V delay line."""
    packer = _handler(GW5AST_138C)
    attr_vals = Device.common_iologic_handler(packer, _bel({"C_STATIC_DLY": 5}))
    assert len(attr_vals) > 3
    assert _gw5a_delay(attr_vals) == [AttrVal("C_STATIC_DLY", 1005)]
    # ...and never the pre-5A one, which would put the step in the wrong bits.
    assert _delays(attr_vals) == []


def test_iodelay_gw5a_refuses_dynamic_and_adaptive_modes():
    """Neither enable has a measured fuse, so neither is packed silently."""
    packer = _handler(GW5AST_138C)
    for parm in ("DYN_DLY_EN", "ADAPT_EN"):
        with pytest.raises(Exception, match=parm):
            packer.handle_iodelay(_bel({"C_STATIC_DLY": 5, parm: "TRUE"}))


def test_iodelay_gw5a_takes_an_explicit_delay_step():
    """The DDR3 PHY sets the DQ delay from calibration, not from the netlist."""
    packer = _handler(GW5AST_138C)
    attr_vals = packer.handle_iodelay_gw5a(_bel({"C_STATIC_DLY": 0}), c_static_dly=5)
    assert _gw5a_delay(attr_vals) == [AttrVal("C_STATIC_DLY", 1005)]
    # The enable set the vendor programs alongside it is `INDEL` alone.
    assert AttrVal("INDEL", "ENABLE") in attr_vals


def test_iodelay_25a_handler_output_unchanged():
    """The 25A keeps the inherited delay line, byte for byte (`S3`)."""
    bel = _bel({"C_STATIC_DLY": 5})
    assert GW5A_25A.handle_iodelay is Device.handle_iodelay
    assert _handler(GW5A_25A).handle_iodelay(bel) == _handler(Device).handle_iodelay(bel)


def test_iodelay_absent_packs_nothing():
    assert _handler(Device).handle_iodelay(_bel({}, iodelay=None)) == []
    assert _handler(GW5AST_138C).handle_iodelay(_bel({}, iodelay=None)) == []
