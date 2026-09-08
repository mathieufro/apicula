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


class _ConfiguredDevice:
    """`GW5AST_138C` with one site's measured attribution and nothing else."""

    def __init__(self, config, x=181, y=108):
        self.device_name = "GW5AST-138C"
        self.chipdb = self
        self._config, self._x, self._y = config, x, y

    def get_adc_config(self, x, y):
        return self._config if (x, y) == (self._x, self._y) else {}


def _configured(config, typ, parms=None, x=181, y=108):
    dev = _ConfiguredDevice(config)
    bel = _Bel(typ)
    object.__setattr__(bel, "x", x)
    object.__setattr__(bel, "y", y)
    bel.cell.parms = dict(parms or {})
    return gowin_pack.GW5AST_138C._adc_fuses(dev, bel)


DIV_CTL_MEASURED = {"DIV_CTL": {0: set(), 1: {(20, 32), (20, 63)},
                                2: {(20, 31), (20, 32), (20, 62), (20, 63)},
                                3: {(20, 31), (20, 62)}}}


def test_adc_div_ctl_emits_the_measured_bits():
    """The one parameter whose axis was swept is packed, not refused."""
    fuses = _configured(DIV_CTL_MEASURED, "ADCLRC", {"DIV_CTL": "10"})
    assert len(fuses) == 1
    assert set(fuses[0].bits) == {(20, 31), (20, 32), (20, 62), (20, 63)}


def test_adc_default_div_ctl_emits_no_fuse():
    """`DIV_CTL=0` measurably moves no bit, so packing one must move none."""
    assert _configured(DIV_CTL_MEASURED, "ADCLRC", {"DIV_CTL": "00"}) == []
    assert _configured(DIV_CTL_MEASURED, "ADCLRC") == []


@pytest.mark.parametrize("parm", ["SAMPLE_CNT_SEL", "ADC_MODE", "VSEN_CTL"])
def test_adc_unattributed_parameter_refused_by_name(parm):
    """A parameter no sweep covered is refused, never defaulted silently."""
    with pytest.raises(gowin_pack.PackRefused) as excinfo:
        _configured(DIV_CTL_MEASURED, "ADCLRC", {parm: "1"})
    text = str(excinfo.value)
    assert text.startswith(f"ADCLRC.{parm} cannot be set on GW5AST-138C:")
    assert "attributed" in text
    assert "not supported" not in text.lower()


def test_adculc_parameters_refused_for_want_of_a_swept_axis():
    """The upper-left block's tables carry none of the measured codes."""
    with pytest.raises(gowin_pack.PackRefused) as excinfo:
        _configured({}, "ADCULC", {"DIV_CTL": "01"}, x=0, y=0)
    assert "ADCULC.DIV_CTL cannot be set" in str(excinfo.value)


def test_adculc_without_parameters_packs():
    """Placing a default block needs no fuse, so it must not be refused."""
    assert _configured({}, "ADCULC", None, x=0, y=0) == []


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


def _load_138c_chipdb():
    import importlib.resources

    from apycula import chipdb as chipdb_mod

    path = importlib.resources.files("apycula") / "GW5AST-138C.msgpack.xz"
    if not path.is_file():
        pytest.skip("no GW5AST-138C chipdb built")
    return chipdb_mod.load_chipdb(str(path))


def test_adc_tile_decodes_without_an_adc_attribute_table():
    """An ADC bel on a die with no `ADC` table must decode, not raise.

    Locating the two blocks gave this die ADC bels for the first time, and
    the unpacker's ADC branch read `logicinfo['ADC']` and
    `shortval[ttyp]['ADC']` unconditionally -- neither of which this `.fse`
    declares.  Every tile walk that reached a corner therefore died with a
    bare `KeyError: 'ADC'`, which took the batch head's self-tests with it.
    The bel is real; only the attribution is missing, and that is what the
    packer refuses on by name.
    """
    from apycula import gowin_unpack

    db = _load_138c_chipdb()
    assert "ADC" not in db.logicinfo, (
        "this guard is only meaningful while the die has no ADC table")

    sites = [(row, col)
             for row in range(db.rows) for col in range(db.cols)
             if any(name.startswith("ADC") for name in db[row, col].bels)]
    assert sites, "the 138C chipdb must carry both ADC bels"

    for row, col in sites:
        tiledata = db[row, col]
        blank = [[0] * tiledata.width for _ in range(tiledata.height)]
        gowin_unpack.parse_tile_(db, row, col, blank)


def test_chipdb_carries_the_measured_div_ctl_attribution():
    """The built chipdb must name the fuses the sweep attributed.

    The codes are read out of the die's own tables rather than written down
    as bit coordinates, so a device-file revision that moves the bits moves
    the attribution with it.
    """
    db = _load_138c_chipdb()
    config = db.extra_func[108, 181]["adc"]["config"]
    assert set(config) == {"DIV_CTL"}, (
        "only DIV_CTL was swept; anything else here is a guess")
    assert {v: set(map(tuple, b)) for v, b in config["DIV_CTL"].items()} == {
        0: set(),
        1: {(20, 32), (20, 63)},
        2: {(20, 31), (20, 32), (20, 62), (20, 63)},
        3: {(20, 31), (20, 62)},
    }


def test_adculc_carries_no_config_attribution():
    """The upper-left corner's tables hold none of the measured codes."""
    db = _load_138c_chipdb()
    assert "config" not in db.extra_func[0, 0]["adc"]


def test_adc_div_ctl_accepts_the_chipdb_round_trip_shape():
    """A loaded chipdb hands back lists, not sets of tuples.

    The attribution is stored in the chipdb and read back through msgpack,
    which has no set and no tuple; a packer that only ever saw the in-memory
    shape crashed on every design that actually set the parameter.
    """
    round_tripped = {"DIV_CTL": {0: [], 1: [[20, 32], [20, 63]],
                                 2: [[20, 31], [20, 32], [20, 62], [20, 63]],
                                 3: [[20, 31], [20, 62]]}}
    fuses = _configured(round_tripped, "ADCLRC", {"DIV_CTL": "01"})
    assert set(fuses[0].bits) == {(20, 32), (20, 63)}


class _ConfigDb:
    """The one chipdb field the ADC decode reads."""

    def __init__(self, config):
        self.extra_func = {(108, 181): {"adc": {"config": config}}}


DIV_CTL_ON_DIE = {"DIV_CTL": {0: [], 1: [[0, 1]], 2: [[0, 0], [0, 1]],
                              3: [[0, 0]]}}


def _decode(bits):
    from apycula import gowin_unpack

    tile = [[1 if (0, col) in bits else 0 for col in range(2)]]
    return gowin_unpack._adc_modes_from_config(
        _ConfigDb(DIV_CTL_ON_DIE), 108, 181, tile)


def test_adc_default_configuration_decodes_as_absent():
    """No fuse is spent on a default, so the bitstream cannot carry it."""
    assert _decode(set()) == set()


@pytest.mark.parametrize("value,bits", [(1, {(0, 1)}), (3, {(0, 0)}),
                                        (2, {(0, 0), (0, 1)})])
def test_adc_configuration_decodes_to_the_value_that_matches_exactly(
        value, bits):
    """One value's fuses are a subset of another's; a subset is not a match."""
    assert _decode(bits) == {f"DIV_CTL={value}"}
