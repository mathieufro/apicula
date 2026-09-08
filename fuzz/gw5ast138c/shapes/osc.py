"""`osc` -- the batch entry point for the oscillator family (`P3.T31`).

`gen.py` loads exactly one `SPEC` per shape module, and `adc_osc.py` is the
single home of both the ADC and the oscillator (the blueprint's file), so this
module is what `--shape osc` names. It adds nothing of its own.
"""
from .adc_osc import OscShape

SPEC = OscShape().spec()
