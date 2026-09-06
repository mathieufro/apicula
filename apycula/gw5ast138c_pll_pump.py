"""Charge-pump and loop-filter constants of the GW5AST-138C `PLL`.

The vendor derives four `PLL` attributes from the operating point alone rather
than from the cell's parameters -- `FLDCOUNT`, `KVCO`, `A_ICP_SEL` and
`A_LPF_RES_SEL`.  On the GW5A-25A that derivation is
`Device.get_pll_pump` driven by `get_pll_freq_R` / `get_pll_coeffs`; this
device has neither, and the 25A's cannot be borrowed, because its VCO band is
`[800, 1600]` MHz against this one's `[650, 1300]` and its loop filter is a
different curve.  The constants below were therefore **measured**, not derived
from a datasheet: no Gowin document publishes them.

How they were measured
----------------------
44 vendor bitstreams, each one hard `PLL` at `PLL_L[0]`, spanning
`Fpfd` 19 .. 50 MHz and `FVCO` 650 .. 1300 MHz -- the whole region
DS1239E Table 3-18 allows and the vendor accepts.  In each, the absolute value
of the four attributes was read back out of the site's `shortval[35]` table.
The runs, in `$OTC/evidence/plla/`:

    p1-pll-sweep-a   20 runs   IDIV / FBDIV axes      (P1.T23)
    p1-pll-sweep-b   20 runs   ODIV0 / ODIV1 / MDIV   (P1.T41)
    p1-pll-pump      10 runs   the (Fpfd, Ndiv) wedge (P1.T41)

47 of those 50 runs produced a bitstream; the fit uses the 44 whose
`MDIV_SEL >= 2` (see `MDIV_SEL_MIN`), and reproduces all 44 exactly.

The model
---------
It is the vendor's own algebra with this device's constants.  The
charge current is proportional to the feedback divider and inversely
proportional to the square of the loop-filter resistor, and the vendor picks
the smallest resistor of its ladder that keeps the current at or below
`ICP_MAX_UA`:

    Ic(R, Ndiv) = ICP_PER_NDIV[R] * Ndiv          (in units of 10 uA)
    R           = the first entry of ICP_PER_NDIV with Ic <= ICP_MAX_UA
    A_ICP_SEL   = round(Ic) * 10

`R` and the pair `(Kvco, C1)` the 25A parameterises this with are **not
separately identifiable** from a bitstream -- only their product appears in
`Ic` -- so the fit is stated as the product and no fictional resistance is
written down.  The two coefficients are each pinned to better than 1 % by the
rounding intervals of the runs that use them (`R4` by 35 runs to
`[0.70313, 0.70833]`, `R5` by 9 to `[0.20238, 0.20652]`), and their ratio,
3.45, is the 1.86 resistor-ladder step the 25A's own table steps by.
"""

#: `A_LPF_RES_SEL` is written as the symbolic value `R<n>`; `pll_attrvals`
#: names `R1` .. `R7`.  Entries are ordered by ascending resistance, which is
#: the order the vendor searches them in.
#:
#: Only `R4` and `R5` are reachable on this device: `R3` would need
#: `Ndiv < 11.5` at a `Fpfd` low enough to keep `FVCO` in band, and `R6` needs
#: `Ndiv > 137` against a maximum of `1300/19 = 68.4`.  Both are therefore
#: absent rather than guessed -- an operating point that asked for one would
#: raise, which is the honest answer for a constant nothing has measured.
ICP_PER_NDIV = ((4, 0.705729), (5, 0.204451))

#: `Ic` ceiling, in the same units as `ICP_PER_NDIV * Ndiv` (10 uA), i.e. the
#: `0.00028` A of the vendor's own loop.  MEASURED to lie in `[39.53, 39.82]`
#: divided by the `R4` coefficient: `Ndiv 38` still uses `R4` and `Ndiv 40`
#: has already stepped to `R5`.
ICP_MAX_UA = 28.0

#: `FLDCOUNT` counts `Fpfd` in 30 MHz steps, one-based and scaled by 16.  The
#: 25A offsets the step by 1 MHz and then corrects four high bands; this device
#: does neither -- MEASURED, the step sits exactly at 30 MHz (`Fpfd` 28.571
#: gives 16 and 30.769 gives 32).  Only the first boundary is observable: a
#: `Fpfd` above 60 MHz needs `FCLKIN > 600` MHz, which this device's vendor
#: flow refuses on a single-ended input (`P1.T41`, `PA2078`).
FLDCOUNT_STEP_MHZ = 30.0

#: `KVCO` is a constant on this device.  The 25A ties it to `FLDCOUNT`
#: (`fclkin_idx // 16`); here it is 7 at every one of the 47 measured points,
#: across the whole `Fpfd` and `FVCO` range, so it is written as the measured
#: constant rather than as a formula that happens to be wrong.
KVCO = 7

#: `MDIV_SEL` 1 is not a supported value.  MEASURED (`P1.T41`, points
#: `f19_n35`, `f40_n17`, `f50_n13`): the vendor validates `FVCO` with the
#: requested `MDIV_SEL 1` and then writes `A_MDIV_SEL 8` -- its own default --
#: together with a charge pump that matches neither divider.  A bitstream
#: built from `MDIV_SEL 1` therefore cannot agree with the vendor's whatever
#: this module does, so the value is refused instead of silently mis-encoded.
MDIV_SEL_MIN = 2


class PllPumpError(Exception):
    """An operating point no measured constant covers."""


def fldcount(fref):
    """`FLDCOUNT` for a phase-detector frequency in MHz."""
    return (int(fref // FLDCOUNT_STEP_MHZ) + 1) * 16


def pump(fref, fvco):
    """`(fldcount, icp, r_idx)` -- the same triple `get_pll_pump` returns.

    `fref` and `fvco` are in MHz; `Ndiv = fvco / fref` is the feedback divider
    the charge current scales with.
    """
    ndiv = fvco / fref
    for r_idx, per_ndiv in ICP_PER_NDIV:
        current = per_ndiv * ndiv
        if current <= ICP_MAX_UA:
            return fldcount(fref), int(current + 0.5) * 10, r_idx
    raise PllPumpError(
        f"no measured loop-filter resistor of the GW5AST-138C carries "
        f"Ndiv {ndiv:.3f} (Fpfd {fref} MHz, FVCO {fvco} MHz): the fitted "
        f"ladder covers Ndiv up to {ICP_MAX_UA / ICP_PER_NDIV[-1][1]:.1f}")
