"""P3.T27 — apicula upstream PR #535 ("Fix LVDS and IBUFs in one bank"), ported
to the 138C data-driven bank-resolution path.

The defect: `Device.check_io_banks` sets a bank's whole `IO_TYPE` to the LVDS
standard whenever the bank carries a true-LVDS output pair, even when that
bank has no ordinary (single-ended) output of its own. `Device.process_IBUF`
then applied that bank-wide `IO_TYPE` to *every* IBUF unconditionally --
corrupting plain single-ended IBUFs that happen to share a bank with a TLVDS
pair. Upstream's fix (apicula PR #535) makes an IBUF adopt the bank-wide
standard only when the bank actually has an ordinary output (`has_outputs`);
an input-only bank leaves each IBUF's own `IO_TYPE` (or the device's ordinary
default) alone.

These tests exercise `BankDesc`/`Device.process_IBUF`/`Device.check_io_banks`
directly, without a chipdb build or a vendor run: the coercion is a pure
Python decision over already-resolved `BankDesc`/`IoBelDesc` objects, and the
fuse translation underneath it (`chipdb.get_iob_attr_val`) is stubbed to
record the `IO_TYPE` string it was asked to translate, not to compute real
bit positions.
"""
import pytest

from apycula.gowin_pack import (
    AttrVal,
    BankDesc,
    CellDesc,
    GW5AST_138C,
    IoBelDesc,
)


class _RecordingChipDB:
    """Stands in for the real chipdb: records the last value asked for each
    IOB attribute instead of resolving it to fuse bits. `get_iob_fuses` is
    stubbed separately (see `_new_device`) since real fuse generation needs
    the built chipdb tile tables, which this task does not touch or need."""

    def __init__(self):
        self.last = {}

    def get_iob_attr_val(self, attrval: AttrVal, av: set):
        self.last[attrval.attr] = attrval.val
        av.add((attrval.attr, attrval.val))


def _new_device() -> GW5AST_138C:
    """A `GW5AST_138C` built without its real `__init__` (which requires a
    built chipdb msgpack). Only the state `check_io_banks`/`process_IBUF`
    read is set up; `default_ibuf_attrs` is left empty on purpose so
    `set_io_attrvals` contributes nothing but the explicit `IO_TYPE`/
    `BANK_VCCIO` calls this test cares about."""
    device = object.__new__(GW5AST_138C)
    device.chipdb = _RecordingChipDB()
    device.default_ibuf_attrs = []
    device.get_iob_fuses = lambda x, y, idx_str, av: []
    return device


def _tlvds_obuf_bel(name: str, idx_str: str) -> IoBelDesc:
    cell = CellDesc(name, "TLVDS_OBUF", {"DIFF": "P", "DIFF_TYPE": "TLVDS_OBUF"},
                     {"IO_TYPE": "LVDS25"}, {})
    return IoBelDesc(0, idx_str == "B", idx_str, cell, {"IS_OUTPUT": 1})


def _plain_ibuf_bel(name: str, idx_str: str, io_type: str = None) -> IoBelDesc:
    attrs = {"IO_TYPE": io_type} if io_type else {}
    cell = CellDesc(name, "IBUF", {}, attrs, {})
    return IoBelDesc(0, int(idx_str), idx_str, cell, {})


def _plain_obuf_bel(name: str, idx_str: str) -> IoBelDesc:
    cell = CellDesc(name, "OBUF", {}, {}, {})
    return IoBelDesc(0, int(idx_str), idx_str, cell, {"IS_OUTPUT": 1})


def _mixed_bank():
    """One TLVDS output pair plus two plain single-ended IBUFs, no ordinary
    OBUF -- the exact shape PR #535 describes: 'a bank has LVDS and only
    input pins' among its single-ended members."""
    bank = BankDesc(0, 0)
    bank.add_io_bel(None, _tlvds_obuf_bel("clk_p", "A"))
    bank.add_io_bel(None, _tlvds_obuf_bel("clk_n", "B"))
    ibuf1 = _plain_ibuf_bel("data0", "2")
    ibuf2 = _plain_ibuf_bel("data1", "3")
    bank.add_io_bel(None, ibuf1)
    bank.add_io_bel(None, ibuf2)
    return bank, ibuf1, ibuf2


def test_mixed_bank_true_lvds_output_does_not_set_has_outputs():
    """Sanity check on the precondition the whole defect depends on: a TLVDS
    output pair is not an ordinary output as far as bank-default resolution
    is concerned."""
    bank, _, _ = _mixed_bank()
    assert bank.has_true_lvds_outputs is True
    assert bank.has_outputs is False


def test_mixed_bank_single_ended_ibufs_keep_lvcmos_io_type():
    """The fixed rule: an input-only bank (no ordinary OBUF) leaves plain
    IBUFs on the device's ordinary default, never the bank's LVDS override.
    This is the assertion that fails against the pre-#535 `process_IBUF`
    (which unconditionally emits `bank_desc.io_type`, i.e. `LVDS25`, for
    every IBUF) and passes once `process_IBUF` special-cases the
    `not bank_desc.has_outputs` case (`apycula/gowin_pack.py:1882`)."""
    bank, ibuf1, ibuf2 = _mixed_bank()
    device = _new_device()
    device.io_banks = {0: bank}
    device.check_io_banks()

    assert bank.io_type == "LVDS25"  # the bank-wide default really is LVDS

    for ibuf in (ibuf1, ibuf2):
        device.chipdb.last.clear()
        device.process_IBUF(bank, ibuf)
        assert device.chipdb.last["IO_TYPE"] == "LVCMOS33", (
            f"{ibuf.cell.name} was coerced to the bank's LVDS standard "
            f"({device.chipdb.last['IO_TYPE']}) instead of keeping its own "
            "single-ended default -- the PR #535 defect"
        )


def test_mixed_bank_ibuf_keeps_explicit_override_over_bank_default():
    """An IBUF with its own explicit `IO_TYPE` in an input-only LVDS bank
    keeps that explicit value, not the bank's LVDS override and not the
    device default either -- `bel.cell.attrs.get('IO_TYPE', ...)` reads the
    pin's own attribute first."""
    bank = BankDesc(0, 0)
    bank.add_io_bel(None, _tlvds_obuf_bel("clk_p", "A"))
    bank.add_io_bel(None, _tlvds_obuf_bel("clk_n", "B"))
    ibuf = _plain_ibuf_bel("data0", "2", io_type="LVCMOS25")
    bank.add_io_bel(None, ibuf)

    device = _new_device()
    device.io_banks = {0: bank}
    device.check_io_banks()

    device.process_IBUF(bank, ibuf)
    assert device.chipdb.last["IO_TYPE"] == "LVCMOS25"


def test_single_type_bank_ibuf_io_type_fuse_unchanged():
    """Guard: a bank with no LVDS at all (the overwhelming majority of real
    designs) must resolve to exactly the same `IO_TYPE` fuse value it did
    before this fix -- `has_outputs` is irrelevant when the bank was never
    going to be coerced to LVDS in the first place, whichever branch of
    `process_IBUF` runs."""
    bank = BankDesc(0, 0)
    ibuf1 = _plain_ibuf_bel("in0", "0")
    ibuf2 = _plain_ibuf_bel("in1", "1")
    bank.add_io_bel(None, ibuf1)
    bank.add_io_bel(None, ibuf2)

    device = _new_device()
    device.io_banks = {0: bank}
    device.check_io_banks()

    assert bank.has_outputs is False
    assert bank.io_type == "LVCMOS33"  # GW5AST_138C.get_default_io_type()

    for ibuf in (ibuf1, ibuf2):
        device.chipdb.last.clear()
        device.process_IBUF(bank, ibuf)
        assert device.chipdb.last["IO_TYPE"] == "LVCMOS33"


def test_single_type_bank_with_output_ibuf_io_type_fuse_unchanged():
    """Guard, output-bearing variant: a bank with an ordinary OBUF (no LVDS
    anywhere) must still route its IBUFs through the bank-wide `IO_TYPE` --
    exactly the `has_outputs` branch the fix leaves untouched."""
    bank = BankDesc(0, 0)
    obuf = _plain_obuf_bel("out0", "0")
    ibuf = _plain_ibuf_bel("in0", "1")
    bank.add_io_bel(None, obuf)
    bank.add_io_bel(None, ibuf)

    device = _new_device()
    device.io_banks = {0: bank}
    device.check_io_banks()

    assert bank.has_outputs is True

    device.process_IBUF(bank, ibuf)
    assert device.chipdb.last["IO_TYPE"] == bank.io_type == "LVCMOS33"


def test_bank_with_conflicting_explicit_io_types_is_refused_by_name():
    """Negative case: a bank the vendor genuinely refuses stays refused. Two
    IBUFs pinned to different explicit standards in the same bank hit
    `BankDesc.check_or_set_attr`'s own conflict guard -- PR #535 only relaxes
    *default* propagation into unconfigured IBUFs, it must not paper over an
    explicit, irreconcilable per-pin conflict."""
    bank = BankDesc(0, 0)
    ibuf1 = _plain_ibuf_bel("data0", "0", io_type="LVCMOS33")
    bank.add_io_bel(None, ibuf1)

    ibuf2 = _plain_ibuf_bel("data1", "1", io_type="LVCMOS18")
    with pytest.raises(Exception, match=r"IO_TYPE conflict"):
        bank.add_io_bel(None, ibuf2)
