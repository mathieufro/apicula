"""The Arora V delay line is one enumerated attribute, not seven one-bit ones.

MEASURED on the GW5AST-138C over 28 vendor bitstreams (`P3.T21`/`P3.T22`): the
whole 0..255 static step lives in `IOLOGIC` attribute 118, `C_STATIC_DLY`,
whose value ids the device's own `logicinfo` table carries -- `2` for step 1
and `1000 + n` for every `n >= 2`.  The pre-5A `DELAY_DEL0`..`DELAY_DEL6` map
this packer inherited addresses attributes this die does not use, so it wrote
no delay bit at all and refused every step with bit 7 set for want of a
`DELAY_DEL7` that was never the question.
"""
import os

import pytest

from apycula import attrids, chipdb, gowin_pack

DEVICE = "GW5AST-138C"

#: The pad tile of the measured `IODELAY`, and the row its step lands in.
TILE = (108, 52)
DELAY_ROW = 21
#: Step bit `i` -> fuse column, MEASURED from the 28-point sweep.
DELAY_COLUMNS = {i: 3 + i for i in range(8)}


@pytest.fixture(scope="module")
def db():
    path = os.path.join(os.path.dirname(gowin_pack.__file__),
                        f"{DEVICE}.msgpack.xz")
    if not os.path.exists(path):  # pragma: no cover - build it first
        pytest.skip(f"{DEVICE}.msgpack.xz absent; run apycula.chipdb_builder")
    return gowin_pack.ChipDB(DEVICE).db


def _fuses(db, attrvals):
    av = set()
    for attr, val in attrvals:
        vid = val if isinstance(val, int) else attrids.iologic_attrvals[val]
        chipdb.add_attr_val(db, "IOLOGIC", av,
                            attrids.iologic_attrids[attr], vid)
    ttyp = db[TILE[0], TILE[1]].ttyp
    return {tuple(c) for c in chipdb.get_shortval_fuses(db, ttyp, av,
                                                       "IOLOGICA")}


def test_the_value_ids_are_the_ones_the_device_table_carries(db):
    """255 non-zero steps: `2` for step 1, `1000 + n` above it."""
    ids = {v for (attr, v) in db.logicinfo["IOLOGIC"] if attr == 118}
    assert ids == {2} | {1000 + n for n in range(2, 256)}
    assert {gowin_pack.GW5AST_138C.c_static_dly_value(n)
            for n in range(1, 256)} == ids


@pytest.mark.parametrize("bit", sorted(DELAY_COLUMNS))
def test_each_step_bit_programs_its_measured_fuse(db, bit):
    """Including bit 7, which is fuse-backed here and was refused before."""
    step = 1 << bit
    value = gowin_pack.GW5AST_138C.c_static_dly_value(step)
    added = _fuses(db, [("C_STATIC_DLY", value)]) - _fuses(db, [])
    assert added == {(DELAY_ROW, DELAY_COLUMNS[bit])}


def test_step_zero_programs_nothing():
    """The sweep's baseline moves no bit, so the attribute has no row for it."""
    assert gowin_pack.GW5AST_138C.delay_step_attrs(
        gowin_pack.GW5AST_138C, format(0, "08b")) == []


def test_a_step_becomes_one_attribute_not_seven():
    attrvals = gowin_pack.GW5AST_138C.delay_step_attrs(
        gowin_pack.GW5AST_138C, format(152, "08b"))
    assert [(av.attr, av.val) for av in attrvals] == [("C_STATIC_DLY", 1152)]


def test_the_enable_set_is_the_one_the_vendor_programs(db):
    """`CLKOMUX` costs a fuse the vendor never sets on a delay point."""
    clkomux = _fuses(db, [("CLKOMUX", "ENABLE")]) - _fuses(db, [])
    assert clkomux, "CLKOMUX would be free, and this test would prove nothing"

    class _Cell:
        attrs = {"IODELAY": "IN"}

    class _Bel:
        cell = _Cell()

    attrvals = gowin_pack.GW5AST_138C.iodelay_enable_attrs(
        gowin_pack.GW5AST_138C, _Bel())
    assert [(av.attr, av.val) for av in attrvals] == [("INDEL", "ENABLE")]


def test_the_pre_5a_families_keep_the_delay_del_map():
    """`S3`: nothing changes for a device whose delay line is the old one."""
    assert gowin_pack.Device.DELAY_STEP_BITS == 7
    attrvals = gowin_pack.Device.delay_step_attrs(
        gowin_pack.Device, format(5, "08b"))
    assert [av.attr for av in attrvals] == ["DELAY_DEL0", "DELAY_DEL2"]
