"""`io_basic` -- the `ODDR`/`IDDR` sweep on the GW5AST-138C (`P3.T11`/`P3.T12`).

One `ODDR` on an output ball and one `IDDR` on an input ball, both clocked
from the board clock on `V22`, sweeping one attribute per run over the two
primitives' whole documented parameter sets (`cells_sim.v:856` `IDDR(D, CLK,
Q0, Q1)` with `Q0_INIT`/`Q1_INIT`, `:898` `ODDR(D0, D1, TX, CLK, Q0, Q1)` with
`TXCLK_POL`/`INIT`).  The baseline is the same design at the documented
defaults, never an empty design, so a moved fuse is the attribute's.

The two data balls are **bank 5** and the clock ball defaults to the board
oscillator in bank 4, so the design crosses a bank boundary on purpose: an
`FCLK` that reaches the IOLOGIC of a ball in another bank than its clock's is
the property that makes the `P3.T06` bank -> HCLK-block table useful at all,
and it is what `P3.T07` measures over `CLOCK_CANDIDATES`.

The design keeps a fabric flop on each side so the IOLOGIC has a real
producer and consumer -- an unconnected `IDDR` output is optimised away and
the vendor then realises no IOLOGIC at all.

The clock ball is a **constructor argument** (`P3.T07`).  `SPEC` -- the object
`gen.load_shape` returns, and the only thing the batch driver can reach -- is
still the board clock on `V22`, so the `P3.T11`/`P3.T12` attribute sweep is
unchanged.  The pin sweep is a second axis over the same shape:
`IoBasicShape(clk_ball="V19").spec()` builds the identical `IDDR` design with
its `CLK` on another ball, and `CLOCK_CANDIDATES` is the twelve-ball set
`P3.T07` measures.  It is a constructor argument rather than a sweep value
because `ShapeSpec.pins` is a plain dict rendered once per shape -- `gen.py` is
Phase 0's and frozen, so a per-sweep-point pin is not something a shape can
ask for -- and every per-pin spec still goes through `assert_envelope` and
`gen.assert_cst_defaults` exactly as `SPEC` does.
"""
from ._io_base import IoShape

#: `(primitive, defparams)` per sweep point.  One axis moves per run
#: (`F12`), which is what lets `attribute.py` attribute a moved fuse.
POINTS = {
    "oddr-default": ("ODDR", {}),
    "oddr-txclk-pol": ("ODDR", {"TXCLK_POL": "1"}),
    "oddr-init": ("ODDR", {"INIT": "1"}),
    "iddr-default": ("IDDR", {}),
    "iddr-q0-init": ("IDDR", {"Q0_INIT": "1'b1"}),
    "iddr-q1-init": ("IDDR", {"Q1_INIT": "1'b1"}),
}

BASELINE = "oddr-default"

#: The clock balls `P3.T07` sweeps for HCLK reachability, and why each is in
#: the set.  Every one is in `_io_base.SAFE_PINS`; the four banks the board
#: brings out at 3.3 V are all represented, and within each bank the balls
#: whose vendor `CFG` names an `SGCLK`/`MGCLK` role come first, so a bank
#: whose dedicated clock ball reaches `FCLK` and whose ordinary balls do not
#: is distinguishable from one where every ball reaches it.
#:
#: Blocks 0 and 2 cannot appear here at all: the `P3.T06` table reaches them
#: only from banks 7 and 6, which are the DDR3 banks, and no Phase-3 shape
#: places a pin there (`D20c`, `D54`).  That is a stated limit of this sweep,
#: not an omission -- see `$OTC/evidence/pin-to-hclk/summary.md`.
CLOCK_CANDIDATES = (
    # ball, bank, vendor CFG clock role or "" for an ordinary ball
    ("V22", 4, "EMCCLK"),        # the board oscillator, examples' `clk`
    ("V19", 4, "SGCLKC_4"),      # dedicated single-ended global clock ball
    ("W20", 4, "MGCLKC_5"),      # dedicated multi-purpose global clock ball
    ("P20", 4, ""),              # ordinary bank-4 ball
    ("N15", 4, ""),              # ordinary bank-4 ball
    ("F20", 2, ""),              # RGMII_GTXCLK -- a clock by board role only
    ("D21", 2, ""),              # ordinary bank-2 ball
    ("F21", 2, ""),              # ordinary bank-2 ball
    ("Y17", 5, ""),              # ordinary bank-5 ball
    ("W14", 5, ""),              # ordinary bank-5 ball
    ("AA9", 5, ""),              # ordinary bank-5 ball
    ("G15", 3, ""),              # ordinary bank-3 ball (HDMI pair, single-ended here)
)

#: The data balls the sweep keeps fixed. Both are bank 5 and neither is a
#: candidate, so no sweep point ever has to move them out of its own way.
DATA_IN_BALL = "AA15"
DATA_OUT_BALL = "AB16"

#: The two tiles the `E0`/`E1` comparison is restricted to: the cells the two
#: data balls sit in, `(x, y)` as `P3.T06`'s measured pin table gives them
#: (`$OTC/evidence/iologic/pin-hclk-138c.json`: `AA15` = `IOB83A` at column
#: 82, `AB16` = `IOB80A` at column 79, both on row 108).
#:
#: An IOLOGIC is only ever realised in its own pad's cell, so the tile under
#: test is fixed by the pin constraint and is known before the run -- it is
#: not a placement the sweep discovers.  A shape that named no scope would
#: compare **nothing**: `equiv.in_scope` reads an empty tile list as an empty
#: set, and the whole-die alternative is not available either, because the
#: vendor's bitstream configures every DFF on the die (138 576 decoded cells
#: against the open flow's 384, MEASURED here).
DATA_TILES = ((79, 108), (82, 108))

#: The MEASURED evidence the `V22` config-role exemption rests on.
_ACK_CLK = ("EMCCLK: 27 vendor runs on this device placed a design with clk "
            "on V22 and gw_sh returned 0 every time (P1.T08d, "
            "$OTC/evidence/hclk/mux38-138c.md 3); it is the Tang Mega 138K "
            "board clock and examples/gw5a/tangmega138k.cst names it")

_ODDR_RTL = """\
    ODDR dut (
        .D0  (d0),
        .D1  (d1),
        .TX  (1'b0),
        .CLK (clk),
        .Q0  (q0),
        .Q1  ()
    );
{defparams}\
    assign dout = q0;
    always @(posedge clk) begin
        d0 <= din_r;
        d1 <= ~din_r;
    end
"""

# The deserialiser's D comes straight off the pad: GowinSynthesis refuses a
# fabric flop between the two -- `ERROR (CK0013) : Instance 'dut' is not
# connected to buffer or IODELAY by wire 'din_r'` (measured, P3.T07) -- because
# an input gearbox is only realisable in the IOLOGIC of its own pad.  The
# output side keeps its fabric flop, which is what gives Q0/Q1 a consumer.
_IDDR_RTL = """\
    IDDR dut (
        .D   (din),
        .CLK (clk),
        .Q0  (q0),
        .Q1  (q1)
    );
{defparams}\
    always @(posedge clk)
        dout_r <= q0 ^ q1;
    assign dout = dout_r;
"""

#: The three balls the HCLK probe needs beside its clocks.  All bank 5, none
#: of them a `CLOCK_CANDIDATES` entry, so no sweep point has to move them out
#: of its own way.  `AB13` is `Key_in[0]` and is pulled up, as `io_des` does.
RESET_BALL = "AB13"
CEN_BALL = "Y13"

#: `CLKDIV.DIV_MODE` per clock index of the probe.  Distinct on purpose: the
#: divider fuse is a one-hot in the lane's own row (`P1.T14`), so the decoded
#: `DIV_MODE` of a `CLKDIV_` cell says **which clock** of the design landed on
#: that block and lane.  Without it a design carrying several clocks would
#: name the blocks it used and not which pin reached each.
PROBE_DIV_MODES = ("2", "4", "5", "8")

#: `P3.T07`'s probe design, and why it is not the plain `IDDR` above.
#:
#: MEASURED, in this order, each on the vendor:
#:
#: 1. The plain `IDDR` design places, routes and returns 0, and the vendor
#:    puts the clock on an **ordinary global** -- the only clock pip at the
#:    IOLOGIC tile is `CLK0 <= GB10` and **zero** HCLK bels are configured
#:    anywhere on the die.  A pin driving an `IDDR` therefore proves nothing
#:    about the HCLK network.
#: 2. Adding an unpinned `CLKDIV` on the same pin does not change that:
#:    `WARN (PR1014) Generic routing resource will be used to clock signal
#:    'clk_d'`, still no HCLK bel.  `HCLKIN` alone does not force the entry.
#: 3. `DHCE` does.  `DHCE.CLKOUT` **is** an HCLK, so a `DHCE` between the pad
#:    and the divider makes the clock enter the network, and the entry
#:    multiplexer that lets it in is fuse-backed and names its block and lane
#:    (`HCLK_MUX_BETA<block><lane>`, `P1.T26`/`P1.T27`).
#: 4. `DHCE.CLKOUT` may not drive an `IDDR`: `ERROR (CK2060) The connection
#:    between instance 'gate0' and instance 'dut' is incorrect`.  It may drive
#:    an `IDES4`, whose `FCLK` is a declared IOLOGIC fast-clock port -- which
#:    is why the probe's IOLOGIC is an `IDES4` and not the `IDDR` of `POINTS`.
#:
#: Nothing in the probe is pinned unless the caller passes `ins_loc`: **which**
#: block and lane the vendor picks is the measurement.  Several clocks may be
#: swept in one design -- each gets its own `DHCE`/`CLKDIV` pair and its own
#: `DIV_MODE` out of `PROBE_DIV_MODES`, so the decode can tell them apart.
_PROBE_HEAD = """\
// Generated by fuzz.gw5ast138c.harness.gen from shapes/io_basic.py -- do not edit.
// Shape: io_basic (primitive under test: IDES4, pin -> HCLK -> FCLK probe)
// Sweep: {axis} = {point}
// Clock balls, in DIV_MODE order: {ball_list}
`default_nettype none

module {top} (
{clk_ports}    input  wire resetn,
    input  wire cen,
    input  wire din,
    output wire dout
);

    wire [{msb}:0] hclk, pclk;
    wire [3:0] word;
    reg  parity;
    reg  [{msb}:0] ring;

"""

_PROBE_LANE = """\
    // clock {i}: ball {ball}
    DHCE gate{i} (
        .CLKIN  (clk{i}),
        .CEN    (cen),
        .CLKOUT (hclk[{i}])
    );

    CLKDIV div{i} (
        .HCLKIN (hclk[{i}]),
        .RESETN (resetn),
        .CALIB  (1'b0),
        .CLKOUT (pclk[{i}])
    );
    defparam div{i}.DIV_MODE = "{div_mode}";

    // The divided clock has to reach fabric or the divider is optimised away
    // and the run measures nothing.
    always @(posedge pclk[{i}])
        ring[{i}] <= ~ring[{i}];

"""

_PROBE_TAIL = """\
    // The IOLOGIC under test: its FCLK is clock 0's HCLK, which is the whole
    // claim -- a board pin, through the HCLK network, into an IOLOGIC's fast
    // clock.
    IDES4 dut (
        .Q3     (word[3]),
        .Q2     (word[2]),
        .Q1     (word[1]),
        .Q0     (word[0]),
        .FCLK   (hclk[0]),
        .PCLK   (pclk[0]),
        .RESET  (~resetn),
        .CALIB  (1'b0),
        .D      (din)
    );

    always @(posedge pclk[0])
        parity <= ^word;

    assign dout = parity ^ (^ring);

endmodule

`default_nettype wire
"""

_TEMPLATE = """\
// Generated by fuzz.gw5ast138c.harness.gen from shapes/io_basic.py -- do not edit.
// Shape: io_basic (primitive under test: {primitive})
// Sweep: {axis} = {point}
`default_nettype none

module {top} (
    input  wire clk,
    input  wire din,
    output wire dout
);

    wire q0, q1;
    reg  d0, d1;
    reg  din_r, dout_r;

    // Registered on both sides so the IOLOGIC has a real producer and
    // consumer; an unconnected gearbox output is optimised away and the
    // vendor then realises no IOLOGIC at all.
    always @(posedge clk)
        din_r <= din;

{body}
endmodule

`default_nettype wire
"""


class IoBasicShape(IoShape):
    """`ODDR` and `IDDR` on two bank-4 balls, clocked from the board clock."""

    name = "io_basic"
    primitive = "ODDR / IDDR"
    sweep_axis = "POINT"
    sweep_values = list(POINTS)
    baseline_value = BASELINE
    config_role_acks = {"V22": _ACK_CLK}

    def __init__(self, clk_ball="V22", hclk_probe=False, clk_balls=None,
                 ins_loc=None):
        """`clk_ball` is the package ball the `IDDR`/`ODDR` clock comes in on.

        The default is the board oscillator, which is what `SPEC` is built
        from, so `P3.T11`/`P3.T12`'s attribute sweep is untouched.

        `hclk_probe=True` selects `P3.T07`'s probe instead (see `_PROBE_HEAD`).
        The probe takes `clk_balls`, an ordered sequence of up to
        `len(PROBE_DIV_MODES)` balls carried in **one** design, each with its
        own `DHCE`/`CLKDIV` pair and its own `DIV_MODE`; `ins_loc` pins a
        divider by `INS_LOC` for the control runs that ask whether the block
        the vendor picks is a property of the pin or of the placer.
        """
        self.hclk_probe = hclk_probe
        self.clk_balls = tuple(clk_balls or (clk_ball,))
        self.clk_ball = self.clk_balls[0]
        self.ins_loc = dict(ins_loc or {})
        if not hclk_probe:
            # The attribute sweep's IOLOGIC is in one of the two data balls'
            # own cells and nowhere else; the probe's is placed by the placer
            # over a ball the caller passes, so it keeps the base class's
            # empty scope and is compared the way `P3.T07` compared it.
            self.scope_tiles = DATA_TILES
            self.ports = {
                "clk": (clk_ball, "input"),
                "din": (DATA_IN_BALL, "input"),
                "dout": (DATA_OUT_BALL, "output"),
            }
            return
        if len(self.clk_balls) > len(PROBE_DIV_MODES):
            raise ValueError(
                "the probe tells its clocks apart by DIV_MODE, so it carries "
                "at most %d of them (asked for %d)"
                % (len(PROBE_DIV_MODES), len(self.clk_balls)))
        if len(set(self.clk_balls)) != len(self.clk_balls):
            raise ValueError("a probe design claims each clock ball once")
        self.ports = {
            "clk%d" % i: (ball, "input")
            for i, ball in enumerate(self.clk_balls)
        }
        self.ports["resetn"] = (RESET_BALL, "input", {"pull_mode": "UP"})
        self.ports["cen"] = (CEN_BALL, "input")
        self.ports["din"] = (DATA_IN_BALL, "input")
        self.ports["dout"] = (DATA_OUT_BALL, "output")

    @property
    def clocks(self):
        """One `create_clock` per clock port, 50 MHz -- the board's own rate."""
        if not self.hclk_probe:
            return {"clk": 20.0}
        return {"clk%d" % i: 20.0 for i in range(len(self.clk_balls))}

    def _probe_rtl(self, sweep_value):
        clk_ports = "".join("    input  wire clk%d,\n" % i
                            for i in range(len(self.clk_balls)))
        msb = len(self.clk_balls) - 1
        body = "".join(
            _PROBE_LANE.format(i=i, ball=ball, div_mode=PROBE_DIV_MODES[i])
            for i, ball in enumerate(self.clk_balls))
        return (_PROBE_HEAD.format(
            axis=self.sweep_axis, point=sweep_value, top=self.top_module,
            ball_list=", ".join(self.clk_balls), clk_ports=clk_ports, msb=msb)
            + body + _PROBE_TAIL)

    def rtl(self, sweep_value):
        if self.hclk_probe:
            return self._probe_rtl(sweep_value)
        primitive, defparams = POINTS[sweep_value]
        rendered = "".join('    defparam dut.%s = %s;\n' % (key, value)
                           for key, value in sorted(defparams.items()))
        body = (_ODDR_RTL if primitive == "ODDR" else _IDDR_RTL).format(
            defparams=rendered)
        return _TEMPLATE.format(primitive=primitive, axis=self.sweep_axis,
                                point=sweep_value, top=self.top_module,
                                body=body)


SPEC = IoBasicShape().spec()
