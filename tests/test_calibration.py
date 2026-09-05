"""`P0.T33` / `V5` -- the `S6` whole-design calibration on three baselines.

`S6` is a *calibration* criterion, not an equivalence pass (`D32`): the
deliverable is that every difference between the vendor and open-flow
bitstreams is listed **by category**, none unexplained.  These tests assert
the shape of the recorded evidence and of the checker's own stdout contract,
so a later change cannot quietly drop a category or widen the mask.
"""
import json
import os
import re
import subprocess

import pytest

from fuzz.gw5ast138c.harness import evidence

try:
    _EVIDENCE_ROOT = evidence.evidence_root()
except evidence.EvidenceSchemaError:
    _EVIDENCE_ROOT = None
CALIB = os.path.join(_EVIDENCE_ROOT, "calibration") if _EVIDENCE_ROOT else None
RUNS = os.path.join(CALIB, "runs.jsonl") if CALIB else "/nonexistent/runs.jsonl"
STDOUT = (os.path.join(CALIB, "calibration-stdout.txt") if CALIB
          else "/nonexistent/calibration-stdout.txt")
DESIGNS = ("big-shift", "attosoc", "uart-message")
OK_LINE = re.compile(r"^CALIBRATION ok: \d+ diffs enumerated, 0 unexplained$")

APICULA = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _rows():
    """The `S6` whole-design calibration rows -- one per `DESIGNS` entry.

    `runs.jsonl` is append-only and shared with every other primitive/shape
    this evidence *slug* records (`spec-harness.md` Sec 5), so this filters
    to rows carrying a `design` key naming one of `DESIGNS` rather than
    assuming the file holds nothing else.
    """
    if not os.path.isfile(RUNS):
        pytest.skip(f"no calibration evidence yet at {RUNS}")
    with open(RUNS) as fh:
        rows = [json.loads(line) for line in fh if line.strip()]
    return [r for r in rows if r.get("design") in DESIGNS]


def _stdout():
    if not os.path.isfile(STDOUT):
        pytest.skip(f"no recorded calibration stdout at {STDOUT}")
    with open(STDOUT) as fh:
        return fh.read()


def test_calibration_three_designs_enumerated():
    """One row per design, each with an empty `unexplained_bits` and a count."""
    rows = _rows()
    assert len(rows) == 3, f"expected 3 rows, got {len(rows)}"
    assert sorted(r["design"] for r in rows) == sorted(DESIGNS)
    for row in rows:
        assert row["unexplained_bits"] == [], (
            f"{row['design']}: unexplained_bits must be empty, got "
            f"{row['unexplained_bits']}")
        assert row["diff_count"] is not None, f"{row['design']}: null diff_count"


def test_calibration_stdout_contract():
    """Three `CALIBRATION ok` lines and no `FAIL` line (`V5`'s Done-when)."""
    text = _stdout()
    ok = [ln for ln in text.splitlines() if OK_LINE.match(ln)]
    assert len(ok) == 3, f"expected 3 CALIBRATION ok lines, got {len(ok)}: {ok}"
    fails = [ln for ln in text.splitlines() if ln.startswith("FAIL")]
    assert fails == [], f"FAIL lines present: {fails}"


def test_calibration_uses_makefile_flags():
    """The open side was built by `examples/gw5a/Makefile`'s own recipe (F13)."""
    rows = {r["design"]: r for r in _rows()}
    big = rows["big-shift"]["yosys_cmd"]
    for flag in ("-setundef", "-D INV_BTN=0", "-D LEDS_NR=16"):
        assert flag in big, f"big-shift yosys line missing {flag!r}: {big}"
    for design in ("attosoc", "uart-message"):
        cmd = rows[design]["yosys_cmd"]
        assert "-D INV_BTN=0" in cmd, f"{design} yosys line missing -D INV_BTN=0"
        assert cmd.count("-D LEDS_NR") == 0, f"{design} must not set LEDS_NR"
    for design in DESIGNS:
        assert rows[design]["yosys_cmd"].count("-nolutram") == 0, (
            f"{design}: no tangmega138k target passes -nolutram")
    assert "--top attosoc" in rows["attosoc"]["nextpnr_cmd"]


def test_calibration_chipdb_pinned():
    """Each nextpnr line pins the chipdb once, and the Makefile is unmodified."""
    for row in _rows():
        assert row["nextpnr_cmd"].count("chipdb-GW5AST-138C.bin") == 1, (
            f"{row['design']}: chipdb must be pinned exactly once")
    changed = subprocess.run(
        ["git", "-C", APICULA, "diff", "--name-only"],
        capture_output=True, text=True, check=True).stdout.split()
    touched = [p for p in changed if p.startswith("examples/gw5a/")]
    assert touched == [], f"examples/gw5a is frozen, but modified: {touched}"


# --- unit-level guards for what the calibration measured ------------------

def test_fuse_group_category_names_routing_and_io_defaults():
    """A chipdb fuse group decides the residual category, not a byte offset."""
    from fuzz.gw5ast138c.harness import equiv

    assert equiv.group_category("pip") == "net_route"
    assert equiv.group_category("alonenode") == "net_route"
    assert equiv.group_category("longval:IOBA") == "io_default_unused_pins"
    assert equiv.group_category("shortval:5A_PCLK_ENABLE_16") == \
        "unmodelled_config_fuse"
    assert equiv.group_category("shortval:BSRAM_SP") == "bsram_mode_fuse"
    assert equiv.group_category("shortval:LUT") is None


def test_line_delta_splits_command_words_from_config_frames(tmp_path):
    """Wide extra lines are configuration frames, not command words."""
    from fuzz.gw5ast138c.harness import equiv

    common = ["0" * 64]
    vendor = tmp_path / "v.fs"
    open_ = tmp_path / "o.fs"
    vendor.write_text("\n".join(common + ["1" * 64] + ["0" * 496] * 3) + "\n")
    open_.write_text("\n".join(common) + "\n")
    split = equiv._line_delta_bytes(str(vendor), str(open_))
    assert split["command"] == 8 and split["command_lines"] == 1
    assert split["config_frame"] == 3 * 62
    assert split["config_frame_lines"] == 3


@pytest.mark.heavy  # reads a real vendor .fs bitstream from disk
def test_bslib_reads_a_bitstream_carrying_bsram_slots():
    """A 62-byte slot line is never read as a device id or a frame count."""
    from apycula.bslib import read_bitstream
    from fuzz.gw5ast138c.harness import equiv

    fs = os.path.join(equiv.DATASTORE, "calibration", "uart-message", "top.fs")
    if not os.path.isfile(fs):
        pytest.skip(f"no BSRAM-slot bitstream at {fs}")
    bitmap, _hdr, ftr, _slots = read_bitstream(fs)
    assert len({len(row) for row in bitmap}) == 1, "bitmap rows must be uniform"
    assert len(bitmap) == 1517 and len(bitmap[0]) == 21872
    assert len(ftr) > 1000, "the slot lines must land in the footer, not the bitmap"
