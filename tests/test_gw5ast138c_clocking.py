"""Phase 1 (clocking) unit tests for GW5AST-138C.

Owned by `blueprints/P1-clocking.md`; one section per task. The HCLK facts
asserted here are the MEASURED ones recorded in
`$OTC/evidence/hclk/topology-138c.md` (P1.T04) -- notably the **2 top / 4
bottom** die-half partition, which refutes the blueprint's assumed 3/3.
"""
import os
import re
from pathlib import Path

import pytest

from apycula import chipdb
from apycula import wirenames as wnames


# ---------------------------------------------------------------- P1.T05

def test_gw5_ihclk_wire_num_has_138c():
    n = chipdb.gw5_ihclk_wire_num('GW5AST-138C')
    assert isinstance(n, int) and n > 0
    # the 25A value is untouched
    assert chipdb.gw5_ihclk_wire_num('GW5A-25A') == 65
    # no `.get(device, ...)` default was introduced
    for absent in ('GW1N-9', 'GW5AT-60B'):
        with pytest.raises(KeyError):
            chipdb.gw5_ihclk_wire_num(absent)


# ---------------------------------------------------------------- P1.T06

def test_gw5a_hclk_locs_138c_six_blocks():
    locs = chipdb._gw5a_hclk_locs['GW5AST-138C']
    assert sorted(locs) == [0, 1, 2, 3, 4, 5]
    assert len(set(locs.values())) == 6
    a25 = chipdb._gw5a_hclk_locs['GW5A-25A']
    assert len(a25) == 4
    assert a25[0] == (0, 64)
