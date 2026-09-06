// GW5AST-138C hard PLL parameter header (P1.T39).
//
// This is the Phase-1 -> Phase-4/Phase-7 stub: one reference PLL operating
// point for the board's 50 MHz reference clock, measured against the vendor
// oracle and admitted by the packer's own datasheet checks. Phase 1 owns
// this file's content; Phases 4 and 7 `include it and must not rewrite it --
// a consumer that needs a different operating point raises a coordination
// note instead of editing here.
//
// Primitive: `PLL`, not `PLLA` -- D96 measured that the GW5AST-138C has no
// PLLA resource (vendor RP0008 "There is no PLLA resource in current
// device"; UG306E lists PLLA for GW5A-25 only). The divider algebra below
// (Fpfd = Fclkin/IDIV, Fclkfb = Fpfd*FBDIV, Fvco = Fclkfb*MDIV,
// Fclkout0 = Fvco/ODIV0) is `apycula/gowin_pll.py`'s `plla_freqs()`, shared
// by both primitives' internal-feedback path.
//
// Values measured by:
//   - evidence/plla/sites-138c.md section 8 (P1.T19 site trace): this exact
//     operating point (FCLKIN 50 MHz, IDIV 1, FBDIV 1, MDIV 16, ODIV0 8) was
//     placed and routed by the vendor oracle on all twelve PLL sites,
//     run id `pll-trace-pilot2-clocking_pll_trace-0000` (site `PLL_L[0]`,
//     anchor tile (27, 1)).
//   - evidence/plla/attrmap-138c.md (P1.T22): the four divider attributes
//     this point exercises -- `A_IDIV_SEL` (109), `A_FBDIV_SEL` (110),
//     `A_MDIV_SEL` (113), `A_ODIV0_SEL` (114) -- are all attributed against
//     the shipped `shortval[35]` table.
//   - `apycula/gowin_pack.py` `GW5AST_138C.get_permitted_pll_freqs()` /
//     `check_pll_fvco()` (P1.T20/P1.T21): the five-tuple
//     `(800., 1000., 5.079, 1300., 650.)` MHz (max_in, max_out, min_out,
//     max_vco, min_vco), DS1239E Table 3-18. This point's Fvco (800 MHz)
//     lands inside `[650, 1300]` MHz, its Fclkout0 (100 MHz) inside
//     `[5.079, 1000]` MHz and its Fpfd (50 MHz) inside the datasheet's
//     `[19, 81.25]` MHz PFD band.
//
// No PENDING fields: every `define below is a value this device's PLL sweep
// has already measured and attributed (P1.T17-T22, T19 site trace, T23
// batch A). Batches B/C/D (P1.T41-T43) extend the ODIV/MDIV/DYN attribution
// campaign to more operating points; they do not change this single
// reference point's already-measured values, so nothing here is deferred to
// them.
//
// Stated non-goal (verbatim, `P1.T24`'s summary / blueprint P1.T24 HOW):
// PLLA cannot synthesize 24.576 / 49.152 MHz from the 50 MHz board reference
// at any Fvco in [650, 1300] MHz, fractional dividers included, because the
// achievable set contains no factor of 5^3 -- a carrier-board fact, not a
// toolchain gap (spec-primitives.md section 1).

`ifndef GW5AST_138C_PLL_VH
`define GW5AST_138C_PLL_VH

`define GW5AST_138C_PLL_FCLKIN_MHZ   50.0
`define GW5AST_138C_PLL_IDIV_SEL     1
`define GW5AST_138C_PLL_FBDIV_SEL    1
`define GW5AST_138C_PLL_MDIV_SEL     16
`define GW5AST_138C_PLL_ODIV0_SEL    8
`define GW5AST_138C_PLL_CLKOUT0_MHZ  100.0
`define GW5AST_138C_PLL_FVCO_MHZ     800.0

`endif // GW5AST_138C_PLL_VH
