// Dual-purpose configuration pins released to the fabric.
//
// The logic is deliberately dull -- a free-running counter with its top bits
// on the LEDs -- because the point of this example is the bitstream, not the
// design.  The pack step hands the configuration pins to the fabric, which is
// what a design that needs those pads as ordinary I/O after configuration has
// to ask for; see the Makefile for which options this device honours.
`default_nettype none

module top (
    input  wire clk,
    input  wire reset,
    output wire [15:0] led
);

    // The reset button pulls the pin low.
    reg [39:0] cnt;
    always @(posedge clk)
        if (!reset)
            cnt <= 40'b0;
        else
            cnt <= cnt + 1'b1;

    assign led = cnt[39:24];

endmodule
