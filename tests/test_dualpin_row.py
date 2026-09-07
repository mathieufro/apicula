"""The Dual-purpose-pins row itself (`P2.T29`).

`spec-primitives.md` §6 sets one bar: `E1` per option, nine options.  These
tests read the row the sweep wrote, not the code that wrote it, so a row that
silently lost a point or slipped to `E0` fails here rather than in a reader's
head three phases later.

`test_dualpin_attributed_bits_match_packer` is the one that matters: it says
the bits the vendor moves for an option are exactly the bits `gowin_pack`
emits for it.  A non-empty symmetric difference is a `DIFF` -- either the
packer sets a fuse the vendor does not (a used pin configured differently from
the vendor's own, the PR #423 class) or it misses one the vendor sets.
"""
import collections
import json
import os
import types

import pytest

from apycula import gowin_pack as gp
from fuzz.gw5ast138c.harness import evidence
from fuzz.gw5ast138c.shapes import dualpin


def _slug(name):
    path = os.path.join(evidence.evidence_root(), 'dualpin', name)
    if not os.path.exists(path):
        pytest.skip(f'{path} not written yet')
    return path


def rows():
    with open(_slug('runs.jsonl')) as fh:
        return [json.loads(line) for line in fh if line.strip()]


def test_dualpin_row_count_is_nine():
    assert len(rows()) == 9


def test_dualpin_all_nine_rows_e1():
    assert [r['level'] for r in rows()] == ['E1'] * 9
    assert all(r['verdict'] in ('ok', 'diff') for r in rows())


def test_dualpin_attributed_bits_match_packer():
    with open(os.path.join(_slug('diff'), '_all.json')) as fh:
        measured = json.load(fh)
    assert sorted(measured) == sorted(dualpin.SWEEP_POINTS)
    for point, data in measured.items():
        assert data['symdiff'] == {}, (point, data['symdiff'])


def test_dualpin_cpu_as_gpio_2_resolved():
    with open(_slug('summary.md')) as fh:
        lines = [l for l in fh if 'CPU_AS_GPIO_2' in l]
    named = [l for l in lines if 'emitted' in l or 'sets no bit' in l]
    assert len(named) == 1, lines


def test_dualpin_packer_agrees_with_the_row_on_cpu_as_gpio_2():
    """The code and the record say the same thing about attrid 37."""
    args = types.SimpleNamespace(
        **{f'{o}_as_gpio': (o == 'cpu') for o in dualpin.OPTIONS})
    stub = types.SimpleNamespace(cli_args=types.SimpleNamespace(args=args))
    emitted = {av.attr for av in gp.GW5AST_138C.get_pins_attr_vals(stub)}
    assert ('CPU_AS_GPIO_2' in emitted) == dualpin.CPU_AS_GPIO_2_SETS_A_BIT
