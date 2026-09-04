# apicula `tests/`

Created by `P0.T14` (`blueprints/P0-foundation.md`). This directory does not
exist upstream — `spec.md`'s `V3` and `V7` assume it, so it is created here
as an importable pytest package.

## Running

```sh
cd $FL/apicula && vendor/venv/bin/python -m pytest tests -q     # this suite only
cd $FL/apicula && vendor/venv/bin/python -m pytest -q           # whole repo, via testpaths=tests in pytest.ini
```

`pytest.ini` at the repo root sets `testpaths = tests`, so a bare `pytest` /
`python -m pytest` invocation from the repo root collects only `tests/` and
does not walk into `legacy/` (an unmaintained script, not a test suite —
`legacy/test_clk.py` raises at import time if `GOWINHOME`/`DEVICE` are unset).

## Fixtures (`conftest.py`)

- `gowinhome` — the selected Gowin install directory. Reads `GOWINHOME` from
  the environment first, then `$PIPE/evidence/_runs/gowinhome.selected`.
  Skips (does not fail) if neither is available.
- `device_file(device, ext)` — the path to an installed device file, e.g.
  `device_file('GW5AST-138C', 'fse')`.
- `mutated_header(path, offset, byte)` — a one-byte-mutated copy of `path`
  under `tmp_path`, for synthesizing version-drift without touching the real
  installed file.

## Convention

This directory is **append-only** for later phases: Phases 1-6 add their own
`test_*.py` files here and must not edit `conftest.py`'s existing fixtures
(`blueprints/P0-foundation.md` File ownership).
