"""The 16-bit gearboxes are refused by name on the GW5A series (`P3.T17`, `D30`).

`P3.T16` adjudicated `OSER16`/`IDES16` against the vendor on the GW5AST-138C
and the expected refusal was **refuted**: `gw_sh` builds both with zero errors
and its PnR resource report names the primitive it realised. So the refusal
these guards pin is a statement about *apicula*, not about the die -- the
chipdb creates no `OSER16`/`IDES16` bel for a GW5A device and no fuse set for
either has ever been measured, and a bitstream emitted anyway would be wrong
with no error.

`V16`: the message names the primitive and the device. It must never degrade to
the generic "Not supported cell type" the base dispatcher raises, and it must
never claim the *device* lacks the primitive, which is now known false.
"""
import inspect

import pytest

from apycula import chipdb, gowin_pack


def _device(cls, name):
    """A device object with just enough state to reach the refusal.

    Constructing one for real loads a chipdb; the refusal reads exactly one
    attribute, so binding that one is the whole fixture.
    """
    dev = object.__new__(cls)
    dev.device_name = name
    return dev


class _Cell:
    def __init__(self, typ):
        self.typ = typ
        self.name = "dut"


class _Bel:
    def __init__(self, typ):
        self.cell = _Cell(typ)


def test_unsupported_error_oser16_gw5ast138c():
    dev = _device(gowin_pack.GW5AST_138C, "GW5AST-138C")
    with pytest.raises(gowin_pack.PackRefused) as excinfo:
        dev.get_OSER16_fuses(_Bel("OSER16"))
    assert str(excinfo.value).startswith(
        "OSER16 is not implemented on GW5AST-138C:")


def test_unsupported_error_ides16_gw5ast138c():
    dev = _device(gowin_pack.GW5AST_138C, "GW5AST-138C")
    with pytest.raises(gowin_pack.PackRefused) as excinfo:
        dev.get_IDES16_fuses(_Bel("IDES16"))
    assert str(excinfo.value).startswith(
        "IDES16 is not implemented on GW5AST-138C:")


@pytest.mark.parametrize("typ", ["OSER16", "IDES16"])
def test_unsupported_error_names_the_vendor_measurement_not_a_device_limit(typ):
    """The wording may not say the device lacks the primitive: it has it."""
    dev = _device(gowin_pack.GW5AST_138C, "GW5AST-138C")
    with pytest.raises(gowin_pack.PackRefused) as excinfo:
        getattr(dev, f"get_{typ}_fuses")(_Bel(typ))
    text = str(excinfo.value)
    assert "the vendor builds it on this device" in text
    assert "not supported" not in text.lower()


def test_unsupported_error_is_raised_for_every_gw5a_device():
    """The refusal belongs to the series, not to one part."""
    for cls, name in ((gowin_pack.GW5A_25A, "GW5A-25A"),
                      (gowin_pack.GW5AT_60B, "GW5AT-60B"),
                      (gowin_pack.GW5AST_138C, "GW5AST-138C")):
        dev = _device(cls, name)
        with pytest.raises(gowin_pack.PackRefused) as excinfo:
            dev.get_OSER16_fuses(_Bel("OSER16"))
        assert str(excinfo.value).startswith(
            f"OSER16 is not implemented on {name}:")


def test_oser16_still_supported_gw1ns4():
    """The GW1N/GW1NS path keeps its bels: `chipdb.py`'s device sets are intact.

    A built `GW1NS-4` chipdb is not reachable without that device's vendor
    files, so the guard is on the table the bel creation reads, which is what a
    GW5A change could plausibly have broken.
    """
    body = inspect.getsource(chipdb)
    assert "if device in {'GW1NS-4'} and ttyp in {142, 143, 144, 58, 59}:" in body
    assert "if device in {'GW1N-9', 'GW1N-9C'} and ttyp in {52, 66, 63, 91, 92}:" in body
    # and the GW1N devices must not inherit the GW5A refusal
    assert not issubclass(gowin_pack.GW1NS_4, gowin_pack.GW5A)
    assert not hasattr(gowin_pack.GW1NS_4, "_refuse_io16")
