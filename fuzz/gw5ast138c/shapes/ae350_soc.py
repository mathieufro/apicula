"""`ae350_soc` -- the `AE350_SOC` fabric-tap vehicle as a harness shape.

The `Emb_TCM` subset the blueprint originally scoped is *not* the vehicle,
because run `p2t26-tilewires` showed the vendor
places and routes **all 149 ports at once in 15 seconds**, so the full port
set is cheaper than the subset and strictly more informative.  What was
missing from the earlier hand-written vehicle was not a smaller design --
it was a `ShapeSpec`, and
without one `equiv` has no `ScopeSpec` and can only run the whole-device
calibration (`D32`, F6).  This file is that `ShapeSpec`.

Four things this shape fixes that the earlier hand-written vehicle could not
express:

1. **Six distinct clock nets.**  The earlier vehicle drove `CORE_CLK`,
   `DDR_CLK`, `AHB_CLK`, `APB_CLK`, `RTC_CLK` and `DBG_TCK` from one fabric
   net, so the six `CLK`-class taps in the block's band were
   indistinguishable and the *head order* -- which tap belongs to which clock
   port -- was unresolvable by construction.  Here each of the six is a
   different net: `CORE_CLK` comes from the `PLL` at `PLL_R[0]`, the other
   five from the five stages of a ripple divider.  A seventh input,
   `INTEG_TCK`, also lands on a `CLK` wire (measured from the chipdb map, and
   the reason the vendor run showed *seven* clock-class taps where the
   dossier names six); it keeps its own shift-chain bit, which is a distinct
   net too, so all seven are separable.
2. **`PLL_R[0]` drives the core clock**, as MUG1031 requires of a real AE350
   design, rather than an ordinary fabric clock.  The `.sdc` carries
   `create_clock` on the input pin only -- never on the PLL output feeding
   `CORE_CLK`, matching the shipped reference `.sdc`, because the core domain
   is a dedicated route the fabric STA does not see.
3. **Pinned port flops.**  Eight `DFF` primitives with flat instance names sit
   at fixed CLS sites of one tile.  Four drive an `AE350_SOC` input, four
   capture an output.  Both flows read the `RxCy[cls][A|B]` spelling of
   `INS_LOC` (`gen.OPEN_FLOW_INS_LOC_FORMS`), so the vendor and nextpnr are
   given the *same* placement and `E1` has something in scope to assert.
4. **A scope.**  `ScopeSpec` names the block's own band, its 216 configuration
   tiles, the `PLL_R[0]` site and the pinned-flop tile -- and nothing else.

The port map is **not** written down here: buses, widths, directions and the
unmapped bits are all read from `extra_func[(0, 159)]['ae350']` of the chipdb
this run is measured against, so a correction to the map changes the vehicle
with no edit to this file.
"""
import re

from . import PinSpec, ScopeSpec, ShapeSpec

#: The bel's own tile: die row 0, column 159 (MEASURED, `evidence/ae350/portmap-138c.md`).
AE350_ANCHOR = (0, 159)

#: The block's measured footprint in die row 0 (`wire-map-138c.md` §3): the
#: band is documented as columns 145-181 and kept whole, never used as a
#: filter.
BAND_ROW = 0
BAND_COLS = range(145, 182)

#: `PLL_R[0]`'s anchor `(row, col)` and the three tiles of the site
#: (`shapes/clocking_pll.py`, MEASURED, `evidence/plla/`).
PLL_SITE = "PLL_R[0]"
PLL_ANCHOR = (27, 177)

#: The tile the eight pinned port flops sit in, as `(row, col)`.  Row 1 is the
#: first fabric row with `CLS` bels -- die row 0 is the AE350's own band and
#: has none at all (tile type 242: 0 bels, 125 pips), which is why the block's
#: taps cannot be met by placing a cell "at" them.
FLOP_TILE = (1, 160)

#: `PLL` parameters: the operating point MEASURED in `evidence/plla/`, with
#: `CLKOUT1` enabled
#: because that is the output MUG1031 routes to `CORE_CLK`.
PLL_PARAMS = (
    ("FCLKIN", '"100.0"'),
    ("IDIV_SEL", "2"),
    ("FBDIV_SEL", "2"),
    ("MDIV_SEL", "13"),
    ("ODIV0_SEL", "8"),
    ("ODIV1_SEL", "8"),
    ("CLKOUT0_EN", '"TRUE"'),
    ("CLKOUT1_EN", '"TRUE"'),
    ("CLKFB_SEL", '"INTERNAL"'),
    ("DYN_IDIV_SEL", '"FALSE"'),
    ("DYN_FBDIV_SEL", '"FALSE"'),
    ("DYN_ODIV0_SEL", '"FALSE"'),
)

#: The five clock ports driven by the ripple divider, in stage order.  The
#: sixth, `CORE_CLK`, is the PLL's; the order here is the shape's own and is
#: recorded so a reader never has to re-derive which stage drove what.
DIVIDER_CLOCKS = ("DDR_CLK", "AHB_CLK", "APB_CLK", "RTC_CLK", "DBG_TCK")

#: The port bit each pinned flop carries, and the CLS site it is pinned at.
#: `(instance, port bit, cls, half)`; the drivers come first.
PINNED_DRIVERS = (
    ("wit_por_n", "POR_N", 0, "A"),
    ("wit_hw_rstn", "HW_RSTN", 0, "B"),
    ("wit_gpio_in0", "GPIO_IN0", 1, "A"),
    ("wit_uart2_rxd", "UART2_RXD", 1, "B"),
)
PINNED_CAPTURES = (
    ("wit_gpio_out0", "GPIO_OUT0", 2, "A"),
    ("wit_uart2_txd", "UART2_TXD", 2, "B"),
    ("wit_apb_psel", "APB_PSEL", 3, "A"),
    ("wit_ddr_hwrite", "DDR_HWRITE", 3, "B"),
)

_BIT_RE = re.compile(r"^(.*?)(\d+)$")


class PortMapError(Exception):
    """The chipdb's AE350 port map is not the shape this vehicle needs."""


def _split_bit(name):
    """`'GPIO_IN7'` -> `('GPIO_IN', 7)`; a scalar port -> `(name, None)`."""
    match = _BIT_RE.match(name)
    if match is None:
        return name, None
    return match.group(1), int(match.group(2))


def _buses(bits):
    """`{port: width or None}` for a direction's bit names, in port order.

    A group is a bus only when its indices are exactly `0..n-1`: that is what
    tells a real bus apart from a scalar port whose name happens to end in a
    digit, and a group that is neither raises rather than being guessed at.
    """
    groups = {}
    for name in bits:
        base, index = _split_bit(name)
        groups.setdefault(base, []).append(index)
    out = {}
    for base in sorted(groups):
        indices = groups[base]
        if indices == [None]:
            out[base] = None
            continue
        if None in indices or sorted(indices) != list(range(len(indices))):
            raise PortMapError(
                f"port group {base!r} has indices {sorted(indices)!r}, which "
                "is neither a scalar nor a contiguous bus")
        out[base] = len(indices)
    return out


def _load_map():
    """The chipdb's own AE350 port map, as `(ins, outs, unmapped)` dicts."""
    from ..harness.equiv import load_db

    extra = load_db().extra_func.get(AE350_ANCHOR, {}).get("ae350")
    if not extra:
        raise PortMapError(
            f"the chipdb has no extra_func[{AE350_ANCHOR}]['ae350']: this "
            "shape is only meaningful against a database that carries the "
            "AE350 bel")
    return extra["ins"], extra["outs"], extra.get("unmapped", {})


def _wire_of(port, value):
    """The tile wire a tap names, with the `AE350_SOC<port>` prefix removed."""
    prefix = "AE350_SOC" + port
    return value[len(prefix):] if str(value).startswith(prefix) else str(value)


class PortMap:
    """The vehicle's view of the chipdb map: buses, clocks and mapped bits."""

    def __init__(self):
        ins, outs, unmapped = _load_map()
        self.unmapped = set(unmapped)
        self.clock_bits = tuple(sorted(
            bit for bit, value in ins.items()
            if _wire_of(bit, value).startswith("CLK")))
        self.in_buses = _buses(ins)
        self.out_buses = _buses(outs)
        self.in_bits = tuple(sorted(ins, key=lambda n: (_split_bit(n)[0],
                                                        _split_bit(n)[1] or 0)))
        self.out_bits = tuple(sorted(outs, key=lambda n: (_split_bit(n)[0],
                                                          _split_bit(n)[1] or 0)))
        #: Every input bit that is not one of the six named clocks: those get
        #: their own shift-chain bit.  `INTEG_TCK` is deliberately here even
        #: though its tap is `CLK`-class -- a shift-chain bit is a distinct
        #: net, which is all the head-order resolution needs.
        self.data_in_bits = tuple(b for b in self.in_bits
                                  if b not in NAMED_CLOCKS)
        self.captured_out_bits = tuple(
            b for b in self.out_bits
            if b not in self.unmapped
            and b not in {p for _, p, _, _ in PINNED_CAPTURES})

    def width(self, port, direction):
        table = self.in_buses if direction == "in" else self.out_buses
        return table[port]


#: The six clock ports the dossier names, in the order this shape drives them.
NAMED_CLOCKS = ("CORE_CLK",) + DIVIDER_CLOCKS

_MAP = None


def port_map():
    """The chipdb port map, loaded once."""
    global _MAP
    if _MAP is None:
        _MAP = PortMap()
    return _MAP


# --------------------------------------------------------------------------
# Verilog
# --------------------------------------------------------------------------
def _blackbox(pmap):
    """The `AE350_SOC` blackbox, seen by **yosys only**.

    `yosys` predefines the macro `YOSYS`, and `gw_sh` does not, so this
    declaration reaches the open flow -- which has no cell library entry for
    the block -- and never shadows GowinSynthesis's own primitive, which would
    silently synthesise the design with an empty core.
    """
    ports = []
    for port in sorted(pmap.in_buses):
        width = pmap.in_buses[port]
        ports.append("    input  wire %s%s"
                     % (("[%d:0] " % (width - 1)).ljust(9) if width else " " * 9,
                        port))
    for port in sorted(pmap.out_buses):
        width = pmap.out_buses[port]
        ports.append("    output wire %s%s"
                     % (("[%d:0] " % (width - 1)).ljust(9) if width else " " * 9,
                        port))
    return ("`ifdef YOSYS\n(* blackbox *)\nmodule AE350_SOC (\n"
            + ",\n".join(ports) + "\n);\nendmodule\n`endif\n")


def _pll(pmap):
    params = ",\n".join("        .%s(%s)" % (k, v) for k, v in PLL_PARAMS)
    return """\
    // MUG1031: a real AE350 takes its core clock from a PLL pinned at
    // PLL_R[0].  CLKOUT1 is that output; the .sdc never constrains it.
    wire pll_core_clk;
    wire pll_aux_clk;
    wire pll_lock;
    PLL #(
%s
    ) u_pll (
        .CLKIN(clk), .CLKFB(1'b0), .RESET(~rst_n), .PLLPWD(1'b0),
        .RESET_I(1'b0), .RESET_O(1'b0),
        .FBDSEL(6'b0), .IDSEL(6'b0), .MDSEL(7'b0), .MDSEL_FRAC(3'b0),
        .ODSEL0(7'b0), .ODSEL0_FRAC(3'b0),
        .ODSEL1(7'b0), .ODSEL2(7'b0), .ODSEL3(7'b0),
        .ODSEL4(7'b0), .ODSEL5(7'b0), .ODSEL6(7'b0),
        .DT0(4'b0), .DT1(4'b0), .DT2(4'b0), .DT3(4'b0),
        .ICPSEL(6'b0), .LPFRES(3'b0), .LPFCAP(2'b0),
        .PSSEL(3'b000), .PSDIR(1'b0), .PSPULSE(1'b0),
        .ENCLK0(1'b1), .ENCLK1(1'b1), .ENCLK2(1'b0), .ENCLK3(1'b0),
        .ENCLK4(1'b0), .ENCLK5(1'b0), .ENCLK6(1'b0),
        .SSCPOL(1'b0), .SSCON(1'b0), .SSCMDSEL(7'b0), .SSCMDSEL_FRAC(3'b0),
        .LOCK(pll_lock),
        .CLKOUT0(pll_aux_clk), .CLKOUT1(pll_core_clk),
        .CLKOUT2(), .CLKOUT3(), .CLKOUT4(), .CLKOUT5(), .CLKOUT6(),
        .CLKFBOUT()
    );
""" % params


def _divider():
    """Five ripple stages: five distinct clock nets, and no ALU cell.

    A counter would pack into `ALU` bels, which the `c1` decode check unpacks
    with `noalu=True` and therefore reports missing (MEASURED, `evidence/clkdiv/`); a
    toggle chain is LUT+DFF only and does not step on that.
    """
    lines = ["    // Five ripple stages -- one distinct clock net per AE350",
             "    // clock port, so each CLK-class tap has its own driver.",
             "    reg [4:0] ck;",
             "    always @(posedge clk)     if (!rst_n) ck[0] <= 1'b0; else ck[0] <= ~ck[0];"]
    for stage in range(1, 5):
        lines.append(
            "    always @(posedge ck[%d]) if (!rst_n) ck[%d] <= 1'b0; else ck[%d] <= ~ck[%d];"
            % (stage - 1, stage, stage, stage))
    return "\n".join(lines) + "\n"


def _connection(pmap, port, direction, driver_of=None):
    """The connection expression for one whole port."""
    width = pmap.width(port, direction)
    if direction == "out":
        return "o_%s" % port
    if width is None:
        return driver_of(port)
    bits = ", ".join(driver_of("%s%d" % (port, i))
                     for i in reversed(range(width)))
    return "{%s}" % bits


def rtl(spec, sweep_value=None):
    """Render the vehicle for the one sweep point this shape has."""
    pmap = port_map()
    drv_index = {bit: i for i, bit in enumerate(pmap.data_in_bits)}
    pinned_driver = {port: instance for instance, port, _, _ in PINNED_DRIVERS}
    pinned_capture = {port: instance for instance, port, _, _ in PINNED_CAPTURES}
    clock_net = {"CORE_CLK": "pll_core_clk"}
    for stage, port in enumerate(DIVIDER_CLOCKS):
        clock_net[port] = "ck[%d]" % stage

    def driver_of(bit):
        if bit in clock_net:
            return clock_net[bit]
        if bit in pinned_driver:
            return "q_%s" % pinned_driver[bit]
        return "drv[%d]" % drv_index[bit]

    body = []
    body.append(_pll(pmap))
    body.append(_divider())
    body.append("""
    // The shift chain: one flop per driven input bit, so no port can be
    // folded away and every tap has its own fabric endpoint.
    localparam integer NI = %d;
    reg [NI-1:0] drv;
    always @(posedge clk)
        if (!rst_n) drv <= {NI{1'b0}};
        else        drv <= {drv[NI-2:0], din};
""" % len(pmap.data_in_bits))

    body.append("\n    // The pinned port flops (INS_LOC in both flows).\n")
    for instance, port, _cls, _half in PINNED_DRIVERS:
        body.append('    wire q_%s;\n    DFF %s (.D(drv[%d]), .CLK(clk), '
                    '.Q(q_%s));\n'
                    % (instance, instance, drv_index[port], instance))

    body.append("\n    // Every output bus, whole -- unmapped bits included,\n"
                "    // so the instantiation is the block's real port list.\n")
    for port in sorted(pmap.out_buses):
        width = pmap.out_buses[port]
        body.append("    wire %so_%s;\n"
                    % (("[%d:0] " % (width - 1)) if width else "", port))
    for instance, port, _cls, _half in PINNED_CAPTURES:
        base, index = _split_bit(port)
        target = ("o_%s[%d]" % (base, index) if index is not None
                  else "o_%s" % port)
        body.append('    wire q_%s;\n    DFF %s (.D(%s), .CLK(clk), .Q(q_%s));\n'
                    % (instance, instance, target, instance))

    ports = []
    for port in sorted(pmap.in_buses):
        ports.append("        .%s(%s)"
                     % (port, _connection(pmap, port, "in", driver_of)))
    for port in sorted(pmap.out_buses):
        ports.append("        .%s(o_%s)" % (port, port))
    body.append("\n    AE350_SOC u_ae350 (\n" + ",\n".join(ports) + "\n    );\n")

    captured = []
    for bit in pmap.captured_out_bits:
        base, index = _split_bit(bit)
        captured.append("o_%s[%d]" % (base, index) if index is not None
                        else "o_%s" % bit)
    extras = (["q_%s" % i for i, _, _, _ in PINNED_CAPTURES]
              + ["pll_lock", "pll_aux_clk"])
    stages = ["    localparam integer NO = %d;" % len(captured),
              "    reg [NO-1:0] cap;",
              "    always @(posedge clk) begin"]
    for i, bit in enumerate(captured):
        terms = [bit]
        if i:
            terms.append("cap[%d]" % (i - 1))
        if i < len(extras):
            terms.append(extras[i])
        stages.append("        cap[%d] <= %s;" % (i, " ^ ".join(terms)))
    stages += ["    end", "", "    assign dout = cap[NO-1];", ""]
    body.append("\n" + "\n".join(stages))

    return ("""\
// Generated by fuzz.gw5ast138c.harness.gen from shapes/%s.py -- do not edit.
// Shape: %s (primitive under test: %s)
// Sweep: %s = %s
`default_nettype none

%s
module %s (
    input  wire clk,
    input  wire rst_n,
    input  wire din,
    output wire dout
);

%s
endmodule

`default_nettype wire
""" % (spec.name, spec.name, spec.primitive, spec.sweep_axis, sweep_value,
       _blackbox(pmap), spec.top_module, "".join(body)))


# --------------------------------------------------------------------------
# Placement and scope
# --------------------------------------------------------------------------
def ins_loc():
    """`{instance: site}` -- the PLL and the eight pinned port flops.

    Every site here is a spelling **both** `gw_sh` and nextpnr's `.cst` reader
    resolve (`gen.OPEN_FLOW_INS_LOC_FORMS`), so the two flows are handed the
    identical placement and `E1` is an assertion about the device rather than
    about one flow's placer.
    """
    row, col = FLOP_TILE
    out = {"u_pll": PLL_SITE}
    for instance, _port, cls, half in PINNED_DRIVERS + PINNED_CAPTURES:
        out[instance] = "R%dC%d[%d][%s]" % (row + 1, col + 1, cls, half)
    return out


def scope_tiles():
    """`(x, y)` tiles the `E0`/`E1` comparison is restricted to (`D32`).

    The block's own band and the `PLL_R[0]` site.  The PLL is in scope because
    `PLL_R[0].CLKOUT1 -> CORE_CLK` is part of what this row has to prove
    (`spec-primitives.md` §5), not context.

    Two tile sets are deliberately **out** of scope, both on measurement:

    * the 216 `ae350_config` tiles -- ordinary fabric tiles that also carry
      the block's interface band.  The vendor fills them with the design's own
      LUTs and flops, so comparing them at `E0` compares free placement, which
      `D32` excludes by definition (MEASURED, `evidence/ae350/e1-138c.md`: including them turns
      0 in-scope cell differences into 1 515).  Their bits are covered by the
      raw residual of §5.1b, which is where a configuration difference
      belongs.
    * the pinned-flop tile -- context in the sense of `F6`, exactly as the
      `smoke` shape's three context stages are.  It is where `E1` gets its
      `INS_LOC` evidence, and it also carries the one thing the two flows
      spell differently: GowinSynthesis realises a bare `DFF` primitive as the
      `DFFR` mode with `LSR` tied to `VCC`, yosys and nextpnr as plain `DFF`
      (MEASURED, `evidence/ae350/e1-138c.md`: 16 attribute items over the 8 flops).  That is the
      two synthesisers' flop decomposition (`S6`, `D32`, §5.1d), a property of
      neither the AE350 nor this shape, and §5.3 forbids masking it.
    """
    tiles = [(col, BAND_ROW) for col in BAND_COLS]
    tiles += [(PLL_ANCHOR[1] + i, PLL_ANCHOR[0]) for i in range(3)]
    seen, out = set(), []
    for tile in tiles:
        if tile not in seen:
            seen.add(tile)
            out.append(tile)
    return out


SPEC = ShapeSpec(
    name="ae350_soc",
    primitive="AE350_SOC",
    sweep_axis="none",
    sweep_values=[None],
    baseline_value=None,
    pins={
        "clk": PinSpec(loc="AA9", bank=5, drive=None, direction="input"),
        "rst_n": PinSpec(loc="AA10", bank=5, pull_mode="UP", drive=None,
                         direction="input"),
        "din": PinSpec(loc="AA11", bank=5, pull_mode="UP", drive=None,
                       direction="input"),
        "dout": PinSpec(loc="P20", bank=4, direction="output"),
    },
    bank_vccio={4: "3.3", 5: "3.3"},
    scope=ScopeSpec(tiles=scope_tiles()),
    rtl=rtl,
    ins_loc=ins_loc(),
    clocks={"clk": 20.0},
    # `-use_cpu_as_gpio 1` is already in the fixed Tcl header (`oracle.py`);
    # the AE350's DK-board JTAG also lands on the SSPI and MSPI config pins.
    extra_gwsh_options=["-use_sspi_as_gpio 1", "-use_mspi_as_gpio 1"],
    extra_pack_flags=["--sspi_as_gpio", "--mspi_as_gpio"],
    # `gowin_pack.get_PINCFG_fuses` raises when nextpnr and the packer
    # disagree about a dual-purpose pin, so the SSPI setting is given to both.
    # `mspi_as_gpio` and `cpu_as_gpio` are packer-only flags: nextpnr's gowin
    # uarch declares `sspi_as_gpio` and `i2c_as_gpio` and nothing else
    # (`gowin.cc:145-146`), and passing it an option it does not declare is a
    # hard error, not a warning.
    extra_nextpnr_vopts=["sspi_as_gpio"],
)
