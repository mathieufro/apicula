"""The four measured Phase-1 clocking gaps, one property each (`P1.F3`).

Every fact asserted here is MEASURED against a vendor bitstream and recorded
in the evidence file the test names; none of it is inferred from the vendor
files alone.
"""
import pytest

from apycula import chipdb

from tests.test_gw5ast138c_clocking import (_build, _CHIPDB, _NEXTPNR,
                                            _YOSYS)

#: The bottom-left quadrant cell and the spine `p1f3-pll-route/b-b0` and
#: `b-b1` program from a logic-to-clock gate
#: (`$OTC/evidence/plla/hclk-entry-138c.md` section 1).
QUADRANT_CELL_138C = (81, 85)
QUADRANT_SPINE_138C = 'SPINE9'
QUADRANT_GATE_138C = 'BRMDCLK1_BOT'

#: `PLL_L[0]`'s anchor tile and the clock-plane wire its `CLKOUT0` drives,
#: measured in `p1f3-pll-route/a-l0-hclk` as `(54, 93) SPINE9 <= TLPLL0CLK0`.
PLL_L0_CELL_138C = (27, 1)
PLL_L0_CLK_WIRE_138C = 'TLPLL0CLK0'

#: HCLK block 5, and the lane whose logic entry is an ordinary fabric wire
#: (`$OTC/evidence/dhcen/lane3-138c.md`).
BLOCK5_CELL_138C = (108, 117)
FABRIC_ENTRY_138C = {'lanes': [3], 'sinks': ['CLKDIV_I53']}


@pytest.mark.heavy  # parses a real multi-MB vendor .fse via _build()
def test_quadrant_spine_takes_a_logic_clock_gate_source_138c(gowinhome):
    """A gate drives a quadrant spine, not only the central bridge's."""
    dev, _ = _build('GW5AST-138C', gowinhome)
    srcs = dev[QUADRANT_CELL_138C].clock_pips[QUADRANT_SPINE_138C]
    assert QUADRANT_GATE_138C in srcs
    assert srcs[QUADRANT_GATE_138C], 'the gate source must carry its fuses'


@pytest.mark.heavy  # parses a real multi-MB vendor .fse via _build()
def test_pll_site_reaches_its_measured_clock_wire_138c(gowinhome):
    """`PLL_L[0]`'s `CLKOUT0` and the clock plane's `TLPLL0CLK0` are joined."""
    dev, _ = _build('GW5AST-138C', gowinhome)
    row, col = PLL_L0_CELL_138C
    assert dev[row, col].pips[PLL_L0_CLK_WIRE_138C] == {'MPLLCLKOUT0': set()}
    members = dev.nodes[PLL_L0_CLK_WIRE_138C][1]
    assert (row, col, PLL_L0_CLK_WIRE_138C) in members
    assert len(members) > 1, 'the site must share the node with the bridge'


@pytest.mark.heavy  # parses a real multi-MB vendor .fse via _build()
def test_fabric_entry_lanes_are_recorded_per_block_138c(gowinhome):
    """Every HCLK block names the lane a clock can only enter over fabric."""
    dev, _ = _build('GW5AST-138C', gowinhome)
    for row, col in chipdb._gw5a_hclk_locs['GW5AST-138C'].values():
        assert dev.extra_func[row, col]['hclk_fabric_entry']['lanes'] == [3]
    assert dev.extra_func[BLOCK5_CELL_138C]['hclk_fabric_entry'] == \
        FABRIC_ENTRY_138C


@pytest.mark.heavy  # runs the real yosys + nextpnr against the installed pair
def test_nextpnr_routes_four_buffered_clocks_138c(tmp_path):
    """Four buffered global clock nets build; before `P1.F3` the first failed."""
    import subprocess
    for tool in (_NEXTPNR, _CHIPDB, _YOSYS):
        if not tool.exists():
            pytest.skip(f'{tool} absent')
    (tmp_path / 'top.v').write_text(FOUR_CLOCK_RTL)
    (tmp_path / 'top.cst').write_text(FOUR_CLOCK_CST)
    subprocess.run(
        [str(_YOSYS), '-p',
         'read_verilog top.v; synth_gowin -family gw5a -setundef -json top.json'],
        cwd=tmp_path, check=True, capture_output=True)
    proc = subprocess.run(
        [str(_NEXTPNR), '--device', 'GW5AST-LV138PG484AC1/I0',
         '--chipdb', str(_CHIPDB), '--vopt', 'cst=top.cst', '--json', 'top.json',
         '--write', 'top_pnr.json', '--top', 'top', '--timing-allow-fail'],
        cwd=tmp_path, capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr[-2000:]


FOUR_CLOCK_RTL = """\
`default_nettype none
module top (input wire clk0, input wire clk1, input wire clk2, input wire clk3,
            input wire reset, output wire [3:0] led);
    wire div_clk;
    (* BEL = "X117Y108/CLKDIV_0" *) CLKDIV div0 (
        .HCLKIN(clk0), .RESETN(reset), .CALIB(1'b0), .CLKOUT(div_clk));
    defparam div0.DIV_MODE = "4";
    reg d0;
    reg [3:0] raw;
    always @(posedge div_clk) d0 <= ~d0;
    always @(posedge clk0) raw[0] <= ~raw[0];
    always @(posedge clk1) raw[1] <= ~raw[1];
    always @(posedge clk2) raw[2] <= ~raw[2];
    always @(posedge clk3) raw[3] <= ~raw[3];
    assign led = raw ^ {3'b0, d0};
endmodule
`default_nettype wire
"""

FOUR_CLOCK_CST = """\
IO_LOC  "clk0" V22;
IO_PORT "clk0" IO_TYPE=LVCMOS33 PULL_MODE=NONE PULL_STRENGTH=MEDIUM BANK_VCCIO=3.3;
IO_LOC  "clk1" Y12;
IO_PORT "clk1" IO_TYPE=LVCMOS33 PULL_MODE=NONE PULL_STRENGTH=MEDIUM BANK_VCCIO=3.3;
IO_LOC  "clk2" AA11;
IO_PORT "clk2" IO_TYPE=LVCMOS33 PULL_MODE=NONE PULL_STRENGTH=MEDIUM BANK_VCCIO=3.3;
IO_LOC  "clk3" AA9;
IO_PORT "clk3" IO_TYPE=LVCMOS33 PULL_MODE=NONE PULL_STRENGTH=MEDIUM BANK_VCCIO=3.3;
IO_LOC  "reset" AA10;
IO_PORT "reset" IO_TYPE=LVCMOS33 PULL_MODE=UP PULL_STRENGTH=MEDIUM BANK_VCCIO=3.3;
IO_LOC  "led[0]" P20;
IO_PORT "led[0]" IO_TYPE=LVCMOS33 PULL_MODE=NONE PULL_STRENGTH=MEDIUM DRIVE=8 BANK_VCCIO=3.3;
IO_LOC  "led[1]" Y17;
IO_PORT "led[1]" IO_TYPE=LVCMOS33 PULL_MODE=NONE PULL_STRENGTH=MEDIUM DRIVE=8 BANK_VCCIO=3.3;
IO_LOC  "led[2]" W14;
IO_PORT "led[2]" IO_TYPE=LVCMOS33 PULL_MODE=NONE PULL_STRENGTH=MEDIUM DRIVE=8 BANK_VCCIO=3.3;
IO_LOC  "led[3]" Y16;
IO_PORT "led[3]" IO_TYPE=LVCMOS33 PULL_MODE=NONE PULL_STRENGTH=MEDIUM DRIVE=8 BANK_VCCIO=3.3;
"""
