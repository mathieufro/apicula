"""Every `AE350_SOC` tap points the way the routing graph allows.

The block sits in die row 0, a row of tiles that carry pips but no bels. A tap
is therefore an ordinary local wire, and its direction is fixed by that wire's
role in the routing graph rather than by the `.dat` table it was read from:
`F`/`Q`/`OF` end no pip, so only the block can drive them and they are its
outputs; `A`-`D`, `CE`, `CLK` and `LSR` are pip destinations and dead ends
unless the block reads them, so they are its inputs.

The counts are measured from the vendor bitstream of the 149-port vehicle
(`$OTC/evidence/ae350/e0-138c.md`): 415 of the 416 fabric-driven wires carry a
pip the vendor set, 418 pips are sourced from `F`/`Q`/`OF`, and the `CE`, `LSR`
and `CLK` tap counts are exactly the block's 13 clock-enable, 2 reset and 6
clock inputs.
"""

import os
import re
from pathlib import Path

import pytest

from apycula import chipdb as chipdb_mod

DEVICE = "GW5AST-138C"
ANCHOR = (0, 159)
INPUT_BITS = 416
OUTPUT_BITS = 495
#: Wire classes only the block can drive.
BLOCK_DRIVEN = re.compile(r"(?:Q|F|OF)\d+\Z")


def portmap():
    path = Path(__file__).resolve().parent.parent / "apycula" / f"{DEVICE}.msgpack.xz"
    if not path.is_file():
        pytest.skip(f"{path} is absent; run `make apycula/{DEVICE}.msgpack.xz`")
    db = chipdb_mod.load_chipdb(str(path))
    return db.extra_func[ANCHOR]["ae350"]


def tap_wire(port, value):
    """The bare wire name behind a port map entry, or None when unmapped."""
    if value.startswith(chipdb_mod._AE350_UNMAPPED_PREFIX):
        return None
    alias = f"AE350_SOC{port}"
    return value[len(alias):] if value.startswith(alias) else value


def test_ae350_inputs_never_sit_on_a_block_driven_wire():
    ef = portmap()
    assert len(ef["ins"]) == INPUT_BITS
    wrong = {p: w for p, v in ef["ins"].items()
             if (w := tap_wire(p, v)) and BLOCK_DRIVEN.match(w)}
    assert wrong == {}


def test_ae350_outputs_only_sit_on_block_driven_wires():
    ef = portmap()
    assert len(ef["outs"]) == OUTPUT_BITS
    wrong = {p: w for p, v in ef["outs"].items()
             if (w := tap_wire(p, v)) and not BLOCK_DRIVEN.match(w)}
    assert wrong == {}


def test_ae350_reset_and_clock_inputs_sit_on_dedicated_lines():
    ef = portmap()
    resets = {p: tap_wire(p, ef["ins"][p]) for p in chipdb_mod._AE350_SOC_RESET_PORTS}
    clocks = {p: tap_wire(p, ef["ins"][p]) for p in chipdb_mod._AE350_SOC_CLOCK_PORTS}
    assert all(w and w.startswith("LSR") for w in resets.values()), resets
    assert all(w and w.startswith("CLK") for w in clocks.values()), clocks


def test_ae350_clock_enable_inputs_sit_on_the_thirteen_ce_lines():
    ef = portmap()
    ce = {p: w for p, v in ef["ins"].items()
          if (w := tap_wire(p, v)) and w.startswith("CE")}
    assert sorted(ce) == sorted(
        ["CORE_CE", "AXI_CE", "DDR_CE", "AHB_CE", "APB2AHB_CE"]
        + [f"APB_CE{i}" for i in range(8)])


def test_ae350_output_map_spans_both_table_runs():
    """The output map is stored either side of the input map, not in one table."""
    ef = portmap()
    mapped = [p for p, v in ef["outs"].items()
              if tap_wire(p, v) is not None]
    # The head run (`Ae350SocOuts` below the input run) and the tail run above it
    # both have to contribute, or one of the two stores was dropped.
    assert tap_wire("PRDYN_CHAIN_O", ef["outs"]["PRDYN_CHAIN_O"]) is not None
    assert tap_wire("ROM_HADDR0", ef["outs"]["ROM_HADDR0"]) is not None
    assert len(mapped) == OUTPUT_BITS - len(
        [p for p in ef["unmapped"] if p in ef["outs"]])
