# `fuzz/gw5ast138c/shapes/`

One file per fuzzing shape (A..G) and per primitive row (`spec-harness.md`
§7). Created by `P0.T18`; the `ShapeSpec` type and the first shape were added
by `P0.T20`.

**This directory is append-only for Phases 1-5b.** A later phase adds its own
shape file(s) here; it must never remove or rewrite a shape file another
phase already landed.

## The types (`__init__.py`)

- `PinSpec(loc, bank, io_type, pull_mode, pull_strength, drive, extra)` — one
  used pin. `bank` is the physical IO bank of `loc`, read from the chipdb's
  `pin_bank` table for `GW5AST-LV138PG484AC1/I0`; it is never inferred from
  the port name, because the bank 6/7 policy is checked against it.
- `ScopeSpec(tiles, include_bel_attrs, include_port_nets)` — the tile set the
  `E0` comparison is restricted to (`P0.T23`), derived from the shape's
  placement constraint.
- `ShapeSpec(name, primitive, sweep_axis, sweep_values, baseline_value, pins,
  bank_vccio, scope, rtl, top_module, ins_loc, clocks, extra_gwsh_options,
  extra_pack_flags)` — the whole shape. `primitive` is **never null** for a
  shape admitted to a batch (F6). `rtl` is a callable `(spec, sweep_value) ->
  Verilog`.

## The rules every shape obeys

- One parameter varies per run. Where the sweep is a wide integer covering
  `range(n)`, `gen.sweep_order()` emits it **Gray-coded** so adjacent runs
  differ in exactly one bit.
- The baseline of a sweep is the same design with the parameter at its
  documented default, not an empty design; block affiliation comes from a
  separate presence diff.
- **The generation-time `.cst` assertion is unconditional** and lives in
  `harness/gen.py`, not here, so a shape file cannot bypass it: every used pin
  carries `IO_TYPE`, every bank in use carries `BANK_VCCIO`, non-DDR pins are
  `IO_TYPE=LVCMOS33` with `PULL_STRENGTH=MEDIUM`, and no `LVCMOS*` appears on
  any bank 6/7 pin (`spec.md` §7.10(5)-(6), `D20a`-`D20c`). A bank/pull change
  on this silicon is a live thermal hazard (F73, PR #423).

## Running one shape

    python -m fuzz.gw5ast138c.harness.gen --design-dir <dir> --shape smoke

writes `top.v`, `top.cst` and `top.sdc` into `<dir>` — and refuses, writing
nothing, if the shape fails the `.cst` assertion.

## Shapes present

| Shape | Primitive under test | Scope tiles | Sweep |
|---|---|---|---|
| `smoke` | `DFF` (`INS_LOC "dut_dff" R2C3[0][A]`) | `[(2, 1)]` | none (single point) |
| `clocking_clkdiv` | `CLKDIV`, HCLK block 5, lane 0 (`INS_LOC "div0" BOTTOMSIDE[4]` + `(* BEL = "X117Y108/CLKDIV_0" *)`) | `[(117, 108)]` | `DIV_MODE` over the nine UG306E p.25 values |
| `clocking_clkdiv_baseline` | `CLKDIV`, same pinning, documented default `DIV_MODE="2"` | `[(117, 108)]` | none (the sweep's own baseline run) |
| `clocking_clkdiv_free` | `CLKDIV`, placement free on both flows | `[(117, 108)]` | none (the `E0` control of `clocking_clkdiv`; `diff` by construction) |
| `clocking_clkdiv2` | `CLKDIV2` -> `CLKDIV` chain, HCLK block 5 | `[(117, 108)]` | `(lane, RESETN)`; lane parity selects the CLKDIV2 input path |
| `clocking_clkdiv2_free` | same chain, placement free on both flows | `[(117, 108)]` | none (the `E0` control of `clocking_clkdiv2`) |

## Two rules the P1 clocking shapes added

* **`ShapeSpec.ins_loc` may be a callable** `(spec, sweep_value) -> dict`, so a
  shape can sweep the placement itself (`clocking_clkdiv2` sweeps the four
  CLKDIV2 lanes of one HCLK block).  A plain dict is unchanged.
* **`gen.run` writes two `.cst` files**: `top.cst` for the vendor and
  `top-open.cst`, identical minus the `INS_LOC` block, for the open flow.
  MEASURED: `nextpnr-himbaechel`'s reader (`cst.cc:130-140`) accepts only
  `{TOP,RIGHT,BOTTOM,LEFT}SIDE[0|1]`, so the 138C's own `SIDE[0~7]` spelling
  (SUG1018-1.7E Table 2-2) reaches the placement-macro branch and `log_error`s
  the run.  The open flow is pinned by the RTL `(* BEL = ... *)` attribute
  instead.  `openflow.run_openflow` prefers `top-open.cst` when it exists.
* **A config-role pin needs `PinSpec.config_role_ack`**, a MEASURED
  justification string, or `gen.py` still refuses it.  The refusal is not
  weakened: it now takes evidence to lift, and the evidence is printed into
  the `.cst`.
