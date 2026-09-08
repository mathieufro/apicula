"""The `tangmega138k` example set: one buildable design per closed primitive.

`DONE-STD` clause (d) is what these guard.  The examples themselves are
generated from the shape files that measured the rows, so what is left to pin
here is the Makefile wiring: that every generated example is reachable from
the board's phony target, that the other boards' target lists did not move,
and that the shared constraint file was not rewritten to make room.
"""
import os
import re
import subprocess

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
EXAMPLES = os.path.join(HERE, os.pardir, "examples", "gw5a")
MAKEFILE = os.path.join(EXAMPLES, "Makefile")
CST = os.path.join(EXAMPLES, "tangmega138k.cst")

#: The examples this phase added, in the order the emitter writes them.
IO_EXAMPLES = (
    "oddr-io", "iddr-io",
    "oser4-io", "oser8-io", "oser10-io", "ovideo-io",
    "ides4-io", "ides8-io", "ides10-io",
    "oser16-io", "ides16-io",
    "tlvds-ibuf-io", "tlvds-obuf-io", "tlvds-tbuf-io", "tlvds-iobuf-io",
    "iodelay-static-io", "adclrc-io",
)

#: The six targets the board already had before this phase.
INHERITED = (
    "big-shift-tangmega138k.fs", "attosoc-tangmega138k.fs",
    "uart-message-tangmega138k.fs", "ae350-emb-tcm-tangmega138k.fs",
    "dualpin-tangmega138k.fs", "iddr-boardclk-tangmega138k.fs",
)


def _target_list(text, name):
    """The prerequisites of a phony target, with line continuations dropped."""
    match = re.search(rf"^{name}:((?:.*\\\n)*.*)$", text, re.M)
    assert match, f"no {name}: target in the Makefile"
    return [word for word in match.group(1).split() if word != "\\"]


@pytest.fixture(scope="module")
def makefile():
    with open(MAKEFILE, encoding="utf-8") as fh:
        return fh.read()


def test_makefile_tangmega138k_targets_added(makefile):
    """Every closed primitive is reachable from the board's phony target."""
    targets = _target_list(makefile, "tangmega138k")
    assert len(targets) == len(set(targets)), "a target is listed twice"
    assert set(INHERITED) <= set(targets)
    assert {f"{name}-tangmega138k.fs" for name in IO_EXAMPLES} <= set(targets)
    assert len(targets) == len(INHERITED) + len(IO_EXAMPLES)


def test_makefile_primer25k_list_unchanged(makefile):
    """The other board's list is not this phase's to touch."""
    assert len(_target_list(makefile, "primer25k")) == 44


def test_every_io_example_has_its_own_design_and_constraints(makefile):
    """A listed target with no design or no pins would fail only at build."""
    for name in IO_EXAMPLES:
        assert os.path.isfile(os.path.join(EXAMPLES, f"{name}.v"))
        assert os.path.isfile(
            os.path.join(EXAMPLES, f"{name}-tangmega138k.cst"))
        assert f"{name}-tangmega138k.json: {name}-tangmega138k-synth.json" \
            in makefile


def test_cst_appended_only():
    """The shared constraint file is untouched: each example brings its own.

    These designs claim balls by primitive rather than by the board's LED and
    UART set, and the gearbox rows pin a `CLKDIV` lane with an `INS_LOC` line;
    putting either in the shared file would change what every other example on
    this board is constrained to.
    """
    head = subprocess.run(
        ["git", "show", "HEAD:examples/gw5a/tangmega138k.cst"],
        cwd=os.path.join(HERE, os.pardir), capture_output=True)
    if head.returncode != 0:
        pytest.skip("not a git checkout")
    with open(CST, "rb") as fh:
        current = fh.read()
    assert current.split(b"\n")[:44] == head.stdout.split(b"\n")[:44]
