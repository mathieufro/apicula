YOSYS ?= yosys
YOSYS_FLAGS = -setundef
NEXTPNR ?= nextpnr-himbaechel
NEXTPNR_FLAGS ?= --timing-allow-fail -r
DEBUG = -v --debug
DEBUG =

.DEFAULT_GOAL := all

.PHONY: all primer25k tangmega138k clean

primer25k: \
	in-out-primer25k.fs in-inv-out-primer25k.fs in-or-inv-out-primer25k.fs \
	lut8-primer25k.fs big-shift-primer25k.fs alu-simple-primer25k.fs lutram-primer25k.fs \
	blinky-osc-primer25k.fs pll7-primer25k.fs dcs-primer25k.fs \
	bsram-DPB-primer25k.fs bsram-DPB16-primer25k.fs bsram-DPX9B-primer25k.fs bsram-DPX9B18-primer25k.fs \
	bsram-pROM-primer25k.fs bsram-pROMX9-primer25k.fs bsram-SP-primer25k.fs bsram-SPX9-primer25k.fs \
	bsram-SDPB-primer25k.fs bsram-SDPX9B-primer25k.fs bsram-SDPB32-primer25k.fs \
	femto-riscv-15-primer25k.fs femto-riscv-16-primer25k.fs femto-riscv-18-primer25k.fs \
	dsp-mult12x12-primer25k.fs dsp-multaddalu12x12-primer25k.fs dsp-multalu27x18-primer25k.fs \
	dsp-mult27x36-primer25k.fs \
	adc-temp-primer25k.fs adc-loc-left-primer25k.fs adc-glo-right-primer25k.fs attosoc-primer25k.fs \
	oddr-tlvds-primer25k.fs oser4-primer25k.fs oser8-primer25k.fs oser10-primer25k.fs ovideo-primer25k.fs \
	iddr-primer25k.fs iddrc-primer25k.fs ides4-primer25k.fs ivideo-primer25k.fs \
	ides8-primer25k.fs ides10-primer25k.fs \
	oser10-clkdiv-tlvds-primer25k.fs

tangmega138k: \
	big-shift-tangmega138k.fs attosoc-tangmega138k.fs uart-message-tangmega138k.fs \
	ae350-emb-tcm-tangmega138k.fs dualpin-tangmega138k.fs \
	iddr-boardclk-tangmega138k.fs \
	oddr-io-tangmega138k.fs iddr-io-tangmega138k.fs \
	oser4-io-tangmega138k.fs oser8-io-tangmega138k.fs oser10-io-tangmega138k.fs \
	ovideo-io-tangmega138k.fs \
	ides4-io-tangmega138k.fs ides8-io-tangmega138k.fs ides10-io-tangmega138k.fs \
	oser16-io-tangmega138k.fs ides16-io-tangmega138k.fs \
	tlvds-ibuf-io-tangmega138k.fs tlvds-obuf-io-tangmega138k.fs \
	tlvds-tbuf-io-tangmega138k.fs tlvds-iobuf-io-tangmega138k.fs \
	iodelay-static-io-tangmega138k.fs adclrc-io-tangmega138k.fs

tangconsole138k: \
	uart-message-tangmega138k.fs

tangconsole60k: \
	in-out-tangconsole60k.fs in-inv-out-tangconsole60k.fs in-or-inv-out-tangconsole60k.fs

all: primer25k tangmega138k tangconsole138k tangconsole60k

clean:
	rm -f *.json *.fs *-unpacked.v

# ============================================================
# TangPrimer25k
%-primer25k.fs: %-primer25k.json
	gowin_pack --sspi_as_gpio --cpu_as_gpio -d GW5A-25A -o $@ $<

%-primer25k.json: %-primer25k-synth.json primer25k.cst
	$(NEXTPNR) ${NEXTPNR_FLAGS} ${DEBUG} --top top --json $< --write $@ --device GW5A-LV25MG121NES --vopt cst=primer25k.cst --vopt sspi_as_gpio

big-shift-primer25k.json: big-shift-primer25k-synth.json big-shift-primer25k.cst
	$(NEXTPNR) ${NEXTPNR_FLAGS} ${DEBUG} --top top --json $< --write $@ --device GW5A-LV25MG121NES --vopt cst=big-shift-primer25k.cst --vopt sspi_as_gpio

alu-%-primer25k.json: alu-%-primer25k-synth.json alu-%-primer25k.cst
	$(NEXTPNR) ${NEXTPNR_FLAGS} ${DEBUG} --top top --json $< --write $@ --device GW5A-LV25MG121NES --vopt cst=$(basename $@).cst --vopt sspi_as_gpio

%-primer25k-synth.json: %.v
	$(YOSYS) -D INV_BTN=1 -D LEDS_NR=8 -D OSC_TYPE_OSCA  -D CPU_FREQ=50 -D BAUD_RATE=115200 -p "read_verilog $^; synth_gowin -json $@ -family gw5a -nolutram ${YOSYS_FLAGS}"

big-shift-primer25k-synth.json: big-shift.v 
	$(YOSYS) -D INV_BTN=1 -D LEDS_NR=24 -D OSC_TYPE_OSCA -p "read_verilog $^; synth_gowin -json $@ -family gw5a ${YOSYS_FLAGS}"

bsram-%-primer25k-synth.json: pll/GW5A-25A.vh io444.vh display-640x480.v %-image-rom.v %-video-ram.v %.v clock-PLLA.v
	$(YOSYS) -D INV_BTN=1 -p "read_verilog $^; synth_gowin -json $@ -family gw5a ${YOSYS_FLAGS}"

femto-%-primer25k-synth.json: femto-%.v
	$(YOSYS) -D INV_BTN=1 -D LEDS_NR=8 -D OSC_TYPE_OSCA -D CPU_FREQ=50 -D BAUD_RATE=115200 -p "read_verilog $^; synth_gowin -json $@ -nolutram -family gw5a ${YOSYS_FLAGS}"

attosoc-primer25k.json: attosoc-primer25k-synth.json primer25k.cst
	$(NEXTPNR) ${NEXTPNR_FLAGS} ${DEBUG} --top attosoc --json $< --write $@ --device GW5A-LV25MG121NES --vopt cst=primer25k.cst --vopt sspi_as_gpio

attosoc-primer25k-synth.json: attosoc/attosoc.v attosoc/picorv32.v
	$(YOSYS) -D INV_BTN=1 -p "read_verilog $^; synth_gowin -json $@ -nolutram -strict-gw5a-dffs -family gw5a ${YOSYS_FLAGS}"

# ============================================================
# TangMega138k
%-tangmega138k.fs: %-tangmega138k.json
	gowin_pack -d GW5AST-138C -o $@ $<

%-tangmega138k.json: %-tangmega138k-synth.json tangmega138k.cst
	$(NEXTPNR) ${NEXTPNR_FLAGS} ${DEBUG} --json $< --write $@ --device GW5AST-LV138PG484AC1/I0 --vopt cst=tangmega138k.cst

# One IDDR clocked from the board oscillator (P3.T09). The clock reaches the
# gearbox over the global clock plane, which is what this die does: it carries
# no HCLK -> IOLOGIC fast-clock edge, for the vendor or for the open flow
# (evidence/pin-to-hclk/summary.md).
iddr-boardclk-tangmega138k-synth.json: iddr-boardclk.v
	$(YOSYS) -D INV_BTN=0 -p "read_verilog $^; synth_gowin -json $@ -family gw5a ${YOSYS_FLAGS}"

big-shift-tangmega138k-synth.json: big-shift.v
	$(YOSYS) -D INV_BTN=0 -D LEDS_NR=16 -p "read_verilog $^; synth_gowin -json $@ -family gw5a ${YOSYS_FLAGS}"

attosoc-tangmega138k.json: attosoc-tangmega138k-synth.json tangmega138k.cst
	$(NEXTPNR) ${NEXTPNR_FLAGS} ${DEBUG} --top attosoc --json $< --write $@ --device GW5AST-LV138PG484AC1/I0 --vopt cst=tangmega138k.cst

attosoc-tangmega138k-synth.json: attosoc/attosoc.v attosoc/picorv32.v
	$(YOSYS) -D INV_BTN=0 -p "read_verilog $^; synth_gowin -json $@ -family gw5a ${YOSYS_FLAGS}"

uart-message-tangmega138k-synth.json: uart-message-tangconsole138k.v
	$(YOSYS) -D INV_BTN=0 -p "read_verilog $^; synth_gowin -json $@ -family gw5a ${YOSYS_FLAGS}"

# The AE350 hard SoC.  There is deliberately no companion AE350_RAM example:
# that block is not a resource gowin_pack can place on this device, so no
# bitstream can express it and no example could be built.
# The design uses only ordinary I/O, so the shared pack rule above serves it
# unchanged -- in particular the SSPI pins stay with the configuration
# controller, which is where an AE350 finds its boot flash. Place-and-route
# needs its own constraint file: CORE_CLK has no fabric entrance, so the PLL
# that drives it must be pinned to a site the dedicated hop exists from.
ae350-emb-tcm-tangmega138k-synth.json: ae350-emb-tcm.v
	$(YOSYS) -p "read_verilog $^; synth_gowin -json $@ -family gw5a ${YOSYS_FLAGS}"

ae350-emb-tcm-tangmega138k.json: ae350-emb-tcm-tangmega138k-synth.json ae350-emb-tcm-tangmega138k.cst
	$(NEXTPNR) ${NEXTPNR_FLAGS} ${DEBUG} --json $< --write $@ --device GW5AST-LV138PG484AC1/I0 --vopt cst=ae350-emb-tcm-tangmega138k.cst

# The dual-purpose pins.  gowin_pack accepts eight of them; the six the pack
# line below asks for are every one this device honours.  The two left out are
# refusals, not oversights:
#   --reconfign_as_gpio  the vendor tools decline RECONFIG_N on this device, so
#                        there is no bitstream to reproduce;
#   --i2c_as_gpio        the device has no I2CCFG block, so nextpnr emits no
#                        I2C pin-configuration cell and gowin_pack rejects the
#                        flag as disagreeing with it.
# sspi_as_gpio has to be given to both tools: it is the one option nextpnr also
# carries, and gowin_pack checks that the two agree.
dualpin-tangmega138k-synth.json: dualpin.v
	$(YOSYS) -p "read_verilog $^; synth_gowin -json $@ -family gw5a ${YOSYS_FLAGS}"

dualpin-tangmega138k.json: dualpin-tangmega138k-synth.json tangmega138k.cst
	$(NEXTPNR) ${NEXTPNR_FLAGS} ${DEBUG} --json $< --write $@ --device GW5AST-LV138PG484AC1/I0 --vopt cst=tangmega138k.cst --vopt sspi_as_gpio

dualpin-tangmega138k.fs: dualpin-tangmega138k.json
	gowin_pack --jtag_as_gpio --sspi_as_gpio --mspi_as_gpio --ready_as_gpio --done_as_gpio -d GW5AST-138C -o $@ $<


# The IO/IOLOGIC examples, one per primitive that closed at E1.  Each one is
# the design its evidence row was measured on -- both the .v and the .cst are
# generated from the shape file that drove the vendor comparison, so an
# example cannot drift away from the measurement that justifies it.  Each
# carries its own .cst because these designs claim balls by primitive, not the
# board's LED/UART set, and because the gearbox rows pin their CLKDIV lane
# with an INS_LOC line the shared constraint file has no business holding.

oddr-io-tangmega138k-synth.json: oddr-io.v
	$(YOSYS) -p "read_verilog $^; synth_gowin -json $@ -family gw5a ${YOSYS_FLAGS}"

oddr-io-tangmega138k.json: oddr-io-tangmega138k-synth.json oddr-io-tangmega138k.cst
	$(NEXTPNR) ${NEXTPNR_FLAGS} ${DEBUG} --json $< --write $@ --device GW5AST-LV138PG484AC1/I0 --vopt cst=oddr-io-tangmega138k.cst

iddr-io-tangmega138k-synth.json: iddr-io.v
	$(YOSYS) -p "read_verilog $^; synth_gowin -json $@ -family gw5a ${YOSYS_FLAGS}"

iddr-io-tangmega138k.json: iddr-io-tangmega138k-synth.json iddr-io-tangmega138k.cst
	$(NEXTPNR) ${NEXTPNR_FLAGS} ${DEBUG} --json $< --write $@ --device GW5AST-LV138PG484AC1/I0 --vopt cst=iddr-io-tangmega138k.cst

oser4-io-tangmega138k-synth.json: oser4-io.v
	$(YOSYS) -p "read_verilog $^; synth_gowin -json $@ -family gw5a ${YOSYS_FLAGS}"

oser4-io-tangmega138k.json: oser4-io-tangmega138k-synth.json oser4-io-tangmega138k.cst
	$(NEXTPNR) ${NEXTPNR_FLAGS} ${DEBUG} --json $< --write $@ --device GW5AST-LV138PG484AC1/I0 --vopt cst=oser4-io-tangmega138k.cst

oser8-io-tangmega138k-synth.json: oser8-io.v
	$(YOSYS) -p "read_verilog $^; synth_gowin -json $@ -family gw5a ${YOSYS_FLAGS}"

oser8-io-tangmega138k.json: oser8-io-tangmega138k-synth.json oser8-io-tangmega138k.cst
	$(NEXTPNR) ${NEXTPNR_FLAGS} ${DEBUG} --json $< --write $@ --device GW5AST-LV138PG484AC1/I0 --vopt cst=oser8-io-tangmega138k.cst

oser10-io-tangmega138k-synth.json: oser10-io.v
	$(YOSYS) -p "read_verilog $^; synth_gowin -json $@ -family gw5a ${YOSYS_FLAGS}"

oser10-io-tangmega138k.json: oser10-io-tangmega138k-synth.json oser10-io-tangmega138k.cst
	$(NEXTPNR) ${NEXTPNR_FLAGS} ${DEBUG} --json $< --write $@ --device GW5AST-LV138PG484AC1/I0 --vopt cst=oser10-io-tangmega138k.cst

ovideo-io-tangmega138k-synth.json: ovideo-io.v
	$(YOSYS) -p "read_verilog $^; synth_gowin -json $@ -family gw5a ${YOSYS_FLAGS}"

ovideo-io-tangmega138k.json: ovideo-io-tangmega138k-synth.json ovideo-io-tangmega138k.cst
	$(NEXTPNR) ${NEXTPNR_FLAGS} ${DEBUG} --json $< --write $@ --device GW5AST-LV138PG484AC1/I0 --vopt cst=ovideo-io-tangmega138k.cst

ides4-io-tangmega138k-synth.json: ides4-io.v
	$(YOSYS) -p "read_verilog $^; synth_gowin -json $@ -family gw5a ${YOSYS_FLAGS}"

ides4-io-tangmega138k.json: ides4-io-tangmega138k-synth.json ides4-io-tangmega138k.cst
	$(NEXTPNR) ${NEXTPNR_FLAGS} ${DEBUG} --json $< --write $@ --device GW5AST-LV138PG484AC1/I0 --vopt cst=ides4-io-tangmega138k.cst

ides8-io-tangmega138k-synth.json: ides8-io.v
	$(YOSYS) -p "read_verilog $^; synth_gowin -json $@ -family gw5a ${YOSYS_FLAGS}"

ides8-io-tangmega138k.json: ides8-io-tangmega138k-synth.json ides8-io-tangmega138k.cst
	$(NEXTPNR) ${NEXTPNR_FLAGS} ${DEBUG} --json $< --write $@ --device GW5AST-LV138PG484AC1/I0 --vopt cst=ides8-io-tangmega138k.cst

ides10-io-tangmega138k-synth.json: ides10-io.v
	$(YOSYS) -p "read_verilog $^; synth_gowin -json $@ -family gw5a ${YOSYS_FLAGS}"

ides10-io-tangmega138k.json: ides10-io-tangmega138k-synth.json ides10-io-tangmega138k.cst
	$(NEXTPNR) ${NEXTPNR_FLAGS} ${DEBUG} --json $< --write $@ --device GW5AST-LV138PG484AC1/I0 --vopt cst=ides10-io-tangmega138k.cst

oser16-io-tangmega138k-synth.json: oser16-io.v
	$(YOSYS) -p "read_verilog $^; synth_gowin -json $@ -family gw5a ${YOSYS_FLAGS}"

oser16-io-tangmega138k.json: oser16-io-tangmega138k-synth.json oser16-io-tangmega138k.cst
	$(NEXTPNR) ${NEXTPNR_FLAGS} ${DEBUG} --json $< --write $@ --device GW5AST-LV138PG484AC1/I0 --vopt cst=oser16-io-tangmega138k.cst

ides16-io-tangmega138k-synth.json: ides16-io.v
	$(YOSYS) -p "read_verilog $^; synth_gowin -json $@ -family gw5a ${YOSYS_FLAGS}"

ides16-io-tangmega138k.json: ides16-io-tangmega138k-synth.json ides16-io-tangmega138k.cst
	$(NEXTPNR) ${NEXTPNR_FLAGS} ${DEBUG} --json $< --write $@ --device GW5AST-LV138PG484AC1/I0 --vopt cst=ides16-io-tangmega138k.cst

tlvds-ibuf-io-tangmega138k-synth.json: tlvds-ibuf-io.v
	$(YOSYS) -p "read_verilog $^; synth_gowin -json $@ -family gw5a ${YOSYS_FLAGS}"

tlvds-ibuf-io-tangmega138k.json: tlvds-ibuf-io-tangmega138k-synth.json tlvds-ibuf-io-tangmega138k.cst
	$(NEXTPNR) ${NEXTPNR_FLAGS} ${DEBUG} --json $< --write $@ --device GW5AST-LV138PG484AC1/I0 --vopt cst=tlvds-ibuf-io-tangmega138k.cst

tlvds-obuf-io-tangmega138k-synth.json: tlvds-obuf-io.v
	$(YOSYS) -p "read_verilog $^; synth_gowin -json $@ -family gw5a ${YOSYS_FLAGS}"

tlvds-obuf-io-tangmega138k.json: tlvds-obuf-io-tangmega138k-synth.json tlvds-obuf-io-tangmega138k.cst
	$(NEXTPNR) ${NEXTPNR_FLAGS} ${DEBUG} --json $< --write $@ --device GW5AST-LV138PG484AC1/I0 --vopt cst=tlvds-obuf-io-tangmega138k.cst

tlvds-tbuf-io-tangmega138k-synth.json: tlvds-tbuf-io.v
	$(YOSYS) -p "read_verilog $^; synth_gowin -json $@ -family gw5a ${YOSYS_FLAGS}"

tlvds-tbuf-io-tangmega138k.json: tlvds-tbuf-io-tangmega138k-synth.json tlvds-tbuf-io-tangmega138k.cst
	$(NEXTPNR) ${NEXTPNR_FLAGS} ${DEBUG} --json $< --write $@ --device GW5AST-LV138PG484AC1/I0 --vopt cst=tlvds-tbuf-io-tangmega138k.cst

tlvds-iobuf-io-tangmega138k-synth.json: tlvds-iobuf-io.v
	$(YOSYS) -p "read_verilog $^; synth_gowin -json $@ -family gw5a ${YOSYS_FLAGS}"

tlvds-iobuf-io-tangmega138k.json: tlvds-iobuf-io-tangmega138k-synth.json tlvds-iobuf-io-tangmega138k.cst
	$(NEXTPNR) ${NEXTPNR_FLAGS} ${DEBUG} --json $< --write $@ --device GW5AST-LV138PG484AC1/I0 --vopt cst=tlvds-iobuf-io-tangmega138k.cst

iodelay-static-io-tangmega138k-synth.json: iodelay-static-io.v
	$(YOSYS) -p "read_verilog $^; synth_gowin -json $@ -family gw5a ${YOSYS_FLAGS}"

iodelay-static-io-tangmega138k.json: iodelay-static-io-tangmega138k-synth.json iodelay-static-io-tangmega138k.cst
	$(NEXTPNR) ${NEXTPNR_FLAGS} ${DEBUG} --json $< --write $@ --device GW5AST-LV138PG484AC1/I0 --vopt cst=iodelay-static-io-tangmega138k.cst

adclrc-io-tangmega138k-synth.json: adclrc-io.v
	$(YOSYS) -p "read_verilog $^; synth_gowin -json $@ -family gw5a ${YOSYS_FLAGS}"

adclrc-io-tangmega138k.json: adclrc-io-tangmega138k-synth.json adclrc-io-tangmega138k.cst
	$(NEXTPNR) ${NEXTPNR_FLAGS} ${DEBUG} --json $< --write $@ --device GW5AST-LV138PG484AC1/I0 --vopt cst=adclrc-io-tangmega138k.cst

# ============================================================
# TangConsole138k
%-tangconsole138k.fs: %-tangconsole138k.json
	gowin_pack -d GW5AST-138C -o $@ $<

%-tangconsole138k.json: %-tangconsole138k-synth.json tangconsole138k.cst
	$(NEXTPNR) ${NEXTPNR_FLAGS} ${DEBUG} --json $< --write $@ --device GW5AST-LV138PG484AC1/I0 --vopt cst=tangconsole138k.cst

uart-message-tangconsole138k-synth.json: uart-message-tangconsole138k.v
	$(YOSYS) -D INV_BTN=0 -p "read_verilog $^; synth_gowin -json $@ -family gw5a ${YOSYS_FLAGS}"
	
# ============================================================
# TangConsole60k
%-tangconsole60k.fs: %-tangconsole60k.json
	gowin_pack --cpu_as_gpio -d GW5AT-60B -o $@ $<

%-tangconsole60k.json: %-tangconsole60k-synth.json tangconsole60k.cst
	$(NEXTPNR) ${NEXTPNR_FLAGS} ${DEBUG} --json $< --write $@ --device GW5AT-LV60PG484AC1/I0 --vopt cst=tangconsole60k.cst

%-tangconsole60k-synth.json: %.v
	$(YOSYS) -D INV_BTN=1 -D LEDS_NR=8 -D OSC_TYPE_OSCA  -D CPU_FREQ=50 -D BAUD_RATE=115200 -p "read_verilog $^; synth_gowin -json $@ -family gw5a -nolutram ${YOSYS_FLAGS}"
