"""`diff_io_iobuf` -- the single `TLVDS_IOBUF` adjudication point (`P3.T24`).

`chipdb.fse_create_diff_types` removes `TLVDS_IOBUF` for every device outside
`{GW5A-25A, GW2A-18, GW2A-18C, GW1N-4}` with no recorded rationale.  Whether
that removal is right on this die is a question only the oracle can answer,
so the type lives in a shape of its own rather than in `diff_io`'s sweep:
`diff_io` must stay free of it until the adjudication lands, and a one-point
shape is what lets the batch spend exactly one run on the question.
"""
from .diff_io import DiffIoShape

POINTS = ("tlvds-iobuf",)

BASELINE = "tlvds-iobuf"


class TlvdsIobufShape(DiffIoShape):
    """One `TLVDS_IOBUF` on the board's TMDS pair -- the adjudication design."""

    name = "diff_io_iobuf"
    primitive = "TLVDS_IOBUF"
    sweep_values = list(POINTS)
    baseline_value = BASELINE


SPEC = TlvdsIobufShape().spec()
