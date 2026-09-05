// Structural proof (P1.T11) that the GW5AST-138C chipdb yields a placeable
// CLKDIV bel: an input clock drives one CLKDIV in DIV_MODE "2", whose output
// clocks a counter whose high bits drive four LEDs.
// Board: Tang Mega 138K (GW5AST-LV138PG484AC1/I0), pins in tangmega138k.cst.
module top (
	input  wire clk,
	input  wire reset,
	output wire [3:0] led
);

	wire div_clk;

	CLKDIV div2 (
		.HCLKIN(clk),
		.RESETN(reset),
		.CALIB(1'b0),
		.CLKOUT(div_clk)
	);
	defparam div2.DIV_MODE = "2";

	reg [23:0] ctr;
	always @(posedge div_clk)
		ctr <= ctr + 1'b1;

	assign led = ~ctr[23:20];

endmodule
