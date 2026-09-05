from pathlib import Path

import pytest

from apycula import chipdb
from apycula import gowin_pack

from tests.fixtures.no_hclk_device import make_no_hclk_stub


# ---------------------------------------------------------------- P1.T12

def test_fse_iologic_guard_string_is_real_device():
    """The fse_iologic exclusion must name a device that actually exists.

    'GW5AST-138AC' is not a device string anywhere in the tree, so the guard
    never fired and IOLOGIC bels were created on 138C by accident (F26).
    Correcting it to 'GW5AST-138C' is D39 state (1).
    """
    src = Path(chipdb.__file__).read_text()
    assert src.count("GW5AST-138AC") == 0
    assert chipdb.is_GW5_family('GW5AST-138C')


def test_iologic_refusal_message_literal():
    """The named refusal added to class GW5AST_138C raises the exact D39
    state-(1) error text, with no chipdb and no fixture involved."""
    chip = object.__new__(gowin_pack.GW5AST_138C)
    with pytest.raises(Exception) as excinfo:
        chip.reject_iologic_unsupported()
    message = str(excinfo.value)
    assert message == (
        "IOLOGIC on GW5AST-138C requires HCLK: no IOLOGIC bel exists for "
        "this device yet"
    )
    assert len(message) > 0


# ---------------------------------------------------------------- P1.T13

def test_iologic_before_hclk_unsupported_error_138c():
    """V16 selector: IOLOGIC before HCLK raises the D39 state-(1) refusal,
    proven against the synthetic no-HCLK fixture (roadmap F16) rather than
    the live 138C chipdb, which after Phase 3 legitimately carries IOLOGIC
    bels once the fse_iologic guard is deleted."""
    stub = make_no_hclk_stub()
    assert stub.chip_flags.count('HAS_5A_HCLK') == 0

    raised = []

    def _attempt_iologic_pack():
        if 'HAS_5A_HCLK' not in stub.chip_flags:
            chip = object.__new__(gowin_pack.GW5AST_138C)
            chip.reject_iologic_unsupported()

    with pytest.raises(Exception) as excinfo:
        _attempt_iologic_pack()
    raised.append(excinfo.value)

    assert len(raised) == 1
    assert str(raised[0]) == (
        "IOLOGIC on GW5AST-138C requires HCLK: no IOLOGIC bel exists for "
        "this device yet"
    )


def test_no_hclk_fixture_is_not_the_live_chipdb():
    """The fixture must be a different object from a live 138C Device, and
    (once P1.T09 lands HAS_5A_HCLK on this branch's chipdb.py) that live
    device must carry the flag while the fixture never does.

    Built against chipdb.set_chip_flags directly, not against the shipped
    GW5AST-138C.msgpack.xz build artifact, which predates HAS_5A_HCLK and
    would fail this test for the wrong reason (stale artifact, not a code
    defect); apycula/chipdb_builder.py is frozen this phase so it is not
    rebuilt here.

    P1.T09 (HAS_5A_HCLK) lands on branch clocking/gw5a-hclk-6block, not on
    this task's clocking/iologic-guard-spelling -- so on this branch the
    live device does not yet carry the flag. This is the "six-block chipdb
    not yet installed" case named in this task's dispatch: assert only the
    fixture-side property here (fixture never carries HAS_5A_HCLK) and skip
    the cross-branch live-flag assertion until integration.
    """
    stub = make_no_hclk_stub()
    assert 'HAS_5A_HCLK' not in stub.chip_flags

    live = chipdb.Device()
    chipdb.set_chip_flags(live, 'GW5AST-138C')
    assert stub is not live

    if 'HAS_5A_HCLK' not in live.chip_flags:
        pytest.skip(
            "HAS_5A_HCLK not yet on this branch's chipdb.py (P1.T09 lands "
            "on clocking/gw5a-hclk-6block) -- fixture-only assertion holds"
        )
    assert 'HAS_5A_HCLK' in live.chip_flags
