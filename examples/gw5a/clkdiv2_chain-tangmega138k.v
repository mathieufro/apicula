// Structural proof (P1.T11) that the GW5AST-138C chipdb yields a placeable
// CLKDIV2 bel. CLKDIV2.CLKOUT cannot drive ordinary fabric logic on this
// family (vendor CK2060, measured in evidence/hclk/topology-138c.md section 7),
// so it chains into a CLKDIV, which is what clocks the counter.
// Board: Tang Mega 138K (GW5AST-LV138PG484AC1/I0), pins in tangmega138k.cst.
module top (
	input  wire clk,
	input  wire reset,
	output wire [3:0] led
);

	wire half_clk;
	wire div_clk;

	// CLKDIV2 takes no DIV_MODE parameter (prim_sim.v:13122).
	CLKDIV2 div2 (
		.HCLKIN(clk),
		.RESETN(reset),
		.CLKOUT(half_clk)
	);

	CLKDIV div (
		.HCLKIN(half_clk),
		.RESETN(reset),
		.CALIB(1'b0),
		.CLKOUT(div_clk)
	);
	defparam div.DIV_MODE = "2";

	reg [23:0] ctr;
	always @(posedge div_clk)
		ctr <= ctr + 1'b1;

	assign led = ~ctr[23:20];

endmodule
