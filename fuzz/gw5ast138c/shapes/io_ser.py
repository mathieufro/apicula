"""`io_ser` -- the output-serialiser family on the GW5AST-138C (`P3.T13`).

`OSER4`, `OSER8`, `OSER10` and `OVIDEO`, one per run.  `OSER4` in its `MODDRX21`
(2:1 DDR) mode is the RGMII TX gearbox -- the thing `RGMII_TXD[3:0]` and
`RGMII_GTXCLK` need at 125 MHz -- so closing this family closes the RGMII TX
half of `S10`.

**The row is measured in HCLK block 4, on bank 5, and not on the dock's own
RGMII balls, for a measured reason.**  What makes the HCLK *lane* part of the
comparison rather than each allocator's private choice is a `CLKDIV` pinned to
a named lane of the gearbox's own block: it consumes that lane's
`HCLK_MUX_ALPHA` wire, so the `FCLK` net has to land there on both sides
(`D107`).  The RGMII balls are served by block 1, and block 1 has no modelled
clock escape (`D100a`): a divider placed there cannot reach the gearbox's
`PCLK` at all -- MEASURED, `nextpnr` reports `Failed to find a route for arc 0
of net pclk`.  Bank 5's general-purpose 3.3 V balls are all in block 4, which
`P1.T08d` mapped lane by lane, so that is where the family is measured.  The
two `P3.T13` runs already spent on a bank-2 `OSER4` are what measured the
consequence of *not* pinning the lane and are kept in `summary.md`.

One `INS_LOC` line places the divider in **both** flows: `nextpnr-himbaechel`'s
`.cst` reader now splits a `{SIDE}[0~7]` index into an HCLK block ordinal and a
lane, so the vendor's own spelling is the open flow's constraint too and the
`(* BEL *)` attribute this shape used to carry is gone.

**Every producer and consumer of the primitive under test is a package ball**
(`D105`).  A gearbox fed from fabric flops closes `E1` on cells and attributes
and then differs on `conns`, because a fabric cell is placed independently by
the two flows and `equiv.net_id` digests a net's endpoint *sites*;
GowinSynthesis renames the flop, so `INS_LOC` cannot pin it either (MEASURED,
`P3.T12`).  The parallel word therefore comes off two balls, even bits from one
and odd bits from the other -- the two edges of the DDR word -- and the
serialised output drives a third.

The swept axis is the primitive's own documented parameter set, one axis per
run (`F12`).  `prim_sim.v` declares `HWL` and `TXCLK_POL` on `OSER4` (`:10342`)
and `OSER8` (`:10912`) and **no parameter at all** on `OSER10` (`:11303`) or
`OVIDEO` (`:10718`); a `defparam` naming a parameter the primitive does not
declare is a GowinSynthesis error, not a no-op.  Both parameters are swept on
`OSER4` and neither on `OSER8`: `gowin_pack` reads them in
`common_iologic_handler`, which is one handler for every width, so a second
width would re-measure the same code path with a run this row does not have --
`P3.T13`'s cap is eight and two are already spent.
"""
from ._io_base import (GEARBOX_CLKDIV_INS_LOC, GEARBOX_DIV_MODE, IoShape,
                       clkdiv_rtl)

#: `(width, attribute, value)` per sweep point, one axis per run (`F12`).
POINTS = {
    "oser4-default": (4, None, None),
    "oser4-txclk-pol": (4, "TXCLK_POL", "1'b1"),
    "oser4-hwl": (4, "HWL", '"true"'),
    "oser8-default": (8, None, None),
    "oser10-default": (10, None, None),
    "ovideo-default": (7, None, None),
}

BASELINE = "oser4-default"

#: The primitive each gearbox width names.
PRIMITIVE_OF_WIDTH = {4: "OSER4", 7: "OVIDEO", 8: "OSER8", 10: "OSER10"}

#: The balls, and why each is the one it is.
#:
#: `AA9` is `IOB53A`, cell `(108,52)`, tile type 247: the **A** half, because
#: `db.shortval[ttyp]['IOLOGICB']` holds 3 fuse coordinates against
#: `IOLOGICA`'s 100 on every IO tile type this package bonds, so an IOLOGIC is
#: configurable on the A half only (`P3.T11`'s named gap).  It is also in HCLK
#: block 4 (bottom edge, columns 2..90) and on a tile type whose `IOLOGICA`
#: bel carries a full port map -- the bottom edge also holds tile types 63 and
#: 251, whose `IOLOGICA` has **no ports at all**, and a gearbox placed there
#: fails in `nextpnr`'s global router with `Net 'pclk' has an invalid sink port
#: dut.PCLK` (MEASURED here; `Y17`, `P20` and `N15` are those tile types).
OSER_BALL = "AA9"          # IOB53A, cell (108,52), sk9822_da
DIN_EVEN_BALL = "W15"      # IOB72A, sd_cs
DIN_ODD_BALL = "W16"       # IOB72B, LCD_CTP[0], pair of W15
RESET_BALL = "T16"         # IOB76A, LCD_CTP[2]
RESETN_BALL = "AB13"       # IOB89B, Key_in[0], the CLKDIV's own reset
FCLK_BALL = "V22"          # IOB104B, the board oscillator

#: The one tile the `E0`/`E1` comparison is restricted to: the serialiser's
#: own pad cell, which is the only cell an IOLOGIC can be realised in.  A
#: `ScopeSpec` tile is `(x, y)` = `(col, row)`, the Himbaechel spelling, not
#: the `(row, col)` the chipdb tables use.  The
#: balls that feed it sit in other tiles and are pinned by `IO_LOC`, so every
#: net of this tile has all of its endpoints at a site both flows agree on
#: without either of them being compared here.
SCOPE_TILES = ((52, 108),)

_ACK_CLK = ("EMCCLK: 27 vendor runs on this device placed a design with clk "
            "on V22 and gw_sh returned 0 every time (P1.T08d, "
            "$OTC/evidence/hclk/mux38-138c.md 3); it is the Tang Mega 138K "
            "board clock and examples/gw5a/tangmega138k.cst names it")

_TEMPLATE = """\
// Generated by fuzz.gw5ast138c.harness.gen from shapes/io_ser.py -- do not edit.
// Shape: io_ser (primitive under test: {primitive})
// Sweep: {axis} = {point}
`default_nettype none

module {top} (
    input  wire fclk,
    input  wire resetn,
    input  wire rst,
    input  wire din_even,
    input  wire din_odd,
    output wire dout
);

    wire pclk;

{clkdiv}
    {primitive} dut (
{ports}    );
{defparams}
endmodule

`default_nettype wire
"""


def _port_block(width, primitive):
    """The gearbox's ports: the parallel word off two balls, `Q` onto a third.

    Even bits come off `din_even` and odd bits off `din_odd`, so the two DDR
    edges are distinguishable in the decode while the design still holds no
    fabric cell.
    """
    lines = ["        .%-6s (din_%s)," % ("D%d" % i,
                                          "even" if i % 2 == 0 else "odd")
             for i in range(width - 1, -1, -1)]
    if primitive in ("OSER4", "OSER8"):
        # TX0..TX(width/2-1) drive the pad's output enable; a serialiser that
        # never enables its pad realises no output buffer.
        lines += ["        .%-6s (1'b1)," % ("TX%d" % i)
                  for i in range(width // 2 - 1, -1, -1)]
    lines += [
        "        .FCLK   (fclk),",
        "        .PCLK   (pclk),",
        "        .RESET  (rst),",
    ]
    if primitive in ("OSER4", "OSER8"):
        lines += ["        .Q0     (dout),", "        .Q1     ()"]
    else:
        lines += ["        .Q      (dout)"]
    return "\n".join(lines) + "\n"


class IoSerShape(IoShape):
    """One output serialiser per run on the dock's RGMII balls."""

    name = "io_ser"
    primitive = "OSER4 / OSER8 / OSER10 / OVIDEO"
    sweep_axis = "POINT"
    sweep_values = list(POINTS)
    baseline_value = BASELINE
    ports = {
        "fclk": (FCLK_BALL, "input"),
        # The divider's reset is active low and the gearbox's active high, so
        # they are two balls and not one inverter: an inverter is a fabric
        # cell, and the gearbox's reset net reaches into the scoped tile.
        "resetn": (RESETN_BALL, "input", {"pull_mode": "UP"}),
        "rst": (RESET_BALL, "input", {"pull_mode": "DOWN"}),
        "din_even": (DIN_EVEN_BALL, "input"),
        "din_odd": (DIN_ODD_BALL, "input"),
        "dout": (OSER_BALL, "output"),
    }
    clocks = {"fclk": 8.0}
    config_role_acks = {FCLK_BALL: _ACK_CLK}
    scope_tiles = SCOPE_TILES
    #: The one placement constraint of the shape, read by **both** flows.  It
    #: does two things at once: the `PCLK` net ends on the scoped tile's
    #: IOLOGIC, so a freely placed divider would give that net two identities,
    #: and the divider consumes its lane's `HCLK_MUX_ALPHA` wire, so pinning it
    #: pins the lane the gearbox's `FCLK` lands on (`D107`).
    ins_loc = {"pclk_div": GEARBOX_CLKDIV_INS_LOC}

    def rtl(self, sweep_value):
        width, attribute, value = POINTS[sweep_value]
        primitive = PRIMITIVE_OF_WIDTH[width]
        defparams = ("    defparam dut.%s = %s;\n" % (attribute, value)
                     if attribute else "")
        return _TEMPLATE.format(
            primitive=primitive, axis=self.sweep_axis, point=sweep_value,
            top=self.top_module, clkdiv=clkdiv_rtl(width),
            ports=_port_block(width, primitive), defparams=defparams)


#: Sanity that the module's two tables agree -- a width with no `DIV_MODE`
#: would render a `CLKDIV` with no divider and silently clock the gearbox
#: wrong.
assert set(PRIMITIVE_OF_WIDTH) == set(GEARBOX_DIV_MODE)

SPEC = IoSerShape().spec()
