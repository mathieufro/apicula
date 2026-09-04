"""Test-design generator: `top.v` + `top.cst` + `top.sdc` from a shape spec.

Module rooting is fixed: this module is always addressed as
`fuzz.gw5ast138c.harness.gen` and run from `$FL/apicula`; it never depends on
cwd -- the design directory is always passed explicitly via `--design-dir`
(`spec-harness.md` §1, `spec.md` V5/V6).

**The generation-time `.cst` assertion is unconditional** (`spec.md`
§7.10(5)-(6), `D20a`-`D20c`, `spec-harness.md` §7).  Before a single byte is
written, every used pin must carry `IO_TYPE`, every bank in use must carry
`BANK_VCCIO`, non-DDR pins must be `IO_TYPE=LVCMOS33` with
`PULL_STRENGTH=MEDIUM`, and **no `LVCMOS*` may appear on any bank 6/7 pin**.
That is the same assertion the Hardware Gate runs, applied before a shape is
admitted to a batch.  A bank/pull change on this silicon is a **live thermal
hazard** (F73, PR #423), so the assertion has no opt-out and no flag.
"""
import argparse
import importlib
import os
import sys
from pathlib import Path

from ..shapes import DDR_BANKS, DEFAULT_IO_TYPE, DEFAULT_PULL_STRENGTH

#: Default root of the (git-ignored) data store; overridable for tests.
DATASTORE_DEFAULT = "/Users/alex/fine-line-data/open-toolchain-gw5ast"


class ShapeSpecError(Exception):
    """Base class for every refusal to generate a design."""


class CstDefaultError(ShapeSpecError):
    """A used pin or bank is missing a mandatory `.cst` default (`D20a`)."""


class BankPolicyError(ShapeSpecError):
    """An IO configuration of the class PR #423 identified (`D20b`/`D20c`).

    Raised, in particular, for any `LVCMOS*` value on a bank 6/7 pin.  This is
    a thermal-safety refusal, not a style check.
    """


def datastore_root():
    """Root of the data store; `$FL_DATASTORE` wins if set."""
    return Path(os.environ.get("FL_DATASTORE", DATASTORE_DEFAULT))


def load_shape(name):
    """Import `fuzz.gw5ast138c.shapes.<name>` and return its `SPEC`."""
    module = importlib.import_module("fuzz.gw5ast138c.shapes." + name)
    return module.SPEC


# --------------------------------------------------------------------------
# The unconditional .cst assertion
# --------------------------------------------------------------------------
def assert_cst_defaults(spec):
    """Raise on the first violation; return `[]` when the spec is clean.

    Returned for symmetry with the Hardware Gate's collector: a clean spec
    yields an empty error list, a dirty one never returns at all.
    """
    for port, pin in spec.pins.items():
        # (c) bank 6/7 first: an LVCMOS* there is the thermal hazard, and it
        # must not be masked by the non-DDR default rule below.
        if pin.bank in DDR_BANKS:
            if pin.io_type and pin.io_type.upper().startswith("LVCMOS"):
                raise BankPolicyError(
                    "pin %r at %s: IO_TYPE=%s on bank %d -- no LVCMOS* is "
                    "permitted on a bank %s pin (D20c, F73/PR #423)"
                    % (port, pin.loc, pin.io_type, pin.bank,
                       "/".join(str(b) for b in DDR_BANKS))
                )
        # (a) every used pin carries IO_TYPE
        if not pin.io_type:
            raise CstDefaultError(
                "pin %r at %s (bank %d) has no IO_TYPE -- every used pin "
                "carries one (D20a, spec.md 7.10(5))" % (port, pin.loc, pin.bank)
            )
        # (a) every bank in use carries BANK_VCCIO
        if pin.bank not in spec.bank_vccio:
            raise CstDefaultError(
                "pin %r at %s is in bank %d, which has no BANK_VCCIO in the "
                "shape's bank_vccio table (D20a)" % (port, pin.loc, pin.bank)
            )
        # (b) non-DDR pins are LVCMOS33 with PULL_STRENGTH=MEDIUM
        if pin.bank not in DDR_BANKS:
            if pin.io_type.upper() != DEFAULT_IO_TYPE:
                raise CstDefaultError(
                    "pin %r at %s (bank %d): IO_TYPE=%s, expected %s on a "
                    "non-DDR pin (spec.md 7.10(5))"
                    % (port, pin.loc, pin.bank, pin.io_type, DEFAULT_IO_TYPE)
                )
            if (pin.pull_strength or "").upper() != DEFAULT_PULL_STRENGTH:
                raise CstDefaultError(
                    "pin %r at %s (bank %d): PULL_STRENGTH=%s, expected %s -- "
                    "the defect PR #423 fixed (D20b)"
                    % (port, pin.loc, pin.bank, pin.pull_strength,
                       DEFAULT_PULL_STRENGTH)
                )
    return []


# --------------------------------------------------------------------------
# Sweep ordering
# --------------------------------------------------------------------------
def gray(index):
    """The `index`-th Gray code."""
    return index ^ (index >> 1)


def sweep_order(spec):
    """The order the sweep's values are built in.

    Where the sweep is a wide integer covering `range(n)`, the values are
    emitted **Gray-coded** so adjacent runs differ in exactly one bit and fuse
    attribution is unambiguous (`spec-harness.md` §7).  Any other sweep is
    emitted in the order the shape declares.
    """
    values = list(spec.sweep_values)
    if values and all(isinstance(v, int) and not isinstance(v, bool) for v in values):
        if set(values) == set(range(len(values))):
            return [gray(i) for i in range(len(values))]
    return values


# --------------------------------------------------------------------------
# Rendering
# --------------------------------------------------------------------------
def render_verilog(spec, sweep_value=None):
    return spec.rtl(spec, sweep_value)


def render_cst(spec):
    """Render `top.cst`: one `IO_LOC`/`IO_PORT` pair per pin, then `INS_LOC`."""
    lines = [
        "// Generated by fuzz.gw5ast138c.harness.gen from shapes/%s.py -- do not edit."
        % spec.name,
        "// Every line below passed the unconditional generation-time .cst",
        "// assertion (spec.md 7.10(5)-(6), D20a-D20c).",
        "",
    ]
    for port in spec.pins:
        pin = spec.pins[port]
        attrs = ["IO_TYPE=%s" % pin.io_type, "PULL_MODE=%s" % pin.pull_mode]
        if pin.pull_strength:
            attrs.append("PULL_STRENGTH=%s" % pin.pull_strength)
        if pin.drive is not None:
            attrs.append("DRIVE=%d" % pin.drive)
        attrs.append("BANK_VCCIO=%s" % spec.bank_vccio[pin.bank])
        attrs.extend("%s=%s" % (k, v) for k, v in pin.extra)
        lines.append('IO_LOC  "%s" %s;' % (port, pin.loc))
        lines.append('IO_PORT "%s" %s;' % (port, " ".join(attrs)))
    if spec.ins_loc:
        lines.append("")
        for instance in spec.ins_loc:
            lines.append('INS_LOC "%s" %s;' % (instance, spec.ins_loc[instance]))
    lines.append("")
    return "\n".join(lines)


def render_sdc(spec):
    """Render `top.sdc`: one `create_clock` per declared clock port."""
    lines = [
        "# Generated by fuzz.gw5ast138c.harness.gen from shapes/%s.py -- do not edit."
        % spec.name,
    ]
    if not spec.clocks:
        lines.append("# shape %s declares no clock" % spec.name)
    for port in spec.clocks:
        period = spec.clocks[port]
        lines.append(
            "create_clock -name %s -period %g -waveform {0 %g} [get_ports {%s}]"
            % (port, period, period / 2.0, port)
        )
    lines.append("")
    return "\n".join(lines)


def run(spec, design_dir, sweep_value=None):
    """Write `top.v`, `top.cst`, `top.sdc` into `design_dir`; return the paths.

    The `.cst` assertion runs **first**: on a violation nothing is written and
    `design_dir` is not even created.
    """
    assert_cst_defaults(spec)
    if sweep_value is None and spec.sweep_values:
        sweep_value = spec.baseline_value

    verilog = render_verilog(spec, sweep_value)
    cst = render_cst(spec)
    sdc = render_sdc(spec)

    design_dir = Path(design_dir)
    design_dir.mkdir(parents=True, exist_ok=True)
    written = []
    for name, text in (("top.v", verilog), ("top.cst", cst), ("top.sdc", sdc)):
        path = design_dir / name
        path.write_text(text)
        written.append(path)
    return written


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------
def build_parser():
    """Return this module's argparse parser.

    Every harness module parser carries a required `--design-dir` so no
    harness command depends on the current working directory
    (`spec-harness.md` §1, `spec.md` V5/V6).
    """
    parser = argparse.ArgumentParser(prog="fuzz.gw5ast138c.harness.gen")
    parser.add_argument(
        "--design-dir",
        required=True,
        help="Directory holding the test design for this run (never inferred from cwd).",
    )
    parser.add_argument(
        "--shape",
        required=True,
        help="Shape name; imported as fuzz.gw5ast138c.shapes.<shape>.",
    )
    parser.add_argument(
        "--sweep-value",
        default=None,
        help="Sweep point to generate; default is the shape's baseline value.",
    )
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    spec = load_shape(args.shape)
    written = run(spec, args.design_dir, args.sweep_value)
    for path in written:
        print(path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
