"""The 138C's dual-purpose-pin attribute emission (`P2.T27`/`P2.T29`).

`get_pins_attr_vals` is the one place a device says which configuration pins
it hands to the fabric.  It reads nothing but the parsed command line, so the
tests below call it on a stub carrying only `cli_args.args` -- no chipdb, no
device file, no bitstream.

The 138C's two measured gaps this file guards:

* `--sspi_as_gpio` was accepted on the command line and then dropped on the
  floor, because the 138C override had no `sspi` branch at all while both
  sibling GW5 devices emit `SSPI_AS_GPIO` unconditionally;
* `attrids.cfg_attrids` defines `CPU_AS_GPIO_2` for this device and the
  override emitted only `CPU_AS_GPIO_0` and `CPU_AS_GPIO_1`.

The `CPU_AS_GPIO_2` count is deliberately a range: `P2.T29`'s sweep is what
narrows it, and until a bit is measured for it the device must not emit an
attribute whose fuse nobody has seen -- a used pin's IO configuration is the
PR #423 thermal class.
"""
import itertools
import types

import pytest

from apycula import attrids
from apycula.gowin_pack import AttrVal, GW5A_25A, GW5AST_138C

#: Every dual-purpose option `CliArgs` accepts, in its declaration order.
OPTIONS = ("jtag", "sspi", "mspi", "ready", "done", "reconfign", "cpu", "i2c")


def stub(**on):
    """A `self` for `get_pins_attr_vals`: the parsed command line and nothing else."""
    args = types.SimpleNamespace(
        **{f"{opt}_as_gpio": on.get(opt, False) for opt in OPTIONS})
    return types.SimpleNamespace(cli_args=types.SimpleNamespace(args=args))


def test_138c_sspi_as_gpio_emits_attrval():
    attrvals = GW5AST_138C.get_pins_attr_vals(stub(sspi=True))
    assert attrvals.count(AttrVal('SSPI_AS_GPIO', 'YES')) == 1


def test_138c_sspi_as_gpio_is_off_by_default():
    """The 138C gates SSPI on the flag; the siblings emit it unconditionally."""
    assert AttrVal('SSPI_AS_GPIO', 'YES') not in GW5AST_138C.get_pins_attr_vals(stub())


def test_138c_cpu_as_gpio_emits_two_or_three_attrvals():
    emitted = [av for av in GW5AST_138C.get_pins_attr_vals(stub(cpu=True))
               if av.attr.startswith('CPU_AS_GPIO')]
    assert 2 <= len(emitted) <= 3
    assert [av.attr for av in emitted] == sorted({av.attr for av in emitted})
    assert all(av.attr in attrids.cfg_attrids for av in emitted)


def test_138c_cpu_as_gpio_2_only_with_a_measured_bit():
    """Attrid 37 is emitted only once the sweep has seen a bit move for it.

    `P2.T29` resolves this either way; the assertion is that the emission and
    the measurement agree, never that one of them is right.
    """
    from fuzz.gw5ast138c.shapes import dualpin

    emitted = {av.attr for av in GW5AST_138C.get_pins_attr_vals(stub(cpu=True))}
    assert ('CPU_AS_GPIO_2' in emitted) == dualpin.CPU_AS_GPIO_2_SETS_A_BIT


def test_25a_pins_attr_vals_unchanged():
    """The sibling device is untouched, for all 2**3 flag combinations tested."""
    for jtag, cpu, i2c in itertools.product((False, True), repeat=3):
        attrvals = GW5A_25A.get_pins_attr_vals(stub(jtag=jtag, cpu=cpu, i2c=i2c))
        expected = []
        if jtag:
            expected.append(AttrVal('JTAG_AS_GPIO', 'YES'))
        expected.append(AttrVal('SSPI_AS_GPIO', 'YES'))
        if i2c:
            expected.append(AttrVal('I2C_AS_GPIO', 'YES'))
        if cpu:
            expected.append(AttrVal('CPU_AS_GPIO_25', 'YES'))
        assert attrvals == expected
