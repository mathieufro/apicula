"""The 138C's ADC and oscillator, as measured (`P3.T28`-`P3.T31`).

Both blueprint tasks said "create the bel". Both measurements said something
else, and these guards pin what was measured rather than what was expected:

* the ADC **exists** -- four vendor runs place `ADCLRC`/`ADCULC` with zero
  errors -- but its `.dat` portmap tables are mis-based, so no bel is created
  and the packer refuses by name (`D30`);
* the oscillator **does not exist** -- three vendor runs, both primitives,
  refused by name before place-and-route -- so `fse_create_osc`'s early return
  for this device is correct, and the `.fse`'s oscillator table 51 must not be
  mistaken for evidence that the die bonds the block.
"""
import inspect

import pytest

from apycula import chipdb, gowin_pack


def _device(cls, name):
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


@pytest.mark.parametrize("typ", ["ADCLRC", "ADCULC"])
def test_adc_refused_by_name_on_138c(typ):
    dev = _device(gowin_pack.GW5AST_138C, "GW5AST-138C")
    with pytest.raises(gowin_pack.PackRefused) as excinfo:
        getattr(dev, f"get_{typ}_fuses")(_Bel(typ))
    text = str(excinfo.value)
    assert text.startswith(f"{typ} is not implemented on GW5AST-138C:")
    # The refusal must not claim the die lacks the block: it has it.
    assert "the vendor builds it on this device" in text
    assert "not supported" not in text.lower()


def test_adc_bel_is_not_created_for_138c():
    """No bel from a table whose base has drifted (`P3.T28`)."""
    src = inspect.getsource(chipdb.fse_create_adc)
    assert 'if device not in {"GW5A-25A"}:' in src


def test_adc_25a_branch_is_untouched():
    """The 25A path still reads its own tables and places its own bel."""
    src = inspect.getsource(chipdb.fse_create_adc)
    assert "dat.gw5aStuff['Adc25kIns'][idx]" in src
    assert "dat.gw5aStuff['Adc25kOuts'][idx]" in src
    assert "row, col = 0, dev.cols - 1" in src


def test_osc_early_return_covers_138c():
    """The die has no oscillator; the early return is the measured truth."""
    src = inspect.getsource(chipdb.fse_create_osc)
    assert "if device in {'GW5AT-60B', 'GW5AST-138C'}:" in src


def test_osc_60b_early_return_unchanged():
    """`GW5AT-60B` is out of scope and nothing measured here moves it."""
    src = inspect.getsource(chipdb.fse_create_osc)
    assert "GW5AT-60B" in src
    assert "_osc_ports[osc_type, device]" in src


def test_no_osc_ports_entry_invented_for_138c():
    """A port map for a block the vendor refuses to place would be fiction."""
    assert not [k for k in chipdb._osc_ports if k[1] == "GW5AST-138C"]
