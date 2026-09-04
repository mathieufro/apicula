"""P0.T15b: `gw_sh` must be exec'd directly on macOS.

The historical invocation went through `/usr/bin/env` to set `LD_PRELOAD`.
`/usr/bin/env` is SIP-protected on macOS, so dyld strips `DYLD_LIBRARY_PATH`
and `DYLD_FRAMEWORK_PATH` across that exec and `gw_sh` dies with
`Library not loaded: @rpath/libGWTE.dylib` -- which is how every pre-5-series
chipdb build (GW1N/GW2A, the only ones that shell out to `gw_sh`) failed on
this box with `pnr_result=None`.
"""
import os

import pytest

from apycula import codegen


GOWINHOME = '/Applications/GowinIDE.app/Contents/Resources/Gowin_EDA'


def test_gw_sh_command_is_direct_on_macos(monkeypatch):
    monkeypatch.setattr(codegen.sys, 'platform', 'darwin')
    monkeypatch.setenv('DYLD_LIBRARY_PATH', GOWINHOME + '/IDE/lib')
    argv, env = codegen.gw_sh_command(GOWINHOME, '/tmp/run.tcl')
    assert argv == [GOWINHOME + '/IDE/bin/gw_sh', '/tmp/run.tcl'], argv
    assert '/usr/bin/env' not in argv
    assert 'LD_PRELOAD' not in env
    # the loader variables the caller exported survive into the child
    assert env['DYLD_LIBRARY_PATH'] == GOWINHOME + '/IDE/lib'


def test_gw_sh_command_keeps_ld_preload_on_linux(monkeypatch):
    monkeypatch.setattr(codegen.sys, 'platform', 'linux')
    argv, env = codegen.gw_sh_command(GOWINHOME, '/tmp/run.tcl')
    assert argv == [GOWINHOME + '/IDE/bin/gw_sh', '/tmp/run.tcl'], argv
    assert env['LD_PRELOAD'] == (
        GOWINHOME + '/Programmer/bin/libfontconfig.so.1')


@pytest.mark.skipif(not os.path.isdir(GOWINHOME),
                    reason='Standard Gowin install not present')
def test_gw_sh_binary_named_by_the_command_is_executable():
    argv, _env = codegen.gw_sh_command(GOWINHOME, '/tmp/run.tcl')
    assert os.access(argv[0], os.X_OK), argv[0]
