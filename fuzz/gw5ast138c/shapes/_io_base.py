"""The base every IO/IOLOGIC shape of the 138C is built on (`P3.T10`).

`harness/gen.py` already refuses the configurations that are *unsafe on any
board* -- a config-role pin, `DRIVE` on an input, an `LVCMOS*` on a DDR bank,
a missing `IO_TYPE` or `BANK_VCCIO`.  This module adds the half that is about
*this* board: a shape may only claim package balls that the Tang Mega 138K SOM
and its NEO dock actually bring out at 3.3 V, and may only name an `IO_TYPE`
the vendor emits for this device.  The two checks compose -- `assert_envelope`
never replaces `gen.assert_cst_defaults`, it runs before it.

Why an allowlist rather than a denylist: the failure that matters here is a
shape reaching a ball nobody has looked at.  A ball wired to a DDR3 data line,
a 1.5 V rail or a config strap is not distinguishable from a free ball by any
property the shape can compute, so the safe set has to be enumerated from the
board's own `.cst` and stated here (`SAFE_PINS`), with each entry carrying the
net it is, the bank the vendor pinout puts it in, and why it is safe.

The bank numbers in `SAFE_PINS` are the vendor's, cross-checked against the
`.dat` `Bank` table for all 297 balls of this package
(`$OTC/evidence/iologic/pin-hclk-138c.{json,md}`, `P3.T06`);
`test_io_shapes_138c.py` re-checks them against `apycula.pindef` whenever a
Gowin install is present, so a typo here cannot survive a run of the suite on
a machine with the IDE.

Usage -- a shape file subclasses `IoShape`, and `SPEC` is what `gen.py`
loads::

    class OddrShape(IoShape):
        primitive = "ODDR"
        sweep_axis = "ATTR"
        sweep_values = ["TXCLK_POL=0", "TXCLK_POL=1"]
        baseline_value = "TXCLK_POL=0"
        ports = {...}
        def rtl(self, sweep_value): ...

    SPEC = OddrShape().spec()
"""
from . import (DDR_BANKS, DEFAULT_IO_TYPE, DEFAULT_PULL_STRENGTH, PinSpec,
               ScopeSpec, ShapeSpec)

__all__ = [
    "EnvelopeError",
    "IoShape",
    "SafePin",
    "SAFE_PINS",
    "VENDOR_IO_TYPES",
    "VENDOR_VCCIO",
]


class EnvelopeError(ValueError):
    """A shape reached outside the board's measured-safe IO envelope."""


class SafePin:
    """One package ball a Phase-3 shape is allowed to claim.

    `net` is the board net the ball carries in
    `vendor/gowin/mega-138k/08_Misc/tang_mega_138K_pins.cst`, which is what
    makes the ball known-safe: that file is the vendor's own constraint set
    for the SOM, every entry of it is `IO_TYPE=LVCMOS33` on a 3.3 V bank, and
    a ball not in it has not been looked at by anyone.
    """

    __slots__ = ("loc", "site", "bank", "net", "note")

    def __init__(self, loc, site, bank, net, note=""):
        self.loc = loc
        self.site = site
        self.bank = bank
        self.net = net
        self.note = note

    def __repr__(self):
        return f"SafePin({self.loc!r}, {self.site!r}, bank={self.bank})"


def _safe(*rows):
    return {row[0]: SafePin(*row) for row in rows}


#: The balls a Phase-3 shape may claim, and nothing else.
#:
#: Bank 5 and bank 4 are the SOM's general-purpose 3.3 V banks and bank 2 is
#: the RGMII side of the dock; all three are 3.3 V on the 138K SKU (the 60K
#: runs one bank at 1.5 V -- another reason the set is per-board and
#: enumerated).  Bank 3 appears only as the HDMI TMDS pairs, which are this
#: board's only true-LVDS pairs and so the only place a `TLVDS` shape can go.
#: Banks 6 and 7 are the DDR3 banks and appear here nowhere at all.
#:
#: Balls whose vendor `CFG` names a flash/SSPI/CPU-mode config function are
#: deliberately absent even when the board drives them (the four `LEDs[4..7]`
#: at `U21`/`T21`/`R19`/`P19` are `D04..D07`/`SI`/`SSPI_CLK`/`SSPI_WPN`), and
#: `V22` is present only because 27 vendor runs measured its `EMCCLK` role not
#: firing (`P1.T08d`) -- it still needs a `config_role_ack` to pass
#: `gen.assert_cst_defaults`.
SAFE_PINS = _safe(
    # -- bank 5, SOM general-purpose 3.3 V, no config role at all ----------
    ("Y17", "IOB91A", 5, "HP_BCK", "audio header"),
    ("W14", "IOB85A", 5, "", "P1.T14 LED pin; 27 P1.T08d vendor runs drove it"),
    ("Y14", "IOB85B", 5, "rxp (dock rev 31002)", "pair of W14"),
    ("Y16", "IOB78A", 5, "sd_mosi", ""),
    ("AA16", "IOB78B", 5, "HP_DIN", "pair of Y16"),
    ("AB16", "IOB80A", 5, "PA_EN", ""),
    ("AB17", "IOB80B", 5, "HP_WS", "pair of AB16"),
    ("AA15", "IOB83A", 5, "sd_miso", ""),
    ("W15", "IOB72A", 5, "sd_cs", ""),
    ("W16", "IOB72B", 5, "LCD_CTP[0]", "pair of W15"),
    ("T16", "IOB76A", 5, "LCD_CTP[2]", ""),
    ("U16", "IOB76B", 5, "LCD_CTP[1]", "pair of T16"),
    ("T15", "IOB70B", 5, "LCD_CTP[3]", ""),
    ("Y13", "IOB87A", 5, "cmos_sda", ""),
    ("AA14", "IOB87B", 5, "cmos_scl", "pair of Y13"),
    ("AB13", "IOB89B", 5, "Key_in[0]", ""),
    ("AA9", "IOB53A", 5, "sk9822_da", ""),
    # -- bank 4, SOM general-purpose 3.3 V ---------------------------------
    ("P20", "IOB92A", 4, "LCD_BL", "P1.T14 LED pin"),
    ("N15", "IOB146A", 4, "cmos_db[4]", ""),
    # -- bank 4, the board clock: config role, MEASURED not to fire --------
    ("V22", "IOB104B", 4, "sys_clk", "EMCCLK; needs config_role_ack"),
    # -- bank 2, the dock's RGMII / RTL8211F side --------------------------
    ("F20", "IOR33B", 2, "RGMII_GTXCLK", ""),
    ("D21", "IOR51B", 2, "RGMII_TXD[0]", ""),
    ("E21", "IOR51A", 2, "RGMII_TXD[1]", "pair of D21"),
    ("D22", "IOR49B", 2, "RGMII_TXD[2]", ""),
    ("E22", "IOR49A", 2, "RGMII_TXD[3]", "pair of D22"),
    ("F21", "IOR55A", 2, "RGMII_TXEN", ""),
    ("W20", "IOB122B", 4, "RGMII_RST_N", "MGCLKC_5 clock ball"),
    ("V19", "IOB114B", 4, "PHY_CLK", "SGCLKC_4 clock ball"),
    # -- bank 3, the HDMI TMDS pairs: this board's true-LVDS pairs ---------
    ("J14", "IOR103A", 3, "tmds_d_p_0[0]+", "TRUELVDS pair with H14"),
    ("H14", "IOR103B", 3, "tmds_d_p_0[0]-", "TRUELVDS pair with J14"),
    ("J15", "IOR101A", 3, "tmds_d_p_0[1]+", "TRUELVDS pair with H15"),
    ("H15", "IOR101B", 3, "tmds_d_p_0[1]-", "TRUELVDS pair with J15"),
    ("G15", "IOR105A", 3, "tmds_clk_p_0+", "TRUELVDS pair with G16"),
    ("G16", "IOR105B", 3, "tmds_clk_p_0-", "TRUELVDS pair with G15"),
)

#: `IO_TYPE` values the vendor emits for this device, and the only ones a
#: shape may name.  `LVCMOS33` is the single-ended default PR #423 forced
#: (`gowin_pack.py:6829-6831`).  `LVDS25E` is apicula's **default `IO_TYPE`
#: for an ELVDS buffer** (`get_default_elvds_io_type`,
#: `gowin_pack.py:1658-1660`) -- a default, explicitly **not** a 2.5 V VCCIO
#: requirement (`spec-primitives.md:125`) -- and `LVDS25` is the plain
#: spelling beside it.  A shape naming anything else is naming a string
#: nobody has seen the vendor emit, which is the failure this list exists to
#: stop; the full vendor `IO_TYPE`/VCCIO matrix is *recorded from the oracle*
#: by `P3.T25`, and this set grows only from that record.
VENDOR_IO_TYPES = frozenset({
    DEFAULT_IO_TYPE,          # LVCMOS33
    "LVDS25",
    "LVDS25E",
})

#: `BANK_VCCIO` levels a Phase-3 shape may declare.  Every ball in
#: `SAFE_PINS` is on a 3.3 V bank of this board, so 3.3 is the only level a
#: shape can declare without contradicting the board it is built for; the
#: rest of the ELVDS/VCCIO matrix is measured on the oracle, never asserted
#: from a shape (`P3.T25`).
VENDOR_VCCIO = frozenset({"3.3"})


class IoShape:
    """Base class of the Phase-3 IO/IOLOGIC shapes.

    A subclass declares the shape (`primitive`, `sweep_axis`, `sweep_values`,
    `baseline_value`, `ports`, `scope_tiles`, `clocks`) and implements `rtl`;
    `spec()` assembles the `ShapeSpec` `gen.py` consumes and refuses anything
    outside the board envelope on the way out.
    """

    #: The 3.3 V bank constants every Phase-3 shape is built from.  Phase 5b
    #: adds the DDR set beside it and touches nothing here (`D54`).
    BANK_CONSTANTS = {
        "IO_TYPE": DEFAULT_IO_TYPE,
        "PULL_MODE": "NONE",
        "DRIVE": "8",
        "BANK_VCCIO": "3.3",
        "PULL_STRENGTH": DEFAULT_PULL_STRENGTH,
    }

    # Phase 5b (D54): bank-6 constants

    #: Filled in by the subclass.
    name = None
    primitive = None
    sweep_axis = None
    sweep_values = ()
    baseline_value = None
    #: `{port name: (ball, direction)}` or `{port: (ball, direction, kwargs)}`.
    ports = {}
    #: `[(x, y), ...]` the `E0` comparison is restricted to; empty means the
    #: shape does not pin a tile and the harness compares the whole die.
    scope_tiles = ()
    #: `{port: period in ns}`.
    clocks = {}
    #: Package balls whose config role has a MEASURED acknowledgement.
    config_role_acks = {}
    #: Ports that are halves of a differential pad pair.  They are exempt
    #: from the `IO_TYPE` rules and never from the bank rules.
    diff_pads = ()
    top_module = "top"
    ins_loc = {}

    def rtl(self, sweep_value):
        """The Verilog for one sweep point.  Subclasses implement this."""
        raise NotImplementedError

    # -- pins -------------------------------------------------------------
    def pin(self, ball, direction, **overrides):
        """A `PinSpec` for `ball`, defaulted from `BANK_CONSTANTS`.

        `DRIVE` is dropped on inputs rather than defaulted onto them, because
        the vendor refuses it there (`CT1108`, measured `P0.T19`) and a shape
        that carried it would fail generation rather than the board.
        """
        safe = SAFE_PINS.get(ball)
        if safe is None:
            raise EnvelopeError(
                f"ball {ball!r} is not in SAFE_PINS -- a Phase-3 shape may "
                "claim only balls the Tang Mega 138K brings out at 3.3 V "
                "(add it there, with its board net, or use another ball)")
        drive = overrides.pop("drive", int(self.BANK_CONSTANTS["DRIVE"]))
        spec = dict(
            loc=ball,
            bank=safe.bank,
            io_type=self.BANK_CONSTANTS["IO_TYPE"],
            pull_mode=self.BANK_CONSTANTS["PULL_MODE"],
            pull_strength=self.BANK_CONSTANTS["PULL_STRENGTH"],
            drive=drive if direction == "output" else None,
            direction=direction,
            config_role_ack=self.config_role_acks.get(ball, ""),
        )
        spec.update(overrides)
        return PinSpec(**spec)

    def pins(self):
        """`{port: PinSpec}` from the subclass's `ports` table."""
        built = {}
        for port, entry in self.ports.items():
            ball, direction = entry[0], entry[1]
            extra = entry[2] if len(entry) > 2 else {}
            built[port] = self.pin(ball, direction, **extra)
        return built

    def bank_vccio(self, pins):
        """One `BANK_VCCIO` per bank in use, from `BANK_CONSTANTS`."""
        return {pin.bank: self.BANK_CONSTANTS["BANK_VCCIO"]
                for pin in pins.values()}

    # -- the envelope -----------------------------------------------------
    def assert_envelope(self, spec):
        """Raise on the first ball or setting outside the board envelope.

        Returns `[]` on a clean spec, matching `gen.assert_cst_defaults`'s
        shape so the two can be called in sequence.
        """
        for port, pin in spec.pins.items():
            if port in self.diff_pads:
                # A differential pad takes its standard from the buffer
                # primitive, not from an `IO_TYPE` string -- which is how the
                # vendor's own board constraints spell it
                # (`tang_mega_138K_pins.cst` gives the TMDS pairs
                # `PULL_MODE`/`DRIVE` and no `IO_TYPE` at all).
                if pin.io_type is not None:
                    raise EnvelopeError(
                        f"pin {port!r} at {pin.loc}: a differential pad "
                        "carries no IO_TYPE; the buffer primitive names the "
                        "standard")
                continue
            safe = SAFE_PINS.get(pin.loc)
            if safe is None:
                raise EnvelopeError(
                    f"pin {port!r} at {pin.loc}: not a board ball "
                    "(SAFE_PINS); a shape must not reach a ball nobody has "
                    "checked the wiring of")
            if pin.bank != safe.bank:
                raise EnvelopeError(
                    f"pin {port!r} at {pin.loc}: shape says bank {pin.bank}, "
                    f"the vendor pinout says bank {safe.bank}")
            if pin.bank in DDR_BANKS:
                raise EnvelopeError(
                    f"pin {port!r} at {pin.loc}: bank {pin.bank} is a DDR3 "
                    "bank; no Phase-3 shape places a pin there (D20c, D54)")
            if pin.io_type not in VENDOR_IO_TYPES:
                raise EnvelopeError(
                    f"pin {port!r} at {pin.loc}: IO_TYPE={pin.io_type!r} is "
                    "not one the vendor emits for this device "
                    f"({sorted(VENDOR_IO_TYPES)})")
        for bank, vccio in spec.bank_vccio.items():
            if bank in DDR_BANKS:
                raise EnvelopeError(
                    f"bank {bank} is a DDR3 bank and must not appear in a "
                    "Phase-3 shape's bank_vccio table")
            if vccio not in VENDOR_VCCIO:
                raise EnvelopeError(
                    f"bank {bank}: BANK_VCCIO={vccio!r} is not a level this "
                    f"board is built for ({sorted(VENDOR_VCCIO)})")
        return []

    # -- assembly ---------------------------------------------------------
    def spec(self):
        """The validated `ShapeSpec` `gen.py` loads as the shape file's `SPEC`."""
        pins = self.pins()
        spec = ShapeSpec(
            name=self.name,
            primitive=self.primitive,
            sweep_axis=self.sweep_axis,
            sweep_values=list(self.sweep_values),
            baseline_value=self.baseline_value,
            pins=pins,
            bank_vccio=self.bank_vccio(pins),
            scope=ScopeSpec(tiles=[list(t) for t in self.scope_tiles]),
            rtl=lambda spec, sweep_value=None: self.rtl(
                sweep_value if sweep_value is not None else self.baseline_value),
            top_module=self.top_module,
            ins_loc=dict(self.ins_loc),
            clocks=dict(self.clocks),
            diff_pads=tuple(self.diff_pads),
        )
        self.assert_envelope(spec)
        return spec


#: The HCLK block a gearbox row is measured in, and the lane its `FCLK`
#: lands on -- MEASURED (`P3.T13`, `D107`).
#:
#: Block **4**, cell `(row 108, col 64)`, `(x, y) = (64, 108)` in Himbaechel
#: spelling.  Not block 1, which serves the dock's RGMII balls: a `CLKDIV`
#: placed there is what pins the lane, and block 1 has no modelled clock
#: escape (`D100a`), so its divider's output cannot reach the gearbox's
#: `PCLK` at all -- MEASURED, `nextpnr` reports `Failed to find a route for
#: arc 0 of net pclk`.  The two bottom blocks are the pair `P1.T08d` mapped
#: lane by lane, and every general-purpose 3.3 V ball of bank 5 this board
#: brings out sits in block 4.
GEARBOX_HCLK_BLOCK_XY = (64, 108)

#: `INS_LOC` index of the first lane of that block: SUG1018-1.7E Table 2-2
#: numbers a side's lanes across its blocks, so block 4 is `BOTTOMSIDE[0..3]`
#: and block 5 `BOTTOMSIDE[4..7]` (`P1.T08d`,
#: `$OTC/evidence/hclk/mux38-138c.md` 2).
GEARBOX_HCLK_INS_LOC_BASE = 0

#: The lane the row pins.  Any of the four would do; 2 is the lane the
#: vendor's own unconstrained `OSER4` picked on block 1, so a run that
#: reproduces it is telling us the constraint was read and not that both
#: allocators happened to start at zero.
GEARBOX_FCLK_LANE = 2

#: The one line that pins the divider -- and with it the HCLK lane the
#: gearbox's `FCLK` lands on -- in **both** flows.  `nextpnr-himbaechel`'s
#: `.cst` reader splits the index into a block ordinal and a lane
#: (`cst.cc getConstrainedHCLKBel`), so the vendor's own spelling is the open
#: flow's constraint too and no `(* BEL *)` attribute is needed (`D107`).
GEARBOX_CLKDIV_INS_LOC = "BOTTOMSIDE[%d]" % (GEARBOX_HCLK_INS_LOC_BASE
                                             + GEARBOX_FCLK_LANE)

#: `CLKDIV.DIV_MODE` per gearbox width: a `w`-bit gearbox runs its slow clock
#: at `FCLK / (w / 2)` (UG304E p.62-69), and `3.5` is why `CLKDIV` documents a
#: fractional mode at all -- `OVIDEO` is the 7-bit gearbox.
GEARBOX_DIV_MODE = {4: "2", 7: "3.5", 8: "4", 10: "5"}


def clkdiv_rtl(width, hclkin="fclk", clkout="pclk"):
    """A `CLKDIV` making a gearbox's `PCLK` from its `FCLK`.

    It carries no placement attribute of its own: the `INS_LOC` line both
    flows now read (`GEARBOX_CLKDIV_INS_LOC`) places it, which is what makes
    the HCLK lane part of the comparison rather than each allocator's own
    choice (`D107`).
    """
    return (
        '    CLKDIV %s_div (\n'
        '        .HCLKIN (%s),\n'
        '        .RESETN (resetn),\n'
        '        .CALIB  (1\'b0),\n'
        '        .CLKOUT (%s)\n'
        '    );\n'
        '    defparam %s_div.DIV_MODE = "%s";\n'
        % (clkout, hclkin, clkout, clkout, GEARBOX_DIV_MODE[width]))
