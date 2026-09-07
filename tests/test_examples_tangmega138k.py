"""The Tang Mega 138K examples that go with the AE350 and dual-purpose rows.

Two things can rot here without anyone noticing.  The Makefile is shared by
every GW5A board, so a new target is easy to add in a way that quietly drops
an existing one; and the dual-purpose example's whole point is *which* options
it asks for, which is a property of one command line and of nothing else.
Both are read here out of the Makefile itself rather than out of a build.
"""
import os
import re
import shutil
import subprocess

import pytest

EXAMPLES = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        'examples', 'gw5a')

#: The bitstreams the board's list carried before the AE350 work, in order.
ORIGINAL_TARGETS = ('big-shift-tangmega138k.fs', 'attosoc-tangmega138k.fs',
                    'uart-message-tangmega138k.fs')

NEW_TARGETS = ('ae350-emb-tcm-tangmega138k.fs', 'dualpin-tangmega138k.fs')


def makefile():
    with open(os.path.join(EXAMPLES, 'Makefile')) as fh:
        return fh.read()


def recipe(target):
    """The recipe lines of an explicit Makefile target, or `None`."""
    match = re.search(r'^%s:[^\n]*\n((?:\t[^\n]*\n)+)' % re.escape(target),
                      makefile(), re.M)
    return match.group(1) if match else None


def test_makefile_tangmega138k_list_names_the_new_targets():
    body = re.search(r'^tangmega138k:((?:[^\n]*\\\n)*[^\n]*)\n', makefile(), re.M)
    assert body is not None
    listed = body.group(1).replace('\\', '').split()
    assert listed[:len(ORIGINAL_TARGETS)] == list(ORIGINAL_TARGETS)
    assert set(NEW_TARGETS) <= set(listed[len(ORIGINAL_TARGETS):])


@pytest.mark.parametrize('target', [t[:-len('.fs')] + '-synth.json'
                                    for t in NEW_TARGETS])
def test_makefile_has_explicit_synth_rules_for_new_examples(target):
    """There is no `%-tangmega138k-synth.json` pattern rule to fall back on."""
    assert recipe(target) is not None


def test_dualpin_example_omits_the_two_refused_options():
    """`reconfign` and `i2c` are refusals on this device, not oversights."""
    pack = recipe('dualpin-tangmega138k.fs')
    assert pack is not None
    assert '--reconfign_as_gpio' not in pack
    assert '--i2c_as_gpio' not in pack


def test_ae350_example_declares_the_blackbox():
    """The open flow has no cell for the block, and `gw_sh` must not see one."""
    with open(os.path.join(EXAMPLES, 'ae350-emb-tcm.v')) as fh:
        source = fh.read()
    assert re.search(r'`ifdef\s+YOSYS\s*\n\(\* blackbox \*\)\s*\n'
                     r'module\s+AE350_SOC\s*\(', source)


@pytest.mark.heavy
def test_examples_build():
    """The two examples really do reach a bitstream, from a clean state.

    The tools are required, not optional: `gate.env` puts the installed
    `nextpnr-himbaechel` (the one paired with the installed chipdb) and the
    venv's `gowin_pack` on `PATH`, so a missing tool is a broken gate
    environment and is named as one rather than surfacing as an opaque
    `make` exit status.
    """
    for tool in ('nextpnr-himbaechel', 'gowin_pack', 'yosys'):
        assert shutil.which(tool), (
            f'{tool} is not on PATH; the gate environment (gate.env) is '
            f'incomplete, so this test cannot say anything about the examples')
    for target in NEW_TARGETS:
        for stale in (target, target[:-len('.fs')] + '.json',
                      target[:-len('.fs')] + '-synth.json'):
            path = os.path.join(EXAMPLES, stale)
            if os.path.exists(path):
                os.remove(path)
    assert subprocess.call(['make', '-C', EXAMPLES, *NEW_TARGETS]) == 0
    for target in NEW_TARGETS:
        assert os.path.getsize(os.path.join(EXAMPLES, target)) > 0
