"""The GW5AST-138C fuzzing harness package (P0.T18, `spec-harness.md` §1).

Module rooting is fixed: everything runs from `$FL/apicula` and is addressed
as `fuzz.gw5ast138c.harness.<module>`. No harness command depends on cwd; the
design directory is always an explicit argument (`--design-dir`).

Modules (each a stub until its owning task lands):
    __main__    entry point: one shape, one sweep, one batch (P0.T19+)
    gen         test-design generator: RTL + .cst + .sdc from a shape spec (P0.T20+)
    oracle      gw_sh driver: writes run.tcl, runs it, collects artefacts (P0.T19)
    openflow    yosys -> nextpnr-himbaechel -> gowin_pack for the same inputs (P0.T21+)
    equiv       the equivalence checker, spec-harness.md §5 (P0.T23-P0.T26, P0.T33)
    attribute   fuse attribution: which bits moved, in which tile, for which attr (P0.T22+)
    evidence    appends one row per run to the evidence table, spec-harness.md §6 (P0.T28)
    selftest    injects a single known fuse difference and asserts it is found (P0.T29+)
"""
