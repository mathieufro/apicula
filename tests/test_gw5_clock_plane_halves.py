"""The split of a GW5A clock plane into halves is a table, not a literal.

`fse_create_5a138_clocks` divides the 138C's clock plane into a `TOP` and a
`BOTTOM` half fed from the bridge, and two independent places need to know
where the split falls: the bridge builder, which names each half's
`CBRIDGEOUT_<half><n>` node, and `dcs_clkout_node`, which joins a DCS output
to it.  Both now read `chipdb._gw5_clock_plane_halves`, so a die with a
different split cannot have one of them build names off a stale constant.
"""
import pytest

from apycula import chipdb


def test_the_138c_halves_come_from_the_table_not_from_a_literal(monkeypatch):
    """Move the split in the table and every derived name moves with it."""
    monkeypatch.setitem(chipdb._gw5_clock_plane_halves, 'GW5AST-138C',
                        (('TOP', 'SPINE8', 4), ('BOTTOM', 'SPINE12', 4)))

    assert chipdb.gw5_clock_plane_half('GW5AST-138C', 'SPINE14') == ('BOTTOM', 2)
    assert chipdb.dcs_clkout_node('GW5AST-138C', 'SPINE14') == 'CBRIDGEOUT_BOTTOM2'


def test_the_measured_138c_split_maps_every_dcs_output_spine():
    """The four DCS outputs of the two quadrants (`P1.T31`), as measured."""
    node = chipdb.dcs_clkout_node
    assert node('GW5AST-138C', 'SPINE14') == 'CBRIDGEOUT_TOP6'
    assert node('GW5AST-138C', 'SPINE15') == 'CBRIDGEOUT_TOP7'
    assert node('GW5AST-138C', 'SPINE22') == 'CBRIDGEOUT_BOTTOM6'
    assert node('GW5AST-138C', 'SPINE23') == 'CBRIDGEOUT_BOTTOM7'


def test_a_device_with_an_undivided_plane_keeps_its_spine_as_the_node():
    """Pre-5A dies are not in the table: there the spine *is* the network."""
    assert chipdb.gw5_clock_plane_half('GW1N-9', 'SPINE14') is None
    assert chipdb.dcs_clkout_node('GW1N-9', 'SPINE14') == 'SPINE14'


def test_a_spine_outside_every_half_is_named_by_no_bridge_out():
    """`SPINE0..7` feed the plane, they do not come out of the bridge."""
    assert chipdb.gw5_clock_plane_half('GW5AST-138C', 'SPINE3') is None
