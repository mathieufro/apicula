"""P1.T28 -- re-derive the 138C DQCE/DCS tile-hosting cells with vendor compiles.

Method, same as `evidence/clocking/probe_hclk.py` (P1.T04, the maintainer's
own: `apycula/chipdb.py:2758-2763`): build a baseline with no DQCE, and
designs with an increasing count of `DQCE` instances present, then
`presence_diff` the vendor bitstreams. The tile(s) whose fuses move between
`n` and `n+1` instances are the cells the vendor toolchain actually uses to
host the (n+1)-th DQCE -- independent of apicula's own `chipdb.py` tile-type
search, which is exactly the thing being checked.

Two sequences of 4 (n_dqce = 1..4), 8 oracle runs total:

  * sequence A ("presence probe"): CE for instance i is a distinct
    combinational function of two IO pins (`key`, `rst_n`).
  * sequence B ("fuse probe"): the same 4 designs, but with the CE
    assignment permuted/negated -- if the vendor keeps re-using the *same*
    physical cell per instance index regardless of which combinational
    signal drives CE, that confirms (`chipdb.py`'s existing comment) that
    the CE **wire choice** is a spine/index property, not a per-build
    routing accident.

Every run is one oracle run against the `D`-budget and is appended to
`$OTC/evidence/_budget/clocking-runs.tsv` by the caller script
(`evidence/dqce/run_probe.py`), not by this module -- this module only knows
how to render the RTL/CST and does not touch the budget ledger itself.

Run from `$FL_WT/apicula` (this worktree): see `evidence/dqce/run_probe.py`.
"""
import os

# Known-good, non-config-role, bank-4/5 pins for GW5AST-LV138PG484AC1/I0,
# measured by P0.T19/T20 and reused from `fuzz/gw5ast138c/shapes/smoke.py`.
CST = """IO_LOC  "clk" AA9;
IO_PORT "clk" IO_TYPE=LVCMOS33 PULL_MODE=NONE PULL_STRENGTH=MEDIUM BANK_VCCIO=3.3;
IO_LOC  "rst_n" AA10;
IO_PORT "rst_n" IO_TYPE=LVCMOS33 PULL_MODE=UP PULL_STRENGTH=MEDIUM BANK_VCCIO=3.3;
IO_LOC  "key" AA11;
IO_PORT "key" IO_TYPE=LVCMOS33 PULL_MODE=UP PULL_STRENGTH=MEDIUM BANK_VCCIO=3.3;
IO_LOC  "dout" P20;
IO_PORT "dout" IO_TYPE=LVCMOS33 PULL_MODE=NONE PULL_STRENGTH=MEDIUM BANK_VCCIO=3.3;
"""
SDC = "create_clock -name clk -period 20 -waveform {0 10} [get_ports {clk}]\n"

# sequence -> list of 4 CE expressions (Verilog), indexed by instance i.
CE_EXPR = {
    "A": ["key", "~key", "key & rst_n", "key | ~rst_n"],
    "B": ["~key", "key", "key | rst_n", "key & ~rst_n"],
}


def rtl(seq, n_dqce):
    """Render `top.v` with `n_dqce` DQCE instances using CE sequence `seq`."""
    assert 1 <= n_dqce <= 4
    ce_exprs = CE_EXPR[seq]
    L = ["`default_nettype none",
         "module top (input wire clk, input wire rst_n, input wire key, output wire dout);",
         f"    wire [{n_dqce - 1}:0] clkout;",
         f"    wire [{n_dqce - 1}:0] ce;"]
    for i in range(n_dqce):
        L.append(f"    assign ce[{i}] = {ce_exprs[i]};")
    for i in range(n_dqce):
        # NB (measured, this task): the vendor Verilog primitive for the
        # Arora V / GW5A(ST) family is named `DCE`, not `DQCE` -- `DQCE` is
        # the pre-5A-series name (UG306-1.0.1E S3.1 "Dynamic Clock Enable";
        # no `DQCE` string appears anywhere in that Arora V Clock User
        # Guide). apycula's `chipdb.py` keys its *own* internal dict entry
        # `extra_func['dqce']` regardless of family -- that is an internal
        # apycula convention, not the vendor's instantiable module name, and
        # is unaffected by this fix (only the RTL emitted by *this probe*
        # needed the family-correct primitive name to compile against the
        # 138C oracle at all).
        L.append(f"    DCE dqce{i} (.CLKIN(clk), .CE(ce[{i}]), .CLKOUT(clkout[{i}]));")
    L.append(f"    reg [{n_dqce - 1}:0] q;")
    L.append("    genvar gi;")
    L.append("    generate")
    L.append(f"        for (gi = 0; gi < {n_dqce}; gi = gi + 1) begin : g")
    L.append("            always @(posedge clkout[gi]) q[gi] <= ~q[gi] ^ rst_n;")
    L.append("        end")
    L.append("    endgenerate")
    L.append(f"    assign dout = ^q;")
    L.append("endmodule")
    L.append("`default_nettype wire")
    return "\n".join(L) + "\n"


def write_design(d, seq, n_dqce):
    os.makedirs(d, exist_ok=True)
    open(os.path.join(d, "top.v"), "w").write(rtl(seq, n_dqce))
    open(os.path.join(d, "top.cst"), "w").write(CST)
    open(os.path.join(d, "top.sdc"), "w").write(SDC)


#: The 8-run plan (`P1.T28` "8 oracle runs = 4 quadrants x 2").
PLAN = [(f"{seq}{n}", seq, n) for seq in ("A", "B") for n in (1, 2, 3, 4)]
