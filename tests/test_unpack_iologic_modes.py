"""`gowin_unpack` must be able to name every gearbox it can pack (`P3.T13/T14`).

Two IOLOGIC mode ids on the GW5AST-138C resolve to a value the mode table did
not carry, so a bitstream both flows wrote identically decoded to no cell at
all.  Both are measured against real vendor bitstreams, and each fix is
confined to the direction it was measured in.
"""
from apycula import attrids
from apycula import gowin_unpack


def test_video_gearbox_is_named_under_the_spelling_the_table_returns():
    """`VIDEOTX` and `VIDEORX` share value id 50, and the reverse table keeps
    `VIDEOTX`, so keying the mode table on `VIDEORX` alone left a video
    gearbox unnamed."""
    assert attrids.iologic_num2val[attrids.iologic_attrvals['VIDEOTX']] \
        == 'VIDEOTX'
    assert gowin_unpack._iologic_mode['VIDEOTX'] == 'OVIDEO'
    assert gowin_unpack._iologic_mode['VIDEORX'] == 'OVIDEO'


def test_ides8_input_mode_alias_is_input_only():
    """`IDES8` packs `INMODE=IDDRX4` and decodes back as the unnamed id 76.
    The alias names it on the input path and nowhere else -- the same id in
    `OUTMODE` is a different mode and must keep failing to resolve."""
    assert gowin_unpack._iologic_inmode_alias['UNK76'] == 'IDES8'
    assert 'UNK76' not in gowin_unpack._iologic_mode


def test_no_alias_shadows_a_named_mode():
    """An alias may only name an id the shipped table left unnamed."""
    for spelling in gowin_unpack._iologic_inmode_alias:
        assert spelling.startswith('UNK'), spelling
        assert spelling not in gowin_unpack._iologic_mode, spelling


def test_video_serialiser_is_named_from_the_id_the_packer_writes():
    """`gowin_pack` encodes an `OVIDEO` as `OUTMODE = LVDSOUT` (74) on the
    GW5A and the vendor writes the same fuses, so keying the mode table on
    `VIDEOTX` alone recovered no video serialiser from any bitstream."""
    assert attrids.iologic_attrvals['LVDSOUT'] == 74
    assert gowin_unpack._iologic_outmode_alias['LVDSOUT'] == 'OVIDEO'


def test_outmode_alias_does_not_reach_the_input_path():
    """The two directions share one attribute-value table, and an id means a
    different mode in each; an alias measured on one may not name the other."""
    assert 'LVDSOUT' not in gowin_unpack._iologic_inmode_alias
    assert 'UNK76' not in gowin_unpack._iologic_outmode_alias
