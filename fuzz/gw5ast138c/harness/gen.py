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

The same pass also enforces the vendor rules `P0.T19` measured against
`gw_sh` directly, so `gen.py` -- not a hand-tuned shape file -- is the single
source of truth for them: no pin may sit at a config-role package location
(`ConfigPinError`; `config_role_of_loc`/`CONFIG_ROLE_PINS_PG484`), `DRIVE` may
only be set on an output pin (`DriveDirectionError`; `CT1108`), and every
`INS_LOC` instance path must be the flat instance name, never module-qualified
(`InsLocError`; `CT1135`).
"""
import argparse
import importlib
import os
import re
import sys
from pathlib import Path

from . import paths
from ..shapes import DDR_BANKS, DEFAULT_IO_TYPE, DEFAULT_PULL_STRENGTH

#: Default root of the (git-ignored) data store; `$DATASTORE` overrides it.
DATASTORE_DEFAULT = paths.datastore()


class ShapeSpecError(Exception):
    """Base class for every refusal to generate a design."""


class CstDefaultError(ShapeSpecError):
    """A used pin or bank is missing a mandatory `.cst` default (`D20a`)."""


class BankPolicyError(ShapeSpecError):
    """An IO configuration of the class PR #423 identified (`D20b`/`D20c`).

    Raised, in particular, for any `LVCMOS*` value on a bank 6/7 pin.  This is
    a thermal-safety refusal, not a style check.
    """


class DriveDirectionError(ShapeSpecError):
    """`DRIVE` was set on a non-output pin.

    Measured by `P0.T19`'s `V4` run: `gw_sh` raises `CT1108 Illegal port
    attribute value specified 'DRIVE = 8'` (`DRIVE=NONE` included) for any
    `DRIVE` attribute on an input port.  `DRIVE` is legal only on outputs.
    """


class InsLocError(ShapeSpecError):
    """An `INS_LOC` instance path was not the flat instance name.

    Measured by `P0.T19`'s `V4` run: `gw_sh` resolves only the flat instance
    name (`dut_dff`) and raises `CT1135 Can't find object named 'top.dut_dff'`
    on a module-qualified one.
    """


class ConfigPinError(ShapeSpecError):
    """A pin location is reserved for a chip config-role function.

    A shape must never claim a pin that the vendor tooling treats as a
    configuration pin (`EMCCLK`, `SGCLK*`, `RECONFIG_N`, `READY`, `DONE`,
    JTAG `TCK`/`TMS`/`TDI`/`TDO`, `MSPI*`/`SSPI*`) -- doing so either fails
    generation-time placement or silently reprograms a config function,
    neither of which is a plain I/O test.
    """


#: Package locations on `GW5AST-LV138PG484AC1/I0` (package `PG484`) measured
#: or documented to carry a config-role function rather than plain I/O.  This
#: is the fallback used when no chipdb pin-function table is loadable
#: (`config_role_of_loc` tries the chipdb first) -- it is **not** exhaustive,
#: but every location listed here is a confirmed config pin and must never be
#: claimed by a shape (`P0.T19`: `V22` = `EMCCLK` raised a placement failure
#: when used as a plain smoke pin; `Y12`/`U15` = `SGCLK` likewise).
CONFIG_ROLE_PINS_PG484 = {
    "V22": "EMCCLK",
    "Y12": "SGCLK",
    "U15": "SGCLK",
}


def config_role_of_loc(loc):
    """Return the config-role name of package location `loc`, or `None`.

    Measured (`P0.T20`): the saved chipdb (`$DATASTORE/chipdb/**/*.bin`) does
    not load in this environment (`lzma.LZMAError: Input format not supported
    by decoder`) and its `io_cfg` table is keyed by internal IO name (e.g.
    `IOB53A`), not by package location, so there is no cheap location-keyed
    lookup to fall back to at runtime without building one offline first.
    Rather than trust a best-effort chipdb read that could silently return
    `None` on a key-namespace mismatch (worse than not checking at all), this
    always consults the documented `CONFIG_ROLE_PINS_PG484` denylist. Update
    that table -- not this function -- when a location-keyed chipdb export
    becomes available.
    """
    return CONFIG_ROLE_PINS_PG484.get(loc)


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
def ins_loc_of(spec, sweep_value=None):
    """The shape's vendor placement constraints for one sweep point.

    `ShapeSpec.ins_loc` is a `{instance: site}` dict, or a callable
    `(spec, sweep_value) -> dict` for a shape whose swept parameter **is** the
    placement.  Without the callable form a placement sweep is impossible:
    `ShapeSpec` is frozen and `gen.run` renders one `.cst` per sweep point from
    one spec, so `P1.T15`'s four CLKDIV2 lanes would need four shape files
    (measured while writing `shapes/clocking_clkdiv2.py`).
    """
    value = spec.ins_loc
    if callable(value):
        value = value(spec, sweep_value)
    return dict(value or {})


def assert_cst_defaults(spec, sweep_value=None):
    """Raise on the first violation; return `[]` when the spec is clean.

    Returned for symmetry with the Hardware Gate's collector: a clean spec
    yields an empty error list, a dirty one never returns at all.
    """
    for port, pin in spec.pins.items():
        # (d) no config-role pin, ever -- checked before anything else so a
        # config pin never even gets a chance to look like a clean I/O.
        role = config_role_of_loc(pin.loc)
        if role is not None and not getattr(pin, "config_role_ack", ""):
            raise ConfigPinError(
                "pin %r at %s is a config-role pin (%s) -- a shape must never "
                "claim a config pin as plain I/O (measured, P0.T19/P0.T20)"
                % (port, pin.loc, role)
            )
        # (e) DRIVE is legal on outputs only (CT1108, measured P0.T19).
        if pin.drive is not None and pin.direction != "output":
            raise DriveDirectionError(
                "pin %r at %s: DRIVE=%s set on a %s pin -- DRIVE is legal "
                "only on outputs (CT1108, P0.T19)"
                % (port, pin.loc, pin.drive, pin.direction)
            )
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
    # (f) every INS_LOC instance path is the flat instance name -- gw_sh
    # resolves only that (CT1135, measured P0.T19).
    for instance in ins_loc_of(spec, sweep_value):
        if "." in instance:
            raise InsLocError(
                "INS_LOC instance %r is not a flat instance name -- gw_sh "
                "raises CT1135 Can't find object named %r (P0.T19); use the "
                "flat name (e.g. %r)"
                % (instance, instance, instance.rsplit(".", 1)[-1])
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


#: The `INS_LOC` site spellings `nextpnr-himbaechel`'s `.cst` reader accepts
#: (`cst.cc`): the CLS form, the two-index HCLK side form, and -- since the PLL
#: work landed its macro table -- the placement-macro form.  A site outside
#: this set is emitted for the vendor and withheld from the open flow, which
#: would `log_error` the whole run on it rather than ignore the line.
OPEN_FLOW_INS_LOC_FORMS = (
    re.compile(r"^R\d+C\d+\[\d\]\[[AB]\]$"),
    re.compile(r"^(TOP|RIGHT|BOTTOM|LEFT)SIDE\[[01]\]$"),
    re.compile(r"^PLL_[LRB]\[\d\]$"),
)


def open_flow_reads_ins_loc(site):
    """Can `nextpnr-himbaechel`'s `.cst` reader resolve this site?"""
    return any(form.match(site) for form in OPEN_FLOW_INS_LOC_FORMS)


def render_cst(spec, sweep_value=None, with_ins_loc=True):
    """Render a `.cst`: one `IO_LOC`/`IO_PORT` pair per pin, then `INS_LOC`.

    `with_ins_loc=False` renders the **open-flow** copy (`top-open.cst`).
    Measured on this device (`nextpnr-himbaechel` `cst.cc:130-140`): the reader
    accepts only `{TOP,RIGHT,BOTTOM,LEFT}SIDE[0|1]`, so the 138C's own
    `SIDE[0~7]` spelling (SUG1018-1.7E Table 2-2, row `GW5A(S)(T)-138`) falls
    through to the placement-macro branch and `log_error`s the whole run with
    `Unknown placement macro BOTTOMSIDE`.  The vendor needs the line and the
    open flow cannot read it, so the two flows get two files; the open flow is
    pinned by the RTL `(* BEL = ... *)` attribute instead, which nextpnr does
    honour.  Fixing the reader is a nextpnr change and is not this task's.

    An `ins_loc` **value** may also be a callable `(sweep_value) -> site`, for
    a shape whose swept axis *is* the placement (`P1.T19` sweeps one PLL over
    the twelve `PLL_{L,R,B}[n]` sites).  Plain strings, the only form Phase 0
    used, are passed through unchanged, so this is additive.
    """
    lines = [
        "// Generated by fuzz.gw5ast138c.harness.gen from shapes/%s.py -- do not edit."
        % spec.name,
        "// Every line below passed the unconditional generation-time .cst",
        "// assertion (spec.md 7.10(5)-(6), D20a-D20c).",
    ]
    for port in spec.pins:
        ack = getattr(spec.pins[port], "config_role_ack", "")
        if ack:
            lines.append("// config-role pin %s (%s) claimed on MEASURED "
                         "evidence: %s"
                         % (spec.pins[port].loc,
                            config_role_of_loc(spec.pins[port].loc), ack))
    lines.append("")
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
    ins_loc = ins_loc_of(spec, sweep_value)
    if not with_ins_loc:
        ins_loc = {i: s for i, s in ins_loc.items()
                   if open_flow_reads_ins_loc(
                       s(sweep_value) if callable(s) else s)}
    if ins_loc:
        lines.append("")
        for instance in ins_loc:
            site = ins_loc[instance]
            if callable(site):
                site = site(sweep_value)
            lines.append('INS_LOC "%s" %s;' % (instance, site))
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
    if sweep_value is None and spec.sweep_values:
        sweep_value = spec.baseline_value
    assert_cst_defaults(spec, sweep_value)

    verilog = render_verilog(spec, sweep_value)
    cst = render_cst(spec, sweep_value)
    open_cst = render_cst(spec, sweep_value, with_ins_loc=False)
    sdc = render_sdc(spec)

    design_dir = Path(design_dir)
    design_dir.mkdir(parents=True, exist_ok=True)
    written = []
    for name, text in (("top.v", verilog), ("top.cst", cst),
                       ("top-open.cst", open_cst), ("top.sdc", sdc)):
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
