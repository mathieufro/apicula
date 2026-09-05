# pll tool to find best match for the target frequency
# calculations based on: https://github.com/juj/gowin_fpga_code_generators/blob/main/pll_calculator.html
# limits from:
# - http://cdn.gowinsemi.com.cn/DS117E.pdf,
# - http://cdn.gowinsemi.com.cn/DS861E.pdf,
# - https://cdn.gowinsemi.com.cn/DS226E.pdf

import argparse
import re
import sys


# ---------------------------------------------------------------------------
# Frequency algebra
#
# Two different PLL families live in this tool and they do NOT share divider
# semantics.  Keeping the two formulas in named functions is what apicula
# issue #427 cost us: the GW5A-25 entry was served by the rPLL algebra.
# ---------------------------------------------------------------------------

#: PLLA divider ranges, `$GOWINHOME/IDE/bin/prim_syns/gw5a/primitive.xml`
#: (`PLLA`/`PLL` module, `<PARAMETER type="number">` min/max pairs).
PLLA_IDIV_RANGE = range(1, 65)
PLLA_FBDIV_RANGE = range(1, 65)
PLLA_MDIV_RANGE = range(1, 129)
PLLA_ODIV_MIN = 1
PLLA_ODIV_MAX = 128


def rpll_freqs(fclkin, idiv_sel, fbdiv_sel, odiv_sel):
    """(PFD, CLKOUT, VCO) for an rPLL/PLLVR, UG286 -- unchanged behaviour.

    The `_SEL` arguments are the raw minus-one-encoded parameter values, which
    is how the rPLL primitive spells them.
    """
    pfd = fclkin / (idiv_sel + 1)
    clkout = fclkin * (fbdiv_sel + 1) / (idiv_sel + 1)
    vco = clkout * odiv_sel
    return pfd, clkout, vco


def plla_freqs(fclkin, idiv, fbdiv, mdiv, odiv):
    """(Fpfd, Fclkfb, Fvco, Fclkout) for a GW5A PLLA/PLL, internal feedback.

    `UG306-1.0.9E` section 5.1 "PLL", verbatim:

        1. Fpfd   = Fclkin / IDIV
        2. Fclkfb = Fpfd * FBDIV
        3. internal feedback: Fvco = Fclkfb * MDIV
        5. VCO in mode (INMUX from VCO): Fclkoutx = Fvco / ODIVx

    This is the formula apicula issue #427 is about.  The rPLL algebra that
    used to serve the `GW5A-25 ES` entry -- `rpll_freqs()` above -- is wrong
    for a PLLA in three independent ways:

    * PLLA dividers are **direct** (`IDIV_SEL` 1..64), not minus-one encoded,
      so every divider was off by one;
    * the PLLA has an **MDIV** multiplier stage that the rPLL has not, and the
      generator never emitted `MDIV_SEL` at all -- it stayed at its default;
    * on a PLLA the ODIV **divides the VCO down** to the output, whereas the
      rPLL's ODIV multiplies the output up to the VCO.  The old code therefore
      solved `VCO = CLKOUT * ODIV` for a part where `CLKOUT = VCO / ODIV`.

    Together those explain the reported symptom exactly: for the shipped
    `examples/gw5a/clock-PLLA.v` operating point the emitted design ran far
    below the requested frequency and the VCO did not respond to `IDIV`,
    `FBDIV` or `MDIV` as the datasheet says it should.
    """
    pfd = fclkin / idiv
    fclkfb = pfd * fbdiv
    fvco = fclkfb * mdiv
    return pfd, fclkfb, fvco, fvco / odiv


def solve_rpll(limits, fclkin, ftarget):
    """Best rPLL/PLLVR setup for `ftarget`, or `{}`.  Behaviour is unchanged."""
    setup = {}
    min_diff = fclkin
    for IDIV_SEL in range(64):
        for FBDIV_SEL in range(64):
            for ODIV_SEL in [2, 4, 8, 16, 32, 48, 64, 80, 96, 112, 128]:
                PFD, CLKOUT, VCO = rpll_freqs(fclkin, IDIV_SEL, FBDIV_SEL, ODIV_SEL)
                if not (limits["pfd_min"] <= PFD <= limits["pfd_max"]):
                    continue
                if not (limits["clkout_min"] < CLKOUT < limits["clkout_max"]):
                    continue
                if not (limits["vco_min"] < VCO < limits["vco_max"]):
                    continue
                diff = abs(ftarget - CLKOUT)
                if diff < min_diff:
                    min_diff = diff
                    setup = {
                        "IDIV_SEL": IDIV_SEL,
                        "FBDIV_SEL": FBDIV_SEL,
                        "ODIV_SEL": ODIV_SEL,
                        "PFD": PFD,
                        "CLKOUT": CLKOUT,
                        "VCO": VCO,
                        "ERROR": diff,
                    }
    return setup


def solve_plla(limits, fclkin, ftarget):
    """Best PLLA/PLL setup for `ftarget`, or `{}`.

    Searches `IDIV` x `FBDIV` x `MDIV` and derives `ODIV0` directly from the
    VCO, which is exact because `CLKOUT0 = FVCO / ODIV0`.  Band membership is
    inclusive at both ends: the datasheet limits are attainable values, not
    open bounds.
    """
    setup = {}
    min_diff = None
    for IDIV in PLLA_IDIV_RANGE:
        pfd = fclkin / IDIV
        if not (limits["pfd_min"] <= pfd <= limits["pfd_max"]):
            continue
        for FBDIV in PLLA_FBDIV_RANGE:
            fclkfb = pfd * FBDIV
            if fclkfb * PLLA_MDIV_RANGE.start > limits["vco_max"]:
                break
            for MDIV in PLLA_MDIV_RANGE:
                fvco = fclkfb * MDIV
                if fvco > limits["vco_max"]:
                    break
                if fvco < limits["vco_min"]:
                    continue
                for ODIV in {min(max(int(round(fvco / ftarget)) + d, PLLA_ODIV_MIN),
                                 PLLA_ODIV_MAX)
                             for d in (-1, 0, 1)}:
                    clkout = fvco / ODIV
                    if not (limits["clkout_min"] <= clkout <= limits["clkout_max"]):
                        continue
                    diff = abs(ftarget - clkout)
                    if min_diff is None or diff < min_diff:
                        min_diff = diff
                        setup = {
                            "IDIV_SEL": IDIV,
                            "FBDIV_SEL": FBDIV,
                            "MDIV_SEL": MDIV,
                            "ODIV0_SEL": ODIV,
                            "PFD": pfd,
                            "CLKFB": fclkfb,
                            "CLKOUT": clkout,
                            "VCO": fvco,
                            "ERROR": diff,
                        }
    return setup


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "-i", "--input-freq-mhz", help="PLL Input Frequency", type=float, default=27
    )
    parser.add_argument(
        "-o", "--output-freq-mhz", help="PLL Output Frequency", type=float, default=108
    )
    parser.add_argument(
        "-d", "--device", help="Device", type=str, default="GW1NR-9 C6/I5"
    )
    parser.add_argument(
        "-f",
        "--filename",
        help="Save PLL configuration as Verilog to file",
        type=str,
        default=None,
    )
    parser.add_argument(
        "-m",
        "--module-name",
        help="Specify different Verilog module name than the default 'pll'",
        type=str,
        default="pll",
    )
    parser.add_argument("-l", "--list-devices", help="list device", action="store_true")

    args = parser.parse_args()

    device_name = args.device
    match = re.search(
        r"(GW[125][A-Z]{1,3})-[A-Z]{0,2}([0-9]{1,2})[A-Z]{1,3}[0-9]{1,3}P*N*(C[0-9]/I[0-9]|ES)",
        device_name,
    )
    if match:
        device_name = f"{match.group(1)}-{match.group(2)} {match.group(3)}"
    else:
        print(f'Warning: cannot decipher the name of the device {device_name}.')

    device_limits = {
        "GW1N-1 C6/I5": {
            "comment": "Untested",
            "pll_name": "rPLL",
            "pfd_min": 3,
            "pfd_max": 400,
            "vco_min": 400,
            "vco_max": 900,
            "clkout_min": 3.125,
            "clkout_max": 450,
        },
        "GW1N-1 C5/I4": {
            "comment": "Untested",
            "pll_name": "rPLL",
            "pfd_min": 3,
            "pfd_max": 320,
            "vco_min": 320,
            "vco_max": 720,
            "clkout_min": 2.5,
            "clkout_max": 360,
        },
        "GW1NR-2 C7/I6": {
            "comment": "Untested",
            "pll_name": "PLLVR",
            "pfd_min": 3,
            "pfd_max": 400,
            "vco_min": 400,
            "vco_max": 800,
            "clkout_min": 3.125,
            "clkout_max": 750,
        },
        "GW1NR-2 C6/I5": {
            "comment": "Untested",
            "pll_name": "PLLVR",
            "pfd_min": 3,
            "pfd_max": 400,
            "vco_min": 400,
            "vco_max": 800,
            "clkout_min": 3.125,
            "clkout_max": 750,
        },
        "GW1NR-2 C5/I4": {
            "comment": "Untested",
            "pll_name": "PLLVR",
            "pfd_min": 3,
            "pfd_max": 320,
            "vco_min": 320,
            "vco_max": 640,
            "clkout_min": 2.5,
            "clkout_max": 640,
        },
        "GW1NR-4 C6/I5": {
            "comment": "Untested",
            "pll_name": "PLLVR",
            "pfd_min": 3,
            "pfd_max": 400,
            "vco_min": 400,
            "vco_max": 1000,
            "clkout_min": 3.125,
            "clkout_max": 500,
        },
        "GW1NR-4 C5/I4": {
            "comment": "Untested",
            "pll_name": "PLLVR",
            "pfd_min": 3,
            "pfd_max": 320,
            "vco_min": 320,
            "vco_max": 800,
            "clkout_min": 2.5,
            "clkout_max": 400,
        },
        "GW1NSR-4 C7/I6": {
            "comment": "Untested",
            "pll_name": "PLLVR",
            "pfd_min": 3,
            "pfd_max": 400,
            "vco_min": 400,
            "vco_max": 1200,
            "clkout_min": 3.125,
            "clkout_max": 600,
        },
        "GW1NSR-4 C6/I5": {
            "comment": "Untested",
            "pll_name": "PLLVR",
            "pfd_min": 3,
            "pfd_max": 400,
            "vco_min": 400,
            "vco_max": 1200,
            "clkout_min": 3.125,
            "clkout_max": 600,
        },
        "GW1NSR-4 C5/I4": {
            "comment": "Untested",
            "pll_name": "PLLVR",
            "pfd_min": 3,
            "pfd_max": 320,
            "vco_min": 320,
            "vco_max": 960,
            "clkout_min": 2.5,
            "clkout_max": 480,
        },
        "GW1NSR-4C C7/I6": {
            "comment": "Untested",
            "pll_name": "PLLVR",
            "pfd_min": 3,
            "pfd_max": 400,
            "vco_min": 400,
            "vco_max": 1200,
            "clkout_min": 3.125,
            "clkout_max": 600,
        },
        "GW1NSR-4C C6/I5": {
            "comment": "Untested",
            "pll_name": "PLLVR",
            "pfd_min": 3,
            "pfd_max": 400,
            "vco_min": 400,
            "vco_max": 1200,
            "clkout_min": 3.125,
            "clkout_max": 600,
        },
        "GW1NSR-4C C5/I4": {
            "comment": "Untested",
            "pll_name": "PLLVR",
            "pfd_min": 3,
            "pfd_max": 320,
            "vco_min": 320,
            "vco_max": 960,
            "clkout_min": 2.5,
            "clkout_max": 480,
        },
        "GW1NR-9 C7/I6": {
            "comment": "Untested",
            "pll_name": "rPLL",
            "pfd_min": 3,
            "pfd_max": 400,
            "vco_min": 400,
            "vco_max": 1200,
            "clkout_min": 3.125,
            "clkout_max": 600,
        },
        "GW1NR-9 C6/I5": {
            "comment": "tested on TangNano9K Board",
            "pll_name": "rPLL",
            "pfd_min": 3,
            "pfd_max": 400,
            "vco_min": 400,
            "vco_max": 1200,
            "clkout_min": 3.125,
            "clkout_max": 600,
        },
        "GW1NR-9 C6/I4": {
            "comment": "Untested",
            "pll_name": "rPLL",
            "pfd_min": 3,
            "pfd_max": 320,
            "vco_min": 3200,
            "vco_max": 960,
            "clkout_min": 2.5,
            "clkout_max": 480,
        },
        "GW1NZ-1 C6/I5": {
            "comment": "untested",
            "pll_name": "rPLL",
            "pfd_min": 3,
            "pfd_max": 400,
            "vco_min": 400,
            "vco_max": 800,
            "clkout_min": 3.125,
            "clkout_max": 400,
        },
        "GW2A-18 C8/I7": {
            "comment": "untested",
            "pll_name": "rPLL",
            "pfd_min": 3,
            "pfd_max": 500,
            "vco_min": 500,
            "vco_max": 1250,
            "clkout_min": 3.90625,
            "clkout_max": 625,
        },
        "GW2AR-18 C8/I7": {
            "comment": "untested",
            "pll_name": "rPLL",
            "pfd_min": 3,
            "pfd_max": 500,
            "vco_min": 500,
            "vco_max": 1250,
            "clkout_min": 3.90625,
            "clkout_max": 625,
        },
        "GW5A-25 ES": {
            "comment": "untested",
            # apicula issue #427: this entry used to say "rPLL". The GW5A-25's
            # PLL primitive is PLLA (UG306-1.0.1E Table 5-11 lists GW5A-25 as
            # the only PLLA part), whose divider algebra is NOT the rPLL's --
            # see solve_plla() below.
            "pll_name": "PLLA",
            "pll_kind": "PLLA",
            "pfd_min": 19,
            "pfd_max": 800,
            "vco_min": 800,
            "vco_max": 1600,
            # The previous four parameters are taken from the datasheet (as in
            # this case from https://cdn.gowinsemi.com.cn/DS1103E.pdf), but I
            # don't know where these two come from:(
            "clkout_min": 6.25,
            "clkout_max": 1600,
        },
    }

    if args.list_devices:
        for device in device_limits:
            print(f"{device} - {device_limits[device]['comment']}")
        sys.exit(0)

    if device_name not in device_limits:
        print(f"ERROR: device '{device_name}' not found")
        sys.exit(1)

    limits = device_limits[device_name]
    kind = limits.get("pll_kind", "rPLL")

    FCLKIN = args.input_freq_mhz

    if kind == "PLLA":
        setup = solve_plla(limits, FCLKIN, args.output_freq_mhz)
    else:
        setup = solve_rpll(limits, FCLKIN, args.output_freq_mhz)

    if not setup:
        return

    if kind == "PLLA":
        pll_v = f"""/**
 * PLL configuration
 *
 * This Verilog module was generated automatically
 * using the gowin-pll tool.
 * Use at your own risk.
 *
 * Target-Device:                {device_name}
 * Given input frequency:        {args.input_freq_mhz:0.3f} MHz
 * Requested output frequency:   {args.output_freq_mhz:0.3f} MHz
 * Achieved output frequency:    {setup['CLKOUT']:0.3f} MHz
 */

module {args.module_name}(
        input  clock_in,
        output clock_out,
        output locked
    );

    {limits['pll_name']} #(
        .FCLKIN("{args.input_freq_mhz}"),
        .IDIV_SEL({setup['IDIV_SEL']}), // -> PFD = {setup['PFD']} MHz (range: {limits['pfd_min']}-{limits['pfd_max']} MHz)
        .FBDIV_SEL({setup['FBDIV_SEL']}), // -> CLKFB = {setup['CLKFB']} MHz
        .MDIV_SEL({setup['MDIV_SEL']}), // -> VCO = {setup['VCO']} MHz (range: {limits['vco_min']}-{limits['vco_max']} MHz)
        .ODIV0_SEL({setup['ODIV0_SEL']}), // -> CLKOUT0 = {setup['CLKOUT']} MHz (range: {limits['clkout_min']}-{limits['clkout_max']} MHz)
        .CLKOUT0_EN("TRUE"),
        .CLKFB_SEL("INTERNAL")
    ) pll (
        .CLKIN(clock_in), // {args.input_freq_mhz} MHz
        .CLKFB(1'b0), .RESET(1'b0), .PLLPWD(1'b0), .RESET_I(1'b0), .RESET_O(1'b0),
        .PSSEL(3'b0), .PSDIR(1'b0), .PSPULSE(1'b0),
        .SSCPOL(1'b0), .SSCON(1'b0), .SSCMDSEL(7'b0), .SSCMDSEL_FRAC(3'b0),
        .CLKOUT0(clock_out), // {setup['CLKOUT']} MHz
        .CLKOUT1(), .CLKOUT2(), .CLKOUT3(), .CLKOUT4(), .CLKOUT5(), .CLKOUT6(),
        .CLKFBOUT(),
        .LOCK(locked)
    );

endmodule
"""
    else:
        extra_options = ""
        if limits["pll_name"] == "PLLVR":
            extra_options = ".VREN(1'b1),"

        pll_v = f"""/**
 * PLL configuration
 *
 * This Verilog module was generated automatically
 * using the gowin-pll tool.
 * Use at your own risk.
 *
 * Target-Device:                {device_name}
 * Given input frequency:        {args.input_freq_mhz:0.3f} MHz
 * Requested output frequency:   {args.output_freq_mhz:0.3f} MHz
 * Achieved output frequency:    {setup['CLKOUT']:0.3f} MHz
 */

module {args.module_name}(
        input  clock_in,
        output clock_out,
        output locked
    );

    {limits['pll_name']} #(
        .FCLKIN("{args.input_freq_mhz}"),
        .IDIV_SEL({setup['IDIV_SEL']}), // -> PFD = {setup['PFD']} MHz (range: {limits['pfd_min']}-{limits['pfd_max']} MHz)
        .FBDIV_SEL({setup['FBDIV_SEL']}), // -> CLKOUT = {setup['CLKOUT']} MHz (range: {limits['clkout_min']}-{limits['clkout_max']} MHz)
        .ODIV_SEL({setup['ODIV_SEL']}) // -> VCO = {setup['VCO']} MHz (range: {limits['vco_min']}-{limits['vco_max']} MHz)
    ) pll (.CLKOUTP(), .CLKOUTD(), .CLKOUTD3(), .RESET(1'b0), .RESET_P(1'b0), .CLKFB(1'b0), .FBDSEL(6'b0), .IDSEL(6'b0), .ODSEL(6'b0), .PSDA(4'b0), .DUTYDA(4'b0), .FDLY(4'b0), {extra_options}
        .CLKIN(clock_in), // {args.input_freq_mhz} MHz
        .CLKOUT(clock_out), // {setup['CLKOUT']} MHz
        .LOCK(locked)
    );

endmodule
"""

    if args.filename:
        open(args.filename, "w").write(pll_v)
    else:
        print(pll_v)


if __name__ == "__main__":
    main()
