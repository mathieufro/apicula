"""A port tied to a power rail compares as that rail, not as a digest.

MEASURED (`P2.T23`, the `ae350_soc` row): `gowin_unpack` reports a tied `CE`,
`LSR` or `ADCEN` with the union-find root `VCC`, and every unrouted port of
the die joins that same component -- 310 040 endpoints in the vendor
bitstream against 6 120 in the open one for the *same* design.  Identifying a
net by its endpoint set therefore made two ports tied to the same rail
compare unequal, which is an artefact of the naming, not a difference in the
configuration.
"""
from fuzz.gw5ast138c.harness.equiv import (CONSTANT_NET_ROOTS, net_id,
                                           net_label)
from fuzz.gw5ast138c.harness.equiv import Cell


def _eps(n):
    return frozenset((Cell(x=i, y=0, z=0, type="DFF"), "CE") for i in range(n))


def test_a_rail_compares_by_name_whatever_it_collected():
    assert net_label("VCC", _eps(3)) == net_label("VCC", _eps(3000))
    assert net_label("VCC", _eps(3)) == "net:VCC"


def test_every_rail_root_is_covered():
    for root in CONSTANT_NET_ROOTS:
        assert net_label(root, _eps(2)) == "net:" + root


def test_an_ordinary_net_still_compares_by_its_endpoints():
    assert net_label("R2C161_Q0", _eps(3)) == net_id(_eps(3))
    assert net_label("R2C161_Q0", _eps(3)) != net_label("R2C161_Q0", _eps(4))
