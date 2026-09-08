"""`diff_io_vccio_probe` -- the vendor's ELVDS/VCCIO matrix (`P3.T25`).

**A measurement instrument, not a board design.**  Every other Phase-3 shape
declares `BANK_VCCIO=3.3` because that is what the Tang Mega 138K actually
powers its non-DDR banks at (`_io_base.VENDOR_VCCIO`).  This one declares
levels the board does **not** run, on purpose, because the question it answers
can only be put to the vendor: `P3.T25` must *record* the ELVDS/VCCIO matrix
from the oracle rather than assert it, and the 3.3 V sweep came back
`refused` on all three ELVDS types with

    ERROR (CT1108): Illegal port attribute value specified 'BANK_VCCIO = 3.3'

which on its own cannot separate "ELVDS is illegal on this die" from "ELVDS
is illegal at 3.3 V".

What keeps that safe is what the shape is *for*.  It is built to read an
acceptance out of `gw_sh` and nothing else: no bitstream it produces is ever
loaded (no hardware before Phase 9), it stays on bank 3 -- never 6 or 7
(`D20c`, `D54`) -- and its rows go to `evidence/elvds/vccio-matrix.tsv`,
**excluded from the row that closes**, which is carried by the
`diff_io_elvds` sweep at the board's own level.  The opt-in is this module by
name; no other shape can reach a non-board VCCIO.

There is no module-level `SPEC`: a probe is one design per level, and
`spec_for(vccio)` is the only way to get one.
"""
from dataclasses import replace

from .diff_io import DiffIoShape

#: The levels asked about.  2.5 V is `LVDS25E`'s nominal rail -- apicula's
#: default `IO_TYPE` for an ELVDS buffer (`gowin_pack.py:1658-1660`) -- and
#: 1.8 V is the next level down, so the two together say whether the vendor
#: gates ELVDS on one level or on a ceiling.
LEVELS = ("2.5", "1.8")

#: The buffer the probe carries.  One type is enough: the 3.3 V sweep refused
#: all three ELVDS types with the same words, so the axis under test is the
#: rail, not the type.
POINT = "elvds-obuf"


class ElvdsVccioProbeShape(DiffIoShape):
    """One `ELVDS_OBUF` at one VCCIO level the board does not run."""

    name = "diff_io_vccio_probe"
    primitive = "ELVDS_OBUF"
    sweep_axis = "BANK_VCCIO"
    sweep_values = list(LEVELS)
    baseline_value = LEVELS[0]

    def rtl(self, sweep_value):
        # The design never varies: the swept axis is the constraint file.
        return super().rtl(POINT)


#: The bank the differential pair sits in -- the only one the probe moves.
#: The `LVCMOS33` pins of banks 4 and 5 stay at 3.3 V: moving their rail too
#: would make *them* illegal and the vendor's refusal would no longer be
#: about ELVDS.
PROBED_BANK = 3


def spec_for(vccio):
    """The `ShapeSpec` for one probed rail.

    Built by validating the shape at the board's own level and then replacing
    `bank_vccio[PROBED_BANK]`, so the envelope check still runs over every
    pin, every ball and both DDR-bank rules -- only the one field the probe
    exists to vary is set outside it.
    """
    if vccio not in LEVELS:
        raise ValueError(f"{vccio!r} is not a probed level ({', '.join(LEVELS)})")
    base = ElvdsVccioProbeShape().spec()
    banks = dict(base.bank_vccio)
    banks[PROBED_BANK] = vccio
    return replace(base, bank_vccio=banks)
