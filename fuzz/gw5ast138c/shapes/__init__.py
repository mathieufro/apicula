"""Fuzzing shapes for the GW5AST-138C harness (`spec-harness.md` §7).

One file per shape / primitive row.  This directory is **append-only** for
Phases 1-5b: later phases add shape files here and must not remove or rewrite
an existing one.  See `README.md` in this directory.

This module (P0.T18 skeleton, `ShapeSpec` added by P0.T20) holds the shape
description types every shape file instantiates and `gen.py` renders:

    PinSpec     one used pin: port, package location, bank and its IO settings
    ScopeSpec   the tile set the `E0` comparison is restricted to (`P0.T23`)
    ShapeSpec   the whole shape: primitive under test, sweep, pins, banks

The types carry *description only*.  Every policy assertion -- the
generation-time `.cst` assertion of `spec.md` §7.10(5)-(6) / `D20a`-`D20c` --
lives in `harness/gen.py`, so a shape file cannot bypass it by constructing a
spec directly.
"""
from dataclasses import dataclass, field
from typing import Callable, Optional

__all__ = [
    "PinSpec",
    "ScopeSpec",
    "ShapeSpec",
    "DDR_BANKS",
    "DEFAULT_IO_TYPE",
    "DEFAULT_PULL_STRENGTH",
]

#: Banks that carry the DDR3 interface on this die (`D20c`, `D54`).  A
#: `LVCMOS*` value on any pin of these banks is a **live thermal hazard**
#: (F73, PR #423), never a cosmetic defect.
DDR_BANKS = (6, 7)

#: The measured apicula defaults for this device on non-DDR pins
#: (`spec.md` §7.10(5): `gowin_pack.py:6829-6831` / `:5391-5392`).
DEFAULT_IO_TYPE = "LVCMOS33"
DEFAULT_PULL_STRENGTH = "MEDIUM"


@dataclass(frozen=True)
class PinSpec:
    """One used pin of a shape.

    `bank` is the physical IO bank the package location sits in, taken from
    the chipdb's `pin_bank` table for `GW5AST-LV138PG484AC1/I0` -- it is what
    the bank-6/7 policy is checked against, so it is never inferred from the
    port name.

    `direction` is `"input"` or `"output"` -- it is what the `DRIVE`-on-output-
    only rule (measured `P0.T19`: `CT1108 Illegal port attribute value
    specified 'DRIVE = 8'` on an input) is checked against, so `gen.py` can
    refuse a `drive` value on an input pin instead of silently emitting it.
    """

    loc: str                                   # package location, e.g. "V22"
    bank: int                                  # physical IO bank of `loc`
    io_type: Optional[str] = DEFAULT_IO_TYPE   # None => the pin has no IO_TYPE
    pull_mode: str = "NONE"
    pull_strength: Optional[str] = DEFAULT_PULL_STRENGTH
    drive: Optional[int] = 8
    direction: str = "input"                   # "input" | "output" (D37/F-CT1108)
    extra: tuple = ()                          # ((key, value), ...) verbatim
    #: A MEASURED justification for claiming a package location that
    #: `gen.config_role_of_loc` calls a config-role pin.  Empty (the default)
    #: keeps the refusal absolute.  A non-empty string means: this exact pin
    #: has been run through the vendor on this device and the config role did
    #: not fire -- the string says which runs measured it, so the exemption is
    #: evidence, not an opt-out flag.  `gen.py` prints it into the `.cst`.
    config_role_ack: str = ""


@dataclass(frozen=True)
class ScopeSpec:
    """The tile set the `E0` comparison is restricted to (`P0.T23`).

    Derived from the shape's placement constraint: a shape whose primitive
    under test is pinned by an `INS_LOC` line names exactly the tile that
    `INS_LOC` selects, so the surrounding context stages are not compared.
    """

    tiles: list                                # [(x, y), ...], 0-based
    include_bel_attrs: bool = True
    include_port_nets: bool = True


@dataclass(frozen=True)
class ShapeSpec:
    """A complete vendor project differing from its baseline in one parameter.

    `primitive` is **never null** for a shape admitted to a batch (F6): the
    scope rule of `P0.T23` is undefined without it.
    """

    name: str
    primitive: str
    sweep_axis: str
    sweep_values: list
    baseline_value: object
    pins: dict                                 # port name -> PinSpec
    bank_vccio: dict                           # bank number -> VCCIO string
    scope: ScopeSpec
    rtl: Callable                              # (spec, sweep_value) -> Verilog
    top_module: str = "top"
    #: Vendor placement constraints: `{flat instance name: site}`, rendered as
    #: `INS_LOC` lines into the **vendor** `.cst` only.  May also be a callable
    #: `(spec, sweep_value) -> dict`, which is what lets a shape sweep the
    #: placement itself (`P1.T15` sweeps the four CLKDIV2 lanes of one HCLK
    #: block); a plain dict is unchanged.
    ins_loc: object = field(default_factory=dict)
    clocks: dict = field(default_factory=dict)   # port -> period in ns
    extra_gwsh_options: list = field(default_factory=list)
    extra_pack_flags: list = field(default_factory=list)
