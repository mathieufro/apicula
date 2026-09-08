"""The 16-bit gearboxes on the GW5A series (`P3.T16`, `P3.T17`, `P3.T16a`).

`P3.T16` adjudicated `OSER16`/`IDES16` against the vendor on the GW5AST-138C
and the expected refusal was **refuted**: `gw_sh` builds both with zero errors
and its PnR resource report names the primitive it realised.  `P3.T17` turned
the open flow's accidental "can not be placed at <ball>" into a refusal that
named the gap, and `P3.T16a` closed the gap, so there is nothing left to
refuse: these guards now pin the implementation and the geometry it rests on.

The geometry is the load-bearing measurement.  An Arora V `IOLOGIC` carries
sixteen `D` and sixteen `Q` fabric wires, so a 16-bit gearbox fits in ONE pad
pair -- `OSER16` in the pair's `A` and `B` halves, `IDES16` in `A` alone --
where GW1N/GW1NS spread it over two consecutive cells.  A guard that assumed
the pre-5A geometry would pass on a database that places the aux half in the
wrong tile, so each of these asserts the pair, not the pattern.
"""
import inspect

import pytest

from apycula import attrids, chipdb, gowin_pack, gowin_unpack


def test_gw5a_io16_is_no_longer_refused():
    """The refusal `P3.T17` raised is gone, not merely reworded."""
    assert not hasattr(gowin_pack.GW5A, "_refuse_io16")
    assert not hasattr(gowin_pack.GW5A, "get_OSER16_fuses")
    assert not hasattr(gowin_pack.GW5A, "get_IDES16_fuses")


def test_gw5a_iologic_half_of_a_gearbox_has_a_fuse_handler():
    """`nextpnr` presents the gearbox as `IOLOGIC` cells; they must pack."""
    src = inspect.getsource(gowin_pack.GW5A.get_IOLOGIC_fuses)
    assert "common_out_iologic_handler" in src
    assert "common_in_iologic_handler" in src


def test_io16_bels_need_both_iologic_halves():
    """The bel exists exactly where the pad pair does (`fse_iologic`)."""
    src = inspect.getsource(chipdb.fse_iologic)
    assert ("if is_GW5_family(device) and {'IOLOGICA', 'IOLOGICB'} <= bels.keys():"
            in src)


def test_io16_aux_is_the_same_cell_not_the_next_one():
    """`pair` is (0, 0) on this family, and `aux` says why."""
    src = inspect.getsource(chipdb.dat_portmap)
    assert "'role': 'MAIN', 'pair': (0, 0), 'aux': 'IOLOGICB'" in src


def test_iologicb_fuses_follow_its_pad_into_the_aux_cell():
    """A `B` half's IOLOGIC fuses live where its `IOBB` fuses live."""
    src = inspect.getsource(chipdb)
    assert "main_cell.bels['IOLOGICB'].fuse_cell_offset = off" in src
    place = inspect.getsource(gowin_pack.Device.iologic_fuse_bits)
    assert "get_iologic_fuse_cell" in place


@pytest.mark.parametrize("prim,ports", [
    ("OSER16", tuple("D%d" % i for i in range(16))),
    ("IDES16", tuple("Q%d" % i for i in range(16))),
])
def test_io16_portmap_covers_the_whole_word(prim, ports):
    """Sixteen data wires, taken from the pair's own `IOLOGICA`."""
    wanted = (chipdb._gw5_oser16_ports if prim == "OSER16"
              else chipdb._gw5_ides16_ports)
    for port in ports:
        assert port in wanted
    assert "FCLK" in wanted and "PCLK" in wanted and "RESET" in wanted


def test_ides16_inmode_value_is_named_and_decodes_back():
    """The die's 16:1 input code, in both directions of the round trip."""
    assert attrids.iologic_attrvals["UNK105"] == 105
    assert attrids.iologic_num2val[105] == "UNK105"
    assert gowin_unpack._iologic_inmode_alias["UNK105"] == "IDES16"
    assert gowin_pack.GW5AST_138C._INMODE_ALIASES["IDDRX16"] == "UNK105"


def test_oser16_aux_half_adds_oclkce():
    """The one attribute of the pair the generic handler misses."""
    class _Cell:
        parms = {"OUTMODE": "DDRENABLE16"}

    class _Bel:
        cell = _Cell()

    attr_vals = gowin_pack.GW5AST_138C.oser16_aux_attrs(_Bel())
    assert [(av.attr, av.val) for av in attr_vals] == [("OCLKCE", "CE")]

    class _MainCell:
        parms = {"OUTMODE": "ODDRX8"}

    class _MainBel:
        cell = _MainCell()

    assert gowin_pack.GW5AST_138C.oser16_aux_attrs(_MainBel()) == []


def test_decoded_gearbox_is_reported_under_both_bels():
    """The gearbox bel and the `IOLOGIC` half it configures are both true."""
    class _TileData:
        bels = {"IOLOGICA": None, "IOLOGICB": None, "OSER16": None,
                "IDES16": None}

    assert gowin_unpack.io16_bels(_TileData(), "IOLOGICA", "OSER16") == (
        "IOLOGICA", "OSER16")
    assert gowin_unpack.io16_bels(_TileData(), "IOLOGICA", "OSER10") == (
        "IOLOGICA",)

    class _NoIo16:
        bels = {"IOLOGICA": None}

    assert gowin_unpack.io16_bels(_NoIo16(), "IOLOGICA", "OSER16") == (
        "IOLOGICA",)


def test_oser16_still_supported_gw1ns4():
    """The GW1N/GW1NS path keeps its bels and its own geometry.

    A built `GW1NS-4` chipdb is not reachable without that device's vendor
    files, so the guard is on the tables the bel creation reads, which is what
    a GW5A change could plausibly have broken.
    """
    body = inspect.getsource(chipdb)
    assert "if device in {'GW1NS-4'} and ttyp in {142, 143, 144, 58, 59}:" in body
    assert "if device in {'GW1N-9', 'GW1N-9C'} and ttyp in {52, 66, 63, 91, 92}:" in body
    # the pre-5A aux cell is still the neighbouring one
    assert "df.setdefault((0, i + 1), {})['io16'] = {'role': 'AUX', 'pair': (0, -1)}" in body
