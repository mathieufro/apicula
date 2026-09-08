"""`io_ser_b` -- an `OSER4` on the **B** half of a pad pair (`P3.F3`).

`io_ser` measures the output-serialiser family on `AA9`, an `A`-half ball, for
a reason that is now retracted (see `io_basic_b` and
`$OTC/evidence/oddr-iddr/summary.md`).  This shape moves the serialiser alone
onto `AB17` (`IOB80B`, cell `(108,79)`, aux cell `(108,80)`) and changes
nothing else, so a difference between the two rows is the half and not the
design.

One sweep point, `oser4-default`: `OSER4` is the RGMII TX gearbox and the
width whose parameters `io_ser` already swept on the `A` half, so the question
this run adds is exactly "does the `B` column configure", not "does a second
width behave".
"""
from ._io_base import GEARBOX_CLKDIV_INS_LOC, GEARBOX_DIV_MODE
from .io_ser import (DIN_EVEN_BALL, DIN_ODD_BALL, FCLK_BALL, POINTS,
                     RESETN_BALL, RESET_BALL, IoSerShape, _ACK_CLK)

#: The pad under test: the `B` half of the pair whose `A` half `io_basic`
#: drives, chosen because it is the ball the retracted "A half only"
#: conclusion was drawn on.
OSER_B_BALL = "AB17"       # IOB80B, cell (108,79) B half, aux cell (108,80)

#: The `B` half's own cell **and** the aux cell its IOLOGIC fuses live in.
SCOPE_TILES = ((79, 108), (80, 108))

BASELINE = "oser4-default"


class IoSerBShape(IoSerShape):
    """`io_ser`'s `OSER4` point, moved to the `B` half of a pad pair."""

    name = "io_ser_b"
    primitive = "OSER4 (B half)"
    sweep_values = [BASELINE]
    baseline_value = BASELINE
    ports = {
        "fclk": (FCLK_BALL, "input"),
        "resetn": (RESETN_BALL, "input", {"pull_mode": "UP"}),
        "rst": (RESET_BALL, "input", {"pull_mode": "DOWN"}),
        "din_even": (DIN_EVEN_BALL, "input"),
        "din_odd": (DIN_ODD_BALL, "input"),
        "dout": (OSER_B_BALL, "output"),
    }
    clocks = {"fclk": 8.0}
    config_role_acks = {FCLK_BALL: _ACK_CLK}
    scope_tiles = SCOPE_TILES
    ins_loc = {"pclk_div": GEARBOX_CLKDIV_INS_LOC}


#: The one point this shape carries must be one `io_ser` knows, or the two
#: rows would not be comparable.
assert BASELINE in POINTS
assert POINTS[BASELINE][0] in GEARBOX_DIV_MODE

SPEC = IoSerBShape().spec()
