"""The differential-IO rows of the GW5AST-138C (`P3.T23`, `P3.T24`, `P3.T25`).

Each test names one property of the evidence the three tasks produced, and
reads it from the committed rows rather than from anything the shapes claim.
"""
import json
import os
import re

import pytest

from fuzz.gw5ast138c.harness import gen
from fuzz.gw5ast138c.shapes import diff_io, diff_io_elvds, diff_io_iobuf

#: The `open-toolchain` checkout the evidence lives in (`C10`).  A tree
#: without it skips: these tests read landed evidence, they do not produce it.
OTC = os.environ.get(
    "OTC",
    os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                 "..", "open-toolchain"))
EVIDENCE = os.path.normpath(os.path.join(OTC, "evidence"))

#: Banks no Phase-3 pin may sit in (`D20c`, `D54`).
DDR_BANKS = (6, 7)

#: Row counts, stated once.  They are the axes the vendor actually exposes,
#: not the blueprint's estimates: a differential pad carries no `DRIVE`, so
#: TLVDS is three points and not six, and the board runs one VCCIO level
#: outside banks 6/7, so ELVDS is three points and not ten.
TLVDS_ROWS = 3
ELVDS_ROWS = 3


def _rows(slug):
    path = os.path.join(EVIDENCE, slug, "runs.jsonl")
    if not os.path.isfile(path):
        pytest.skip(f"no evidence at {path}")
    with open(path) as fh:
        return [json.loads(line) for line in fh if line.strip()]


def _pins_of(shape_module):
    return gen.load_shape(shape_module).pins


# -- P3.T23 -----------------------------------------------------------------
def test_tlvds_rows_e1():
    rows = _rows("tlvds")
    assert len(rows) == TLVDS_ROWS
    closed = [r for r in rows if r["level"] == "E1" and r["verdict"] == "ok"]
    assert len(closed) == TLVDS_ROWS


def test_tlvds_types_covered():
    swept = {list(r["sweep"].values())[0] for r in _rows("tlvds")}
    covered = {diff_io.ALL_POINTS[point] for point in swept}
    assert covered == {"TLVDS_IBUF", "TLVDS_OBUF", "TLVDS_TBUF"}


def test_tlvds_bank_is_33v():
    """Every generated `.cst` line for these pins carries `BANK_VCCIO=3.3`."""
    spec = gen.load_shape("diff_io")
    for point in spec.sweep_values:
        for line in gen.render_cst(spec, point).splitlines():
            if line.startswith("IO_PORT"):
                assert "BANK_VCCIO=3.3" in line, line


# -- P3.T24 -----------------------------------------------------------------
def _adjudication():
    path = os.path.join(EVIDENCE, "tlvds-iobuf", "adjudication.md")
    if not os.path.isfile(path):
        pytest.skip(f"no adjudication at {path}")
    with open(path) as fh:
        return fh.read()


def test_tlvds_iobuf_adjudication_recorded():
    verdicts = re.findall(r"^VERDICT: (restored|removal-confirmed)$",
                          _adjudication(), re.M)
    assert len(verdicts) == 1


def test_tlvds_iobuf_chipdb_matches_verdict():
    """The chipdb says what the adjudication says, for this device."""
    from apycula import chipdb
    verdict = re.search(r"^VERDICT: (\w[\w-]*)$", _adjudication(), re.M).group(1)
    types = _diff_io_types("GW5AST-138C", chipdb)
    assert ("TLVDS_IOBUF" in types) == (verdict == "restored")


def test_tlvds_iobuf_25a_unchanged():
    from apycula import chipdb
    assert "TLVDS_IOBUF" in _diff_io_types("GW5A-25A", chipdb)


def _diff_io_types(device, chipdb):
    import importlib.resources
    path = importlib.resources.files("apycula") / f"{device}.msgpack.xz"
    if not path.is_file():
        pytest.skip(f"no chipdb for {device}")
    return chipdb.load_chipdb(str(path)).diff_io_types


# -- P3.T25 -----------------------------------------------------------------
def test_elvds_rows_terminal():
    rows = _rows("elvds")
    assert len(rows) == ELVDS_ROWS
    assert all(r["verdict"] in ("ok", "diff", "aborted", "refused")
               for r in rows)


def test_elvds_no_bank6_pins():
    """No ELVDS pin -- swept or probed -- resolves to bank 6 or 7."""
    for module in ("diff_io_elvds", "diff_io"):
        for pin in _pins_of(module).values():
            assert pin.bank not in DDR_BANKS
    from fuzz.gw5ast138c.shapes import diff_io_vccio_probe
    assert diff_io_vccio_probe.PROBED_BANK not in DDR_BANKS


def test_elvds_deferred_point_named():
    path = os.path.join(EVIDENCE, "elvds", "summary.md")
    if not os.path.isfile(path):
        pytest.skip(f"no summary at {path}")
    with open(path) as fh:
        summary = fh.read()
    line = "deferred-point: elvds-iobuf-sstl15d -> P5b"
    assert len([l for l in summary.splitlines() if l.strip() == line]) == 1


def test_elvds_amendment_cited():
    assert all("SA-P3-1" in r["notes"] for r in _rows("elvds"))


def test_elvds_matrix_recorded():
    path = os.path.join(EVIDENCE, "elvds", "vccio-matrix.tsv")
    if not os.path.isfile(path):
        pytest.skip(f"no matrix at {path}")
    with open(path) as fh:
        data = [l for l in fh
                if l.strip() and not l.startswith("#")][1:]
    assert len(data) >= 3


def test_elvds_status_cell_carries_no_deferred_point():
    """`deferred-point:` is prose; it is not in the status vocabulary."""
    spec = os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "..", "..", "..", ".atelier", "pipelines",
        "2026-09-03-open-toolchain-gw5ast-7e84", "spec-primitives.md")
    spec = os.path.normpath(spec)
    if not os.path.isfile(spec):
        pytest.skip(f"no spec at {spec}")
    with open(spec) as fh:
        row = [l for l in fh if l.startswith("| **ELVDS_")]
    assert row and all("deferred-point" not in l for l in row)


# -- the shapes themselves --------------------------------------------------
def test_elvds_shape_omits_elvds_ibuf():
    """UG304E documents no `ELVDS_IBUF`; the input side is `ELVDS_IOBUF`."""
    types = {diff_io.ALL_POINTS[p] for p in diff_io_elvds.POINTS}
    assert types == {"ELVDS_OBUF", "ELVDS_TBUF", "ELVDS_IOBUF"}


def test_iobuf_shape_is_one_point():
    assert diff_io_iobuf.POINTS == ("tlvds-iobuf",)


def test_diff_io_designs_hold_no_fabric_cell():
    """`D105`: every net of a differential shape ends on a package ball."""
    for module in ("diff_io", "diff_io_elvds", "diff_io_iobuf"):
        spec = gen.load_shape(module)
        for point in spec.sweep_values:
            rtl = gen.render_verilog(spec, point)
            assert "always" not in rtl, (module, point)
            assert "reg " not in rtl, (module, point)
