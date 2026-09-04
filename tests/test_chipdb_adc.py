"""P0.T13b (b): a device file with no ADC description must not crash the build.

`GW5A-25A.dat` from Gowin IDE 1.9.11.03 (Education) and 1.9.12.03 (Standard)
carries `Adc25kIns` filled entirely with `[-1, -1, -1]` and an `Adc25kOuts`
whose rows `[92, 124, -1]`, `[90, 125, -1]` and `[90, 22, -1]` name a cell but
no wire. `fse_create_adc` tested only the row and column, so it reached
`wirenames[-1]` and the whole chipdb build died with a bare `KeyError: -1`.
"""
import pytest

from apycula import chipdb
from apycula import wirenames as wnames


ABSENT = [[-1, -1, -1]] * 30

# The real GW5A-25A output table as shipped by both installed editions: some
# rows are usable, three name a cell but carry wire index -1.
REAL_OUTS = [[-1, -1, -1], [-1, -1, -1], [-1, -1, -1], [-1, -1, -1],
             [-1, -1, -1], [-1, -1, 4], [92, 124, -1], [-1, -1, 3],
             [92, 16, 3], [92, 12, 3], [92, 8, 3], [92, 4, 10],
             [90, 6, 10], [90, 28, 10], [90, 125, -1], [-1, -1, 10],
             [89, 0, 10], [89, 4, 10], [89, 8, 10], [89, 12, 10],
             [89, 16, 10], [89, 20, 10], [89, 24, 10], [89, 28, 10],
             [90, 22, -1], [-1, -1, 10], [90, 30, 10], [90, 26, 3]]


class _Dat:
    def __init__(self, stuff):
        if stuff is not None:
            self.gw5aStuff = stuff


class _ExplodingDev:
    """Any access at all is a failure: the ADC must be skipped, not built."""
    cols = 92

    def __getitem__(self, key):
        raise AssertionError(f'ADC bel creation was attempted: dev[{key}]')


@pytest.mark.parametrize('stuff', [
    None,                                                    # no gw5aStuff
    {},                                                      # no ADC tables
    {'Adc25kIns': ABSENT, 'Adc25kOuts': ABSENT},             # both absent
    {'Adc25kIns': ABSENT, 'Adc25kOuts': REAL_OUTS},          # the real 25A
])
def test_chipdb_adc_absent_is_skipped(stuff, capsys, monkeypatch):
    monkeypatch.setenv('GOWIN_IDE_VERSION', '1.9.11.03')
    monkeypatch.setenv('GOWINHOME', '/some/GowinIDE/Gowin_EDA')
    chipdb.fse_create_adc(_ExplodingDev(), 'GW5A-25A', {}, _Dat(stuff))
    warning = capsys.readouterr().err
    assert 'no ADC description' in warning, warning
    for needle in ('GW5A-25A', '1.9.11.03', '/some/GowinIDE/Gowin_EDA'):
        assert needle in warning, warning


def test_chipdb_adc_skipped_for_devices_without_one():
    """The pre-existing device gate is untouched: no warning, no bel."""
    chipdb.fse_create_adc(_ExplodingDev(), 'GW5AST-138C', {}, _Dat(None))


def test_chipdb_adc_absent_port_row_is_recognised():
    assert not chipdb._port_row_present([92, 124, -1])
    assert not chipdb._port_row_present([-1, -1, 4])
    assert not chipdb._port_row_present([1, 2])
    assert chipdb._port_row_present([90, 26, 3])


def test_chipdb_adc_is_built_when_the_description_is_present():
    """A described ADC still builds, and an absent port row is just skipped."""
    ins = list(ABSENT)
    ins[0] = [1, 1, 3]        # CLK, in our own cell
    ins[2] = [92, 124, -1]    # a cell with no wire -> skipped, not a KeyError
    wnames.select_wires('GW5A-25A')
    dat = _Dat({'Adc25kIns': ins, 'Adc25kOuts': REAL_OUTS})
    dev = chipdb.Device(grid=[[0]], tiles={0: chipdb.Tile(1, 1, 0)})
    chipdb.fse_create_adc(dev, 'GW5A-25A', {}, dat)
    assert 'ADC' in dev[0, dev.cols - 1].bels
    adc = dev.extra_func[(0, dev.cols - 1)]['adc']
    assert 'VSENCTL0' not in adc['inputs']
    assert 'CLK' in adc['inputs']
    assert 'ADCVALUE4' not in adc['outputs']   # [92, 124, -1]
    assert 'ADCVALUE6' in adc['outputs']       # [92, 16, 3]
