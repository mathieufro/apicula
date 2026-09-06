"""`clocking_pll` -- the GW5AST-138C `PLL` sweep shape shared by `P1.T23`/`T41`-`T43`.

The primitive is **`PLL`**, not `PLLA` (`D96`: this device has no `PLLA`; the
evidence slug stays `plla` for path stability only).

One hard `PLL` at a pinned site (`INS_LOC "dut_pll" PLL_{L,R,B}[n]`), `CLKIN`
driven from an IO pin, `CLKOUT0` driving a fabric register.  Exactly **one**
`#(...)` parameter differs between a sweep point and its axis baseline, so a
moved fuse is that parameter's fuse and nothing else.  The port list is
byte-identical across every point of every axis, so a moved bit can never be a
connectivity artefact.

Axis selector (`P1.T41`-`T43` reuse this file **unedited**)
----------------------------------------------------------
The batch CLI is frozen at exactly seven options (`F11`/`F29`,
`harness/__main__.py`), so the axis selector is the environment variable
`FUZZ_PLL_AXIS` -- the same mechanism `__main__.py` uses for its own
test-only overrides, and for the same reason.  It is a comma-separated list of
axis names from `AXES`; the default is batch A.

    FUZZ_PLL_AXIS=idiv,fbdiv   P1.T23  batch A   (this task, 20 runs)
    FUZZ_PLL_AXIS=odiv0,odiv1,mdiv   P1.T41  batch B (20 runs)
    FUZZ_PLL_AXIS=dyn          P1.T42  batch C
    FUZZ_PLL_AXIS=site         P1.T43  batch D

Operating points, and why they are not all `FCLKIN = 100 MHz`
-------------------------------------------------------------
Every point must satisfy, all at once (`P1.T20` five-tuple from DS1239E
Table 3-18, and the same table's `FPFDMIN`/`FPFDMAX`):

    Fpfd   = FCLKIN / IDIV   in [19, 81.25] MHz
    FVCO   = FCLKIN * FBDIV * MDIV / IDIV   in [650, 1300] MHz   (`S7`)
    CLKOUT = FVCO / ODIV                    in [5.079, 1000] MHz
    FCLKIN                                  <= 800 MHz  (`FINMAX`)

The VCO band is exactly a factor of **two** wide, so a one-parameter sweep of
a divider `D` can only cover `D in [n, 2n]` -- at most `n + 1` values.  For the
`IDIV` axis `Fpfd >= 19` then forces `FCLKIN >= 38 n`: nine `IDIV` points
(`n = 9`) are *impossible* below 342 MHz.  Hence the `IDIV` axis runs at
`FCLKIN = 400 MHz` (well inside `FINMAX` 800) and the `FBDIV` axis, which does
not move `Fpfd` at all, stays at the familiar 100 MHz.  Each axis carries its
own baseline, and a sweep point differs from **its own** baseline in exactly
one parameter.

Gray ordering (`spec-harness.md` §7)
------------------------------------
`sweep_order` Gray-codes only a sweep that is exactly `range(n)`; these axes
are integer *subsets*, so the ordering is done here: the axis values are
emitted in the order of the full Gray sequence restricted to the axis's legal
set, with the baseline emitted first as the reference `.fs`.  Adjacent points
therefore differ in one bit wherever the restriction leaves them adjacent.
"""
import os

from . import PinSpec, ScopeSpec, ShapeSpec

#: `$OTC/evidence/plla/sites-138c.json`: `(row, col)` anchor per `pll_idx`,
#: and the vendor `INS_LOC` macro that selects it (`P1.T19`, MEASURED).
#: `SITES[macro] = (anchor_row, anchor_col)`; the site's scope is the three
#: horizontally adjacent tiles starting at the anchor.
SITES = {
    "PLL_L[0]": (27, 1),
    "PLL_R[0]": (27, 177),
    "PLL_L[1]": (45, 0),
    "PLL_R[1]": (45, 178),
    "PLL_L[2]": (63, 0),
    "PLL_R[2]": (63, 178),
    "PLL_L[3]": (81, 1),
    "PLL_R[3]": (81, 177),
    "PLL_B[0]": (108, 28),
    "PLL_B[1]": (108, 32),
    "PLL_B[2]": (108, 146),
    "PLL_B[3]": (108, 150),
}

#: The site every axis but `site` pins its `PLL` to -- the one `P1.T22`
#: attributed its fuses at, so batch A's fuses are directly comparable with
#: `$OTC/evidence/plla/attrmap-138c.json`.
DEFAULT_SITE = "PLL_L[0]"


def scope_tiles(site):
    """The three `(x, y)` = `(col, row)` tiles of a site (`P1.T17` §3)."""
    row, col = SITES[site]
    return [(col + i, row) for i in range(3)]


#: Parameters every point carries, in this emission order, so the generated
#: Verilog is byte-stable.  An axis's operating point overrides some of them
#: and its swept parameter overrides exactly one more.
BASE_PARAMS = {
    "FCLKIN": '"100.0"',
    "IDIV_SEL": "2",
    "FBDIV_SEL": "2",
    "MDIV_SEL": "13",
    "ODIV0_SEL": "8",
    "ODIV1_SEL": "8",
    "CLKOUT0_EN": '"TRUE"',
    "CLKOUT1_EN": '"FALSE"',
    "CLKFB_SEL": '"INTERNAL"',
    "DYN_IDIV_SEL": '"FALSE"',
    "DYN_FBDIV_SEL": '"FALSE"',
    "DYN_ODIV0_SEL": '"FALSE"',
}
PARAM_ORDER = list(BASE_PARAMS)


class Axis:
    """One sweep axis: an operating point, a swept parameter and its values."""

    def __init__(self, name, param, values, baseline, operating_point,
                 site=DEFAULT_SITE):
        self.name = name                      # "IDIV", "FBDIV", ...
        self.param = param                    # "IDIV_SEL", ...
        self.values = list(values)
        self.baseline = baseline
        self.operating_point = dict(operating_point)
        self.site = site
        if baseline not in self.values:
            raise ValueError(f"{name}: baseline {baseline!r} not in values")

    def ordered(self):
        """Baseline first, then the remaining values in Gray order."""
        rest = [v for v in _gray_restricted(self.values) if v != self.baseline]
        return [self.baseline] + rest

    def params(self, value):
        parms = dict(BASE_PARAMS)
        parms.update(self.operating_point)
        parms[self.param] = str(value)
        return parms

    def fvco(self, value):
        """`FVCO` in MHz for one value of this axis -- the `S7` guard's input."""
        parms = self.params(value)
        fclkin = float(parms["FCLKIN"].strip('"'))
        return (fclkin * int(parms["FBDIV_SEL"]) * int(parms["MDIV_SEL"])
                / int(parms["IDIV_SEL"]))

    def fpfd(self, value):
        parms = self.params(value)
        return float(parms["FCLKIN"].strip('"')) / int(parms["IDIV_SEL"])

    def clkout0(self, value):
        return self.fvco(value) / int(self.params(value)["ODIV0_SEL"])


def _gray_restricted(values):
    """`values` in the order of the full Gray sequence restricted to them."""
    wanted = set(values)
    width = max(1, max(wanted).bit_length() + 1)
    out = []
    for i in range(1 << width):
        g = i ^ (i >> 1)
        if g in wanted:
            out.append(g)
            wanted.discard(g)
    return out + [v for v in values if v in wanted]


# ---------------------------------------------------------------- the axes
#: `IDIV` axis, `P1.T23`. `FCLKIN 400`, `FBDIV 2`, `MDIV 14`, `ODIV0 8`:
#: `FVCO = 11200/IDIV` -> 1244.4 .. 658.8 MHz over `IDIV 9..17`, `Fpfd`
#: 44.4 .. 23.5 MHz, `CLKOUT0` 155.6 .. 82.4 MHz. Nine points; see the module
#: docstring for why nine `IDIV` points cannot exist below `FCLKIN` 342 MHz.
AXIS_IDIV = Axis(
    "IDIV", "IDIV_SEL", range(9, 18), 13,
    {"FCLKIN": '"400.0"', "FBDIV_SEL": "2", "MDIV_SEL": "14", "ODIV0_SEL": "8"})

#: `FBDIV` axis, `P1.T23`. `FCLKIN 100`, `IDIV 4`, `MDIV 2`, `ODIV0 8`:
#: `Fpfd` fixed at 25 MHz, `FVCO = 50*FBDIV` -> 650 .. 1150 MHz over
#: `FBDIV 13..23`, `CLKOUT0` 81.25 .. 143.75 MHz. Eleven points.
AXIS_FBDIV = Axis(
    "FBDIV", "FBDIV_SEL", range(13, 24), 18,
    {"FCLKIN": '"100.0"', "IDIV_SEL": "4", "MDIV_SEL": "2", "ODIV0_SEL": "8"})

#: `ODIV0` axis, `P1.T41`.  `ODIV` divides `CLKOUT0` **after** the VCO, so it
#: moves neither `Fpfd` nor `FVCO`: the whole axis sits at one charge-pump
#: operating point, which is what makes it the clean single-attribute axis of
#: batch B.  `FCLKIN 100`, `IDIV 4`, `FBDIV 18`, `MDIV 2` -> `Fpfd` 25 MHz,
#: `FVCO` 900 MHz; `CLKOUT0 = 900/ODIV0` -> 900 .. 14.06 MHz over the seven
#: values, every one inside `[5.079, 1000]`.  The set mixes powers of two with
#: two odd values so a binary `A_ODIV0_SEL` field is exercised in both halves.
AXIS_ODIV0 = Axis(
    "ODIV0", "ODIV0_SEL", [1, 2, 3, 4, 8, 16, 64], 8,
    {"FCLKIN": '"100.0"', "IDIV_SEL": "4", "FBDIV_SEL": "18", "MDIV_SEL": "2",
     "ODIV0_SEL": "8"})

#: `ODIV1` axis, `P1.T41`.  Same operating point as `ODIV0`, plus
#: `CLKOUT1_EN "TRUE"`: with `CLKOUT1` disabled the vendor emits **no**
#: `A_ODIV1_SEL` fuses at all (MEASURED on batch A, whose `ODIV1_SEL 8` decodes
#: to no value in the `A_ODIV1_SEL` (115) field), so a disabled-output `ODIV1`
#: sweep would be twenty runs of nothing.  `CLKOUT1_EN` is part of this axis's
#: *operating point*, not its swept parameter, so a point still differs from
#: its own baseline in exactly one key.
AXIS_ODIV1 = Axis(
    "ODIV1", "ODIV1_SEL", [2, 4, 8, 16, 32, 64], 8,
    {"FCLKIN": '"100.0"', "IDIV_SEL": "4", "FBDIV_SEL": "18", "MDIV_SEL": "2",
     "ODIV0_SEL": "8", "CLKOUT1_EN": '"TRUE"'})

#: `MDIV` axis, `P1.T41`.  `MDIV` multiplies into the VCO exactly as `FBDIV`
#: does (`FVCO = FCLKIN * FBDIV * MDIV / IDIV`), so the axis is bounded by the
#: factor-of-two VCO band and by nothing else: `FCLKIN 100`, `IDIV 4`,
#: `FBDIV 1` -> `FVCO = 25 * MDIV`, legal for `MDIV` in `[26, 52]`.  Seven
#: values spread across that interval, baseline `36` (`FVCO` 900 MHz, the same
#: VCO frequency the two `ODIV` axes sit at, so the three axes of batch B share
#: one charge-pump operating point at their baselines).
AXIS_MDIV = Axis(
    "MDIV", "MDIV_SEL", [26, 30, 34, 36, 40, 46, 52], 36,
    {"FCLKIN": '"100.0"', "IDIV_SEL": "4", "FBDIV_SEL": "1", "MDIV_SEL": "36",
     "ODIV0_SEL": "8"})

AXES = {
    "idiv": AXIS_IDIV,
    "fbdiv": AXIS_FBDIV,
    "odiv0": AXIS_ODIV0,
    "odiv1": AXIS_ODIV1,
    "mdiv": AXIS_MDIV,
}

#: Batch A (`P1.T23`). `P1.T41`-`T43` set `FUZZ_PLL_AXIS` instead of editing.
DEFAULT_AXES = "idiv,fbdiv"
AXIS_ENV = "FUZZ_PLL_AXIS"


def _resolve_axes():
    """Read `$FUZZ_PLL_AXIS` once, at import time.

    Snapshotting is deliberate: `SPEC.sweep_values` is built here, so a later
    change to the environment would silently desynchronise the spec from
    `points()` and a batch's run ids from its sweep values.
    """
    raw = os.environ.get(AXIS_ENV, DEFAULT_AXES)
    names = [n.strip() for n in raw.split(",") if n.strip()]
    unknown = [n for n in names if n not in AXES]
    if unknown:
        raise ValueError(
            f"{AXIS_ENV}={raw!r}: unknown axis {unknown!r}; "
            f"known axes are {sorted(AXES)}")
    return [AXES[n] for n in names]


#: The axes of THIS import, fixed once (see `_resolve_axes`).
SELECTED_AXES = _resolve_axes()


def selected_axes():
    """The axes this invocation sweeps, in the order named."""
    return SELECTED_AXES


def points():
    """`{point_name: (axis, value)}` for the selected axes, in sweep order."""
    out = {}
    for axis in selected_axes():
        for value in axis.ordered():
            out[f"{axis.name.lower()}_{value:03d}"] = (axis, value)
    return out


def resolve(point_name):
    """`(axis, value)` for one point name."""
    table = points()
    if point_name not in table:
        raise ValueError(f"{point_name!r} is not a point of clocking_pll "
                         f"({AXIS_ENV}={os.environ.get(AXIS_ENV, DEFAULT_AXES)!r})")
    return table[point_name]


def sweep_record(point_name):
    """The evidence `sweep` map of one point: `{axis, <param>}`, two keys.

    A point differs from its axis baseline in **exactly one** key (the swept
    parameter), which is what `test_plla_sweep_batch_a_rows` asserts.
    """
    axis, value = resolve(point_name)
    return {"axis": axis.name, axis.param: value}


def is_baseline(point_name):
    axis, value = resolve(point_name)
    return value == axis.baseline


RTL = """\
// Generated by fuzz.gw5ast138c.harness.gen from shapes/{name}.py -- do not edit.
// Shape: {name} (primitive under test: {primitive})
// Sweep: {sweep_axis} = {sweep_value}  (axis {axis}, {param} = {value})
// Fpfd {fpfd:.4f} MHz, FVCO {fvco:.4f} MHz, CLKOUT0 {clkout0:.4f} MHz
`default_nettype none

module {top_module} (
    input  wire clk,
    input  wire rst_n,
    input  wire din,
    output wire dout
);

    wire pll_clkout0;
    wire pll_lock;

    // The primitive under test. The cell type is `PLL`, not `PLLA` (`D96`).
    // Only the #(...) block varies between points; the port list below is
    // identical in every point of every axis.
    PLL #(
{params}
    ) dut_pll (
        .CLKIN        (clk),
        .CLKFB        (1'b0),
        .RESET        (~rst_n),
        .PLLPWD       (1'b0),
        .RESET_I      (1'b0),
        .RESET_O      (1'b0),
        .FBDSEL       (6'b0),
        .IDSEL        (6'b0),
        .MDSEL        (7'b0),
        .MDSEL_FRAC   (3'b0),
        .ODSEL0       (7'b0), .ODSEL0_FRAC (3'b0),
        .ODSEL1       (7'b0), .ODSEL2 (7'b0), .ODSEL3 (7'b0),
        .ODSEL4       (7'b0), .ODSEL5 (7'b0), .ODSEL6 (7'b0),
        .DT0          (4'b0), .DT1 (4'b0), .DT2 (4'b0), .DT3 (4'b0),
        .ICPSEL       (6'b0),
        .LPFRES       (3'b0),
        .LPFCAP       (2'b0),
        .PSSEL        (3'b000),
        .PSDIR        (1'b0),
        .PSPULSE      (1'b0),
        .ENCLK0       (1'b1),
        .ENCLK1       (1'b0), .ENCLK2 (1'b0), .ENCLK3 (1'b0),
        .ENCLK4       (1'b0), .ENCLK5 (1'b0), .ENCLK6 (1'b0),
        .SSCPOL       (1'b0),
        .SSCON        (1'b0),
        .SSCMDSEL     (7'b0),
        .SSCMDSEL_FRAC(3'b0),
        .LOCK         (pll_lock),
        .CLKOUT0      (pll_clkout0),
        .CLKOUT1      (), .CLKOUT2 (), .CLKOUT3 (),
        .CLKOUT4      (), .CLKOUT5 (), .CLKOUT6 (),
        .CLKFBOUT     ()
    );

    // Context, NOT compared (F6): one fabric flop in the PLL's own clock
    // domain, so CLKOUT0 really has to reach the clock network and neither
    // CLKOUT0 nor LOCK can be optimised away.
    reg q;
    always @(posedge pll_clkout0)
        q <= din ^ pll_lock;

    assign dout = q;

endmodule

`default_nettype wire
"""


def rtl(spec, sweep_value=None):
    """Render this shape's Verilog for one sweep point."""
    point = sweep_value or SPEC.baseline_value
    axis, value = resolve(point)
    parms = axis.params(value)
    lines = [f"        .{a}({parms[a]})" for a in PARAM_ORDER]
    return RTL.format(
        name=spec.name,
        primitive=spec.primitive,
        sweep_axis=spec.sweep_axis,
        sweep_value=point,
        axis=axis.name,
        param=axis.param,
        value=value,
        fpfd=axis.fpfd(value),
        fvco=axis.fvco(value),
        clkout0=axis.clkout0(value),
        params=",\n".join(lines),
        top_module=spec.top_module,
    )


def site(sweep_value):
    """The `INS_LOC` site of one point -- the axis's site (`E1`)."""
    axis, _ = resolve(sweep_value or SPEC.baseline_value)
    return axis.site


def _sweep_values():
    return list(points())


def _baseline_value():
    return _sweep_values()[0]


def _scope():
    sites = {axis.site for axis in selected_axes()}
    tiles = []
    for one in sorted(sites):
        tiles.extend(scope_tiles(one))
    return ScopeSpec(tiles=tiles)


SPEC = ShapeSpec(
    name="clocking_pll",
    primitive="PLL",
    sweep_axis="pll_point",
    sweep_values=_sweep_values(),
    baseline_value=_baseline_value(),
    pins={
        "clk": PinSpec(loc="AA9", bank=5, drive=None, direction="input"),
        "rst_n": PinSpec(loc="AA10", bank=5, pull_mode="UP", drive=None, direction="input"),
        "din": PinSpec(loc="AA11", bank=5, pull_mode="UP", drive=None, direction="input"),
        "dout": PinSpec(loc="P20", bank=4, direction="output"),
    },
    bank_vccio={4: "3.3", 5: "3.3"},
    scope=_scope(),
    rtl=rtl,
    ins_loc={"dut_pll": site},
    clocks={"clk": 2.5},
)
