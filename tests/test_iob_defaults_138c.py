"""The IOB defaults the GW5AST-138C emits are the ones the vendor emits.

`P3.T26` decoded 35 vendor/open bitstream pairs and found the open flow
programming a drive strength on every floating pad of the die -- 22 020 fuse
bits the silicon vendor's own tool leaves clear, inside the attribute class
PR #423 was opened for -- plus a slew rate on every used output and no
hysteresis on any used input.  `D108` fixes all three on this device's packer
class and on no other: the GW5A-25A and the GW5AT-60B have no such
measurement, and a default is not a thing to change on a part nobody has
measured.
"""
import os
import sys

import pytest

from apycula import gowin_pack

_CLASSES = {"GW5AST-138C": gowin_pack.GW5AST_138C,
            "GW5A-25A": gowin_pack.GW5A_25A,
            "GW5AT-60B": gowin_pack.GW5AT_60B}


def _device(name):
    """A packer `Device` built the way the command line builds it."""
    chipdb = os.path.join(os.path.dirname(gowin_pack.__file__),
                          f"{name}.msgpack.xz")
    if not os.path.exists(chipdb):  # pragma: no cover - build it first
        pytest.skip(f"{name}.msgpack.xz absent; run apycula.chipdb_builder")
    argv = sys.argv
    sys.argv = ["gowin_pack", "-d", name, "netlist.json"]
    try:
        return _CLASSES[name](gowin_pack.CliArgs(), None)
    finally:
        sys.argv = argv


def _unused(dev, cfgs=frozenset()):
    """`{attr: value}` the device programs on one floating pad."""
    io_cfg = gowin_pack.IoCfg(0, 0, "A", set(cfgs))
    bank = gowin_pack.BankDesc(0, 0)
    bank.attrs["IO_TYPE"] = "LVCMOS33"
    return {av.attr: av.val for av in dev.get_unused_io_attrvals(io_cfg, bank)}


@pytest.fixture(scope="module")
def dev_138c():
    return _device("GW5AST-138C")


@pytest.fixture(scope="module", params=["GW5A-25A", "GW5AT-60B"])
def sibling(request):
    return _device(request.param)


def test_unused_pin_carries_no_drive_default(dev_138c):
    """The 22 020-bit violation: a drive strength on a floating pad."""
    attrs = _unused(dev_138c)
    assert "DRIVE" not in attrs
    assert "DRIVE_LEVEL" not in attrs


def test_unused_pin_keeps_the_vendor_set(dev_138c):
    """`IO_TYPE`, `OPENDRAIN` and `PADDI` are bit-equal and stay."""
    attrs = _unused(dev_138c)
    assert attrs["IO_TYPE"] == "LVCMOS33"
    assert attrs["OPENDRAIN"] == "OFF"
    assert "PADDI" in attrs


def test_unused_pin_keeps_a_pull_the_vendor_programs(dev_138c):
    """`UP` is bit-equal on 930 site-observations, so it is not dropped."""
    assert _unused(dev_138c)["PULLMODE"] == "UP"


def test_unused_data_pad_keeps_the_pull_the_vendor_programs(dev_138c):
    """`NONE` is bit-equal on 865 site-observations and is left alone."""
    cfg = next(iter(dev_138c._no_pullup_cfgs))
    assert _unused(dev_138c, {cfg})["PULLMODE"] == "NONE"


def test_the_serial_output_pad_keeps_its_pullup(dev_138c):
    """The one unused pad where the open flow programmed a pull the vendor
    did not: it carries `D08` and `SO`, and the vendor treats it as serial."""
    assert _unused(dev_138c, {"D08", "SO"})["PULLMODE"] == "UP"


def test_slewrate_has_no_default_on_this_device(dev_138c):
    """Open-only on all 143 used outputs; a design that asks still gets it."""
    assert all(attr != "SLEWRATE" for attr, _ in dev_138c.default_obuf_attrs)
    assert "SLEWRATE" in dev_138c.design_only_io_attrs


def test_input_hysteresis_matches_the_vendor(dev_138c):
    """Vendor-only on 114 used inputs, always `ON`."""
    assert ("HYSTERESIS", "ON") in dev_138c.default_ibuf_attrs


def test_the_other_gw5a_parts_are_untouched(sibling):
    """`S3`: no unmeasured family member changes behaviour with this fix."""
    assert sibling.design_only_io_attrs == ()
    assert any(attr == "SLEWRATE" for attr, _ in sibling.default_obuf_attrs)
    assert ("HYSTERESIS", "NONE") in sibling.default_ibuf_attrs
    attrs = _unused(sibling)
    assert attrs["DRIVE"] == "8"
    assert attrs["DRIVE_LEVEL"] == "8"
