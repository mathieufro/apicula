"""`c1` and the IOLOGIC aux half (`P3.T13`).

A gearbox wider than a DDR pair takes both halves of its IOLOGIC tile: the
primitive on the A half and an `IOLOGIC_DUMMY` on the B half whose whole
configuration is `OUTMODE`/`INMODE` = `DDRENABLE`.  `gowin_unpack` skips that
value by design -- an aux cell is not a design cell -- so `c1` could never
name it, and `OSER8`, `OSER10` and `OVIDEO` failed the decode check on a cell
the bitstream format does not carry.  It is recovered through the main cell's
wide mode at the same site, and only there.
"""
import collections

from fuzz.gw5ast138c.harness import equiv


class _Netlist:
    def __init__(self, cells):
        self.cells = cells


#: The key shape `decode_check_c1` iterates over: a decoded cell identified by
#: its site, bel type and z.
_Cell = collections.namedtuple("_Cell", "x y type z")


def _cell(x, y, typ, z=0):
    return _Cell(x, y, typ, z)


def _aux(main="dut", site=(52, 108)):
    return {"name": "dut_aux$", "type": "IOLOGIC_DUMMY", "bel": "IOLOGICBO",
            "site": list(site), "attrs": {"MAIN_CELL": main}}


def test_aux_is_recovered_by_the_gearbox_at_its_own_site():
    netlist = _Netlist({_cell(52, 108, "IOLOGICA"): ["MODE=OSER8"]})
    assert equiv._iologic_aux_recovered_via_main(_aux(), netlist) is None


def test_aux_is_missing_when_no_iologic_decodes_at_that_site():
    """An aux half with no decoded gearbox beside it is a real hole: the wide
    mode that needs the half is not in the bitstream either."""
    netlist = _Netlist({_cell(52, 108, "IOB"): ["IO_TYPE=LVCMOS33"]})
    why = equiv._iologic_aux_recovered_via_main(_aux(), netlist)
    assert why and "no IOLOGIC decoded at site" in why


def test_aux_at_another_site_does_not_recover_it():
    netlist = _Netlist({_cell(60, 108, "IOLOGICA"): ["MODE=OSER8"]})
    assert equiv._iologic_aux_recovered_via_main(_aux(), netlist) is not None


def test_aux_without_a_main_cell_is_never_waved_through():
    aux = _aux()
    aux["attrs"] = {}
    netlist = _Netlist({_cell(52, 108, "IOLOGICA"): ["MODE=OSER8"]})
    assert equiv._iologic_aux_recovered_via_main(aux, netlist) is not None


def test_e1_does_not_ask_the_bitstream_about_the_aux_half():
    """`E1` compares bel addresses, and the aux half has none to compare: the
    decode skips it by design, so exporting it turned every wide gearbox into
    an `E0` row with all three set-level counts at zero."""
    cells = [
        {"name": "dut", "type": "OSER8", "bel": "IOLOGICAO", "site": [52, 108]},
        {"name": "dut_aux$", "type": "IOLOGIC_DUMMY", "bel": "IOLOGICBO",
         "site": [52, 108]},
    ]
    exported = equiv.bitstream_bel_exported(cells)
    assert "dut" in exported
    assert "dut_aux$" not in exported
