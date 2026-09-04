import sys
import os
from pathlib import Path
from dataclasses import dataclass

from apycula.fse_parser import FseVersionError, detect_ide_version


class DatLayoutError(ValueError):
    """A `.dat` header did not match the selected layout descriptor.

    Raised instead of letting a misread `partType` silently skip
    `read_5Astuff()` (which surfaced far away as
    ``AttributeError: 'Datfile' object has no attribute 'gw5aStuff'``), so the
    message names the detected IDE version, the layout set in use, the offset
    read and what was found there.
    """


# Every absolute offset below 0x7b4a4 is identical in every shipped `.dat`
# (the asserts in read_primitives/read_portmap/read_io would fire otherwise).
# 0x7b4a4 is where the per-IDE-version drift starts, so it is the one anchor.
DAT_HEADER_ANCHOR = 0x07b4a4

# Per-IDE-version `.dat` header descriptors (same discipline as
# `fse_parser.TABLE_SHAPES`): keyed by a *layout-set name*, never by a version
# string, so a release that keeps the layout reuses an existing set.
#
# `v1_9_11minus` is the historical upstream layout: the anchor holds
#     [partType u16][pad u16][<5-series table block> ...]
#
# `v1_9_12plus` is Gowin IDE 1.9.12.03. The anchor gained a three-u16 field in
# front of `partType` and lost the pad word behind it:
#     [new u16 x3][partType u16][<5-series table block> ...]
# so `partType` sits 6 bytes later while the table block starts only 4 bytes
# later -- which is exactly the +4 total size delta measured on every `.dat`
# shipped in both editions. Reading `partType` at the old anchor yields 0xffff
# on GW5A* (no `gw5aStuff`) and, worse, a *plausible* wrong value on some
# GW1N* parts, so the offset must be selected, not guessed.
DAT_HEADER_SHAPES: dict[str, dict[str, int]] = {
    "v1_9_11minus": {"pre_words": 0, "rs_table_delta": 4},
    "v1_9_12plus": {"pre_words": 3, "rs_table_delta": 2},
}

DEFAULT_DAT_SHAPE_SET = "v1_9_11minus"

# The `partType` values the parser dispatches on. A file whose selected offset
# holds anything else is positively contradicting the layout.
KNOWN_PART_TYPES = frozenset({0, 1, 2, 4, 10})

# Offset of the TopHiq/TopViq/BotHiq/BotViq quad inside the 5-series table
# block; used to confirm the block start against the grid the same file
# already yielded.
RS_TABLE_IQ_OFFSET = 0x24be0


def _version_tuple(ide_version: str) -> tuple[int, ...]:
    parts = []
    for field in (ide_version or "").split("."):
        if not field.isdigit():
            break
        parts.append(int(field))
    return tuple(parts)


def select_dat_header(ide_version: str) -> tuple[str, dict[str, int]]:
    """Map a detected IDE version onto (layout set name, header descriptor)."""
    if _version_tuple(ide_version)[:3] >= (1, 9, 12):
        name = "v1_9_12plus"
    else:
        name = DEFAULT_DAT_SHAPE_SET
    return name, DAT_HEADER_SHAPES[name]


def _active_dat_header() -> tuple[str, str, dict[str, int]]:
    """(ide_version, layout set name, descriptor) for the current environment.

    Version detection is best-effort exactly as in `fse_parser._active_shapes`:
    a missing or unreadable install degrades to the historical layout and
    reports ``unknown`` in any diagnostic.
    """
    try:
        ide_version = detect_ide_version(os.environ.get("GOWINHOME", ""))
    except FseVersionError:
        ide_version = "unknown"
    name, shape = select_dat_header(ide_version)
    return ide_version, name, shape


def part_type_offset(shape: dict[str, int]) -> int:
    return DAT_HEADER_ANCHOR + 2 * shape["pre_words"]


def read_part_type_at(data: bytes, offset: int) -> int:
    """`partType` as the historical code read it.

    Short `.dat` files (the 505 000-byte GW1N/GW2A ones) stop well before the
    anchor; `int.from_bytes(b"")` is 0, i.e. partType 0, and that is the
    behaviour every pre-GW5 device has always relied on.
    """
    return int.from_bytes(data[offset:offset + 2], "little")


# `partType` values the parser dispatches on. Only 2 and 10 select the
# 5-series path, i.e. only they cost `gw5aStuff` if the offset is wrong.
KNOWN_PART_TYPES = frozenset({0, 1, 2, 4, 10})
FIVE_SERIES_PART_TYPES = frozenset({2, 10})


def part_types_by_layout(data: bytes) -> dict[str, int]:
    """The `partType` each known layout set would read out of this file."""
    return {
        name: read_part_type_at(data, part_type_offset(shape))
        for name, shape in DAT_HEADER_SHAPES.items()
    }


@dataclass
class Primitive:
    name: str
    num: int
    num_ins: int
    inputs: list[int]
    input_src: list[list[int]]


@dataclass
class Grid:
    num_rows: int
    num_cols: int
    center_x: int
    center_y: int
    rows: list[list[str]]


class Datfile:
    def __init__(self, path: Path):
        self.data = path.read_bytes()

        (self.ide_version, self.dat_shape_set,
         self._dat_header) = _active_dat_header()
        self._part_type_offset = part_type_offset(self._dat_header)
        self._rs_table_offset = self._part_type_offset + self._dat_header["rs_table_delta"]
        self._confirm_dat_header(path)

        self._cur = self._part_type_offset
        partType = self.read_u16()
        self.part_type = partType

        self.grid = self.read_grid()
        self.primitives = self.read_primitives()
        self.compat_dict = {}
        self.portmap = self.read_portmap()
        self.compat_dict = self.read_portmap()

        if partType == 0:       # 1/2 Series
            self.compat_dict.update(self.read_something())
        elif partType == 1:     # GW1N-2 / GW1N-1P5 family (FNIRSI 2C53T die)
            # Same base .dat layout as partType 0 (all sections are at fixed absolute
            # offsets below 0x7b4a8, guarded by asserts that would fire on misalign).
            # partType 1 only *appends* a ~33 KB extended table at 0x7b4a8 (0x7b4a4
            # for these files is 538638 B vs 505000 B for partType 0) which we do not
            # parse yet — base grid/IO/logic parse identically. See docs/02.
            self.compat_dict.update(self.read_something())
        elif partType == 2 or partType == 10:  # 5 Series
            self._confirm_rs_table(path)
            self.gw5aStuff = self.read_5Astuff()
            self.compat_dict.update(self.read_something())
            self.compat_dict.update(self.read_something5A())
        elif partType == 4:
            raise Exception(f"PartType {partType} is not supported")


        self.compat_dict.update(self.read_io())
        self.cmux_ins: dict[int, list[int]] = self.read_io()['CmuxIns']


    def _confirm_dat_header(self, path):
        """Fail loudly when the selected layout would silently drop 5A data.

        The offset is chosen by IDE version, not guessed, so this is a
        confirmation and not a search. It stays deliberately narrow: upstream
        tolerated a `partType` it has no branch for (GW1NS-4C declares 0x20)
        and that tolerance is preserved. What is *not* tolerated is the T13
        failure -- the selected offset yielding a value the parser cannot
        dispatch on while another known layout reads a 5-series type there,
        because that silently skips `read_5Astuff()` and only surfaces much
        later as ``AttributeError: ... has no attribute 'gw5aStuff'``.
        """
        by_layout = part_types_by_layout(self.data)
        found = by_layout[self.dat_shape_set]
        if found in KNOWN_PART_TYPES:
            return
        five_series = sorted(
            name for name, pt in by_layout.items()
            if name != self.dat_shape_set and pt in FIVE_SERIES_PART_TYPES)
        if not five_series:
            return
        raise DatLayoutError(
            f"{path}: .dat header layout drift. Detected Gowin IDE version "
            f"{self.ide_version!r} selects layout set {self.dat_shape_set!r}, "
            f"whose partType offset 0x{self._part_type_offset:x} holds "
            f"0x{found:x}, which is not a known partType "
            f"({sorted(KNOWN_PART_TYPES)}), while layout set(s) "
            f"{five_series} read a 5-series partType there "
            f"({ {n: by_layout[n] for n in five_series} }). Parsing on the "
            f"selected layout would drop gw5aStuff. partType by layout: "
            f"{by_layout}; file size 0x{len(self.data):x}.")

    def _confirm_rs_table(self, path):
        """Confirm the 5-series table block start against this file's grid.

        The block opens (at +0x24be0) with the TopHiq/TopViq/BotHiq/BotViq
        quad: a row index, a column index, a row index, a column index into
        the grid `read_grid()` just produced from offsets *below* the drifting
        anchor. A block start that is off by even one word puts unrelated
        table data there, so a quad outside the grid is positive evidence
        against the offset rather than a silent misparse 100 kB later.
        """
        base = self._rs_table_offset + RS_TABLE_IQ_OFFSET
        if base + 8 > len(self.data):
            raise DatLayoutError(
                f"{path}: .dat 5-series table block would start at "
                f"0x{self._rs_table_offset:x} (layout set "
                f"{self.dat_shape_set!r}, IDE version {self.ide_version!r}) "
                f"but the file ends at 0x{len(self.data):x}.")
        quad = [int.from_bytes(self.data[base + 2 * i: base + 2 * i + 2],
                               "little") for i in range(4)]
        top_hiq, top_viq, bot_hiq, bot_viq = quad
        rows, cols = self.grid.num_rows, self.grid.num_cols
        if not (top_hiq < rows and bot_hiq < rows
                and top_viq < cols and bot_viq < cols):
            raise DatLayoutError(
                f"{path}: .dat 5-series table block start 0x"
                f"{self._rs_table_offset:x} is contradicted by the file's own "
                f"grid. Layout set {self.dat_shape_set!r} (IDE version "
                f"{self.ide_version!r}) puts TopHiq/TopViq/BotHiq/BotViq = "
                f"{quad} at 0x{base:x}, but the grid is {rows} rows x {cols} "
                f"cols, so hiq must be < {rows} and viq < {cols}.")

    def read_u8(self):
        v = self.data[self._cur]
        self._cur += 1
        return v

    def read_i16(self):
        v = int.from_bytes(self.data[self._cur : self._cur + 2], "little", signed=True)
        self._cur += 2
        return v

    def read_u16(self):
        v = int.from_bytes(self.data[self._cur : self._cur + 2], "little")
        self._cur += 2
        return v

    def read_u8_at(self, pos):
        return self.data[pos]

    def read_u32_at(self, pos):
        return int.from_bytes(self.data[pos : pos + 4], "little")

    def read_i32(self):
        v = int.from_bytes(self.data[self._cur : self._cur + 4], "little", signed=True)
        self._cur += 4
        return v

    def read_u32(self):
        v = int.from_bytes(self.data[self._cur : self._cur + 4], "little")
        self._cur += 4
        return v

    def read_u64(self):
        v = int.from_bytes(self.data[self._cur : self._cur + 8], "little")
        self._cur += 8
        return v

    def read_arr8(self, num: int) -> list[int]:
        arr = [self.read_u8() for _ in range(num)]
        return arr

    def read_arr16(self, num: int) -> list[int]:
        arr = [self.read_i16() for _ in range(num)]
        return arr

    def read_arr16_at(self, num:int, base:int, offset:int):
        ret = []

        for n in range(num):
            self._cur = (n + base) * 2 + offset
            ret.append(self.read_i16())
        return ret

    def read_arr32_at(self, num:int, base:int, offset:int):
        ret = []

        for n in range(num):
            self._cur = (n + base) * 4 + offset
            ret.append(self.read_i32())
        return ret


    def read_arr32(self, num: int) -> list[int]:
        arr = [self.read_i32() for _ in range(num)]
        return arr

    def read_arr8_with_padding(self, num: int, of_which_meaningful: int) -> list[int]:
        arr = self.read_arr8(num)
        for i in range(of_which_meaningful, num):
            assert arr[i] == 0
        return arr[:of_which_meaningful]

    def read_arr16_with_padding(self, num: int, of_which_meaningful: int) -> list[int]:
        arr = self.read_arr16(num)
        for i in range(of_which_meaningful, num):
            assert arr[i] == -1
        return arr[:of_which_meaningful]

    def read_arr32_with_padding(self, num: int, of_which_meaningful: int) -> list[int]:
        arr = self.read_arr32(num)
        for i in range(of_which_meaningful, num):
            assert arr[i] == 0
        return arr[:of_which_meaningful]

    def read_primitive(self, name: str) -> Primitive:
        num = self.read_u8()
        num_ins = self.read_u8()
        ins = []
        for _ in range(num):
            ins.append(self.read_arr16(num_ins))
        obj = self.read_arr16(num)
        return Primitive(name, num, num_ins, obj, ins)

    def read_primitives(self) -> list[Primitive]:
        self._cur = 0xC8
        ret = []
        primitives = [
            "Lut",
            "X0",
            "X1",
            "X2",
            "X8",
            "Clk",
            "Lsrs",
            "Ce",
            "Sel",
            "X11",
        ]
        for p in primitives:
            ret.append(self.read_primitive(p))

        assert self._cur == 0x166E, f"Expected to be at 0x166e but am at 0x{self._cur:x}"
        return ret

    def read_grid(self) -> Grid:
        self._cur = 0x026060
        grid_h = self.read_u16() # chipRows_
        grid_w = self.read_u16() # chipCols_
        cc_y = self.read_u16() # hiq_
        cc_x = self.read_u16() # viq_
        # 26068
        rows = []
        grid_mapping = {
            (0, 0): " ",  # empty
            (0, 1): "u",  # unknown
            (1, 0): "1",  # unknown
            (1, 1): "I",  # I/O
            (2, 1): "L",  # LVDS (GW2A* only)
            (3, 1): "R",  # routing?
            (4, 0): "c",  # CFU, disabled
            (4, 1): "C",  # CFU
            (5, 1): "M",  # CFU with RAM option
            (6, 0): "b",  # blockram padding
            (6, 1): "B",  # blockram
            (7, 0): "d",  # dsp padding
            (7, 1): "D",  # dsp
            (8, 0): "p",  # pll padding
            (8, 1): "P",  # pll
            (9, 1): "Q",  # dll
            (10, 0): "2", # unknown
            (10, 1): "3", # unknown
            (11, 1): "4", # unknown
            (12, 1): "5"  # unknown
        }
        for y in range(grid_h):
            row = []
            for x in range(grid_w):
                idx = y * 200 + x
                a = self.read_u32_at(5744 + 4 * idx)
                b = self.read_u8_at(125744 + idx)
                if (a,b) not in grid_mapping.keys():
                    print(f"no grid_mapping key for coords {y, x}: ", a, b)
                c = grid_mapping[a, b]

                #if x == cc_x and y == cc_y:
                #    assert c == "b"

                row.append(c)
            rows.append(row)
        return Grid(grid_h, grid_w, cc_x, cc_y, rows)

    def patch_grid_bram_138(self):
        for y in range(self.grid.num_rows):
            for x in range(self.grid.num_cols):
                if self.grid.rows[y][x] == '3':
                    patch_str = "BbbBbb"
                    for j in range(len(patch_str)):
                        self.grid.rows[y][x+j] = patch_str[j]

    def read_mult(self, num) -> list[tuple[int, int, int, int]]:
        ret = []
        for _ in range(num):
            a = self.read_i16()
            b = self.read_i16()
            c = self.read_i16()
            d = self.read_i16()
            ret.append((a, b, c, d))
        return ret

    def read_outs(self, num) -> list[tuple[int, int]]:
        ret = []
        for _ in range(num):
            a = self.read_i16()
            b = self.read_i16()
            c = self.read_i16()
            ret.append((a, b, c))
        return ret

    def read_clkins(self, num) -> list[tuple[int, int]]:
        ret = []
        for _ in range(num):
            a = self.read_i16()
            b = self.read_i16()
            ret.append((a, b))
        return ret

    def read_scaledGrid16(self, numRows, numCols, rowScaling, colScaling, baseOffset):
        ret = []

        for row in range(numRows):
            rowArr = []
            for col in range(numCols):
                self._cur = (row * rowScaling) + (col * colScaling * 2) + baseOffset
                rowArr.append(self.read_u16())
            ret.append(rowArr)
        return ret

    # `CibFabricNode` -- the six (row, col, wire) triples that give the PINCFG
    # bel its `UNK*_VCC` / `SSPI` input wires (`chipdb.fse_create_pincfg`).
    # Its delta from the 5-series table anchor drifted between IDE releases:
    # `0x27254` is the historical upstream value (Gowin IDE 1.9.10.03, the
    # release upstream apycula pins), and every 1.9.11.03 / 1.9.12.03 `.dat`
    # measured on this box holds the table 0xb8 further on, at `0x2730c`.
    # Reading the stale delta returns an all-0xffff grid, which is *silently*
    # legal (0xffff is the "port absent" marker), so `fse_create_pincfg` emits
    # an empty `ins` map, apicula still sets `HAS_PINCFG`, and
    # `nextpnr-himbaechel` fails at routing with
    # `No wire found for port UNK0_VCC on destination cell PINCFG`.
    # The candidates are therefore tried in order and the first *populated*
    # one wins -- data-driven, so a 1.9.10 file still reads at its own offset
    # and a future relocation is one list entry.
    CIB_FABRIC_NODE_DELTAS = (0x27254, 0x2730c)

    def read_cib_fabric_node(self, rs_table_offset: int):
        last = None
        for delta in self.CIB_FABRIC_NODE_DELTAS:
            grid = self.read_scaledGrid16(6, 3, 6, 1, rs_table_offset + delta)
            last = grid
            populated = [row for row in grid if row != [0xffff] * 3]
            if not populated:
                continue
            # A populated candidate must be internally consistent: every entry
            # of a used row is a real (row, col, wire) index, never a mix of
            # 0xffff and data, and never an implausibly large index.
            if all(all(v < 0x8000 for v in row) for row in populated):
                return grid
        return last

    def read_scaledGrid16i(self, numRows, numCols, rowScaling, colScaling, baseOffset):
        ret = []

        for row in range(numRows):
            rowArr = []
            for col in range(numCols):
                self._cur = (row * rowScaling) + (col * colScaling * 2) + baseOffset
                rowArr.append(self.read_i16())
            ret.append(rowArr)
        return ret

    def read_5Astuff(self) -> dict:
        RSTable5ATOffset = self._rs_table_offset
        ret = { }

        #These are set (not read from file), but can't find reference
        #ret["UNKNOWN"] = 0x1d
        #ret["UNKNOWN"] = 0x1d
        #ret["UNKNOWN"] = 0x16
        #ret["UNKNOWN"] = 0x16
        #ret["UNKNOWN"] = 0xe

        self._cur = RSTable5ATOffset + 0x24be0
        ret["TopHiq"] = self.read_u16()
        ret["TopViq"] = self.read_u16()
        ret["BotHiq"] = self.read_u16()
        ret["BotViq"] = self.read_u16()

        ret["PllIn"]                = self.read_arr16_at(0xd8, 0, RSTable5ATOffset + 0x1b58)
        ret["PllOut"]               = self.read_arr16_at(0x20, 0, RSTable5ATOffset + 0x1d08)
        ret["PllInDlt"]             = self.read_arr16_at(0xd8, 0, RSTable5ATOffset + 0x1d48)
        ret["PllOutDlt"]            = self.read_arr16_at(0x20, 0, RSTable5ATOffset + 0x1ef8)

        ret["5ATIOLogicAIn"]        = self.read_arr16_at(0x3e, RSTable5ATOffset + 0x1880, 0)
        ret["5ATIOLogicBIn"]        = self.read_arr16_at(0x3e, RSTable5ATOffset + 0x18b8, 0xc)
        ret["5ATIOLogicAOut"]       = self.read_arr16_at(0x27, RSTable5ATOffset + 0x18f8, 8)
        ret["5ATIOLogicBOut"]       = self.read_arr16_at(0x27, RSTable5ATOffset + 0x1920, 6)
        ret["5ATIODelayAOut"]       = self.read_arr16_at(0x27, RSTable5ATOffset + 0x19c0, 0xc)
        ret["5ATIODelayBOut"]       = self.read_arr16_at(0x27, RSTable5ATOffset + 0x19e8, 10)
        ret["5ATIODelayAIn"]        = self.read_arr16_at(0x3e, RSTable5ATOffset + 0x1948, 0x4)
        ret["5ATIODelayBIn"]        = self.read_arr16_at(0x3e, RSTable5ATOffset + 0x1988, 0)

        # The following address offsets are also mentioned
        # All 5 are mentioned in FanIns, but only the 3rd and 4th are mentioned in FanOuts
        #ret["UNKNOWN"]             = self.read_scaledGrid16(0x20, 0x1d, 0x1d, RSTable5ATOffset + 0x3428, 0)
        #ret["UNKNOWN"]             = self.read_scaledGrid16(0xc, 0x16, 0x16, RSTable5ATOffset + 0x3b68, 0)
        #ret["UNKNOWN"]             = self.read_scaledGrid16(0xc, 0x16, 0x16, RSTable5ATOffset + 0x1e98, 8)
        #ret["UNKNOWN"]             = self.read_scaledGrid16(0x20, 0x16, 0x16, RSTable5ATOffset + 0x1fa0, 8)
        #ret["UNKNOWN"]             = self.read_scaledGrid16(0x8, 0xe, 0xe, RSTable5ATOffset + 0x2260, 8)

        ret["PllLTIns"]             = self.read_scaledGrid16(216, 3, 6, 1, RSTable5ATOffset + 0x1f38)
        ret["PllLTOuts"]            = self.read_scaledGrid16( 32, 3, 6, 1, RSTable5ATOffset + 0x2448)
        ret["PllLBIns"]             = self.read_scaledGrid16(216, 3, 6, 1, RSTable5ATOffset + 0x2508)
        ret["PllLBOuts"]            = self.read_scaledGrid16( 32, 3, 6, 1, RSTable5ATOffset + 0x2a18)
        ret["PllRTIns"]             = self.read_scaledGrid16(216, 3, 6, 1, RSTable5ATOffset + 0x2ad8)
        ret["PllRTOuts"]            = self.read_scaledGrid16( 32, 3, 6, 1, RSTable5ATOffset + 0x2fe8)
        ret["PllRBIns"]             = self.read_scaledGrid16(216, 3, 6, 1, RSTable5ATOffset + 0x30a8)
        ret["PllRBOuts"]            = self.read_scaledGrid16( 32, 3, 6, 1, RSTable5ATOffset + 0x35b8)

        """
        ret["MipiIns1"]             = self.read_scaledGrid16(0xc3, 3, 3, RSTable5ATOffset + 0x22d0, 0xe)
        ret["MipiIns2"]             = self.read_scaledGrid16(0xc3, 3, 3, RSTable5ATOffset + 0x2680, 0xe)
        ret["MipiOuts1"]            = self.read_scaledGrid16(0x76, 3, 3, RSTable5ATOffset + 0x2520, 0)
        ret["MipiOuts2"]            = self.read_scaledGrid16(0x76, 3, 3, RSTable5ATOffset + 0x28c8, 6)

        ret["MipiDPhyIns"]          = self.read_scaledGrid16(0xbb, 3, 3, RSTable5ATOffset + 0x91c0, 10)
        ret["MipiDPhyOuts"]         = self.read_scaledGrid16(0x6a, 3, 3, RSTable5ATOffset + 0x93f0, 0xc)

        ret["Gtrl12QuadDBIns1"]     = self.read_scaledGrid16(0x351, 3, 3, RSTable5ATOffset + 0x2a28, 10)
        ret["Gtrl12QuadDBIns2"]     = self.read_scaledGrid16(0x351, 3, 3, RSTable5ATOffset + 0x3420, 0)
        ret["Gtrl12QuadDBOuts1"]    = self.read_scaledGrid16(0x29c, 3, 3, RSTable5ATOffset + 0x6180, 0xc)
        ret["Gtrl12QuadDBOuts2"]    = self.read_scaledGrid16(0x29c, 3, 3, RSTable5ATOffset + 0x6958, 4)

        ret["Gtrl12PmacDBIns"]      = self.read_scaledGrid16(0xb68, 3, 3, RSTable5ATOffset + 0x3e10, 6)
        ret["Gtrl12PmacDBOuts"]     = self.read_scaledGrid16(0xb68, 3, 3, RSTable5ATOffset + 0x7128, 0xc)

        ret["Gtrl12UparDBIns"]      = self.read_scaledGrid16(0x69, 3, 3, RSTable5ATOffset + 0x6048, 6)
        ret["Gtrl12UparDBOuts"]     = self.read_scaledGrid16(0x69, 3, 3, RSTable5ATOffset + 0x8620, 10)
        """

        ret["Ae350SocIns"]          = self.read_scaledGrid16(0x1b1, 3, 3, RSTable5ATOffset + 0x86a0, 6)
        ret["Ae350SocOuts"]         = self.read_scaledGrid16(0x206, 3, 3, RSTable5ATOffset + 0x8bb0, 10)


        ret["CMuxTopInNodes"]       = self.read_scaledGrid16(0xbd, 0x54, 0x54 * 2, 1, RSTable5ATOffset + 0x14af4)
        ret["CMuxBotInNodes"]       = self.read_scaledGrid16(0xbd, 0x54, 0x54 * 2, 1, RSTable5ATOffset + 0x1c6fc)
        ret["CMuxTopIns"]           = self.read_scaledGrid16i(0xbd, 3, 6, 1, RSTable5ATOffset + 0x24304)
        ret["CMuxBotIns"]           = self.read_scaledGrid16i(0xbd, 3, 6, 1, RSTable5ATOffset + 0x24772)

        ret["MipiIO1"]              = self.read_scaledGrid16(10, 0xf, 0xf, RSTable5ATOffset + 0x240e0, 0)
        ret["MipiIO2"]              = self.read_scaledGrid16(10, 0xf, 0xf, RSTable5ATOffset + 0x24176, 0)
        for n in range(5):
            ret["MipiIOName1_{n}"]  = self.read_scaledGrid16(10, 0xf, 0x4b, 5, RSTable5ATOffset + 0x2420c + n)
            ret["MipiIOName2_{n}"]  = self.read_scaledGrid16(10, 0xf, 0x4b, 5, RSTable5ATOffset + 0x244fa + n)
        ret["MipiBank1"]            = self.read_arr16_at(10, RSTable5ATOffset + 0x240e0, 0)
        ret["MipiBank2"]            = self.read_arr16_at(10, RSTable5ATOffset + 0x24176, 0)

        ret["QuadIO1"]              = self.read_scaledGrid16(15, 0xf, 0xf, RSTable5ATOffset + 0x2483c, 0)
        ret["QuafIO2"]              = self.read_scaledGrid16(15, 0xf, 0xf, RSTable5ATOffset + 0x24977, 0)
        for n in range(5):
            ret["QuadIOName1_{n}"]  = self.read_scaledGrid16(15, 0xf, 0x4b, 5, RSTable5ATOffset + 0x2483c + n)
            ret["QuafIOName2_{n}"]  = self.read_scaledGrid16(15, 0xf, 0xf, 5, RSTable5ATOffset + 0x24977 + n)
        ret["QuadBank1"]            = self.read_arr16_at(15, RSTable5ATOffset + 0x123f0, 8)
        ret["QuadBank2"]            = self.read_arr16_at(15, RSTable5ATOffset + 0x12408, 2)

        ret["AdcIO"]                = self.read_scaledGrid16(4, 0xf, 0xf, 1, RSTable5ATOffset + 0x25708)
        for n in range(5):
            ret["QuaAdcIOName_{n}"] = self.read_scaledGrid16(4, 0xf, 0x4b, 5, RSTable5ATOffset + 0x25744 + n)
        ret["AdcBank"]              = self.read_arr16_at(4, RSTable5ATOffset + 0x12b80, 0)

        ret["Mult12x12In"]          = self.read_arr16_at(0x30, 0, RSTable5ATOffset + 0x13598)
        ret["Mult12x12Out"]         = self.read_arr16_at(0x30, 0, RSTable5ATOffset + 0x135f8)
        ret["Mult12x12InDlt"]       = self.read_arr16_at(0x30, 0, RSTable5ATOffset + 0x13658)
        ret["Mult12x12OutDlt"]      = self.read_arr16_at(0x30, 0, RSTable5ATOffset + 0x136b8)

        #The following are defined right next to Mult12x12 so are probably realted, but not referenced
        #ret["UNKNOWN"]              = self.read_arr16_at(0x18, RSTable5ATOffset + 0x12a6a, 0)
        #ret["UNKNOWN"]              = self.read_arr16_at(0x18, RSTable5ATOffset + 0x12b2a, 0)
        #ret["UNKNOWN"]              = self.read_arr16_at(0x18, RSTable5ATOffset + 0x12aca 0)
        #ret["UNKNOWN"]              = self.read_arr16_at(0x18, RSTable5ATOffset + 0x12b8a, 0)

        ret["MultAddAlu12x12In"]    = self.read_arr16_at(0x64, 0, RSTable5ATOffset + 0x13718)
        ret["MultAddAlu12x12Out"]   = self.read_arr16_at(0x60, 0, RSTable5ATOffset + 0x137e0)
        ret["MultAddAlu12x12InDlt"] = self.read_arr16_at(0x64, 0, RSTable5ATOffset + 0x138a0)
        ret["MultAddAlu12x12OutDlt"]= self.read_arr16_at(0x60, 0, RSTable5ATOffset + 0x13968)

        ret["MultAlu27x18In"]       = self.read_arr16_at(0xca, 0, RSTable5ATOffset + 0x13a28)
        ret["MultAlu27x18InDlt"]    = self.read_arr16_at(0xca, 0, RSTable5ATOffset + 0x13cb2)
        ret["MultAlu27x18Out"]      = self.read_arr16_at(0x7b, 0, RSTable5ATOffset + 0x13bbc)
        ret["MultAlu27x18OutDlt"]   = self.read_arr16_at(0x7b, 0, RSTable5ATOffset + 0x13e46)
        ret["MultCtrlIn"]           = self.read_arr16_at(0x6, 0, RSTable5ATOffset + 0x13f3c)
        ret["MultCtrlInDlt"]        = self.read_arr16_at(0x6, 0, RSTable5ATOffset + 0x13f48)

        ret["DqsRLoc"]              = self.read_arr16_at(0x2, RSTable5ATOffset + 0x12c38, 0)
        ret["DqsCLoc"]              = self.read_arr16_at(0x2, RSTable5ATOffset + 0x12c38, 4)

        ret["MDdrDllIns1"]          = self.read_scaledGrid16(4, 3, 3, RSTable5ATOffset + 0x12c38, 8)
        ret["MDdrDllIns2"]          = self.read_scaledGrid16(4, 3, 3, RSTable5ATOffset + 0x12cb0, 2)
        ret["MDdrDllIns3"]          = self.read_scaledGrid16(4, 3, 3, RSTable5ATOffset + 0x12d20, 0xc)
        ret["MDdrDllIns4"]          = self.read_scaledGrid16(4, 3, 3, RSTable5ATOffset + 0x12d98, 6)
        ret["MDdrDllIns5"]          = self.read_scaledGrid16(4, 3, 3, RSTable5ATOffset + 0x12e10, 0)
        ret["MDdrDllIns6"]          = self.read_scaledGrid16(4, 3, 3, RSTable5ATOffset + 0x12e30, 0xe)
        ret["MDdrDllIns7"]          = self.read_scaledGrid16(4, 3, 3, RSTable5ATOffset + 0x12e58, 0xc)

        ret["S0DdrDllIns1"]         = self.read_scaledGrid16(4, 3, 3, RSTable5ATOffset + 0x12c60, 6)
        ret["S0DdrDllIns2"]         = self.read_scaledGrid16(4, 3, 3, RSTable5ATOffset + 0x12cd8, 0)
        ret["S0DdrDllIns3"]         = self.read_scaledGrid16(4, 3, 3, RSTable5ATOffset + 0x12d48, 10)
        ret["S0DdrDllIns4"]         = self.read_scaledGrid16(4, 3, 3, RSTable5ATOffset + 0x12dc0, 4)

        ret["S1DdrDllIns1"]         = self.read_scaledGrid16(4, 3, 3, RSTable5ATOffset + 0x12c88, 4)
        ret["S1DdrDllIns2"]         = self.read_scaledGrid16(4, 3, 3, RSTable5ATOffset + 0x12cf8, 0xe)
        ret["S1DdrDllIns3"]         = self.read_scaledGrid16(4, 3, 3, RSTable5ATOffset + 0x12d70, 8)
        ret["S1DdrDllIns4"]         = self.read_scaledGrid16(4, 3, 3, RSTable5ATOffset + 0x12de8, 2)

        ret["MDdrDllOuts1"]         = self.read_scaledGrid16(9, 3, 3, RSTable5ATOffset + 0x12c48, 0)
        ret["MDdrDllOuts2"]         = self.read_scaledGrid16(9, 3, 3, RSTable5ATOffset + 0x12cb8, 10)
        ret["MDdrDllOuts3"]         = self.read_scaledGrid16(9, 3, 3, RSTable5ATOffset + 0x12d30, 4)
        ret["MDdrDllOuts4"]         = self.read_scaledGrid16(9, 3, 3, RSTable5ATOffset + 0x12da0, 0xe)
        ret["MDdrDllOuts5"]         = self.read_scaledGrid16(9, 3, 3, RSTable5ATOffset + 0x12e18, 8)
        ret["MDdrDllOuts6"]         = self.read_scaledGrid16(9, 3, 3, RSTable5ATOffset + 0x12e40, 6)
        ret["MDdrDllOuts7"]         = self.read_scaledGrid16(9, 3, 3, RSTable5ATOffset + 0x12e68, 4)

        ret["S0DdrDllOuts1"]        = self.read_scaledGrid16(9, 3, 3, RSTable5ATOffset + 0x12c68, 0xe)
        ret["S0DdrDllOuts2"]        = self.read_scaledGrid16(9, 3, 3, RSTable5ATOffset + 0x12ce0, 8)
        ret["S0DdrDllOuts3"]        = self.read_scaledGrid16(9, 3, 3, RSTable5ATOffset + 0x12d58, 2)
        ret["S0DdrDllOuts4"]        = self.read_scaledGrid16(9, 3, 3, RSTable5ATOffset + 0x12dc8, 0xc)

        ret["S1DdrDllOuts1"]        = self.read_scaledGrid16(9, 3, 3, RSTable5ATOffset + 0x12c90, 0xc)
        ret["S1DdrDllOuts2"]        = self.read_scaledGrid16(9, 3, 3, RSTable5ATOffset + 0x12d08, 6)
        ret["S1DdrDllOuts3"]        = self.read_scaledGrid16(9, 3, 3, RSTable5ATOffset + 0x12d80, 0)
        ret["S1DdrDllOuts4"]        = self.read_scaledGrid16(9, 3, 3, RSTable5ATOffset + 0x12df0, 10)

        ret["CmseraIns"]            = self.read_scaledGrid16(0x20, 3, 3, RSTable5ATOffset + 0x12e80, 10)
        ret["CmseraOuts"]           = self.read_scaledGrid16(0x60, 3, 3, RSTable5ATOffset + 0x12ee0, 10)

        ret["AdcLRCIns"]            = self.read_scaledGrid16(0x28, 3, 3, RSTable5ATOffset + 0x13000, 10)
        ret["AdcLRCOuts"]           = self.read_scaledGrid16(0x12, 3, 3, RSTable5ATOffset + 0x13078, 10)
        ret["AdcLRCCfgvsenctl1"]    = self.read_scaledGrid16(3, 3, 3, RSTable5ATOffset + 0x78000, 6)
        ret["AdcLRCCfgvsenctl2"]    = self.read_scaledGrid16(0x24, 3, 3, RSTable5ATOffset + 0x130b8, 8)
        ret["AdcULCOuts"]           = self.read_scaledGrid16(0x12, 3, 3, RSTable5ATOffset + 0x13128, 0)
        ret["AdcULCCfgvsenctl"]     = self.read_scaledGrid16(3, 3, 3, RSTable5ATOffset + 0x13158, 0xc)
        ret["Adc25kIns"]            = self.read_scaledGrid16i(25, 3, 6, 1, RSTable5ATOffset + 0x26dfe)
        ret["Adc25kOuts"]           = self.read_scaledGrid16i(28, 3, 6, 1, RSTable5ATOffset + 0x26e94)

        ret["CibFabricNode"]        = self.read_cib_fabric_node(RSTable5ATOffset)
        ret["SharedIOLogicIOBloc"]  = self.read_scaledGrid16(0x9c, 2, 2, RSTable5ATOffset + 0x13208, 0xe)

        ret["TopAMBGA121N"]         = self.read_arr16_at(200, RSTable5ATOffset + 0x2668e, 0)
        ret["TopBMBGA121N"]         = self.read_arr16_at(200, RSTable5ATOffset + 0x2694a, 0)
        ret["BottomAMBGA121N"]      = self.read_arr16_at(200, RSTable5ATOffset + 0x26756, 0)
        ret["BottomBMBGA121N"]      = self.read_arr16_at(200, RSTable5ATOffset + 0x26a12, 0)
        ret["TopAMBGA121NName"]     = self.read_scaledGrid16(200, 9, 9, RSTable5ATOffset + 0x26c06, 0)
        ret["BottomAMBGA121NName"]  = self.read_scaledGrid16(200, 9, 9, RSTable5ATOffset + 0x2730e, 0)
        ret["TopBMBGA121NName"]     = self.read_scaledGrid16(200, 9, 9, RSTable5ATOffset + 0x284a2, 0)
        ret["BottomBMBGA121NName"]  = self.read_scaledGrid16(200, 9, 9, RSTable5ATOffset + 0x28baa, 0)

        ret["LeftAMBGA121N"]        = self.read_arr16_at(0x96, RSTable5ATOffset + 0x2681e, 0)
        ret["LeftBMBGA121N"]        = self.read_arr16_at(0x96, RSTable5ATOffset + 0x26ada, 0)
        ret["RightAMBGA121N"]       = self.read_arr16_at(0x96, RSTable5ATOffset + 0x268b4, 0)
        ret["RightBMBGA121N"]       = self.read_arr16_at(0x96, RSTable5ATOffset + 0x26b70, 0)
        ret["LeftAMBGA121NName"]    = self.read_scaledGrid16(0x96, 9, 9, RSTable5ATOffset + 0x27a16, 0)
        ret["RightAMBGA121NName"]   = self.read_scaledGrid16(0x96, 9, 9, RSTable5ATOffset + 0x27f5c, 0)
        ret["LeftBMBGA121NName"]    =  self.read_scaledGrid16(0x96, 9, 9, RSTable5ATOffset + 0x292b2, 0)
        ret["RightBMBGA121NName"]   = self.read_scaledGrid16(0x96, 9, 9, RSTable5ATOffset + 0x297f8, 0)

        ret["SpineColumn"]          = self.read_arr16_at(8, RSTable5ATOffset + 0x14e98, 0xe)


        return ret

    def read_portmap(self) -> dict:
        self._cur = 0x55D2C
        # These are ordered by position in the file
        ret = {
            "IobufAIn": self.read_u16(),
            "IobufAOut": self.read_u16(),
            "IobufAOE": self.read_u16(),
            "IObufAIO": self.read_u16(),
            "IobufBIn": self.read_u16(),
            "IobufBOut": self.read_u16(),
            "IobufBOE": self.read_u16(),
            "IObufBIO": self.read_u16(),
            "IobufIns": self.read_arr16(10),
            "IobufOuts": self.read_arr16(10),
            "IobufOes": self.read_arr16(10),
            "IologicAIn": self.read_arr16(0x31),
            "IologicAOut": self.read_arr16(0x16),
            "IologicBIn": self.read_arr16(0x31),
            "IologicBOut": self.read_arr16(0x16),
            "BsramIn": self.read_arr16(0x84),
            "BsramOut": self.read_arr16(0x48),
            "BsramInDlt": self.read_arr16(0x84),
            "BsramOutDlt": self.read_arr16(0x48),
            "SsramIO": self.read_arr16(0x1C),
            "PllIn": self.read_arr16(0x24),
            "PllOut": self.read_arr16(0x5),
            "PllInDlt": self.read_arr16(0x24),
            "PllOutDlt": self.read_arr16(0x5),
            "PllClkin": self.read_clkins(6),
            "SpecPll0Ins": self.read_arr16(108),
            "SpecPll0Outs": self.read_arr16(15),
            "SpecPll0Clkin": self.read_arr16(18),
            "SpecPll1Ins": self.read_arr16(108),
            "SpecPll1Outs": self.read_arr16(15),
            "SpecPll1Clkin": self.read_arr16(18),
            "DllIn": self.read_arr16(4),
            "DllOut": self.read_arr16(9),
            "SpecDll0Ins": self.read_arr16(12),
            "SpecDll0Outs": self.read_arr16(27),
            "SpecDll1Ins": self.read_arr16(12),
            "SpecDll1Outs": self.read_arr16(27),
            "MultIn": self.read_mult(0x4F),
            "MultOut": self.read_mult(0x48),
            "MultInDlt": self.read_mult(0x4F),
            "MultOutDlt": self.read_mult(0x48),
            "PaddIn": self.read_mult(0x4C),
            "PaddOut": self.read_mult(0x36),
            "PaddInDlt": self.read_mult(0x4C),
            "PaddOutDlt": self.read_mult(0x36),
            "AluIn": self.read_clkins(0xA9),
            "AluOut": self.read_clkins(0x6D),
            "AluInDlt": self.read_clkins(0xA9),
            "AluOutDlt": self.read_clkins(0x6D),
            "MdicIn": self.read_clkins(0x36),
            "MdicInDlt": self.read_clkins(0x36),
            "CtrlIn": self.read_mult(0xE),
            "CtrlInDlt": self.read_mult(0xE),
            #"dsp12x12Ins": self.read_clkins(30),
            #"dsp12x12Outs": self.read_clkins(24),
            #"dsp12x12InDlt": self.read_clkins(30),
            #"dsp12x12OutDlt": self.read_clkins(24),
            #"dsp12x12SumIns": self.read_arr16(113),
            #"dsp12x12SumOuts": self.read_arr16(112),
            #"dsp12x12SumInDlt": self.read_arr16(113),
            #"dsp12x12SumOutDlt": self.read_arr16(112),
            #"dsp27x18Ins": self.read_arr16(163),
            #"dsp27x18Outs": self.read_arr16(139),
            #"dsp27x18InDlt": self.read_arr16(163),
            #"dsp27x18OutDlt": self.read_arr16(139),
            #"dspCtrlIns": self.read_clkins(6),
            #"dspCtrlInDlt": self.read_clkins(6),
        }
        assert self._cur == 0x58272 #0x58c8e
        return ret

    def read_io(self):
        self._cur = 0x58272
        ret = {}
        ret["CiuConnection"] = {}
        for i in range(320):
            ret["CiuConnection"][i] = self.read_arr16(60)
        ret["CiuFanoutNum"] = self.read_arr16(320)

        ret["CiuBdConnection"] = {}
        for i in range(320):
            ret["CiuBdConnection"][i] = self.read_arr16(60)

        ret["CiuBdFanoutNum"] = self.read_arr16(320)

        ret["CiuCornerConnection"] = {}
        for i in range(320):
            ret["CiuCornerConnection"][i] = self.read_arr16(60)
        ret["CiuCornerFanoutNum"] = self.read_arr16(320)

        ret["CmuxInNodes"] = {}
        for i in range(106):
            ret["CmuxInNodes"][i] = self.read_arr16(73)

        ret["CmuxIns"] = {}
        for i in range(106):
            ret["CmuxIns"][i] = self.read_arr16(3)

        ret["DqsRLoc"] = self.read_arr16(0x16)
        ret["DqsCLoc"] = self.read_arr16(0x16)
        ret["JtagIns"] = self.read_arr16(5)
        ret["JtagOuts"] = self.read_arr16(11)
        ret["ClksrcIns"] = self.read_arr16(0x27)
        ret["ClksrcOuts"] = self.read_arr16(17)
        ret["UfbIns"] = self.read_outs(0x5A)
        ret["UfbOuts"] = self.read_outs(0x20)
        ret["McuIns"] = self.read_outs(0x109)
        ret["McuOuts"] = self.read_outs(0x174)
        ret["EMcuIns"] = self.read_outs(0x10E)
        ret["EMcuOuts"] = self.read_outs(0x13F)
        ret["AdcIns"] = self.read_outs(0xF)
        ret["AdcOuts"] = self.read_outs(13)
        ret["Usb2PhyIns"] = self.read_outs(0x46)
        ret["Usb2PhyOuts"] = self.read_outs(0x2A)
        ret["Eflash128kIns"] = self.read_outs(0x39)
        ret["Eflash128kOuts"] = self.read_outs(0x21)
        ret["SpmiIns"] = self.read_outs(0x17)
        ret["SpmiOuts"] = self.read_outs(0x2F)
        ret["I3cIns"] = self.read_outs(0x26)
        ret["I3cOuts"] = self.read_outs(0x28)
        assert self._cur == 0x7b43e, hex(self._cur)
        return ret

    def read_something5A(self):
        RSTable5ATOffset = self._rs_table_offset
        ret = {
            "Dqs": {},
            "Cfg5": {},
        }
        """
        ret["Dqs"]["TA"]        = self.read_arr16_at(200, RSTable5ATOffset + 0x9a10, 4)
        ret["Dqs"]["TB"]        = self.read_arr16_at(200, RSTable5ATOffset + 0x9cc8, 0xc)
        ret["Dqs"]["BA"]        = self.read_arr16_at(200, RSTable5ATOffset + 0x9ad8, 4)
        ret["Dqs"]["BB"]        = self.read_arr16_at(200, RSTable5ATOffset + 0x9d90, 0xc)
        ret["Dqs"]["LA"]        = self.read_arr16_at(0x96, RSTable5ATOffset + 0x9ba0, 4)
        ret["Dqs"]["LB"]        = self.read_arr16_at(0x96, RSTable5ATOffset + 0x9e58, 0xc)
        ret["Dqs"]["RA"]        = self.read_arr16_at(0x96, RSTable5ATOffset + 0x9c38, 0)
        ret["Dqs"]["RA"]        = self.read_arr16_at(0x96, RSTable5ATOffset + 0x9ef0, 8)

        ret["Dqs"]["LeftIO"]    = self.read_arr16_at(0x16, RSTable5ATOffset + 0x9f88, 4)
        ret["Dqs"]["RightIO"]   = self.read_arr16_at(0x16, RSTable5ATOffset + 0x9fa0, 0)
        ret["Dqs"]["TopIO"]     = self.read_arr16_at(0x16, RSTable5ATOffset + 0x9fb0, 0xc)
        ret["Dqs"]["BottomIO"]  = self.read_arr16_at(0x16, RSTable5ATOffset + 0x9fc8, 8)
        """

        ret["Cfg5"]["TA"]        = self.read_arr32_at(200, 0,    RSTable5ATOffset)
        ret["Cfg5"]["BA"]        = self.read_arr32_at(200, 200,  RSTable5ATOffset)
        ret["Cfg5"]["LA"]        = self.read_arr32_at(150, 400,  RSTable5ATOffset)
        ret["Cfg5"]["RA"]        = self.read_arr32_at(150, 550,  RSTable5ATOffset)
        ret["Cfg5"]["TB"]        = self.read_arr32_at(200, 700,  RSTable5ATOffset)
        ret["Cfg5"]["BB"]        = self.read_arr32_at(200, 900,  RSTable5ATOffset)
        ret["Cfg5"]["LB"]        = self.read_arr32_at(150, 1100, RSTable5ATOffset)
        ret["Cfg5"]["RB"]        = self.read_arr32_at(150, 1250, RSTable5ATOffset)

        self._cur = RSTable5ATOffset + 0x3678;
        ret["IologicAIn"]  = self.read_arr16(62)
        ret["IologicBIn"]  = self.read_arr16(62)
        ret["IologicAOut"] = self.read_arr16(39)
        ret["IologicBOut"] = self.read_arr16(39)

        return ret

    def read_something(self):
        self._cur = 0x026068
        ret = {
            "Dqs": {},
            "Cfg": {},
            "SpecCfg": {},
            "Bank": {},
            "X16": {},
            "TrueLvds": {},
            "Type": {},
        }

        assert self._cur == 0x026068, hex(self._cur)
        ret["Dqs"]["TA"] = self.read_arr16_with_padding(200, self.grid.num_cols)
        assert self._cur == 0x261F8, hex(self._cur)
        ret["Dqs"]["BA"] = self.read_arr16_with_padding(200, self.grid.num_cols)
        assert self._cur == 0x26388, hex(self._cur)
        ret["Dqs"]["LA"] = self.read_arr16_with_padding(150, self.grid.num_rows)
        ret["Dqs"]["RA"] = self.read_arr16_with_padding(150, self.grid.num_rows)
        ret["Dqs"]["TB"] = self.read_arr16_with_padding(200, self.grid.num_cols)
        ret["Dqs"]["BB"] = self.read_arr16_with_padding(200, self.grid.num_cols)
        ret["Dqs"]["LB"] = self.read_arr16_with_padding(150, self.grid.num_rows)
        ret["Dqs"]["RB"] = self.read_arr16_with_padding(150, self.grid.num_rows)

        assert self._cur == 0x26b58, hex(self._cur)
        ret["Cfg"]["TA"] = self.read_arr32_with_padding(200, self.grid.num_cols)
        ret["Cfg"]["BA"] = self.read_arr32_with_padding(200, self.grid.num_cols)
        ret["Cfg"]["LA"] = self.read_arr32_with_padding(150, self.grid.num_rows)
        ret["Cfg"]["RA"] = self.read_arr32_with_padding(150, self.grid.num_rows)
        ret["Cfg"]["TB"] = self.read_arr32_with_padding(200, self.grid.num_cols)
        ret["Cfg"]["BB"] = self.read_arr32_with_padding(200, self.grid.num_cols)
        ret["Cfg"]["LB"] = self.read_arr32_with_padding(150, self.grid.num_rows)
        ret["Cfg"]["RB"] = self.read_arr32_with_padding(150, self.grid.num_rows)
        ret["SpecCfg"]["IOL"] = self.read_arr32_with_padding(10, 10)
        ret["SpecCfg"]["IOR"] = self.read_arr32_with_padding(10, 10)
        assert self._cur == 0x28188, hex(self._cur)

        ret["Bank"]["TA"] = self.read_arr16_with_padding(200, self.grid.num_cols)
        ret["Bank"]["BA"] = self.read_arr16_with_padding(200, self.grid.num_cols)
        ret["Bank"]["LA"] = self.read_arr16_with_padding(150, self.grid.num_cols)
        ret["Bank"]["RA"] = self.read_arr16_with_padding(150, self.grid.num_cols)
        ret["Bank"]["TB"] = self.read_arr16_with_padding(200, self.grid.num_cols)
        ret["Bank"]["BB"] = self.read_arr16_with_padding(200, self.grid.num_cols)
        ret["Bank"]["LB"] = self.read_arr16_with_padding(150, self.grid.num_cols)
        ret["Bank"]["RB"] = self.read_arr16_with_padding(150, self.grid.num_cols)
        ret["Bank"]["SpecIOL"] = self.read_arr16_with_padding(10, 10)
        ret["Bank"]["SpecIOR"] = self.read_arr16_with_padding(10, 10)

        ret["X16"]["TA"] = self.read_arr16_with_padding(200, self.grid.num_cols)
        ret["X16"]["BA"] = self.read_arr16_with_padding(200, self.grid.num_cols)
        ret["X16"]["LA"] = self.read_arr16_with_padding(150, self.grid.num_cols)
        ret["X16"]["RA"] = self.read_arr16_with_padding(150, self.grid.num_cols)
        ret["X16"]["TB"] = self.read_arr16_with_padding(200, self.grid.num_cols)
        ret["X16"]["BB"] = self.read_arr16_with_padding(200, self.grid.num_cols)
        ret["X16"]["LB"] = self.read_arr16_with_padding(150, self.grid.num_cols)
        ret["X16"]["RB"] = self.read_arr16_with_padding(150, self.grid.num_cols)
        ret["X16"]["SpecIOL"] = self.read_arr16_with_padding(10, 10)
        ret["X16"]["SpecIOR"] = self.read_arr16_with_padding(10, 10)
        assert self._cur == 0x297B8, hex(self._cur)

        ret["TrueLvds"]["TopA"] = self.read_arr8_with_padding(200, self.grid.num_cols)
        ret["TrueLvds"]["BottomA"] = self.read_arr8_with_padding(200, self.grid.num_cols)
        ret["TrueLvds"]["LeftA"] = self.read_arr8_with_padding(150, self.grid.num_rows)
        ret["TrueLvds"]["RightA"] = self.read_arr8_with_padding(150, self.grid.num_rows)
        ret["TrueLvds"]["TopB"] = self.read_arr8_with_padding(200, self.grid.num_cols)
        ret["TrueLvds"]["BottomB"] = self.read_arr8_with_padding(200, self.grid.num_cols)
        ret["TrueLvds"]["LeftB"] = self.read_arr8_with_padding(150, self.grid.num_rows)
        ret["TrueLvds"]["RightB"] = self.read_arr8_with_padding(150, self.grid.num_rows)
        ret["TrueLvds"]["SpecIOL"] = self.read_arr8_with_padding(10, 10)
        ret["TrueLvds"]["SpecIOR"] = self.read_arr8_with_padding(10, 10)

        ret["Type"]["TopA"] = self.read_arr32_with_padding(200, self.grid.num_cols)
        ret["Type"]["BottomA"] = self.read_arr32_with_padding(200, self.grid.num_cols)
        ret["Type"]["LeftA"] = self.read_arr32_with_padding(150, self.grid.num_rows)
        ret["Type"]["RightA"] = self.read_arr32_with_padding(150, self.grid.num_rows)
        ret["Type"]["TopB"] = self.read_arr32_with_padding(200, self.grid.num_cols)
        ret["Type"]["BottomB"] = self.read_arr32_with_padding(200, self.grid.num_cols)
        ret["Type"]["LeftB"] = self.read_arr32_with_padding(150, self.grid.num_rows)
        ret["Type"]["RightB"] = self.read_arr32_with_padding(150, self.grid.num_rows)
        return ret


if __name__ == "__main__":
    gowinhome = os.getenv("GOWINHOME")
    if not gowinhome:
        raise Exception("GOWINHOME not set")
    device = sys.argv[1]
    p = Path(f"{gowinhome}/IDE/share/device/{device}/{device}.dat")
    dat = Datfile(p)

    grid = dat.read_grid()
    for rd in grid.rows:
        for rc in rd:
            print(rc, end='')
        print('')
