"""Phase 3 (IO and IOLOGIC) unit tests for GW5AST-138C.

`D39`'s three ordered states end here: Phase 1 corrected the misspelled
exclusion so it fired, Phase 1 set `HAS_5A_HCLK`, and `P3.T03` deletes the
exclusion so IOLOGIC on this die is deliberate rather than accidental. What
replaces it is a **ttyp-qualified** gate (`P3.T04`) derived from the device
data, not a blanket device gate.

The bel-surface test reads the built `apycula/GW5AST-138C.msgpack.xz` -- the
canonical chipdb the whole open flow consumes (`F7`) -- rather than rebuilding
it, so the phase pays for that build once and every test still asserts against
the artefact that ships.
"""
import os
import re

import pytest

from apycula import chipdb
from apycula.gowin_pack import ChipDB

DEVICE = "GW5AST-138C"

#: The 25A ttyp gate `P3.T03` must leave standing (`F10`, `F11`).
GW5A_25A_IOLOGIC_EXCLUSIONS = {48, 51, 263, 392, 399}


def _fse_iologic_source():
    """The text of `fse_iologic` alone -- a guard elsewhere is not this guard."""
    path = os.path.join(os.path.dirname(chipdb.__file__), "chipdb.py")
    text = open(path, encoding="utf-8").read()
    match = re.search(r"^def fse_iologic\(.*?^(?=def )", text, re.S | re.M)
    assert match, "fse_iologic not found in chipdb.py"
    return match.group(0)


def _iologic_bel_counts(db):
    """`{bel name: cell count}` over the whole grid."""
    counts = {"IOLOGICA": 0, "IOLOGICB": 0}
    for row in db.grid:
        for ttyp in row:
            for name in db.tiles[ttyp].bels:
                if name in counts:
                    counts[name] += 1
    return counts


@pytest.fixture(scope="module")
def db_138c():
    try:
        return ChipDB(DEVICE).db
    except FileNotFoundError:  # pragma: no cover - build it first
        pytest.skip(f"{DEVICE}.msgpack.xz absent; run apycula.chipdb_builder")


def test_iologic_bels_created_on_138c(db_138c):
    """IOLOGIC exists on 138C, and it exists next to a real clock (`D39` state 2)."""
    counts = _iologic_bel_counts(db_138c)
    assert counts["IOLOGICA"] >= 1
    assert counts["IOLOGICA"] + counts["IOLOGICB"] > 0
    assert "HAS_5A_HCLK" in db_138c.chip_flags


def test_iologic_bare_138c_guard_absent():
    """No misspelling anywhere, and no *blanket* 138C exclusion in `fse_iologic`.

    The ttyp-qualified form `P3.T04` adds is deliberately still legal.
    """
    path = os.path.join(os.path.dirname(chipdb.__file__), "chipdb.py")
    assert open(path, encoding="utf-8").read().count("GW5AST-138AC") == 0
    assert _fse_iologic_source().count("if device in {'GW5AST-138C'}:") == 0


def test_iologic_25a_ttyp_gate_intact():
    """The 25A exclusion is untouched -- Phase 3 must not regress a shipped family."""
    source = _fse_iologic_source()
    match = re.search(
        r"if device in \{'GW5A-25A'\} and ttyp in \{([^}]*)\}:\s*\n\s*return bels",
        source)
    assert match, "the GW5A-25A ttyp gate is gone from fse_iologic"
    assert {int(x) for x in match.group(1).split(",")} == \
        GW5A_25A_IOLOGIC_EXCLUSIONS


# ---------------------------------------------------------------- P3.T04

#: The adjudication `P3.T04` derived, relative to this checkout's siblings.
_ADJUDICATION = os.path.join("open-toolchain", "evidence", "oddr-iddr",
                             "ttyp-adjudication.tsv")


def _adjudication_path():
    """`$OTC/evidence/oddr-iddr/ttyp-adjudication.tsv`, from the worktree layout."""
    here = os.path.dirname(os.path.dirname(os.path.abspath(chipdb.__file__)))
    candidates = [os.environ.get("P3_TTYP_ADJUDICATION"),
                  os.path.join(os.path.dirname(here), _ADJUDICATION),
                  os.path.join(os.path.dirname(os.path.dirname(here)),
                               _ADJUDICATION)]
    for candidate in candidates:
        if candidate and os.path.isfile(candidate):
            return candidate
    return None


def _ttyp_gate_literal():
    """The 138C ttyp set `fse_iologic` excludes, as written in the source."""
    match = re.search(
        r"if device in \{'GW5AST-138C'\} and ttyp in \{([^}]*)\}:",
        _fse_iologic_source(), re.S)
    return {int(x) for x in match.group(1).replace("\n", " ").split(",")
            if x.strip()} if match else set()


def test_iologic_ttyp_exclusion_138c_matches_evidence():
    """The literal in the source is the set the evidence rejected -- no more, no less."""
    path = _adjudication_path()
    if path is None:
        pytest.skip("ttyp-adjudication.tsv not reachable from this checkout")
    rows = [line.split("\t") for line in
            open(path, encoding="utf-8").read().splitlines()[1:] if line]
    rejected = {int(r[0]) for r in rows if r[1] == "reject"}
    accepted = {int(r[0]) for r in rows if r[1] == "accept"}
    assert rejected | accepted == {int(r[0]) for r in rows}, "a row has no verdict"
    assert _ttyp_gate_literal() == rejected
    assert len(rejected) == sum(1 for r in rows if r[1] == "reject")
    assert len(rejected) >= 0
