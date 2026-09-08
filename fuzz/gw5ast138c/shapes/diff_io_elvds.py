"""`diff_io_elvds` -- the ELVDS half of the differential sweep (`P3.T25`).

The same shape, pads and RTL as `diff_io`; only the swept values differ, so
the ELVDS row can be batched on its own without re-spending the TLVDS runs
`P3.T23` already paid for (`harness.__main__`'s `--sweep-points` takes a
count from the front of the list, not a subset).

`ELVDS_IBUF` is absent because UG304E documents none -- the input side of the
E family is `ELVDS_IOBUF` (`spec-primitives.md` sec 2).

The VCCIO axis is **one level, measured, not chosen**: every ball the board
brings out on a bank a Phase-3 shape may claim is 3.3 V
(`_io_base.SAFE_PINS` / `VENDOR_VCCIO`), and the 1.5 V / `SSTL15D` point
needs bank 6, which shape identity forbids here (`D54`).  The vendor's
ELVDS/VCCIO matrix is therefore *recorded* from the runs, never asserted, and
the 1.5 V point is carried as the named deferred point of `SA-P3-1`.
"""
from .diff_io import DiffIoShape

#: The ELVDS points, in the order the batch builds them.
POINTS = ("elvds-obuf", "elvds-tbuf", "elvds-iobuf")

BASELINE = "elvds-obuf"


class ElvdsIoShape(DiffIoShape):
    """`ELVDS_OBUF` / `ELVDS_TBUF` / `ELVDS_IOBUF`, one per run."""

    name = "diff_io_elvds"
    # The `spec-primitives.md` row id (`tools/check_evidence.py`).
    primitive = "ELVDS_IBUF / OBUF / TBUF / IOBUF"
    sweep_values = list(POINTS)
    baseline_value = BASELINE


SPEC = ElvdsIoShape().spec()
