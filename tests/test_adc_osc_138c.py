"""The 138C's ADC and oscillator, as measured (`P3.T28`-`P3.T31`).

Both blueprint tasks said "create the bel". Both measurements said something
else, and these guards pin what was measured rather than what was expected:

* the ADC **exists** -- four vendor runs place `ADCLRC`/`ADCULC` with zero
  errors -- and both blocks' port tables are now located by the block's own
  port-group geometry, so both bels exist; what the packer refuses by name is
  *configuring* one, because this die's `.fse` carries no ADC fuse table
  (`D30`);
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


class _GridDevice:
    """The two attributes `_adc_bel_sites`/`_adc_site_is_unique` read."""

    def __init__(self, rows, cols, ttyp):
        self.rows, self.cols = rows, cols
        self.grid = [[ttyp] * cols for _ in range(rows)]


def _grid_device(rows, cols, ttyp=1):
    return _GridDevice(rows, cols, ttyp)


@pytest.mark.parametrize("typ", ["ADCLRC", "ADCULC"])
def test_adc_configuration_refused_by_name_on_138c(typ):
    dev = _device(gowin_pack.GW5AST_138C, "GW5AST-138C")
    with pytest.raises(gowin_pack.PackRefused) as excinfo:
        getattr(dev, f"get_{typ}_fuses")(_Bel(typ))
    text = str(excinfo.value)
    assert text.startswith(f"{typ} cannot be configured on GW5AST-138C:")
    # The refusal must name the gap that is actually left, not the closed one.
    assert "port map is anchored and its bel exists" in text
    assert "no ADC fuse table" in text
    assert "not supported" not in text.lower()


def test_adc_bels_are_created_for_138c():
    """Both blocks get a bel, each on a tile type unique to its corner."""
    src = inspect.getsource(chipdb._fse_create_adc_5a138)
    assert "locate_adc_tables" in src
    sites = chipdb._adc_bel_sites(_grid_device(109, 182))
    assert sites == {"ADCLRC": (108, 181), "ADCULC": (0, 0)}


def test_adc_site_sharing_a_tile_type_is_refused():
    """A bel on a shared tile type would appear at every cell of that type."""
    dev = _grid_device(4, 4, ttyp=7)
    assert not chipdb._adc_site_is_unique(dev, 0, 0)
    dev.grid[0][0] = 99
    assert chipdb._adc_site_is_unique(dev, 0, 0)


def test_adc_25a_branch_is_untouched():
    """The 25A path still reads its own tables and places its own bel."""
    src = inspect.getsource(chipdb.fse_create_adc)
    assert "dat.gw5aStuff['Adc25kIns'][idx]" in src
    assert "dat.gw5aStuff['Adc25kOuts'][idx]" in src


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
