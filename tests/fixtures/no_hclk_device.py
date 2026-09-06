"""Synthetic no-HCLK device stub for the D39 state-(1) IOLOGIC-refusal test.

This is deliberately **not** the live `GW5AST-138C.msgpack.xz` chipdb: it is a
minimal `Device` whose `chip_flags` omit `HAS_5A_HCLK`, so that
`test_iologic_before_hclk_unsupported_error_138c` keeps testing "IOLOGIC
without HCLK" even after Phase 3 lands the HCLK row and deletes the
`fse_iologic` guard this fixture stands in for (`brainstorm-decisions.md`
D39, roadmap F16).
"""

from apycula.chipdb import Bel, Device, Tile

# Any ttyp not excluded by fse_iologic's early returns (48-51, 86/87, etc.);
# 100 is an arbitrary IOLOGIC-capable tile type for this synthetic stub.
_IOLOGIC_TTYP = 100


def make_no_hclk_stub() -> Device:
    """Return a minimal Device with one IOLOGIC-capable tile and no
    HAS_5A_HCLK chip flag."""
    dev = Device()
    dev.chip_flags = [
        'HAS_PINCFG', 'HAS_DFF67', 'HAS_CIN_MUX',
        'NEED_BSRAM_RESET_FIX', 'NEED_CFGPINS_INVERSION', 'HAS_5A_DSP',
    ]
    tile = Tile(width=1, height=1, ttyp=_IOLOGIC_TTYP)
    tile.bels['IOLOGICA'] = Bel()
    tile.bels['IOLOGICB'] = Bel()
    dev.grid = [[_IOLOGIC_TTYP]]
    dev.tiles[_IOLOGIC_TTYP] = tile
    return dev
