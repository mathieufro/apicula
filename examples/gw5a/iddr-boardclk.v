// One IDDR on the Tang Mega 138K, clocked from the board oscillator on V22.
//
// The point of the design is the clock: the IDDR's CLK comes off a real pin,
// through the HCLK network, rather than from fabric logic -- which is what
// makes IOLOGIC on this die usable at all.
`default_nettype none
module top(input wire clk,
	input wire uart_rx,
	output wire [1:0] led);

	IDDR id(
		.D(uart_rx),
		.CLK(clk),
		.Q0(led[0]),
		.Q1(led[1])
	);
	defparam id.Q0_INIT = 1'b0;
	defparam id.Q1_INIT = 1'b0;
endmodule
