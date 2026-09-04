"""Shared pytest fixtures for the apicula test suite (P0.T14).

`tests/` does not exist upstream; created here so `spec.md` `V3`
(`pytest tests -k "fse_version"`) and `V7` (`pytest tests -k "timing_c1i0"`)
have something to run.

This module is append-only for later phases: Phases 1-6 add their own
`test_*.py` files under `tests/` and must not edit the fixtures below
(`blueprints/P0-foundation.md` File ownership).
"""
import os
import shutil

import pytest

from fuzz.gw5ast138c.harness import evidence


def _selected_path():
    # `gowinhome.selected` lives at `$OTC/evidence/_runs/gowinhome.selected`
    # (`C10`/`D80`); resolution goes through the harness's own
    # `evidence.evidence_root()` (`$OTC_EVIDENCE` or `$OTC/evidence`).
    try:
        root = evidence.evidence_root()
    except evidence.EvidenceSchemaError:
        return None
    path = os.path.join(root, '_runs', 'gowinhome.selected')
    return path if os.path.isfile(path) else None


@pytest.fixture
def gowinhome():
    """The oracle-of-record Gowin install (`gowinhome.selected`, F3/D52).

    `GOWINHOME` in the environment wins if set (matches the harness's own
    resolution order); otherwise the pipeline's recorded selection is read.
    Skips with a named reason, rather than failing, when neither is
    available.
    """
    env = os.environ.get('GOWINHOME')
    if env:
        return env
    path = _selected_path()
    if path is None:
        pytest.skip('no Gowin install selected: GOWINHOME is unset and '
                     'gowinhome.selected is absent')
    with open(path) as fh:
        home = fh.read().strip()
    if not home or not os.path.isdir(home):
        pytest.skip(f'gowinhome.selected names {home!r}, which is not a '
                     'directory')
    return home


@pytest.fixture
def device_file(gowinhome):
    """`device_file('GW5AST-138C', 'fse')` -> that device file's path (F4)."""
    def _path(device, ext):
        return f'{gowinhome}/IDE/share/device/{device}/{device}.{ext}'
    return _path


# The Education 1.9.11.03 install was removed from disk on 2026-09-04 (owner
# constraint C9 / D79: the licensed Standard 1.9.12.03 install is GOWINHOME for
# everything). Its `IDE/share/device/` tree was archived beforehand, as a bare
# `<device>/<device>.<ext>` tree with no surrounding IDE, so a 1.9.11-specific
# parser test points the parser at the archived file *directly* and forces the
# version with `GOWIN_IDE_VERSION` (no GOWINHOME-shaped symlink view is built:
# nothing under `IDE/` other than `share/device` was archived, and
# `detect_ide_version` already documents the env override as the mechanism for
# "odd layouts").
ARCHIVED_EDU_DEVICE_TREE = (
    '/Users/alex/fine-line-data/open-toolchain-gw5ast/'
    'ide-share-device/edu-1.9.11.03'
)
ARCHIVED_EDU_VERSION = '1.9.11.03'


@pytest.fixture
def archived_device_file():
    """`archived_device_file('GW5AST-138C', 'fse')` -> archived 1.9.11 path.

    Skips (never fails) when the archive is absent, matching `gowinhome`.
    """
    def _path(device, ext):
        path = os.path.join(ARCHIVED_EDU_DEVICE_TREE, device,
                            f'{device}.{ext}')
        if not os.path.isfile(path):
            pytest.skip(f'archived Education 1.9.11.03 {device}.{ext} absent '
                        f'({path})')
        return path
    return _path


@pytest.fixture
def mutated_header(tmp_path):
    """`mutated_header(path, offset, byte)` -> a one-byte-mutated copy.

    Copies `path` into `tmp_path` and overwrites the single byte at `offset`
    with `byte`, returning the copy's path. Used to synthesize a
    version-drifted header without touching the real installed file.
    """
    def _mutate(path, offset, byte):
        dest = tmp_path / os.path.basename(path)
        shutil.copyfile(path, dest)
        with open(dest, 'r+b') as fh:
            fh.seek(offset)
            fh.write(bytes([byte]))
        return dest
    return _mutate
