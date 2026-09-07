"""A tool declining a design is a measurement, not a crash (`D30`, `P2.T29`).

Both flows have a way of saying "this device cannot do that", and both said it
during the dual-purpose-pin sweep.  The verdict vocabulary distinguishes
`refused` from `aborted` precisely so those two answers do not read as failures
of the harness, and these tests hold the line narrow: only a named refusal is
`refused`; an unexplained non-zero exit stays a crash.
"""
from fuzz.gw5ast138c.harness import openflow, oracle

#: The vendor's own words, verbatim from `p2t29-dualpin2-dualpin-0006`.
GWSH_REFUSAL = """\
add new file: "../top.sdc"
configuration that does not support RECONFIG_N

    while executing
"set_option -use_reconfign_as_gpio 1"
    (file "run.tcl" line 16)
"""

GWSH_CRASH = """\
Segmentation fault
"""

PACK_REFUSAL = """\
  File "apycula/gowin_pack.py", line 5471, in get_PINCFG_fuses
    raise Exception(f" i2c_as_gpio has conflicting settings in nexpnr and gowin_pack.")
Exception:  i2c_as_gpio has conflicting settings in nexpnr and gowin_pack.
"""

PACK_CRASH = """\
Exception: something else entirely
"""


def test_vendor_refusal_returns_the_vendors_own_words():
    got = oracle.vendor_refusal(GWSH_REFUSAL, 1)
    assert got == ('configuration that does not support RECONFIG_N '
                   '(set_option -use_reconfign_as_gpio 1)')


def test_vendor_refusal_is_not_claimed_on_a_clean_exit():
    assert oracle.vendor_refusal(GWSH_REFUSAL, 0) is None


def test_an_unexplained_vendor_exit_stays_a_crash():
    assert oracle.vendor_refusal(GWSH_CRASH, 1) is None


def test_packer_cross_check_is_a_named_refusal():
    steps = [{"returncode": 1, "log_text": PACK_REFUSAL}]
    assert openflow.named_refusal(steps) == (
        'i2c_as_gpio has conflicting settings in nexpnr and gowin_pack.')


def test_any_other_packer_exception_stays_a_crash():
    assert openflow.named_refusal(
        [{"returncode": 1, "log_text": PACK_CRASH}]) is None
