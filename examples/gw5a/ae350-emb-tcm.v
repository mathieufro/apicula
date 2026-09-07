// The AE350 hard RISC-V subsystem of the GW5AST-138, brought up on a Tang
// Mega 138K.
//
// "emb-tcm" names the memory configuration: the cores run out of the block's
// embedded tightly-coupled memory alone, so none of the external memory
// interfaces -- ROM, DDR, the AHB master and slave bridges -- is wired to
// anything.  What is left is the smallest AE350 that still does something
// observable: one clock, one reset, UART2 on the board's console pins and the
// low half of the GPIO port on the LEDs.
//
// The block is hard silicon in die row 0; nothing about it is configured by
// the bitstream, so the fabric's only job here is to carry its taps to pads.
`default_nettype none

// The block has no cell-library entry in the open flow, so yosys is given
// its interface as a blackbox.  The guard keeps that declaration away from
// GowinSynthesis, which knows the primitive already and would otherwise see
// an empty module shadow it.
`ifdef YOSYS
(* blackbox *)
module AE350_SOC (
    input  wire          AHB_CE,
    input  wire          AHB_CLK,
    input  wire          APB2AHB_CE,
    input  wire [7:0]    APB_CE,
    input  wire          APB_CLK,
    input  wire [31:0]   APB_PRDATA,
    input  wire          APB_PREADY,
    input  wire          APB_PSLVERR,
    input  wire          AXI_CE,
    input  wire          CORE_CE,
    input  wire          CORE_CLK,
    input  wire          DBG_TCK,
    input  wire          DDR_CE,
    input  wire          DDR_CLK,
    input  wire [63:0]   DDR_HRDATA,
    input  wire          DDR_HREADY,
    input  wire          DDR_HRESP,
    input  wire [7:0]    DMA_REQ,
    input  wire [2:0]    EMA,
    input  wire          EMAS,
    input  wire [1:0]    EMAW,
    input  wire [31:0]   EXTM_HADDR,
    input  wire [2:0]    EXTM_HBURST,
    input  wire [3:0]    EXTM_HPROT,
    input  wire          EXTM_HREADY,
    input  wire          EXTM_HSEL,
    input  wire [2:0]    EXTM_HSIZE,
    input  wire [1:0]    EXTM_HTRANS,
    input  wire [63:0]   EXTM_HWDATA,
    input  wire          EXTM_HWRITE,
    input  wire [31:0]   EXTS_HRDATA,
    input  wire          EXTS_HREADYIN,
    input  wire          EXTS_HRESP,
    input  wire [31:0]   GPIO_IN,
    input  wire [15:0]   GP_INT,
    input  wire          HW_RSTN,
    input  wire          I2C_SCL_IN,
    input  wire          I2C_SDA_IN,
    input  wire          INTEG_TCK,
    input  wire          INTEG_TDI,
    input  wire          INTEG_TMS,
    input  wire          INTEG_TRST,
    input  wire          PGEN_CHAIN_I,
    input  wire          POR_N,
    input  wire          RET1N,
    input  wire          RET2N,
    input  wire [31:0]   ROM_HRDATA,
    input  wire          ROM_HREADY,
    input  wire          ROM_HRESP,
    input  wire          RTC_CLK,
    input  wire          SCAN_EN,
    input  wire [19:0]   SCAN_IN,
    input  wire          SCAN_TEST,
    input  wire          SPI2_CLK_IN,
    input  wire          SPI2_CSN_IN,
    input  wire          SPI2_HOLDN_IN,
    input  wire          SPI2_MISO_IN,
    input  wire          SPI2_MOSI_IN,
    input  wire          SPI2_WPN_IN,
    input  wire          TDI_IN,
    input  wire          TEST_CLK,
    input  wire          TEST_MODE,
    input  wire          TEST_RSTN,
    input  wire          TMS_IN,
    input  wire          TRST_IN,
    input  wire          UART1_CTSN,
    input  wire          UART1_DCDN,
    input  wire          UART1_DSRN,
    input  wire          UART1_RIN,
    input  wire          UART1_RXD,
    input  wire          UART2_CTSN,
    input  wire          UART2_DCDN,
    input  wire          UART2_DSRN,
    input  wire          UART2_RIN,
    input  wire          UART2_RXD,
    input  wire          WAKEUP_IN,
    output wire [31:0]   APB_PADDR,
    output wire          APB_PENABLE,
    output wire [2:0]    APB_PPROT,
    output wire          APB_PSEL,
    output wire [3:0]    APB_PSTRB,
    output wire [31:0]   APB_PWDATA,
    output wire          APB_PWRITE,
    output wire          CH0_PWM,
    output wire          CH0_PWMOE,
    output wire          CH1_PWM,
    output wire          CH1_PWMOE,
    output wire          CH2_PWM,
    output wire          CH2_PWMOE,
    output wire          CH3_PWM,
    output wire          CH3_PWMOE,
    output wire          CORE0_WFI_MODE,
    output wire [31:0]   DDR_HADDR,
    output wire [2:0]    DDR_HBURST,
    output wire [3:0]    DDR_HPROT,
    output wire [2:0]    DDR_HSIZE,
    output wire [1:0]    DDR_HTRANS,
    output wire [63:0]   DDR_HWDATA,
    output wire          DDR_HWRITE,
    output wire          DDR_RSTN,
    output wire [7:0]    DMA_ACK,
    output wire [63:0]   EXTM_HRDATA,
    output wire          EXTM_HREADYOUT,
    output wire          EXTM_HRESP,
    output wire [31:0]   EXTS_HADDR,
    output wire [2:0]    EXTS_HBURST,
    output wire [3:0]    EXTS_HPROT,
    output wire          EXTS_HSEL,
    output wire [2:0]    EXTS_HSIZE,
    output wire [1:0]    EXTS_HTRANS,
    output wire [31:0]   EXTS_HWDATA,
    output wire          EXTS_HWRITE,
    output wire [31:0]   GPIO_OE,
    output wire [31:0]   GPIO_OUT,
    output wire          HRESETN,
    output wire          I2C_SCL,
    output wire          I2C_SDA,
    output wire          INTEG_TDO,
    output wire          PRDYN_CHAIN_O,
    output wire          PRESETN,
    output wire [31:0]   ROM_HADDR,
    output wire [1:0]    ROM_HTRANS,
    output wire          ROM_HWRITE,
    output wire          RTC_WAKEUP,
    output wire [19:0]   SCAN_OUT,
    output wire          SPI2_CLK_OE,
    output wire          SPI2_CLK_OUT,
    output wire          SPI2_CSN_OE,
    output wire          SPI2_CSN_OUT,
    output wire          SPI2_HOLDN_OE,
    output wire          SPI2_HOLDN_OUT,
    output wire          SPI2_MISO_OE,
    output wire          SPI2_MISO_OUT,
    output wire          SPI2_MOSI_OE,
    output wire          SPI2_MOSI_OUT,
    output wire          SPI2_WPN_OE,
    output wire          SPI2_WPN_OUT,
    output wire          TDO_OE,
    output wire          TDO_OUT,
    output wire          UART1_DTRN,
    output wire          UART1_OUT1N,
    output wire          UART1_OUT2N,
    output wire          UART1_RTSN,
    output wire          UART1_TXD,
    output wire          UART2_DTRN,
    output wire          UART2_OUT1N,
    output wire          UART2_OUT2N,
    output wire          UART2_RTSN,
    output wire          UART2_TXD
);
endmodule
`endif

module top (
    input  wire clk,
    input  wire reset,
    input  wire uart_rx,
    output wire uart_tx,
    output wire [15:0] led
);

    // The board's reset button pulls the pin low, and both of the block's
    // reset inputs are active-low, so the pin drives them directly.
    wire rst_n = reset;

    wire [31:0] gpio_out;

    // No GPIO is driven from the board: the port is output-only here.
    assign led = gpio_out[15:0];

    // CORE_CLK is not a fabric port.  MEASURED (`evidence/ae350/core-clock.md`):
    // the core clock reaches the block over a dedicated, zero-delay hop from a
    // top PLL's CLKOUT1, from either PLL site, and the fabric tap the device
    // data names for it is never realised.  So the pad clock cannot drive it
    // and a PLL is not decoration here -- it is the only entrance.  The other
    // four clocks are ordinary fabric ports and stay on the pad net.
    wire core_clk;
    wire pll_lock;
    PLL #(
        .FCLKIN("100.0"),
        .IDIV_SEL(2),
        .FBDIV_SEL(2),
        .MDIV_SEL(13),
        .ODIV0_SEL(8),
        .ODIV1_SEL(8),
        .CLKOUT0_EN("TRUE"),
        .CLKOUT1_EN("TRUE"),
        .CLKFB_SEL("INTERNAL")
    ) u_pll (
        .CLKIN   (clk),
        .CLKFB   (1'b0),
        .RESET   (~rst_n),
        .PLLPWD  (1'b0),
        .ENCLK0  (1'b1),
        .ENCLK1  (1'b1),
        .LOCK    (pll_lock),
        .CLKOUT1 (core_clk)
    );

    AE350_SOC u_soc (
        // The core clock comes off the PLL; the rest of the subsystem runs
        // from the pad net, which keeps the example to one fabric domain.
        .CORE_CLK   (core_clk),
        .AHB_CLK    (clk),
        .APB_CLK    (clk),
        .DDR_CLK    (clk),
        .RTC_CLK    (clk),

        // Clock enables are active-high and held on; DDR has no PHY here.
        .CORE_CE    (1'b1),
        .AHB_CE     (1'b1),
        .APB2AHB_CE (1'b1),
        .AXI_CE     (1'b1),
        .DDR_CE     (1'b0),

        .POR_N      (rst_n),
        .HW_RSTN    (rst_n),

        // UART2 is the console.  The modem-status inputs are deasserted
        // rather than left floating, so the driver never waits on a handshake
        // this board cannot make.
        .UART2_RXD  (uart_rx),
        .UART2_TXD  (uart_tx),
        .UART2_CTSN (1'b0),
        .UART2_DSRN (1'b1),
        .UART2_DCDN (1'b1),
        .UART2_RIN  (1'b1),

        .GPIO_IN    (32'b0),
        .GPIO_OUT   (gpio_out)
    );

endmodule
