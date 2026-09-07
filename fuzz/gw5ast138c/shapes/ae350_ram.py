"""`ae350_ram` -- the `AE350_RAM` row's vehicle.

`P2.T05` measured the primitive and found no design space at all: 26 ports,
0 parameters, and every port name, direction and width an exact subset of
`AE350_SOC`'s 149.  So this row is not a sweep -- it is a **presence
question**: does the `AE350_RAM` primitive occupy silicon, wires or fuses of
its own, or is it a second name for taps `AE350_SOC` already owns?

The vehicle answers that with one vendor run, by construction:

* The `"soc"` point renders the `P2.T20` `AE350_SOC` vehicle **verbatim** --
  `ae350_soc.rtl` is called, not re-implemented -- and splices one
  `AE350_RAM` instance into it.  Because the `AE350_SOC` half is byte-stable,
  a presence diff against the `P2.T23` bitstream shows the `AE350_RAM` and
  nothing else.
* Every `AE350_RAM` input is wired to the **same net** the `AE350_SOC`'s
  identically-named input already carries, which is MUG1031's external-AHB
  view: `EXTM_*` is an AHB *slave* port on both blocks (`EXTM_HADDR` is an
  input, `EXTM_HRDATA` an output, on both), so one external master drives
  both, and `EXTM_HSEL` -- and only `EXTM_HSEL` -- picks between them.  The
  `AE350_RAM`'s `EXTM_HSEL` is therefore its own net, from its own pinned
  flop.  Sharing the other nets is deliberate and costs no information: if
  the two blocks tap different wires, the router lights the second wire up
  and the diff shows it; if they tap the same wire, nothing moves.
* The three `AE350_RAM` outputs cannot share a net with the `AE350_SOC`'s
  three same-named outputs -- two drivers, one wire -- so they get their own
  capture chain, folded into `dout`.  If the two blocks are one block, that
  is exactly where the vendor refuses, and a refusal is this row's answer,
  not its failure (`spec-harness.md` §5.2).

The `"solo"` point is the contingency the `"soc"` point earns: an
`AE350_RAM` with no `AE350_SOC` beside it, for when the vendor will not have
both.  It is a second sweep point rather than a second shape file because it
is the same question asked with one term removed.

What both points measured (`$OTC/evidence/ae350-ram/summary.md`): the vendor
refuses the block on this device, at tech-mapping, before place and route --

    ERROR (RP0008) : There is no AE350_RAM resource in current device,
    please change device

with the `AE350_SOC` beside it and with the die otherwise empty alike, so the
refusal is the primitive's and not a contest over the single `AE350_SOC`
site.  The vehicle is kept because that is what the refusal is evidence
*from*: it is the design a later device with the resource would be measured
with, and the control `P2.T23` already built without the block.

The port table is written out here rather than read from the chipdb because
the device data has none: `GW5AST-138C.dat`'s `gw5aStuff` carries
`Ae350SocIns`/`Ae350SocOuts` and no `AE350_RAM` table at all (MEASURED --
120 keys, none matching `Ram`).  Its source is the IDE's own
`prim_syns/gw5a/primitive.xml`, transcribed in
`$OTC/evidence/ae350-ram/port-inventory.md`.
"""
import re

from . import ScopeSpec, ShapeSpec
from . import ae350_soc

#: The `AE350_RAM` input ports, in `primitive.xml` order (`P2.T05`).
AE350_RAM_INPUTS = (
    ("POR_N", 1), ("HW_RSTN", 1), ("CORE_CLK", 1), ("AHB_CLK", 1),
    ("APB_CLK", 1), ("RTC_CLK", 1), ("CORE_CE", 1), ("AXI_CE", 1),
    ("AHB_CE", 1), ("EXTM_HADDR", 32), ("EXTM_HBURST", 3),
    ("EXTM_HPROT", 4), ("EXTM_HREADY", 1), ("EXTM_HSEL", 1),
    ("EXTM_HSIZE", 3), ("EXTM_HTRANS", 2), ("EXTM_HWDATA", 64),
    ("EXTM_HWRITE", 1), ("EMA", 3), ("EMAW", 2), ("EMAS", 1),
    ("RET1N", 1), ("RET2N", 1),
)

#: The `AE350_RAM` output ports, in `primitive.xml` order (`P2.T05`).
AE350_RAM_OUTPUTS = (
    ("EXTM_HRDATA", 64), ("EXTM_HREADYOUT", 1), ("EXTM_HRESP", 1),
)

#: The one input the two blocks must not share: `EXTM_HSEL` is the AHB slave
#: select, so a design in which both blocks see the same select has no
#: external-master semantics at all.
RAM_SELECT_PORT = "EXTM_HSEL"

#: The RTL instance name of the block under test.
RAM_INSTANCE = "u_ae350_ram"

#: The tile the two pinned `AE350_RAM` witness flops sit in, as `(row, col)`.
#: One column right of `ae350_soc.FLOP_TILE`, so neither shape's `INS_LOC`
#: can collide with the other's.
RAM_FLOP_TILE = (1, 161)

#: `(instance, cls, half)` of the flop driving the RAM's own `EXTM_HSEL`, and
#: of the flop capturing its `EXTM_HREADYOUT`.  Two flops is what `E1` needs:
#: one net into the block and one out of it, both at a site both flows read.
RAM_PINNED_DRIVER = ("wit_ram_hsel", 0, "A")
RAM_PINNED_CAPTURE = ("wit_ram_hreadyout", 0, "B")

#: The sweep points, in the order they are asked.
COMPANION_SOC = "soc"
COMPANION_SOLO = "solo"


class SpliceError(Exception):
    """The `AE350_SOC` vehicle is not the shape this vehicle splices into."""


def _ram_ports(direction):
    """`(name, width)` pairs of one direction, as declared by the vendor."""
    return AE350_RAM_INPUTS if direction == "in" else AE350_RAM_OUTPUTS


def _blackbox():
    """The `AE350_RAM` blackbox, seen by **yosys only**.

    Guarded exactly as `ae350_soc._blackbox` is, and for the same reason: the
    open flow has no cell library entry for the block, while GowinSynthesis
    ships its own primitive and must not see a shadowing declaration.
    """
    lines = []
    for direction, keyword in (("in", "input "), ("out", "output")):
        for name, width in _ram_ports(direction):
            span = ("[%d:0] " % (width - 1)).ljust(9) if width > 1 else " " * 9
            lines.append("    %s wire %s%s" % (keyword, span, name))
    return ("`ifdef YOSYS\n(* blackbox *)\nmodule AE350_RAM (\n"
            + ",\n".join(lines) + "\n);\nendmodule\n`endif\n")


def _soc_connections(text):
    """`{port: connection expression}` of the rendered `AE350_SOC` instance.

    Read off the generated text rather than re-derived, so the `AE350_RAM`
    provably hangs on the *same* nets as the `AE350_SOC` and the presence
    diff has only one variable in it.
    """
    match = re.search(r"AE350_SOC\s+u_ae350\s*\(\n(.*?)\n    \);", text,
                      re.DOTALL)
    if match is None:
        raise SpliceError("the AE350_SOC vehicle has no `AE350_SOC u_ae350 (` "
                          "instance to read connections from")
    out = {}
    for line in match.group(1).splitlines():
        pair = re.match(r"\s*\.(\w+)\((.*)\),?\s*$", line)
        if pair is None:
            raise SpliceError("unparsable port connection: %r" % line)
        out[pair.group(1)] = pair.group(2)
    return out


def _ram_instance(connections, select_net):
    """The `AE350_RAM` instantiation, its output wires and its capture chain."""
    body = ["\n    // The AE350_RAM: every input on the AE350_SOC's own net\n"
            "    // (MUG1031's external-AHB view -- both blocks are slaves of\n"
            "    // one master), except the slave select, which is what a\n"
            "    // second slave must not share.\n"]
    driver, _cls, _half = RAM_PINNED_DRIVER
    capture, _ccls, _chalf = RAM_PINNED_CAPTURE
    body.append("    wire q_%s;\n    DFF %s (.D(%s), .CLK(clk), .Q(q_%s));\n"
                % (driver, driver, select_net, driver))
    for name, width in AE350_RAM_OUTPUTS:
        span = ("[%d:0] " % (width - 1)) if width > 1 else ""
        body.append("    wire %sram_%s;\n" % (span, name))
    body.append("    wire q_%s;\n    DFF %s (.D(ram_EXTM_HREADYOUT), "
                ".CLK(clk), .Q(q_%s));\n" % (capture, capture, capture))

    ports = []
    for name, _width in AE350_RAM_INPUTS:
        if name == RAM_SELECT_PORT:
            ports.append("        .%s(q_%s)" % (name, driver))
            continue
        if name not in connections:
            raise SpliceError("the AE350_SOC vehicle does not connect %s, so "
                              "the AE350_RAM cannot share its net" % name)
        ports.append("        .%s(%s)" % (name, connections[name]))
    for name, _width in AE350_RAM_OUTPUTS:
        ports.append("        .%s(ram_%s)" % (name, name))
    body.append("\n    AE350_RAM %s (\n" % RAM_INSTANCE
                + ",\n".join(ports) + "\n    );\n")
    body.append(_capture_chain())
    return "".join(body)


def _capture_chain():
    """Fold the RAM's 66 output bits into one bit, XOR by XOR.

    A chain of 2-input XORs, never a reduction operator: a wide XOR packs into
    `MUX2_LUT5..8`, which the unpacker does not decode, and that is what cost
    `P2.T22` its `c1` check (`ae350_soc._divider`, same reasoning).
    """
    bits = []
    for name, width in AE350_RAM_OUTPUTS:
        if width > 1:
            bits += ["ram_%s[%d]" % (name, i) for i in range(width)]
        else:
            bits.append("ram_%s" % name)
    lines = ["\n    localparam integer RNO = %d;" % len(bits),
             "    reg [RNO-1:0] rcap;",
             "    always @(posedge clk) begin"]
    for i, bit in enumerate(bits):
        terms = [bit] + (["rcap[%d]" % (i - 1)] if i else ["q_%s"
                                                           % RAM_PINNED_CAPTURE[0]])
        lines.append("        rcap[%d] <= %s;" % (i, " ^ ".join(terms)))
    lines += ["    end", ""]
    return "\n".join(lines)


_DOUT = "    assign dout = cap[NO-1];"
_MODULE_HEAD = "\nmodule top (\n"
_MODULE_TAIL = "\nendmodule\n\n`default_nettype wire\n"


def _rtl_with_soc(spec):
    """The `P2.T20` vehicle, verbatim, with one `AE350_RAM` spliced into it."""
    text = ae350_soc.rtl(spec, COMPANION_SOC)
    for marker in (_DOUT, _MODULE_HEAD, _MODULE_TAIL):
        if marker not in text:
            raise SpliceError("the AE350_SOC vehicle no longer contains %r; "
                              "this shape splices into it and must be "
                              "re-measured, never re-guessed" % marker)
    connections = _soc_connections(text)
    text = text.replace(_MODULE_HEAD, "\n" + _blackbox() + _MODULE_HEAD, 1)
    text = text.replace(
        _DOUT, "    assign dout = cap[NO-1] ^ rcap[RNO-1];", 1)
    return text.replace(
        _MODULE_TAIL,
        "\n" + _ram_instance(connections, "drv[0]") + _MODULE_TAIL, 1)


def _rtl_solo(spec):
    """An `AE350_RAM` with no `AE350_SOC`: the contingency vehicle.

    Same construction rules as the `"soc"` point -- one distinct net per input
    bit, a 2-input XOR capture chain, two pinned witness flops -- with the
    clock ports taken from the same `PLL_R[0]` and ripple divider, because
    MUG1031 gives the RAM the SoC's clock tree and this row must not invent a
    different one.
    """
    driver, _cls, _half = RAM_PINNED_DRIVER
    capture, _ccls, _chalf = RAM_PINNED_CAPTURE
    clock_net = {"CORE_CLK": "pll_core_clk", "AHB_CLK": "ck[1]",
                 "APB_CLK": "ck[2]", "RTC_CLK": "ck[3]"}
    bits = []
    for name, width in AE350_RAM_INPUTS:
        if name in clock_net or name == RAM_SELECT_PORT:
            continue
        bits += ["%s%d" % (name, i) for i in range(width)] if width > 1 \
            else [name]
    index = {bit: i for i, bit in enumerate(bits)}

    def driver_of(bit):
        return "drv[%d]" % index[bit]

    body = [ae350_soc._pll(None), ae350_soc._divider(),
            "\n    // One flop per driven input bit: no port folds away.\n"
            "    localparam integer NI = %d;\n"
            "    reg [NI-1:0] drv;\n"
            "    always @(posedge clk)\n"
            "        if (!rst_n) drv <= {NI{1'b0}};\n"
            "        else        drv <= {drv[NI-2:0], din};\n" % len(bits)]

    ports = []
    for name, width in AE350_RAM_INPUTS:
        if name in clock_net:
            ports.append("        .%s(%s)" % (name, clock_net[name]))
        elif name == RAM_SELECT_PORT:
            ports.append("        .%s(q_%s)" % (name, driver))
        elif width > 1:
            inner = ", ".join(driver_of("%s%d" % (name, i))
                              for i in reversed(range(width)))
            ports.append("        .%s({%s})" % (name, inner))
        else:
            ports.append("        .%s(%s)" % (name, driver_of(name)))
    for name, _width in AE350_RAM_OUTPUTS:
        ports.append("        .%s(ram_%s)" % (name, name))

    body.append("\n    wire q_%s;\n    DFF %s (.D(drv[0]), .CLK(clk), "
                ".Q(q_%s));\n" % (driver, driver, driver))
    for name, width in AE350_RAM_OUTPUTS:
        span = ("[%d:0] " % (width - 1)) if width > 1 else ""
        body.append("    wire %sram_%s;\n" % (span, name))
    body.append("    wire q_%s;\n    DFF %s (.D(ram_EXTM_HREADYOUT), "
                ".CLK(clk), .Q(q_%s));\n" % (capture, capture, capture))
    body.append("\n    AE350_RAM %s (\n" % RAM_INSTANCE
                + ",\n".join(ports) + "\n    );\n")
    body.append(_capture_chain())
    body.append("\n    assign dout = rcap[RNO-1];\n")

    return ("""\
// Generated by fuzz.gw5ast138c.harness.gen from shapes/%s.py -- do not edit.
// Shape: %s (primitive under test: %s)
// Sweep: %s = %s
`default_nettype none

%s
module %s (
    input  wire clk,
    input  wire rst_n,
    input  wire din,
    output wire dout
);

%s
endmodule

`default_nettype wire
""" % (spec.name, spec.name, spec.primitive, spec.sweep_axis, COMPANION_SOLO,
       _blackbox(), spec.top_module, "".join(body)))


def rtl(spec, sweep_value=None):
    """Render the vehicle for one sweep point."""
    if sweep_value in (None, COMPANION_SOC):
        return _rtl_with_soc(spec)
    if sweep_value == COMPANION_SOLO:
        return _rtl_solo(spec)
    raise SpliceError("unknown companion point %r" % (sweep_value,))


def ins_loc(spec=None, sweep_value=None):
    """`{instance: site}` for one sweep point, in a spelling both flows read."""
    row, col = RAM_FLOP_TILE
    out = {}
    if sweep_value in (None, COMPANION_SOC):
        out.update(ae350_soc.ins_loc())
    else:
        out["u_pll"] = ae350_soc.PLL_SITE
    for instance, cls, half in (RAM_PINNED_DRIVER, RAM_PINNED_CAPTURE):
        out[instance] = "R%dC%d[%d][%s]" % (row + 1, col + 1, cls, half)
    return out


def scope_tiles():
    """The tiles this row's `E0`/`E1` comparison is restricted to.

    Identical to `ae350_soc.scope_tiles()` -- the block's band plus the
    `PLL_R[0]` site -- because the presence diff measured that the
    `AE350_RAM` occupies no tile the `AE350_SOC` does not.  Naming a wider
    scope here would compare the design's own fabric, which `D32` excludes.
    """
    return ae350_soc.scope_tiles()


SPEC = ShapeSpec(
    name="ae350_ram",
    primitive="AE350_RAM",
    sweep_axis="companion",
    sweep_values=[COMPANION_SOC, COMPANION_SOLO],
    baseline_value=COMPANION_SOC,
    pins=dict(ae350_soc.SPEC.pins),
    bank_vccio=dict(ae350_soc.SPEC.bank_vccio),
    scope=ScopeSpec(tiles=scope_tiles()),
    rtl=rtl,
    ins_loc=ins_loc,
    clocks=dict(ae350_soc.SPEC.clocks),
    extra_gwsh_options=list(ae350_soc.SPEC.extra_gwsh_options),
    extra_pack_flags=list(ae350_soc.SPEC.extra_pack_flags),
    extra_nextpnr_vopts=list(ae350_soc.SPEC.extra_nextpnr_vopts),
)
