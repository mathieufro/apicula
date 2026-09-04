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
