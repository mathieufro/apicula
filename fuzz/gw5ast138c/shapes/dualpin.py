"""`dualpin` -- one dual-purpose-pin option at a time (`P2.T28`).

The GW5AST-138C shares eight of its configuration ports with fabric I/O.  A
build hands a port to the fabric by asking for it in **two** namespaces that
must never be confused (`F34`):

* the vendor's Tcl, `set_option -use_<opt>_as_gpio 1`;
* `gowin_pack`'s command line, `--<opt>_as_gpio`.

Two of them, `sspi` and `i2c`, are also declared to `nextpnr-himbaechel` as
`--vopt <opt>_as_gpio`, because `gowin_pack` cross-checks the packer flag
against the placed netlist and raises when the two disagree.

This shape is the vehicle that measures what each option costs in fuses.  The
*design* is constant across all ten runs; only the option set moves, so every
bit that differs between a point and the baseline is attributable to that
option and nothing else.

The vehicle is `clocking_clkdiv`'s, not a bare flop, and that is a measured
choice.  A trivial `input -> DFF -> LED` design was tried first and cannot
reach `E1` for two independent reasons, both observed on the vendor's own
reports (run `p2t29-dualpin-dualpin-0000`):

* its `.tr` carries no `R<r>C<c>[cls][half]` column at all -- the vendor emits
  those only for real register-to-register paths, and this design has none --
  so the vendor's realised CLS placement is unreadable and `level_e1` is blind
  even though `run.vo` names `dut_dff`;
* the one tile such a design could put in scope is the flop's, and a bare
  `DFF` is `DFFRE` to GowinSynthesis and `DFF` to yosys, so that tile diffs on
  the synthesisers' decomposition at `E0` before the sweep says anything.

A `CLKDIV` has neither problem: it is a **bitstream-addressed** bel, so `E1`
is carried by the vendor's own decoded bitstream rather than by a text report
(`equiv.level_e1_bitstream`), and the scope is the HCLK block tile, where no
flop decomposition lives.  The ring counter is context and is not compared --
deliberately a ring and not an adder, because the `c1` decode check unpacks
with `noalu=True`.

**Which side of the mask this shape sits on.**  It is a configuration shape,
not an I/O shape: the swept parameter is a chip-level configuration attribute,
and the three pins are context held fixed.  `dontcare.mask`'s IO-default entry
is therefore left exactly as it is -- masking anything here would erase the
very bits the sweep exists to find.

Ten harness runs: the all-off baseline, then the nine sweep points -- each of
the eight options alone, then the `{sspi, mspi, cpu}` triple a real AE350
design needs (step (4) of the `AE350_SOC` recipe).  The triple is measured as
a point of its own because superposition of three independent option sets is a
claim, not an assumption.

Pins are in banks 4 and 5 -- never 6 or 7 (`D20c`, `D54`, `F73`/PR #423) -- and
are the package locations `shapes/smoke.py` already ran through the vendor
without tripping the config-role refusal.
"""
from . import PinSpec, ScopeSpec, ShapeSpec

#: Every option this device shares between configuration and fabric, in the
#: order `gowin_pack.CliArgs` declares them.  `mode` is deliberately absent:
#: the vendor accepts `-use_mode_as_gpio`, apicula defines no flag for it, and
#: this sweep measures only what both flows can express.
OPTIONS = ("jtag", "sspi", "mspi", "ready", "done", "reconfign", "cpu", "i2c")

#: The options a bare AE350 design hands to the fabric (`P2.T20`, step (4) of
#: the `AE350_SOC` recipe).
AE350_TRIPLE = ("sspi", "mspi", "cpu")

#: The all-off point every sweep point is diffed against.
BASELINE = "none"

#: The nine sweep points, in run order: the eight singles, then the triple.
SWEEP_POINTS = list(OPTIONS) + ["ae350_triple"]

#: The two options `nextpnr-himbaechel` also has to be told about, because
#: `gowin_pack` refuses a packer flag the placed netlist does not corroborate.
NEXTPNR_KNOWN = ("sspi", "i2c")

#: MEASURED (`P2.T29`): does `CPU_AS_GPIO_2` (`attrids` handle 37) move a bit
#: on this device?  `gowin_pack.GW5AST_138C.get_pins_attr_vals` emits the
#: attribute if and only if this is true, and `tests/test_dualpin_138c.py`
#: asserts the two agree.
CPU_AS_GPIO_2_SETS_A_BIT = False


def options_of(sweep_value):
    """The options turned on at one sweep point, as a tuple of bare names."""
    if sweep_value in (None, BASELINE):
        return ()
    if sweep_value == "ae350_triple":
        return AE350_TRIPLE
    if sweep_value in OPTIONS:
        return (sweep_value,)
    raise ValueError(f"unknown dualpin sweep point: {sweep_value!r}")


def gwsh_options(spec, sweep_value=None):
    """The vendor namespace: `-use_<opt>_as_gpio 1`, never `--<opt>_as_gpio`."""
    return [f"-use_{opt}_as_gpio 1" for opt in options_of(sweep_value)]


def pack_flags(spec, sweep_value=None):
    """The packer namespace: `--<opt>_as_gpio`, never `-use_...`."""
    return [f"--{opt}_as_gpio" for opt in options_of(sweep_value)]


def nextpnr_vopts(spec, sweep_value=None):
    """The `--vopt` names, for the two options nextpnr knows (bare, no dashes)."""
    return [f"{opt}_as_gpio" for opt in options_of(sweep_value)
            if opt in NEXTPNR_KNOWN]


#: HCLK block 5 of the 138C (`shapes/clocking_clkdiv.py`, `P1.T04`).
BLOCK5_XY = (117, 108)
INS_LOC_INDEX = 4
LANE = 0

#: The `CLKDIV` operating point held fixed across the sweep: this shape sweeps
#: the dual-purpose options, never the divider.
DIV_MODE = "2"

RTL = """\
// Generated by fuzz.gw5ast138c.harness.gen from shapes/dualpin.py -- do not edit.
// Shape: {name} (primitive under test: {primitive})
// Sweep: {sweep_axis} = {sweep_value}  (options on: {options})
`default_nettype none

module {top_module} (
    input  wire clk,
    input  wire reset,
    output wire [3:0] led
);

    wire div_clk;

    // The primitive under test.  It is here to carry E1, not to be swept:
    // a CLKDIV is addressed in the bitstream, so the vendor's own decoded
    // placement answers "is it where we put it" with no text report.
    (* BEL = "X{bx}Y{by}/CLKDIV_{lane}" *) CLKDIV div0 (
        .HCLKIN (clk),
        .RESETN (reset),
        .CALIB  (1'b0),
        .CLKOUT (div_clk)
    );
    defparam div0.DIV_MODE = "{div_mode}";

    // Context, NOT compared: the ring counter exists so CLKOUT has to leave
    // the block on the clock network.  A ring and not an adder -- an adder
    // packs into ALU bels the c1 decode check unpacks with noalu=True.
    reg [3:0] ring;
    always @(posedge div_clk)
        ring <= {{ring[2:0], ~ring[3]}};

    assign led = ring;

endmodule

`default_nettype wire
"""


def rtl(spec, sweep_value=None):
    """Render this shape's Verilog for one sweep point."""
    return RTL.format(
        name=spec.name,
        primitive=spec.primitive,
        sweep_axis=spec.sweep_axis,
        sweep_value=sweep_value if sweep_value is not None else spec.baseline_value,
        options=",".join(options_of(sweep_value)) or "-",
        top_module=spec.top_module,
        bx=BLOCK5_XY[0], by=BLOCK5_XY[1], lane=LANE, div_mode=DIV_MODE,
    )


#: The MEASURED evidence each config-role pin exemption rests on
#: (`shapes/clocking_clkdiv.py`, `P1.T08d`).
_ACK_CLK = ("EMCCLK: 27 vendor runs on this device placed a CLKDIV with clk on "
            "V22 and gw_sh returned 0 every time (P1.T08d "
            "evidence/hclk/mux38-138c.md 3); it is the Tang Mega 138K board "
            "clock and examples/gw5a/tangmega138k.cst names it")
_ACK_RESET = ("SGCLKC_6: a dedicated global-clock input ball, not a "
              "configuration function; same 27 P1.T08d runs used it as reset")

SPEC = ShapeSpec(
    name="dualpin",
    primitive="CLKDIV",
    sweep_axis="dual_purpose_option",
    sweep_values=[BASELINE] + SWEEP_POINTS,
    baseline_value=BASELINE,
    pins={
        "clk": PinSpec(loc="V22", bank=4, drive=None, direction="input",
                       config_role_ack=_ACK_CLK),
        "reset": PinSpec(loc="Y12", bank=5, pull_mode="UP", drive=None,
                         direction="input", config_role_ack=_ACK_RESET),
        "led[0]": PinSpec(loc="P20", bank=4, direction="output"),
        "led[1]": PinSpec(loc="Y17", bank=5, direction="output"),
        "led[2]": PinSpec(loc="W14", bank=5, direction="output"),
        "led[3]": PinSpec(loc="Y16", bank=5, direction="output"),
    },
    bank_vccio={4: "3.3", 5: "3.3"},
    scope=ScopeSpec(tiles=[list(BLOCK5_XY)]),
    rtl=rtl,
    ins_loc={"div0": "BOTTOMSIDE[%d]" % INS_LOC_INDEX},
    clocks={"clk": 20.0},
    extra_gwsh_options=gwsh_options,
    extra_pack_flags=pack_flags,
    extra_nextpnr_vopts=nextpnr_vopts,
)
