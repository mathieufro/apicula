"""`io_des_b` -- an `IDES4` on the **B** half of a pad pair (`P3.F3`).

`io_des` measures the input-deserialiser family on `AA9`, an `A`-half ball,
for the reason retracted in `$OTC/evidence/oddr-iddr/summary.md`.  This shape
moves the deserialiser's own pad alone onto `T15` (`IOB70B`, cell `(108,69)`,
aux cell `(108,70)`) and leaves the word balls, the clock and the resets where
`io_des` has them, so the only difference between the two rows is the half.

`T15` rather than the `AB17` the two output shapes use: `AB17` is one of
`io_des`'s own word balls, and a deserialiser whose input pad is also one of
its output pads is not a design.
"""
from ._io_base import GEARBOX_CLKDIV_INS_LOC
from .io_des import (FCLK_BALL, POINTS, RESETN_BALL, RESET_BALL, TAP_BALL,
                     WORD_BALLS, IoDesShape, _ACK_CLK)

#: The pad under test.
IDES_B_BALL = "T15"        # IOB70B, cell (108,69) B half, aux cell (108,70)

#: The `B` half's own cell **and** the aux cell its IOLOGIC fuses live in.
SCOPE_TILES = ((69, 108), (70, 108))

BASELINE = "ides4-reset-pad"


class IoDesBShape(IoDesShape):
    """`io_des`'s `IDES4` point, moved to the `B` half of a pad pair."""

    name = "io_des_b"
    #: The table row this shape's evidence joins to (`IDES4` on the `B`
    #: half); the half is carried in `sweep`, not in the row id.
    primitive = "IDES4 / IDES8 / IDES10"
    sweep_values = [BASELINE]
    baseline_value = BASELINE
    ports = dict(
        {
            "fclk": (FCLK_BALL, "input"),
            "resetn": (RESETN_BALL, "input", {"pull_mode": "UP"}),
            "rst": (RESET_BALL, "input", {"pull_mode": "DOWN"}),
            "din": (IDES_B_BALL, "input"),
        },
        **{"q%d" % i: (ball, "output")
           for i, ball in enumerate(WORD_BALLS)},
        tap=(TAP_BALL, "output"),
    )
    clocks = {"fclk": 8.0}
    config_role_acks = {FCLK_BALL: _ACK_CLK}
    scope_tiles = SCOPE_TILES
    ins_loc = {"pclk_div": GEARBOX_CLKDIV_INS_LOC}


#: The deserialiser's pad may not double as one of its word pads.
assert IDES_B_BALL not in WORD_BALLS
assert BASELINE in POINTS

SPEC = IoDesBShape().spec()
