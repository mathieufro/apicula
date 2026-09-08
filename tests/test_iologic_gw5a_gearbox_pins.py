"""The GW5A input gearboxes do not sit on the bel pins the older families use.

The GW5A IOLOGIC carries sixteen fabric outputs where GW1N/GW2A carry ten, and
the window each gearbox occupies was MEASURED on the GW5AST-138C by tracing
every word ball of a vendor bitstream back to the IOLOGIC wire that drives it
(`P3.T12`/`P3.T14`).  Reading the older map on a GW5A put an `IDDR`'s `Q0` on
the wrong wire, which is a wrong bitstream and not a placement choice.
"""
import pytest

from apycula import gowin_unpack


#: primitive -> (first bel-pin index, width), as measured.
MEASURED_WINDOWS = {
    'IDDR': (14, 2),
    'IDDRC': (14, 2),
    'IDES4': (8, 4),
    'IDES8': (8, 8),
    'IDES10': (6, 10),
}


@pytest.mark.parametrize("typ,window", sorted(MEASURED_WINDOWS.items()))
def test_gearbox_occupies_the_measured_window(typ, window):
    base, width = window
    ports = gowin_unpack._iologic_ports_gw5[typ]
    assert {f'Q{base + i}': f'Q{i}' for i in range(width)}.items() <= ports.items()


def test_every_window_fits_the_sixteen_outputs():
    for base, width in MEASURED_WINDOWS.values():
        assert 0 <= base and base + width <= 16


def test_unmeasured_gearboxes_keep_the_pre_5a_map():
    """`IVIDEO` and `IDES16` have no measured GW5A bitstream, so naming a
    window for them would name a wire nothing proved."""
    assert 'IVIDEO' not in gowin_unpack._iologic_ports_gw5
    assert 'IDES16' not in gowin_unpack._iologic_ports_gw5


def test_ports_of_falls_back_when_the_device_is_not_a_gw5a(monkeypatch):
    monkeypatch.setattr(gowin_unpack, '_device', 'GW1N-9C')
    assert gowin_unpack.iologic_ports_of('IDDR') is gowin_unpack._iologic_ports['IDDR']
    monkeypatch.setattr(gowin_unpack, '_device', 'GW5AST-138C')
    assert gowin_unpack.iologic_ports_of('IDDR') is gowin_unpack._iologic_ports_gw5['IDDR']
