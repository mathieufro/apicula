"""`P2.T20` -- the `AE350_SOC` vehicle as a `ShapeSpec`.

The blueprint wrote these tests against the `Emb_TCM` subset and a design
whose clocks were *ports*.  The `P2.T26` rescope replaced that vehicle with
the full 149-port one (the vendor places and routes all of it in 15 s), so the
properties are the same and their subjects moved: there is one clock **pin**
and six internal clock **nets**, and the placement constraint pins the `PLL`
and eight port flops rather than the PLL alone.
"""
import re

import pytest

from fuzz.gw5ast138c.harness import gen
from fuzz.gw5ast138c.shapes import DDR_BANKS, ae350_soc


@pytest.fixture(scope="module")
def spec():
    return ae350_soc.SPEC


@pytest.fixture(scope="module")
def design(tmp_path_factory, spec):
    out = tmp_path_factory.mktemp("ae350_soc")
    gen.run(spec, out)
    return out


def test_ae350_shape_emits_three_files(design):
    for name in ("top.v", "top.cst", "top.sdc"):
        assert (design / name).is_file()
        assert (design / name).read_text()


def test_ae350_shape_sdc_constrains_the_pin_and_never_the_core_clock(design):
    sdc = design / "top.sdc"
    lines = [l for l in sdc.read_text().splitlines()
             if l.startswith("create_clock")]
    assert len(lines) == 1
    assert "clk" in lines[0]
    for forbidden in ("CLKOUT1", "CLKOUT4", "pll_core_clk", "CORE_CLK"):
        assert forbidden not in sdc.read_text()


def test_ae350_shape_cst_pins_the_pll_and_every_port_flop(design):
    lines = [l for l in (design / "top.cst").read_text().splitlines()
             if l.startswith("INS_LOC")]
    expected = ae350_soc.ins_loc()
    assert len(lines) == len(expected) == 9
    assert any('"u_pll" PLL_R[0]' in l for l in lines)
    flops = [l for l in lines if re.search(r"R\d+C\d+\[\d\]\[[AB]\];$", l)]
    assert len(flops) == 8


def test_ae350_shape_open_cst_keeps_every_constraint(design):
    """Both flows must read the same placement, or `E1` asserts nothing."""
    vendor = [l for l in (design / "top.cst").read_text().splitlines()
              if l.startswith("INS_LOC")]
    open_ = [l for l in (design / "top-open.cst").read_text().splitlines()
             if l.startswith("INS_LOC")]
    assert sorted(vendor) == sorted(open_)


def test_ae350_shape_no_bank6_or_bank7_pins(spec):
    assert [p for p in spec.pins.values() if p.bank in DDR_BANKS] == []


def test_ae350_shape_dualpin_option_sets_do_not_cross(spec):
    gwsh = " ".join(spec.extra_gwsh_options)
    pack = " ".join(spec.extra_pack_flags)
    assert gwsh.count("-use_") == 2 and "--" not in gwsh
    assert pack.count("--") == 2 and "-use_" not in pack


def test_ae350_shape_sspi_setting_reaches_nextpnr_and_the_packer(spec):
    """`gowin_pack.get_PINCFG_fuses` raises when the two sides disagree."""
    assert "sspi_as_gpio" in spec.extra_nextpnr_vopts
    assert "--sspi_as_gpio" in spec.extra_pack_flags
    assert not [o for o in spec.extra_nextpnr_vopts if o.startswith("-")]


def test_ae350_shape_six_clock_ports_have_six_distinct_nets(design):
    """The head-order defect `P2.T22` recorded: one net for six taps."""
    text = (design / "top.v").read_text()
    nets = {}
    for port in ae350_soc.NAMED_CLOCKS:
        match = re.search(r"\.%s\(([^)]*)\)" % port, text)
        assert match is not None, port
        nets[port] = match.group(1).strip()
    assert len(set(nets.values())) == 6, nets
    assert nets["CORE_CLK"] == "pll_core_clk"


def test_ae350_shape_drives_every_mapped_input_bit(design):
    text = (design / "top.v").read_text()
    pmap = ae350_soc.port_map()
    assert len(pmap.data_in_bits) == len(pmap.in_bits) - 6
    for port in pmap.in_buses:
        assert re.search(r"\.%s\(" % port, text), port
    assert "localparam integer NI = %d;" % len(pmap.data_in_bits) in text


def test_ae350_shape_scope_covers_band_config_pll_and_flop_tiles(spec):
    tiles = {tuple(t) for t in spec.scope.tiles}
    assert (159, 0) in tiles                       # the bel's own tile
    assert all((col, 0) in tiles for col in ae350_soc.BAND_COLS)
    assert (177, 27) in tiles                      # PLL_R[0]
    # Context, NOT compared: the ae350_config tiles are ordinary fabric, and
    # the pinned-flop tile carries the two synthesisers' flop decomposition.
    assert (145, 10) not in tiles and (180, 100) not in tiles
    assert (160, 1) not in tiles
    assert len(tiles) == 37 + 3


def test_ae350_shape_output_fold_needs_no_wide_lut(design):
    """A wide XOR maps to `MUX2_LUT5..8`, which the unpacker does not decode."""
    text = (design / "top.v").read_text()
    assert "^cap" not in text
    assert "assign dout = cap[NO-1];" in text
    for line in text.splitlines():
        if "cap[" in line and "<=" in line:
            assert line.count("^") <= 2, line


def test_ae350_shape_blackbox_is_yosys_only(design):
    """`gw_sh` must see its own primitive, never an empty user module."""
    text = (design / "top.v").read_text()
    assert "`ifdef YOSYS" in text
    head, rest = text.split("`ifdef YOSYS", 1)
    body, tail = rest.split("`endif", 1)
    assert "module AE350_SOC" in body
    assert "module AE350_SOC" not in head and "module AE350_SOC" not in tail
