"""A DCS control wire nobody measured is refused, not guessed.

`P1.T31` ($OTC/evidence/dcs/ports-138c.md): five vendor compiles route no
external net into either 138C clock-bridge cell for `SELFORCE` or `CLKSEL`, so
the die's real control wires are untraced.  The chipdb still has to name two
different wire sets -- the two DCS of a shared cell cannot name the same ones
-- but it marks them untraced, and `gowin_pack` refuses a design that drives
them rather than routing into a wire this die may not use (`D30`).
"""
import pytest

from apycula import chipdb, gowin_pack


class _Cell:
    def __init__(self, connections):
        self.attrs = {'DCS_MODE': 'RISING'}
        self.connections = connections


class _Bel:
    def __init__(self, connections):
        self.x, self.y, self.idx_int = 54, 93, 0
        self.cell = _Cell(connections)


class _ChipDB:
    def __init__(self, traced):
        self.traced = traced

    def dcs_control_wires_traced(self, x, y, idx_int):
        return self.traced


class _Packer:
    def __init__(self, traced):
        self.chipdb = _ChipDB(traced)


def _reject(traced, connections):
    return gowin_pack.GW5A.reject_untraced_dcs_control(
        _Packer(traced), _Bel(connections))


def test_a_driven_clksel_on_an_untraced_die_is_refused_by_name():
    with pytest.raises(Exception) as exc:
        _reject(False, {'CLKSEL0': [42], 'CLKIN0': [7]})
    assert 'CLKSEL0' in str(exc.value)
    assert 'never been traced' in str(exc.value)


def test_a_driven_selforce_on_an_untraced_die_is_refused_by_name():
    with pytest.raises(Exception) as exc:
        _reject(False, {'SELFORCE': [42]})
    assert 'SELFORCE' in str(exc.value)


def test_an_undriven_control_port_on_an_untraced_die_packs():
    """A statically-selected DCS never routes into the untraced wires."""
    assert _reject(False, {'SELFORCE': [], 'CLKSEL0': [], 'CLKIN0': [7]}) is None


def test_a_traced_die_packs_a_driven_clksel():
    assert _reject(True, {'CLKSEL0': [42]}) is None


def test_the_138c_dcs_control_wires_are_recorded_as_untraced():
    """The per-device table, not a comment, is what the packer reads."""
    assert not chipdb.dcs_control_wires_traced('GW5AST-138C')
    assert chipdb.dcs_control_wires_traced('GW5A-25A')
    assert chipdb.dcs_control_wires_traced('GW1N-9')
