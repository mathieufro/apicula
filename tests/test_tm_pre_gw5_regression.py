"""P0.T35 regression guard: the `S17a` change is GW5A-only.

`read_tm`'s GW5A branch was relabelled and the `_aliases` table emptied
(`doc/timing-c1i0.md`). Neither touches the GW1N or GW2A `chunk_order` lists
(cross-phase F27 forbids editing them), and `_aliases` never had a GW1N/GW2A
entry -- so parsing a pre-GW5 `.tm` must be *identical* to upstream
`apycula==0.33`, which `$FL/vendor/venv-upstream` holds unmodified.

The comparison is made against that installed upstream module, loaded by path,
rather than against golden numbers pinned in this file: it proves equality
against the real reference implementation for every group, path and corner of
the file, not just the handful of values a golden would list.
"""
import glob
import importlib.util
import os

import pytest

from apycula import tm_parser
from fuzz.gw5ast138c.harness import paths

def _upstream_tm_parser_path():
    """`apycula==0.33`'s `tm_parser.py` inside `venv-upstream`, or None.

    The venv's `python3.N` directory name is not part of the claim, so it is
    globbed rather than written down (`S26` is about the baseline package, not
    about this box's interpreter).
    """
    venv = paths.upstream_venv()
    if not venv:
        return None
    hits = sorted(glob.glob(os.path.join(
        venv, 'lib', 'python*', 'site-packages', 'apycula', 'tm_parser.py')))
    return hits[0] if hits else None

PRE_GW5_DEVICES = ['GW1N-9C', 'GW2A-18C']


@pytest.fixture(scope='module')
def upstream_tm_parser():
    """`apycula==0.33`'s own `tm_parser`, loaded from `venv-upstream` by path.

    It imports only `os`/`sys`/`struct`, so it loads standalone without that
    venv being on `sys.path`. Skips (never fails) when the venv is absent.
    """
    upstream = _upstream_tm_parser_path()
    if not upstream or not os.path.isfile(upstream):
        pytest.skip(f'upstream apycula==0.33 not installed at '
                    f'{upstream} (D56 baseline venv)')
    spec = importlib.util.spec_from_file_location(
        'upstream_tm_parser', upstream)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize('device', PRE_GW5_DEVICES)
def test_pre_gw5_tm_parse_matches_upstream(device, device_file,
                                           upstream_tm_parser):
    """GW1N/GW2A `.tm` parsing is unchanged, table for table, value for value."""
    path = device_file(device, 'tm')
    if not os.path.isfile(path):
        pytest.skip(f'{device}.tm absent from the selected Gowin install')
    with open(path, 'rb') as fh:
        ours = tm_parser.read_tm(fh, device)
    with open(path, 'rb') as fh:
        theirs = upstream_tm_parser.read_tm(fh, device)

    assert sorted(ours) == sorted(theirs), 'speed-grade key set changed'
    for grade in theirs:
        assert sorted(ours[grade]) == sorted(theirs[grade]), \
            f'{device} {grade}: group set changed'
        for group in theirs[grade]:
            # `repr`, not `==`: the filler chunks past the real tables decode
            # to NaN on both sides, and NaN != NaN would fail a structural
            # comparison of two byte-identical parses. `repr` also pins the
            # value *types*, so the integer fanout counts cannot silently
            # become floats.
            assert repr(ours[grade][group]) == repr(theirs[grade][group]), \
                f'{device} {grade}.{group} changed'
    assert repr(ours) == repr(theirs)


@pytest.mark.parametrize('device', PRE_GW5_DEVICES)
def test_pre_gw5_grades_untouched_by_the_gw5a_derivation(device, device_file):
    """No `C1/I0` is synthesised, and no key vanishes, on a pre-GW5 device."""
    path = device_file(device, 'tm')
    if not os.path.isfile(path):
        pytest.skip(f'{device}.tm absent from the selected Gowin install')
    with open(path, 'rb') as fh:
        tm = tm_parser.read_tm(fh, device)
    # The GW5A synthesis is gated on the family, so a pre-GW5 device keeps
    # exactly the grades its own `chunk_order` names.
    assert 'unidentified_1' not in tm and 'unidentified_2' not in tm
    assert tm, f'{device}: no speed grades parsed at all'
