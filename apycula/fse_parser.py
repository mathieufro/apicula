import os
import random
import re
from glob import glob

from apycula import bitmatrix


class FseVersionError(ValueError):
    """The installed Gowin IDE version could not be determined."""


class FseShapeError(ValueError):
    """A `.fse` table shape did not match the selected shape descriptor.

    Raised instead of the historical opaque ``ValueError: Unknown type -0x1``
    so the message names the detected IDE version, the shape set in use, the
    table that desynced and the expected-vs-found row width.
    """


# Per-IDE-version table shape descriptors (D16/EC1). Keyed by a *shape-set
# name*, never by a version string, so a new IDE release that keeps the same
# shapes reuses an existing set instead of cloning it.
#
# `v1_9_10` is the historical upstream set, transcribed verbatim from the
# width literals that used to sit inline in the dispatch below.
#
# `v1_9_11plus` keeps every flat width of `v1_9_10`; the 1.9.11+ difference is
# not a flat width at all but a per-subtype one, recorded in
# `TABLE_SUBTYPE_SHAPES` below (P0.T12).
_SHAPES_V1_9_10 = {
    "fuse": 150,
    "fuse_5series": 512,
    "wire": 8,
    "wire_5series": 9,
    "wiresearch": 3,
    "const": 1,
    "shortval": 14,
    "alonenode": 15,
    "logicinfo": 3,
    "longfuse": 17,
    "longval": 28,
    "signedlogicinfo": 3,
    "drpfuse": 10,
}

# `v1_9_12plus` is Gowin IDE 1.9.12.03. It keeps every width of `v1_9_11plus`
# except `drpfuse` (type 0x8b), whose row grew from 10 to 30 u16 (P0.T13b).
# The drift is per *IDE version*, not per device or per subtype: the only two
# devices that ship a `drpfuse` table at all -- GW5A-25A (tile 150, table idx
# 2, 1053 rows, offset 0x707160) and GW5AT-60B (tile 150, idx 2, 2323 rows,
# offset 0x866228) -- both read at 10 on 1.9.11.03 and at 30 on 1.9.12.03, and
# both `.fse` files then parse to EOF. GW5AST-138C ships no `drpfuse` table in
# either edition, which is why the 138C build never saw this.
_SHAPES_V1_9_12 = dict(_SHAPES_V1_9_10, drpfuse=30)

TABLE_SHAPES: dict[str, dict[str, int]] = {
    "v1_9_10": dict(_SHAPES_V1_9_10),
    "v1_9_11plus": dict(_SHAPES_V1_9_10),
    "v1_9_12plus": dict(_SHAPES_V1_9_12),
}

# Device series a subtype override may be scoped to. A `.fse` row width can
# depend on the device generation as well as the IDE version, so the override
# table below carries the series as an explicit key rather than assuming the
# 5-series layout holds for every part the same install ships.
SERIES_GW5A = "gw5a"
SERIES_DEFAULT = "default"


def device_series(device: str) -> str:
    """`"GW5AST-138C"` -> `"gw5a"`; every pre-5-series part -> `"default"`."""
    return SERIES_GW5A if (device or "").lower().startswith("gw5a") \
        else SERIES_DEFAULT


# Per-shape-set, per-series, per-table-*subtype* row widths, consulted before
# the flat width above (P0.T12, rescoped by P0.T13b). A `.fse` row width is not
# always a property of the table kind alone: from Gowin IDE 1.9.11 the longfuse
# subtypes 0x35/0x36 carry 14 u16 per row **on 5-series devices**, while every
# other longfuse subtype (0x12, 0x13, 0x3a) -- and every longfuse subtype at
# all on pre-5-series devices from the same install -- still carries 17.
# Measured on `GW5AST-138C.fse`, `GW5A-25A.fse` and `GW5AT-60B.fse` (14) and on
# `GW1N-9C.fse`, `GW1NZ-1.fse`, `GW2A-18C.fse` (17) from both installed
# editions; all twelve files then parse to EOF.
# P0.T12 keyed this on the IDE version alone, which
# made every pre-5-series `.fse` desync at its first 0x35 table on a 1.9.11+
# install; the series key is the missing dimension.
# A subtype absent here falls back to `TABLE_SHAPES[shape_set][table]`, so
# `v1_9_10` (empty) parses exactly as it did before.
TABLE_SUBTYPE_SHAPES: dict[str, dict[str, dict[str, dict[int, int]]]] = {
    "v1_9_10": {},
    "v1_9_11plus": {SERIES_GW5A: {"longfuse": {0x35: 14, 0x36: 14}}},
    "v1_9_12plus": {SERIES_GW5A: {"longfuse": {0x35: 14, 0x36: 14}}},
}

DEFAULT_SHAPE_SET = "v1_9_10"

_VERSION_RE = re.compile(r"(\d+\.\d+\.\d+\.\d+)")


def detect_ide_version(gowinhome: str) -> str:
    """Return the version of the Gowin EDA install rooted at `gowinhome`.

    The install carries no machine-readable stamp; the release-note filenames
    under ``IDE/doc/`` are the only textual carrier present in every edition
    (Education ``RN100-1.9.11.03Education*``, Standard ``RN100-1.9.12.03*``).
    ``GOWIN_IDE_VERSION`` overrides the probe for tests and odd layouts.
    """
    override = os.environ.get("GOWIN_IDE_VERSION")
    if override:
        return override
    if not gowinhome:
        raise FseVersionError(
            "cannot detect Gowin IDE version: GOWINHOME is empty; "
            "set GOWINHOME or GOWIN_IDE_VERSION")
    for pattern in ("IDE/doc/RN100-*", "IDE/doc/*/RN100-*"):
        for path in sorted(glob(os.path.join(gowinhome, pattern))):
            match = _VERSION_RE.search(os.path.basename(path))
            if match:
                return match.group(1)
    raise FseVersionError(
        f"cannot detect Gowin IDE version under {gowinhome!r}: "
        "no IDE/doc/RN100-<version> release note found; "
        "set GOWIN_IDE_VERSION to override")


def _version_tuple(ide_version: str) -> tuple[int, ...]:
    """`"1.9.12.03"` -> `(1, 9, 12, 3)`; a non-numeric field ends the tuple."""
    parts = []
    for field in (ide_version or "").split("."):
        if not field.isdigit():
            break
        parts.append(int(field))
    return tuple(parts)


def select_shapes(ide_version: str) -> tuple[str, dict[str, int]]:
    """Map a detected IDE version onto (shape set name, shape descriptor)."""
    version = _version_tuple(ide_version)[:3]
    if version >= (1, 9, 12):
        name = "v1_9_12plus"
    elif ide_version and not ide_version.startswith("1.9.10."):
        name = "v1_9_11plus"
    else:
        name = DEFAULT_SHAPE_SET
    return name, TABLE_SHAPES[name]


def _active_shapes() -> tuple[str, str, dict[str, int]]:
    """(ide_version, shape_set_name, shapes) for the current environment.

    Version detection is best-effort: a missing or unreadable install must not
    stop a parse that would otherwise have worked, so it degrades to the
    default shape set and reports ``unknown`` in any diagnostic.
    """
    try:
        ide_version = detect_ide_version(os.environ.get("GOWINHOME", ""))
    except FseVersionError:
        ide_version = "unknown"
    shape_set, shapes = select_shapes(ide_version)
    return ide_version, shape_set, shapes


def read_int(f, w):
    val = int.from_bytes(f.read(w), 'little', signed=True)
    return val

def read_fse(f, device):
    print("check", read_int(f, 4))
    shape_ctx = _active_shapes()
    tiles = {}
    ttyp = read_int(f, 4)
    #print(f"tile type:{ttyp}/{hex(ttyp)}")
    tiles['header'] = read_one_file(f, ttyp, device, shape_ctx)
    while True:
        ttyp = read_int(f, 4)
        if ttyp == 0x9a1d85: break
        #print(f"tile type:{ttyp}/{hex(ttyp)}")
        tiles[ttyp] = read_one_file(f, ttyp, device, shape_ctx)
    return tiles

def read_table(f, size1, size2, w=2):
    return [[read_int(f, w) for j in range(size2)]
                        for i in range(size1)]

# Every table type the dispatch in `read_one_file` below understands. Used only
# to sanity-check a realignment candidate when reporting a desync; keep it in
# step with the dispatch (tests/test_fse_shapes_regression.py guards the ones
# with a pinned row width).
_KNOWN_TABLE_TYPES = frozenset(
    {61, 1, 0x02, 0x26, 0x30, 0x5a, 0x5b, 0x03, 0x04, 6, 0x45,
     0x12, 0x13, 0x35, 0x36, 0x3a, 0x43, 0x86, 0x87, 0x8b, 0x9a}
    | {0x05, 0x11, 0x14, 0x15, 0x16, 0x19, 0x1a, 0x1b,
       0x1c, 0x1d, 0x1e, 0x1f, 0x20, 0x21, 0x22, 0x23,
       0x24, 0x32, 0x33, 0x38, 0x3c, 0x40, 0x42, 0x44,
       0x47, 0x49, 0x4b, 0x4d, 0x4f, 0x50, 0x52, 0x54,
       0x56, 0x58, 0x59, 0x5d, 0x5e, 0x5f, 0x60, 0x61,
       0x62, 0x63, 0x64, 0x65, 0x66, 0x67, 0x68, 0x69,
       0x6a, 0x6b, 0x6c, 0x6d, 0x6e, 0x6f, 0x70, 0x71,
       0x72, 0x73, 0x74, 0x75, 0x76, 0x77, 0x78, 0x79,
       0x7a, 0x7b, 0x7c, 0x7d, 0x7e, 0x7f, 0x80, 0x81,
       0x82, 0x83, 0x84, 0x85, 0x88, 0x89, 0x8a, 0x8c,
       0x8d, 0x8e, 0x8f, 0x90, 0x91, 0x92, 0x93, 0x94,
       0x95, 0x96, 0x97, 0x98, 0x99, 0x9b, 0x9c, 0x9e}
    | {0x07, 0x08, 0x09, 0x0a, 0x0b, 0x0c, 0x0d, 0x0e,
       0x0f, 0x10, 0x27, 0x31, 0x34, 0x37, 0x39, 0x3b,
       0x3e, 0x3f, 0x41, 0x46, 0x48, 0x4a, 0x4c, 0x4e,
       0x51, 0x53, 0x55, 0x57, 0x5c}
    | {0x17, 0x18, 0x25, 0x28, 0x29, 0x2a, 0x2b, 0x2c, 0x2d, 0x2e, 0x2f})

# realignment candidates, widest first is pointless — try narrow to wide and
# take the first width that lands the next 4 bytes on a known table type.
_PROBE_WIDTHS = tuple(range(1, 65))


def _diagnose_desync(f, prev):
    """Best-effort (expected_row_width, found_row_width, table) for a desync.

    A desync is always caused by the *previous* table having been read at the
    wrong row width, so the useful diagnostic is that table's configured width
    versus the width that would have put the file back in step. Read-only: the
    file position is always restored.
    """
    if prev is None:
        return "unknown", "unknown", "unknown"
    typn, _typ, rows, width, data_start = prev
    if typn == "grid" or not rows:
        return width, "unknown", typn
    found = "unknown"
    try:
        if f.seekable():
            here = f.tell()
            try:
                for cand in _PROBE_WIDTHS:
                    if cand == width:
                        continue
                    f.seek(data_start + rows * cand * 2)
                    probe = f.read(4)
                    if len(probe) < 4:
                        break
                    if int.from_bytes(probe, 'little', signed=True) in _KNOWN_TABLE_TYPES:
                        found = cand
                        break
            finally:
                f.seek(here)
    except (OSError, ValueError):
        pass
    return width, found, typn


def row_width(shape_set, shapes, table, typ=None, series=SERIES_DEFAULT):
    """Row width for `table`, honouring a per-series/subtype override."""
    if typ is not None:
        override = (TABLE_SUBTYPE_SHAPES.get(shape_set, {})
                    .get(series, {}).get(table, {}))
        if typ in override:
            return override[typ]
    return shapes[table]


def derive_row_width(f, rows, data_start, limit=4):
    """Row widths the file's own layout admits for the table at `data_start`.

    A table of `rows` rows read at width `w` leaves the reader on the next
    table's 4-byte type tag, so the widths that land on a *known* tag are the
    candidates the data itself supports. Narrow to wide; read-only, the file
    position is always restored. An empty list means the probe is inconclusive
    (the table is the last of its tile, so the following tag is a tile type),
    never that the width is wrong.
    """
    if not rows or not f.seekable():
        return []
    here = f.tell()
    found = []
    try:
        for cand in _PROBE_WIDTHS:
            f.seek(data_start + rows * cand * 2)
            probe = f.read(4)
            if len(probe) < 4:
                break
            if int.from_bytes(probe, 'little', signed=True) in _KNOWN_TABLE_TYPES:
                found.append(cand)
                if len(found) >= limit:
                    break
    except (OSError, ValueError):
        return []
    finally:
        f.seek(here)
    return found


def _confirm_row_width(f, rows, data_start, expected, table,
                       ide_version, shape_set):
    """`expected`, once the file's own layout has been asked to agree with it.

    Raises `FseShapeError` naming both widths when the data positively
    contradicts the shape descriptor, instead of letting the read run on and
    desync at some unrelated offset several tables later.
    """
    found = derive_row_width(f, rows, data_start)
    if not found or expected in found:
        return expected
    raise FseShapeError(
        f"{table} row width mismatch at {hex(data_start)}: "
        f"ide_version={ide_version} shape_set={shape_set} table={table} "
        f"expected_row_width={expected} found_row_width={found[0]}")


def read_one_file(f, tile_type, device, shape_ctx=None):
    if shape_ctx is None:
        shape_ctx = _active_shapes()
    ide_version, shape_set, shapes = shape_ctx
    tmap = {"height": read_int(f, 4),
            "width": read_int(f, 4)}
    tables = read_int(f, 4)
    #print("height: ", tmap["height"], "width: ", tmap["width"], "tables:", tables)

    #v1 = 0x1b8
    #v2 = 3
    #if (tile_type < 0x400):
    #    if ((0x1b7 < tile_type) or (tile_type < 0)):
    #        print("Error: read_one_file 1")
    #else:
    #    if (2 < tile_type + -0x400):
    #        print("Error: read_one_file 2")

    #    v2 = tile_type + -0x400
    #    tile_type = v1

    #v1 = tile_type

    is_5_series = device.lower().startswith("gw5a")
    series = device_series(device)

    # the previously-read table, so a desync can name the table that caused it
    prev = None
    for i in range(tables):
        typ = read_int(f, 4)
        size = read_int(f, 4)
        data_start = f.tell()
        #print(hex(f.tell()), " Table type", typ, "/", hex(typ), "of size", size)
        if typ == 61:
            size2 = read_int(f, 4)
            typn = "grid"
            width = size2
            t = read_table(f, size, size2, 4)
        elif typ == 1:
            # Check if the device is 5 series as tile type 1 needs to be read differently
            typn = "fuse"
            key = "fuse_5series" if is_5_series else "fuse"
            width = shapes[key]
            t = read_table(f, size, width, 2)
        elif typ in {0x02, 0x26, 0x30, 0x5a, 0x5b}:
            typn = "wire"
            width = shapes["wire_5series" if is_5_series else "wire"]
            t = read_table(f, size, width, 2)
        elif typ == 0x03:
            typn = "wiresearch"
            width = shapes["wiresearch"]
            t = read_table(f, size, width, 2)
        elif typ == 0x04:
            typn = "const"
            width = shapes["const"]
            t = read_table(f, size, width, 2)
        elif typ in {0x05, 0x11, 0x14, 0x15, 0x16, 0x19, 0x1a, 0x1b,
                     0x1c, 0x1d, 0x1e, 0x1f, 0x20, 0x21, 0x22, 0x23,
                     0x24, 0x32, 0x33, 0x38, 0x3c, 0x40, 0x42, 0x44,
                     0x47, 0x49, 0x4b, 0x4d, 0x4f, 0x50, 0x52, 0x54,
                     0x56, 0x58, 0x59, 0x5d, 0x5e, 0x5f, 0x60, 0x61,
                     0x62, 0x63, 0x64, 0x65, 0x66, 0x67, 0x68, 0x69,
                     0x6a, 0x6b, 0x6c, 0x6d, 0x6e, 0x6f, 0x70, 0x71,
                     0x72, 0x73, 0x74, 0x75, 0x76, 0x77, 0x78, 0x79,
                     0x7a, 0x7b, 0x7c, 0x7d, 0x7e, 0x7f, 0x80, 0x81,
                     0x82, 0x83, 0x84, 0x85, 0x88, 0x89, 0x8a, 0x8c,
                     0x8d, 0x8e, 0x8f, 0x90, 0x91, 0x92, 0x93, 0x94,
                     0x95, 0x96, 0x97, 0x98, 0x99, 0x9b, 0x9c, 0x9e}:
            typn = "shortval"
            width = shapes["shortval"]
            t = read_table(f, size, width, 2)
        elif typ in {6, 0x45}:
            typn = "alonenode"
            width = shapes["alonenode"]
            t = read_table(f, size, width, 2)
        elif typ in {0x07, 0x08, 0x09, 0x0a, 0x0b, 0x0c, 0x0d, 0x0e,
                     0x0f, 0x10, 0x27, 0x31, 0x34, 0x37, 0x39, 0x3b,
                     0x3e, 0x3f, 0x41, 0x46, 0x48, 0x4a, 0x4c, 0x4e,
                     0x51, 0x53, 0x55, 0x57, 0x5c}:
            typn = "logicinfo"
            width = shapes["logicinfo"]
            t = read_table(f, size, width, 2)
        elif typ in {0x12, 0x13, 0x35, 0x36, 0x3a}:
            typn = "longfuse"
            width = row_width(shape_set, shapes, "longfuse", typ, series)
            width = _confirm_row_width(f, size, data_start, width, typn,
                                       ide_version, shape_set)
            t = read_table(f, size, width, 2)
        elif typ in {0x17, 0x18, 0x25, 0x28, 0x29, 0x2a, 0x2b, 0x2c, 0x2d, 0x2e, 0x2f}:
            typn = "longval"
            width = shapes["longval"]
            t = read_table(f, size, width, 2)
        elif typ == 0x43:
            if device in {'GW1N-1', 'GW1NZ-1', 'GW1N-9', 'GW1N-9C', 'GW1N-4', 'GW1NS-4',
                        'GW2A-18', 'GW2A-18C', 'GW5A-25A', 'GW5AS-25A', 'GW5AST-138C'}:
                typn = "logicinfo"
                width = shapes["logicinfo"]
                t = read_table(f, size, width, 2)
            else: # GW5A-138B GW5AST-138B GW5AT-138 GW5AT-138B GW5AT-75B
                typn = "signedlogicinfo"
                width = shapes["signedlogicinfo"]
                t = read_table(f, size, width, 2)
        elif typ in {0x86, 0x87}:
            typn = "signedlogicinfo"
            #t = read_table(f, size, 6, 2)
            width = shapes["signedlogicinfo"]
            t = read_table(f, size, width, 2)
        elif typ == 0x8b:
            typn = "drpfuse"
            width = row_width(shape_set, shapes, "drpfuse", typ, series)
            width = _confirm_row_width(f, size, data_start, width, typn,
                                       ide_version, shape_set)
            t = read_table(f, size, width, 2)
        elif typ == 0x9a: # 60K
            typn = "logicinfo"
            width = shapes["logicinfo"]
            t = read_table(f, size, width, 2)
        else:
            expected, found, typn_guess = _diagnose_desync(f, prev)
            raise FseShapeError(
                f"unknown table type {hex(typ)} at {hex(f.tell())}: "
                f"ide_version={ide_version} shape_set={shape_set} "
                f"table={typn_guess} "
                f"expected_row_width={expected} found_row_width={found}")
        prev = (typn, typ, size, width, data_start)
        tmap.setdefault(typn, {})[typ] = t
    return tmap

def render_tile(d, ttyp, device):
    w = d[ttyp]['width']
    h = d[ttyp]['height']


    is_5_series = device.lower().startswith("gw5a")

    #if is_5_series:
    #    h = h * 2

    highestnum = 0

    tile = bitmatrix.zeros(h, w)#+(255-ttyp)
    for start, table in [(2, 'shortval'), (2, 'wire'), (16, 'longval'),
                         (1, 'longfuse'), (0, 'const')]:
        if table in d[ttyp]:
            for styp, sinfo in d[ttyp][table].items():
                for i in sinfo:
                    for fuse in i[start:]:
                        if fuse > 0:
                            if ttyp > 0x400: num = d['header']['fuse'][1][fuse][ttyp - 0x400]
                            else: num = d['header']['fuse'][1][fuse][ttyp]

                            if num > highestnum:
                                highestnum = num
                            row = num // 100
                            col = num % 100
                            if is_5_series:
                                row = num // 200
                                col = num % 200

                            if row > h:
                                print("tile(r):", ttyp, "row:", row, "w:", w,"h:", h, "highest:", highestnum)

                            if col > w:
                                print("tile(w):", ttyp, "col:", col, "w:", w,"h:", h, "highest:", highestnum)

                            if table == "wire":
                                if i[0] > 0:
                                    if tile[row][col] == 0:
                                        tile[row][col] = (styp + i[1]) % 256
                                    else:
                                        tile[row][col] = (tile[row][col] + (styp + i[1]) % 256) // 2
                            elif table == "shortval" and styp == 5:
                                #assert tile[row][col] == 0
                                tile[row][col] = (styp + i[0]) % 256
                            else:
                                tile[row][col] = styp

    #print("tile:", ttyp, "w:", w,"h:", h, "highest:", highestnum)

    return tile


def render_bitmap(d, device):
    tiles = d['header']['grid'][61]
    width = sum([d[i]['width'] for i in tiles[0]])
    height = sum([d[i[0]]['height'] for i in tiles])

    is_5_series = device.lower().startswith("gw5a")

    if is_5_series:
        height = height * 2

    bitmap = bitmatrix.zeros(height, width)
    y = 0
    for row in tiles:
        x=0
        for typ in row:
            td = d[typ]
            w = td['width']
            h = td['height']
            #bitmap[y:y+h,x:x+w] += render_tile(d, typ)
            #bitmap[y:y+h,x:x+w] = typ
            rtile = render_tile(d, typ, device)
            y0 = y
            for row in rtile:
                x0 = x
                for val in row:
                    bitmap[y0][x0] += val
                    x0 += 1
                y0 += 1
            x+=w
        y+=h

    return bitmap

def display(fname, data):
    from PIL import Image
    import numpy as np
    data = np.array(data, dtype = np.uint16)
    im = Image.frombytes(
            mode='P',
            size=data.shape[::-1],
            data=data)
    random.seed(123)
    im.putpalette(random.choices(range(256), k=3*256))
    if fname:
        im.save(fname)
    return im

def fuse_lookup(d, ttyp, fuse, device):
    is_5_series = device.lower().startswith("gw5a")

    w = d[ttyp]['width']
    h = d[ttyp]['height']

    if fuse >= 0:
        num = d['header']['fuse'][1][fuse][ttyp]
        row = num // 100
        col = num % 100
        if is_5_series:
            row = num // 200
            col = num % 200

        if row > h:
            print("row too big", ttyp, row, h, col, w, num, h * w)
        if col > w:
            print("col too big", col, w)
        return row, col

def drpfuse_lookup(d, ttyp, fuse, device):
    if fuse >= 0:
        num = d['header']['drpfuse'][139][fuse][ttyp]
        row = num // 200
        col = num % 200
        return row, col

def tile_bitmap(d, bitmap, empty=False):
    tiles = d['header']['grid'][61]
    width = sum([d[i]['width'] for i in tiles[0]])
    height = sum([d[i[0]]['height'] for i in tiles])
    res = {}
    y = 0
    for idx, row in enumerate(tiles):
        x=0
        for jdx, typ in enumerate(row):
            td = d[typ]
            w = td['width']
            h = td['height']
            tile = [row[x:x+w] for row in bitmap[y:y+h]]
            if bitmatrix.any(tile) or empty:
                res[(idx, jdx, typ)] = tile
            x+=w
        y+=h

    return res

def fuse_bitmap(d, bitmap):
    tiles = d['header']['grid'][61]
    width = sum([d[i]['width'] for i in tiles[0]])
    height = sum([d[i[0]]['height'] for i in tiles])
    res = bitmatrix.zeros(height, width)
    y = 0
    for idx, row in enumerate(tiles):
        x=0
        for jdx, typ in enumerate(row):
            td = d[typ]
            w = td['width']
            h = td['height']
            y0 = y
            for row in bitmap[(idx, jdx, typ)]:
                x0 = x
                for val in row:
                    res[y0][x0] = val
                    x0 += 1
                y0 += 1
            x+=w
        y+=h

    return res

def parse_tile(d, ttyp, tile, device):
    w = d[ttyp]['width']
    h = d[ttyp]['height']
    res = {}
    for start, table in [(2, 'shortval'), (2, 'wire'), (16, 'longval'),
                         (1, 'longfuse'), (0, 'const')]:
        if table in d[ttyp]: # skip missing entries
            for subtyp, tablerows in d[ttyp][table].items():
                items = {}
                for row in tablerows:
                    pos = row[0] > 0
                    coords = {(fuse_lookup(d, ttyp, f, device), pos) for f in row[start:] if f > 0}
                    idx = tuple(abs(attr) for attr in row[:start])
                    items.setdefault(idx, {}).update(coords)

                #print(items)
                for idx, item in items.items():
                    test = [tile[loc[0]][loc[1]] == val
                            for loc, val in item.items()]
                    if all(test):
                        row = idx + tuple(item.keys())
                        res.setdefault(table, {}).setdefault(subtyp, []).append(row)

    return res

def parse_tile_exact(d, ttyp, tile, device, fuse_loc=True):
    w = d[ttyp]['width']
    h = d[ttyp]['height']
    res = {}
    for start, table in [(2, 'shortval'), (2, 'wire'), (16, 'longval'),
                         (1, 'longfuse'), (0, 'const')]:
        if table in d[ttyp]: # skip missing entries
            for subtyp, tablerows in d[ttyp][table].items():
                pos_items, neg_items = {}, {}
                active_rows = []
                for row in tablerows:
                    if row[0] > 0:
                        row_fuses  = [fuse for fuse in row[start:] if fuse >= 0]
                        locs = [fuse_lookup(d,ttyp, fuse, device) for fuse in row_fuses]
                        test = [tile[loc[0]][loc[1]] == 1 for loc in locs]
                        if all(test):
                            full_row = row[:start]
                            full_row.extend(row_fuses)
                            active_rows.append(full_row)

                # report fuse locations
                if (active_rows):
                    exact_cover = exact_table_cover(active_rows, start, table)
                    if fuse_loc:
                        for cover_row in exact_cover:
                            cover_row[start:] = [fuse_lookup(d, ttyp, fuse, device) for fuse in cover_row[start:]]

                    res.setdefault(table, {})[subtyp] = exact_cover
    return res


def exact_table_cover(t_rows, start, table=None):
    try:
        import xcover
    except:
        raise ModuleNotFoundError ("The xcover package needs to be installed to use the exact_cover function.\
                                    \nYou may install it via pip: `pip install xcover`")

    row_fuses = [set ([fuse for fuse in row[start:] if fuse!=-1]) for row in t_rows]
    primary = set()
    for row in row_fuses:
        primary.update(row)
    secondary = set()

    # Enforce that every destination node has a single source
    if table == 'wire':
        for id, row in enumerate(t_rows):
            # Casting the wire_id to a string ensures that it doesn't conflict with fuse_ids
            row_fuses[id].add(str(row[1]))
            secondary.add(str(row[1]))

    g = xcover.covers(row_fuses, primary=primary, secondary=secondary, colored=False)
    if g:
        for r in g:
            #g is an iterator, so this is just a hack to return the first solution.
            #A future commit might introduce a heuristic for determining what solution is most plausible
            #where there are multiple solutions
            return [t_rows[idx] for idx in r]
    else:
        return []

def scan_fuses(d, ttyp, tile, device):
    is_5_series = device.lower().startswith("gw5a")

    w = d[ttyp]['width']
    h = d[ttyp]['height']
    fuses = []
    rows, cols = bitmatrix.nonzero(tile)
    for row, col in zip(rows, cols):
        # ripe for optimization
        for fnum, fuse in enumerate(d['header']['fuse'][1]):
            num = fuse[ttyp]
            frow = num // 100
            fcol = num % 100
            #if is_5_series:
            #    frow = num // w
            #    fcol = num % w
            #    print("GO FLUFFY")

            if frow == row and fcol == col and fnum > 100:
                fuses.append(fnum)
    return set(fuses)

def scan_tables(d, tiletyp, fuses):
    res = []
    for tname, tables in d[tiletyp].items():
        if tname in {"width", "height"}: continue
        for ttyp, table in tables.items():
            for row in table:
                row_fuses = fuses.intersection(row)
                if row_fuses:
                    #print(f"fuses {row_fuses} found in {tname}({ttyp}): {row}")
                    res.append(row)
    return res

def reduce_rows(rows, fuses, start=16, tries=1000):
    rowmap = {frozenset(iv[:iv.index(0)]): frozenset(iv[start:(list(iv)+[-1]).index(-1)]) for iv in rows}
    features = {i for s in rowmap.keys() for i in s}
    for _ in range(tries):
        feat = random.sample(features, 1)[0]
        features.remove(feat)
        rem_fuses = set()
        for k, v in rowmap.items():
            if k & features:
                rem_fuses.update(v)
        if rem_fuses != fuses:
            features.add(feat)
    return features

