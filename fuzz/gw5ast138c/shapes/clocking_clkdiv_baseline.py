"""`clocking_clkdiv_baseline` -- the CLKDIV sweep's baseline run (`P1.T14`).

`clocking_clkdiv` at the documented default `DIV_MODE = "2"`
(`gowin_pack.GW5A.get_default_clkdiv_divmode`) and nothing else changed: the
reference point every swept run is differenced against, run as its own oracle
run rather than borrowed from the sweep (`spec-harness.md` §7 -- the baseline
is the same design at the documented default, never an empty design).

It is a separate shape, not a sweep point, because a batch is a list of run
ids derived from one shape's `sweep_values`: giving the baseline its own batch
is what makes it an *independent* measurement of the reference point, and the
two `DIV_MODE = "2"` bitstreams agreeing is itself the sweep's reproducibility
check.
"""
import dataclasses

from .clocking_clkdiv import DEFAULT_DIV_MODE, SPEC as _PINNED

SPEC = dataclasses.replace(
    _PINNED,
    name="clocking_clkdiv_baseline",
    sweep_values=[DEFAULT_DIV_MODE],
    baseline_value=DEFAULT_DIV_MODE,
)
