import os
import sys
import struct

tc = 8 # number of timing classes
chunklen = 15552 # length of each class

def to_float(s):
    return struct.unpack('f', s)[0]

def float_data(data, paths):
    res = {}
    for i, name in enumerate(paths):
        for j in range(4):
            idx = i*4+j
            res.setdefault(name,[]).append(to_float(data[idx*4:idx*4+4]))
    return res

def to_int(s):
    return struct.unpack('I', s)[0]

def int_data(data, paths):
    res = {}
    for i, name in enumerate(paths):
        res[name] = to_int(data[i*4:i*4+4])
    return res

def parse_lut(data):
    paths = ['a_f', 'b_f', 'c_f', 'd_f', 'a_ofx', 'b_ofx', 'c_ofx', 'd_ofx', 'm0_ofx0', 'm1_ofx1', 'fx_ofx1']
    return float_data(data, paths)

def parse_alu(data):
    paths = ['a_f', 'b_f', 'd_f', 'a0_fco', 'b0_fco', 'd0_fco', 'fci_fco', 'fci_f0']
    return float_data(data, paths)

def parse_sram(data):
    paths = [
        'rad0_do', # 0 also unnumbered
        'rad1_do', # 4
        'rad2_do', # 8
        'rad3_do', # 0xc
        'clk_di_set', # 0x10
        'clk_di_hold', # 0x14
        'clk_wre_set', # 0x18
        'clk_wre_hold', # 0x1c
        'clk_wad0_set', # 0x20 also unnumbered
        'clk_wad0_hold', # 0x24 also unnumbered
        'clk_wad1_set', # 0x28
        'clk_wad1_hold', # 0x2c
        'clk_wad2_set', # 0x30
        'clk_wad2_hold', # 0x34
        'clk_wad3_set', # 0x38
        'clk_wad3_hold', # 0x3c
        'clk_do', # 0x40
    ]
    return float_data(data, paths)

def parse_dff(data):
    paths = [
        'di_clksetpos', # 0x0
        'di_clksetneg', # 0x4
        'di_clkholdpos', # 0x8
        'di_clkholdneg', # 0xc
        'ce_clksetpos', # 0x10
        'ce_clksteneg', # 0x14
        'ce_clkholdpos', # 0x18
        'ce_clkholdneg', # 0x1c
        'lsr_clksetpos_syn', # 0x20
        'lsr_clksetneg_syn', # 0x24
        'lsr_clkholdpos_syn', # 0x28
        'lsr_clkholdneg_syn', # 0x2c
        'clk_qpos', # 0x30
        'clk_qneg', # 0x34
        'lsr_q', # 0x38
        'lsr_clksetpos_asyn', # 0x3c
        'lsr_clksetneg_asyn', # 0x40
        'lsr_clkholdpos_asyn', # 0x44
        'lsr_clkholdneg_asyn', # 0x48
        'clk_clk', # 0x4c
        'lsr_lsr', # 0x50
    ]
    return float_data(data, paths)

def parse_dl(data):
    pass

def parse_iddroddr(data):
    pass

# ---------------------------------------------------------------------------
# PLL (`offsets[0x7cc]`), P1.T33
# ---------------------------------------------------------------------------
# The block between the `iddroddr` offset (`0x4a0`) and the `dll` offset
# (`0x81c`) ends in exactly 0x50 = 80 bytes = 5 groups of 4 floats -- the
# `float_data` shape of five named paths.  On `GW5AST-138C.tm` chunk 0 those
# twenty floats are
#
#     0.198  0.1935 0.208  0.2015
#     0.1785 0.1805 0.216  0.2275
#     0.1705 0.181  0.226  0.2215
#     0.169  0.1635 0.2025 0.206
#     0.183  0.1765 0.206  0.221
#
# and they are **byte-identical to `GW2A-18.tm` chunk 0** (as is 15,471 of that
# chunk's 15,552 bytes: only the `iodelay` and `fanout` blocks differ).  Five
# paths is the output count of the *rPLL* primitive GW1N/GW2A ship
# (CLKOUT / LOCK / CLKOUTP / CLKOUTD / CLKOUTD3, the set nextpnr still hard-codes
# at `gowin_arch_gen.py:1766`).  The Arora-V `PLL` this die actually has does not
# have those ports at all: UG306E Table 5-2 gives it CLKOUT0..CLKOUT6, CLKFBOUT
# and LOCK, and the vendor's own SDF for a 138C PLL design emits seven
# `(IOPATH CLKIN CLKOUTn ...)` arcs, every one of them `0.000:0.000:0.000`.
#
# So the block is inherited GW2A rPLL data carried into the GW5A preamble, it
# cannot be mapped onto this die's PLL ports, and the vendor models this die's
# PLL as zero internal delay.  Publishing the five floats under GW5A PLL names
# would invent a model the silicon vendor does not have; `parse_pll` therefore
# emits **no timing group at all**, deliberately and on the record.  The decoder
# is kept as `pll_block` so the claim stays inspectable from the shipped file.
#
# Evidence: `$OTC/evidence/timing-l0-cfu/pll-slice.md` (`P1.T33`, `V12a`),
# DS1239E Table 3-18 (no CLKIN->CLKOUT delay is published at all), `D60`.
_PLL_INHERITED_RPLL_PATHS = [
    'clkin_clkout',    # 0x00  rPLL CLKOUT
    'clkin_lock',      # 0x10  rPLL LOCK
    'clkin_clkoutp',   # 0x20  rPLL CLKOUTP
    'clkin_clkoutd',   # 0x30  rPLL CLKOUTD
    'clkin_clkoutd3',  # 0x40  rPLL CLKOUTD3
]

def pll_block(data):
    """Decode the 0x7cc block verbatim, under its inherited rPLL path names.

    Inspection/regression helper only -- `parse_pll` does not publish it, see
    the comment above.  The names are the GW1N/GW2A rPLL output order and are
    NOT a claim about this die's PLL.
    """
    return float_data(data, _PLL_INHERITED_RPLL_PATHS)

def parse_pll(data):
    """No PLL timing group: the .tm carries no PLL model for this die.

    Returns an empty mapping (falsy, so `read_tm` publishes nothing) rather
    than silently falling off the end of the function.  See above for why, and
    `$OTC/evidence/timing-l0-cfu/pll-slice.md` for the measurement.
    """
    return {}

def parse_dll(data):
    pass

def parse_bram(data):
    paths = [
        'clka_doa', # 0
        'clkb_dob', # 4
        'clkb_do', # 8
        'clk_do', # 0xc
        'clka_doa_bypass', # 0x10
        'clkb_dob_bypass', # 0x14
        'clkb_do_bypass', # 0x18
        'clk_do_bypass', # 0x1c
        'clka_reseta_set', # 0x20
        'clka_ocea_set', # 0x24
        'clka_cea_set', # 0x28
        'clka_wrea_set', # 0x2c
        'clka_dia_set', # 0x30
        'clka_di_set', # 0x34
        'clka_ada_set', # 0x38
        'clka_blksel_set', # 0x3c
        'clka_reseta_hold', # 0x40
        'clka_ocea_hold', # 0x44
        'clka_cea_hold', # 0x48
        'clka_wrea_hold', # 0x4c
        'clka_dia_hold', # 0x50
        'clka_di_hold', # 0x54
        'clka_ada_hold', # 0x58
        'clka_blksel_hold', # 0x50
        'clkb_resetb_set', # 0x60
        'clkb_oceb_set', # 0x64
        'clkb_ceb_set', # 0x68
        'clkb_oce_set', # 0x6c
        'clkb_wreb_set', # 0x70
        'clkb_dib_set', # 0x74
        'clkb_adb_set', # 0x78
        'clkb_blksel_set', # 0x7c
        'clkb_resetb_hold', # 0x80
        'clkb_oceb_hold', # 0x84
        'clkb_ceb_hold', # 0x88
        'clkb_oce_hold', # 0x8c
        'clkb_wreb_hold', # 0x90
        'clkb_dib_hold', # 0x94
        'clkb_adb_hold', # 0x98
        'clkb_blksel_hold', # 0x9c
        'clk_ce_set', # 0xa0
        'clk_oce_set', # 0xa4
        'clk_reset_set', # 0xa8
        'clk_wre_set', # 0xac
        'clk_ad_set', # 0xb0
        'clk_di_set', # 0xb4
        'clk_blksel_set', # 0xb8
        'clk_ce_hold', # 0xbc
        'clk_oce_hold', # 0xc0
        'clk_reset_hold', # 0xc4
        'clk_wre_hold', # 0xc8
        'clk_ad_hold', #0xcc
        'clk_di_hold', # 0xd0
        'clk_blksel_hold', # 0xd4
        'clk_reset_set_syn', # 0xd8
        'clk_reset_hold_syn', # 0xdc
        'clka_reseta_set_syn', # 0xe0
        'clka_reseta_hold_syn', # 0xe4
        'clkb_resetb_set_syn', # 0xe8
        'clkb_resetb_hold_syn', # 0xec
        'clk_clk', # 0xf0
    ]
    return float_data(data, paths)

def parse_dsp(data):
    pass

def parse_fanout(data):
    paths = [
        'X0Fan', # 0x00
        'X1Fan', # 0x04
        'SX1Fan', # 0x08
        'X2Fan', # 0x0C
        'X8Fan', # 0x10
        'FFan', # 0x14
        'QFan', # 0x18
        'OFFan', # 0x1c
    ]
    int_paths = [
        'X0FanNum',
        'X1FanNum',
        'SX1FanNum',
        'X2FanNum',
        'X8FanNum',
        'FFanNum',
        'QFanNum',
        'OFFanNum',
    ]
    return {**float_data(data, paths), **int_data(data[0x80:], int_paths)}

# P/S = primary/secondary clock?
# clock path:
# CIB/PIO -> CENT -> SPINE -> TAP -> BRANCH
# CIB in ECP5 = configurable interconnect block
# PIO in ECP5 = programmable IO
def parse_glbsrc(data):
    paths = [
        'CIB_CENT_PCLK', # 0x00
        'PIO_CENT_PCLK', # 0x04
        'CENT_SPINE_PCLK', # 0x08
        'SPINE_TAP_PCLK', # 0x0c
        'TAP_BRANCH_PCLK', # 0x10
        'BRANCH_PCLK', # 0x14
        'CIB_PIC_INSIDE', # 0x18
        'CIB_CENT_SCLK', # 0x1c
        'PIO_CENT_SCLK', # 0x20
        'CENT_SPINE_SCLK', # 0x24
        'SPINE_TAP_SCLK_0', # 0x28
        'SPINE_TAP_SCLK_1', # 0x2c (getter takes index)
        'TAP_BRANCH_SCLK', # 0x30
        'BRANCH_SCLK', # 0x34
        'GSRREC_SET', # 0x38
        'GSRREC_HLD', # 0x3c
        'GSR_MPW', # 0x40
    ]
    return float_data(data, paths)


# HclkPathDly = 0x8 + 0x0 + 0xc
def parse_hclk(data):
    paths = [
        'HclkInMux', # 0x0
        'HclkHbrgMux', # 0x4
        'HclkOutMux', # 0x8
        'HclkDivMux', # 0xc
    ]
    return float_data(data, paths)

def parse_iodelay(data):
    paths = ['GI_DO', 'SDTAP_DO', 'SETN_DO', 'VALUE_DO',
             'SDTAP_DF', 'SETN_DF', 'VALUE_DF']
    return float_data(data, paths)

def parse_io(data):
    pass

def parse_iregoreg(data):
    pass

def parse_wire(data):
    paths = [
        'X0', # 0x00
        'FX1', # 0x04
        'X2', # 0x08
        'X8', # 0x0C
        'ISB', # 0x10
        'X0CTL', # 0x14
        'X0CLK', # 0x18
        'X0ME', # 0x1C
    ]
    return float_data(data, paths)

offsets = {
    0x0: parse_lut,
    0xb0: parse_alu,
    0x130: parse_sram,
    0x240: parse_dff,
    0x390: parse_dl,
    0x4a0: parse_iddroddr,
    0x7cc: parse_pll,
    0x81c: parse_dll,
    0x8bc: parse_bram,
    0xc8c: parse_dsp,
    0x381c: parse_fanout,
    0x38bc: parse_glbsrc,
    0x39cc: parse_hclk,
    0x3728: parse_iodelay,
    0x3278: parse_io,
    0x306c: parse_iregoreg,
    0x379c: parse_wire,
}
dspoffsets = {
    0x0: 'mult', #DSP
    0x410: 'mac', #DSP
    0x6b0: 'multadd', #DSP
    0xaf0: 'multaddsum', #DSP
    0x1300: 'padd', #DSP
    0x1560: 'alu45', #DSP
}
def parse_chunk(chunk):
    for off, parser in offsets.items():
        if off < len(chunk):
            yield parser.__name__[6:], parser(chunk[off:])

# Per-family speed-grade aliases: a chunk that is published under more than one
# grade name.  GW1N/GW2A have no entries; the GW5A entry
# {"ES": ["C1/I0", "A0"]} was removed -- see `_gw5a_chunk_order` and
# `C1_I0_FROM_C2_I1` below, and `doc/timing-c1i0.md`.
_aliases = {}

# GW5A-family chunk labels.  Chunk 0's numbers match the **C2/I1** column of
# DS1239E Table 3-13 to three decimals (CFU tSR 1.075-1.148, tCO 0.200-0.230),
# so chunk 0 is the C2/I1 source of record even though the vendor tooling's
# ordering was previously guessed to be "ES" first.  Chunks 1 and 2 carry
# plausible but unidentified tables (chunk 1 shares chunk 0's DFF numbers but
# not its LUT numbers; chunk 2 is a uniform 0.862x scaling of chunk 0) and are
# therefore published under non-grade keys so `set_speed_grade` can never
# select them.  Chunk 3 onward is not in chunk format at all (the values decode
# as garbage floats), which is what the `i >= 3` break below stops at.
_gw5a_chunk_order = [
    "C2/I1",          # chunk 0: matches DS1239E Table 3-13 C2/I1 to three
                      # decimals.  C1/I0 is derived from it after the loop.
    "unidentified_1", # chunk 1: content not identified.
    "unidentified_2", # chunk 2: idem.
    "3", "4", "5", "6", "7", "8", "9", "10", "11",
]

# DS1239E Table 3-13 (CFU) and Table 3-14 (BSRAM) give C1/I0 = 1.25 x C2/I1 on
# every published row of our own device's datasheet.  The .tm file carries no
# C1/I0 chunk, so the C1/I0 table is derived from the C2/I1 chunk by this
# ratio.  See `doc/timing-c1i0.md`.
C1_I0_FROM_C2_I1 = 1.25

def _scale(tm, factor):
    """Multiply every delay in one parsed group table by `factor`.

    Only floats are delays.  `parse_fanout` also emits integer fanout *counts*
    (`X0FanNum` and friends), which are topology, not timing, and are carried
    through unscaled.
    """
    if isinstance(tm, dict):
        return {k: _scale(v, factor) for k, v in tm.items()}
    if isinstance(tm, list):
        return [_scale(v, factor) for v in tm]
    if isinstance(tm, float):
        return tm * factor
    return tm

def read_tm(f, device):
    if device.lower().startswith("gw1n"):
        chunk_order = [
            "C5/I4",
            "C5/I4_LV",
            "C6/I5",
            "C6/I5_LV",
            "ES",
            "ES_LV",
            "A4",
            "A4_LV",
            "8",
            "9",
            "10",
            "11",
            "C7/I6",
            "C7/I6_LV"
        ]
    elif device.lower().startswith("gw2a"):
        chunk_order = [
            "C8/I7",
            "C8/I7_LV",
            "C7/I6",
            "C7/I6_LV",
            "A6",
            "A6_LV",
            "C9/I8",
            "C9/I8_LV",
        ]
    elif device.lower().startswith("gw5a"):
        chunk_order = _gw5a_chunk_order
    else:
        raise Exception("unknown family")

    tmdat = {}
    #a = enumerate(iter(lambda: f.read(chunklen), b''))
    for i, chunk in enumerate(iter(lambda: f.read(chunklen), b'')):
        try:
            speed_class = chunk_order[i]
        except IndexError:
            speed_class = str(i)
        # XXX no gw5 for now
        if len(chunk) != chunklen:
            continue
        # XXX GW5A-25A check it
        if i >= 3 and device in {'GW5A-25A', 'GW5AT-60B', 'GW5AST-138C'}:
            break
        tmdat[speed_class] = {}
        #print(f'{i:2} class:{speed_class}' , "len(chunk):", len(chunk), "chunklen:", chunklen)
        #assert len(chunk) == chunklen # 5A the last chunk is smaller 12922 vs. 15552
        res = parse_chunk(chunk)
        for name, tm in res:
            if tm:
                tmdat[speed_class][name] = tm
                for series, aliases in _aliases.items():
                    if device.lower().startswith(series) and speed_class in aliases:
                        for al in aliases[speed_class]:
                            tmdat.setdefault(al, {})[name] = tm
    if "C2/I1" in tmdat and device.lower().startswith("gw5a"):
        # C1/I0 has no chunk of its own; derive it from the C2/I1 chunk.
        tmdat["C1/I0"] = {name: _scale(tm, C1_I0_FROM_C2_I1)
                          for name, tm in tmdat["C2/I1"].items()}
    return tmdat


if __name__ == "__main__":
    gowinhome = os.getenv("GOWINHOME")
    if not gowinhome:
        raise Exception("GOWINHOME not set")
    device = sys.argv[1]

    with open(f"{gowinhome}/IDE/share/device/{device}/{device}.tm", 'rb') as f:
        read_tm(f, device)
