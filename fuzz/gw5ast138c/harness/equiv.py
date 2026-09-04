"""The equivalence checker -- the `E0` core (`spec-harness.md` §5, `P0.T23`).

Module rooting is fixed: this module is always addressed as
`fuzz.gw5ast138c.harness.equiv` and run from `$FL/apicula`; it never depends
on cwd -- the design directory is always passed explicitly via `--design-dir`.

What `E0` compares (`spec-harness.md` §5.1, `D32`): both `.fs` files go
through `gowin_unpack` for `GW5AST-138C` and the resulting netlists are
canonicalised into **three sets**, then diffed:

1. **Cells** -- `(tile_x, tile_y, bel_z, cell_type)`.
2. **Attributes** -- per cell, the `(attr_name, attr_value)` map *as the
   unpacker resolves it*, never raw fuse indices.
3. **Connectivity** -- per cell, `(port, net_id)` where the net id is the
   **sorted set of the net's endpoints**, so a net's identity is its endpoints
   and its route is not compared at `E0`.

Two rules this module implements literally because they are the difference
between a real verdict and a comfortable one:

* **Scope** (`D32`, F6): for a primitive row the comparison is restricted to
  `ShapeSpec.scope.tiles`.  A shape whose `primitive` is `None` has no defined
  scope, so `scope_of()` raises `ScopeUndefinedError` outside `--calibration`
  and such a shape may never produce a row with verdict `ok`.
* **Raw residual** (`D35`, §5.1b) is **mandatory and always printed**.  The
  unpacked comparison is blind to any fuse apicula does not model: such a bit
  is dropped on the vendor side during unpack and never emitted on the open
  side, so two genuinely different bitstreams can compare "identical" at the
  set level.  `raw_bit_delta()` therefore reads both `.fs` with
  `bslib.read_bitstream` and reports, per tile, every frame bit that differs,
  plus the bytes that live **outside** the fuse bitmap entirely (the vendor's
  comment header and its extra pre-fabric command words).  A non-empty,
  non-enumerated residual is a `DIFF`; nothing here hides it.
  `P0.T25` owns the richer `residual()` / `decode_check()` pair; this module
  owns only the raw differential report `E0` cannot be read without.

`load_mask()` (`P0.T24`) parses the checked-in `dontcare.mask` and enforces
§5.3 on it: five required keys per entry, the sixth only on the IO-default
entry, no `primitive:`-scoped entry, and the file's sha256 carried into every
evidence row so a result cannot be improved after the fact by widening the
mask.
"""
import argparse
import collections
import hashlib
import json
import os
import re
import sys
from dataclasses import dataclass, field

DEVICE = "GW5AST-138C"
DATASTORE = "/Users/alex/fine-line-data/open-toolchain-gw5ast"

#: Where each side's bitstream lives inside a design directory.  The vendor
#: path is `gw_sh`'s own (`create_project -name run` chdirs into `run/`,
#: artefacts land in `run/impl/pnr/`); the open flow writes beside the design.
VENDOR_FS = os.path.join("run", "impl", "pnr", "run.fs")
OPEN_FS = "top.fs"

#: Logs a failed build leaves behind, most specific first.
LOG_CANDIDATES = ("gowin_pack.log", "nextpnr.log", "yosys.log", "gw_sh.log")


class EquivError(Exception):
    """Anything the checker refuses to proceed on."""


class ScopeUndefinedError(EquivError):
    """A shape with no `primitive` was compared outside calibration mode (F6).

    There is no defined tile scope for such a shape, so the comparison would
    silently fall back to whole-design -- which `S6` admits only as a
    *calibration* criterion, because GowinSynthesis and yosys do not emit the
    same LUT4/DFF decomposition for a whole design.
    """


# --------------------------------------------------------------------------
# 1. The canonical data model
# --------------------------------------------------------------------------
Cell = collections.namedtuple("Cell", "x y z type")
Cell.__doc__ = "A canonical cell: `(tile_x, tile_y, bel_z, cell_type)`."


@dataclass
class Netlist:
    """One side of a comparison, already in canonical shape.

    `conns` maps a cell to `{port: net_label}` and `nets` maps a net label to
    the frozenset of its `(cell, port)` endpoints.  The labels themselves are
    never compared -- `canonicalise()` replaces each with a digest of its
    endpoint set, which is what makes a net's identity its endpoints.
    """

    cells: dict = field(default_factory=dict)   # Cell -> frozenset((k, v))
    conns: dict = field(default_factory=dict)   # Cell -> {port: net_label}
    nets: dict = field(default_factory=dict)    # net_label -> frozenset((Cell, port))
    pip_count: int = 0
    tile_bits: dict = field(default_factory=dict)  # (x, y) -> frozenset((r, c))
    source: str = ""


# --------------------------------------------------------------------------
# 2. The mask (§5.3, `P0.T24`)
# --------------------------------------------------------------------------
#: Where the checked-in mask lives.  `load_mask(None)` reads **this** file, so
#: no run can quietly compare against a mask that is not the reviewed one.
DEFAULT_MASK_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "dontcare.mask")

#: The five keys every entry must carry (§5.3: "Every entry carries a one-line
#: justification and a citation", plus the initials the third rule demands).
REQUIRED_MASK_KEYS = ("id", "levels", "justification", "citation", "initials")

#: The sixth key, required on the IO-default entry and forbidden on every
#: other one -- §5.3's "The IO-default entry is disabled for any run whose
#: shape is an IO or IOLOGIC primitive ... because there the default *is* the
#: thing under test."
SHAPE_CLASS_KEY = "disabled_for_shape_classes"
IO_DEFAULT_ENTRY_ID = "io_default_unused_pins"
IO_SHAPE_CLASSES = ("iob", "lvds", "iodelay", "iologic_mem")

#: The base set §5.3 admits without new evidence.  Phase 0 ships exactly these
#: six; a seventh entry is a Phase 1-5b decision, reviewed as a claim about
#: the hardware.
BASE_MASK_ENTRY_IDS = ("header_words", "crc_checksum_padding",
                       "unused_tile_fill", "free_placement", "net_route",
                       IO_DEFAULT_ENTRY_ID)

LEVELS = ("E0", "E1", "E2")


class MaskPolicyError(EquivError):
    """The mask file breaks a §5.3 rule.

    Raised, never warned: a mask entry is a claim about the hardware and an
    unreviewable one is worse than no mask at all.
    """


@dataclass(frozen=True)
class MaskEntry:
    """One reviewed don't-care, with the metadata that makes it checkable."""

    id: str
    levels: tuple
    justification: str
    citation: str
    initials: str
    disabled_for_shape_classes: tuple = None

    def applies_at(self, level):
        return level in self.levels

    def active_for(self, level, shape_class=None):
        """Does this entry apply for `level` and this shape class?

        The IO-default entry is switched **off** for an IO/IOLOGIC shape,
        because there the default is the thing under test (§5.3).
        """
        if not self.applies_at(level):
            return False
        disabled = self.disabled_for_shape_classes or ()
        return not (shape_class and shape_class in disabled)


@dataclass(frozen=True)
class Mask:
    """The parsed don't-care mask plus the sha256 every evidence row records."""

    entries: tuple = ()
    sha256: str = ""
    path: str = None

    def masks(self, kind, item, level="E0", shape_class=None):
        """Is `item` (of set `kind`) a don't-care?

        **`False` for every member of the three `E0` sets, by construction.**
        None of the six base entries names a cell, an attribute or a
        connection: header words and CRC words are not in the bitmap at all,
        unused-tile fill and defaulted IO are outside the shape's tile scope
        (`scope_of`, `D32`), free placement is what `E0` is defined not to
        compare and `E1` is defined to assert, and a route is never a verdict
        term.  A cell/attr/conn difference inside the scope is therefore
        always reported -- "An unmasked difference is a failure" (§5.3), and
        Phase 0 masks none of them.
        """
        return False

    def entry(self, entry_id):
        for e in self.entries:
            if e.id == entry_id:
                return e
        return None

    def active(self, level="E0", shape_class=None):
        """The entries in force for this comparison, in file order."""
        return tuple(e for e in self.entries
                     if e.active_for(level, shape_class))

    def explains(self, entry_id, level="E0", shape_class=None):
        """Is `entry_id` in force here?  Used to attribute a residual (§5.1b)."""
        entry = self.entry(entry_id)
        return entry is not None and entry.active_for(level, shape_class)

    @property
    def ids(self):
        return tuple(e.id for e in self.entries)

    @property
    def is_empty(self):
        return not self.entries


def _parse_mask_text(text, path):
    """`[entry]` blocks of `key: value` lines into a list of dicts.

    Deliberately dumb and diff-friendly: a mask is reviewed by reading it, so
    the file format is the one a reviewer can read without a parser.
    """
    blocks = []
    current = None
    for lineno, raw in enumerate(text.splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line == "[entry]":
            current = {}
            blocks.append(current)
            continue
        if current is None:
            raise MaskPolicyError(
                f"{path}:{lineno}: {line!r} outside any [entry] block")
        if ":" not in line:
            raise MaskPolicyError(
                f"{path}:{lineno}: {line!r} is not a `key: value` line")
        key, value = line.split(":", 1)
        key, value = key.strip(), value.strip()
        if key in current:
            raise MaskPolicyError(f"{path}:{lineno}: duplicate key {key!r}")
        current[key] = value
    return blocks


def load_mask(path=None):
    """Parse the don't-care mask and enforce §5.3's rules on it.

    `path=None` means the checked-in `dontcare.mask`; the sha256 returned is
    the file's, because every evidence row records it and "a result cannot be
    silently improved by widening the mask after the fact" (§5.3, last rule).

    Refuses (`MaskPolicyError`):

    * an entry carrying a `primitive:` key -- §5.3 rule 2, "A mask entry may
      never be scoped to a specific primitive row.  If a difference only ever
      appears for one primitive, it is a finding about that primitive, not a
      don't-care";
    * an entry missing any of the five required keys, or with an empty
      justification or citation -- §5.3, "Every entry carries a one-line
      justification and a citation";
    * `disabled_for_shape_classes` on anything but the IO-default entry, or
      missing from it;
    * a level outside E0/E1/E2, or a duplicate id.
    """
    if path is None:
        path = DEFAULT_MASK_PATH
    if not os.path.isfile(path):
        raise EquivError(f"no mask file {path}")
    with open(path, "rb") as f:
        blob = f.read()
    sha = hashlib.sha256(blob).hexdigest()

    entries = []
    seen = set()
    for block in _parse_mask_text(blob.decode(), path):
        if "primitive" in block:
            raise MaskPolicyError(
                f"{path}: entry {block.get('id', '<no id>')!r} is scoped to "
                f"primitive {block['primitive']!r}: a mask entry may never be "
                "scoped to a specific primitive row (spec-harness.md 5.3). A "
                "difference that only appears for one primitive is a finding "
                "about that primitive, not a don't-care.")
        missing = [k for k in REQUIRED_MASK_KEYS if not block.get(k)]
        if missing:
            raise MaskPolicyError(
                f"{path}: entry {block.get('id', '<no id>')!r} is missing or "
                f"empties {', '.join(missing)}; all of "
                f"{', '.join(REQUIRED_MASK_KEYS)} are required")
        entry_id = block["id"]
        if entry_id in seen:
            raise MaskPolicyError(f"{path}: duplicate entry id {entry_id!r}")
        seen.add(entry_id)

        levels = tuple(v.strip() for v in block["levels"].split(",") if v.strip())
        bad = [lv for lv in levels if lv not in LEVELS]
        if bad or not levels:
            raise MaskPolicyError(
                f"{path}: entry {entry_id!r} has levels {block['levels']!r}; "
                f"each must be one of {', '.join(LEVELS)}")

        shape_classes = block.get(SHAPE_CLASS_KEY)
        if entry_id == IO_DEFAULT_ENTRY_ID:
            if not shape_classes:
                raise MaskPolicyError(
                    f"{path}: the IO-default entry {entry_id!r} must carry "
                    f"{SHAPE_CLASS_KEY}: it is disabled for any IO/IOLOGIC "
                    "shape, because there the default is the thing under test "
                    "(spec-harness.md 5.3)")
        elif shape_classes:
            raise MaskPolicyError(
                f"{path}: entry {entry_id!r} carries {SHAPE_CLASS_KEY}, which "
                f"is admissible only on {IO_DEFAULT_ENTRY_ID!r}")

        extra = set(block) - set(REQUIRED_MASK_KEYS) - {SHAPE_CLASS_KEY}
        if extra:
            raise MaskPolicyError(
                f"{path}: entry {entry_id!r} carries unknown key(s) "
                f"{', '.join(sorted(extra))}")

        entries.append(MaskEntry(
            id=entry_id,
            levels=levels,
            justification=block["justification"],
            citation=block["citation"],
            initials=block["initials"],
            disabled_for_shape_classes=(
                tuple(v.strip() for v in shape_classes.split(",") if v.strip())
                if shape_classes else None),
        ))

    return Mask(entries=tuple(entries), sha256=sha, path=path)


# --------------------------------------------------------------------------
# 3. Scope
# --------------------------------------------------------------------------
def scope_of(spec, calibration=False):
    """The `ScopeSpec` a shape is compared under, or `None` in calibration.

    Raises `ScopeUndefinedError` for a null-`primitive` shape outside
    calibration mode (F6): no shape shipped in this epic is null-primitive, so
    this is a guard, not a path.
    """
    if getattr(spec, "primitive", None) is None:
        if not calibration:
            raise ScopeUndefinedError(
                f"shape {getattr(spec, 'name', '?')!r} has primitive=None: no "
                "tile scope is defined, so E0/E1/E2 is not admissible; "
                "whole-design comparison is a --calibration path only (F6, S6)")
        return None
    if calibration:
        return None
    return spec.scope


# --------------------------------------------------------------------------
# 4. Canonicalisation -- the three sets
# --------------------------------------------------------------------------
_BEL_SUFFIX = re.compile(r"^(?P<name>.*?)(?P<idx>\d+)?(?P<side>[A-Z])?$")
_LETTER_BELS = ("IOB", "IOLOGIC", "ODDR", "BUF")


def split_bel_name(name):
    """`'DFF3'` -> `('DFF', 3)`; `'IOBA'` -> `('IOB', 0)`; `'ALU'` -> `('ALU', 0)`.

    `bel_z` is the numeric site index inside the tile as apicula names it: a
    trailing digit run, or the `A`/`B` side letter the IO and IOLOGIC bels use.
    """
    m = _BEL_SUFFIX.match(name)
    base = m.group("name")
    idx = m.group("idx")
    side = m.group("side")
    if side is not None and base.startswith(_LETTER_BELS) and idx is None:
        return base, ord(side) - ord("A")
    if side is not None:
        base = base + (idx or "") + side
        return base, 0
    return base, int(idx) if idx is not None else 0


def canon_attr(flag):
    """A raw unpacker flag string -> `(attr_name, attr_value)`.

    The unpacker resolves a bel's fuses to strings, some already `K=V` shaped
    (`DEVICE="GW5AST-138C"`, `INIT=16'hFFFF`) and some bare mode names
    (`IBUF`, `SET`).  A bare flag is a set-valued attribute: its value is `1`.
    Raw fuse indices never appear here (§5.1 point 2).
    """
    if isinstance(flag, tuple):
        return (str(flag[0]), str(flag[1]))
    text = str(flag)
    if "=" in text:
        name, value = text.split("=", 1)
        return (name.strip(), value.strip())
    return (text, "1")


def net_id(endpoints):
    """A net's canonical identity: a digest of its **sorted endpoint set**.

    The label the two flows chose (`net_17` vs `$auto$4711`) never enters, and
    neither does the route: at `E0` a net *is* its endpoints (§5.1 point 3).
    """
    items = sorted(
        (c.x, c.y, c.z, c.type, port) for c, port in endpoints)
    blob = json.dumps(items, sort_keys=True).encode()
    return "net:" + hashlib.sha256(blob).hexdigest()[:16]


def in_scope(cell, scope):
    if scope is None:
        return True
    return (cell.x, cell.y) in {tuple(t) for t in scope.tiles}


def canonicalise(netlist, scope):
    """Return the three comparable sets for one side.

    * cells: `set[Cell]`
    * attrs: `set[(Cell, attr_name, attr_value)]`
    * conns: `set[(Cell, port, net_id)]`

    All three are restricted to `scope`; `scope=None` (calibration) compares
    the whole design.
    """
    cells = {c for c in netlist.cells if in_scope(c, scope)}
    attrs = set()
    if scope is None or scope.include_bel_attrs:
        for cell in cells:
            for flag in netlist.cells[cell]:
                name, value = canon_attr(flag)
                attrs.add((cell, name, value))
    conns = set()
    if scope is None or scope.include_port_nets:
        ids = {label: net_id(eps) for label, eps in netlist.nets.items()}
        for cell in cells:
            for port, label in netlist.conns.get(cell, {}).items():
                conns.add((cell, port, ids.get(label, "net:unrouted")))
    return cells, attrs, conns


# --------------------------------------------------------------------------
# 5. Unpacking a real bitstream into a Netlist
# --------------------------------------------------------------------------
def _reset_unpacker_state(gu):
    """Clear `gowin_unpack`'s module-level caches between two unpacks.

    They are keyed by nothing but call order (`_pll_cells`, `_bsram_cells`),
    so unpacking two bitstreams in one process without this would make the
    second side's cell indices depend on the first side's.
    """
    for name in ("_pll_cells", "_bsram_cells", "_bank_fuse_tables"):
        cache = getattr(gu, name, None)
        if isinstance(cache, dict):
            cache.clear()


def load_db(device=DEVICE):
    """Load the chipdb `gowin_unpack` itself would load (`importlib.resources`)."""
    import importlib.resources
    from apycula.chipdb import load_chipdb
    with importlib.resources.path("apycula", f"{device}.msgpack.xz") as path:
        return load_chipdb(path)


def unpack_netlist(fs_path, device=DEVICE, db=None, noalu=False):
    """`gowin_unpack` one `.fs` into a canonical `Netlist`.

    This calls the same functions `gowin_unpack.main()` calls, in the same
    order (banks first, so IO standards are known), and stops one step short
    of `tile2verilog` -- Verilog is `gowin_unpack`'s output format, not a
    comparable netlist (§5.4: there is no repack path, so the Verilog is a
    dead end for a diff).  `gowin_unpack.py` itself is **frozen** and not
    edited (§1 Frozen).
    """
    from apycula import chipdb as _chipdb
    from apycula import gowin_unpack as gu
    from apycula.bslib import read_bitstream

    if db is None:
        db = load_db(device)
    _reset_unpacker_state(gu)
    gu._device = device
    gu._pinout = db.pinout[device][gu._packages[device]]

    bitmap, _hdr, _ftr, _slots = read_bitstream(fs_path)
    bm = _chipdb.tile_bitmap(db, bitmap)

    netlist = Netlist(source=os.path.abspath(fs_path))
    bank_positions = set(db.bank_tiles.values())
    raw_pips = {}          # (row, col) -> {dest_global: src_global}

    def absorb(row, col, bels, pips, clock_pips):
        for name, flags in bels.items():
            cell_type, z = split_bel_name(name)
            cell = Cell(col, row, z, cell_type)
            netlist.cells[cell] = frozenset(flags)
        merged = {}
        for dest, src in list(pips.items()) + list(clock_pips.items()):
            merged[_chipdb.wire2global(row + 1, col + 1, db, dest)] = \
                _chipdb.wire2global(row + 1, col + 1, db, src)
        raw_pips[(row, col)] = merged
        netlist.pip_count += len(merged)

    for row, col in sorted(bank_positions):
        tile = bm.get((row, col))
        if tile is None:
            continue
        absorb(row, col, *gu.parse_tile_(db, row, col, tile, bm))

    for (row, col), tile in sorted(bm.items()):
        if (row, col) in bank_positions:
            continue
        bels, pips, clock_pips = gu.parse_tile_(db, row, col, tile, bm,
                                                noiostd=False)
        if noalu:
            gu.removeALUs(bels)
        else:
            gu.removeLUTs(bels)
        gu.ram16_remove_bels(bels)
        absorb(row, col, bels, pips, clock_pips)

    _build_nets(netlist, db, raw_pips)
    return netlist


class _UnionFind(dict):
    def find(self, x):
        root = x
        while self.get(root, root) != root:
            root = self[root]
        while self.get(x, x) != root:
            self[x], x = root, self[x]
        return root

    def union(self, a, b):
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self[rb] = ra


def _build_nets(netlist, db, raw_pips):
    """Group wires into nets by union-find over every pip, then attach ports.

    A net is a connected component of the pip graph; its endpoints are the
    `(cell, port)` pairs of the **used** cells whose portmap wires fall in that
    component.  The pips themselves are never compared -- their count is a
    statistic (`diff_count.pips`, `D32`).
    """
    uf = _UnionFind()
    for tile_pips in raw_pips.values():
        for dest, src in tile_pips.items():
            uf.setdefault(dest, dest)
            uf.setdefault(src, src)
            uf.union(src, dest)

    endpoints = collections.defaultdict(set)
    port_wire = {}
    for cell in netlist.cells:
        row, col = cell.y, cell.x
        try:
            tiledata = db[row, col]
        except Exception:
            continue
        bel = _find_bel(tiledata, cell)
        if bel is None:
            continue
        for port, wire in bel.portmap.items():
            if not isinstance(wire, str):
                continue
            g = db_wire2global(db, row, col, wire)
            root = uf.find(g) if g in uf else g
            endpoints[root].add((cell, port))
            port_wire[(cell, port)] = root

    netlist.nets = {root: frozenset(eps) for root, eps in endpoints.items()}
    for (cell, port), root in port_wire.items():
        netlist.conns.setdefault(cell, {})[port] = root


def db_wire2global(db, row, col, wire):
    from apycula import chipdb as _chipdb
    return _chipdb.wire2global(row + 1, col + 1, db, wire)


def _find_bel(tiledata, cell):
    """The chipdb `Bel` a canonical `Cell` came from, by re-forming its name."""
    for candidate in (f"{cell.type}{cell.z}",
                      f"{cell.type}{chr(ord('A') + cell.z)}",
                      cell.type):
        bel = tiledata.bels.get(candidate)
        if bel is not None:
            return bel
    return None


# --------------------------------------------------------------------------
# 6. The raw residual (`D35`, §5.1b) -- mandatory, never hidden
# --------------------------------------------------------------------------
def raw_bit_delta(vendor_fs, open_fs):
    """Every raw difference between the two `.fs`, whether or not it unpacks.

    Two layers, because the two blind spots are different:

    * **frame bits** -- `bslib.read_bitstream` gives the fuse bitmap; the
      symmetric difference is reported per tile-row so a residual has a place,
      never a byte offset (§5.2).
    * **outside the bitmap** -- everything `read_bitstream` discards: the
      vendor's `//` comment header and any command words one side emits and
      the other does not.  This is where a size difference between two
      set-identical bitstreams lives, and it is reported in bytes and lines.
    """
    from apycula.bslib import read_bitstream

    a_map, _, _, _ = read_bitstream(vendor_fs)
    b_map, _, _, _ = read_bitstream(open_fs)

    rows = min(len(a_map), len(b_map))
    per_row = {}
    total = 0
    for r in range(rows):
        ra, rb = a_map[r], b_map[r]
        width = min(len(ra), len(rb))
        n = int(sum(1 for c in range(width) if ra[c] != rb[c]))
        n += abs(len(ra) - len(rb))
        if n:
            per_row[r] = n
            total += n
    shape_delta = abs(len(a_map) - len(b_map))

    return {
        "frame_bits": total,
        "frame_rows": per_row,
        "bitmap_shape": [[len(a_map), len(a_map[0]) if len(a_map) else 0],
                         [len(b_map), len(b_map[0]) if len(b_map) else 0]],
        "bitmap_row_delta": shape_delta,
        "outside_bitmap": _outside_bitmap(vendor_fs, open_fs),
    }


def _outside_bitmap(vendor_fs, open_fs):
    """Bytes present in one file and absent from the other, outside the fuses.

    Enumerated, not summarised: a residual that is not enumerated is a `DIFF`
    (§5.1b), so the categories here are the justification, and each entry
    carries one.
    """
    out = {}
    for label, path in (("vendor", vendor_fs), ("open", open_fs)):
        comment_bytes = comment_lines = 0
        with open(path) as f:
            for line in f:
                if not line.startswith("//"):
                    break
                comment_lines += 1
                comment_bytes += len(line)
        out[label] = {
            "size_bytes": os.path.getsize(path),
            "comment_lines": comment_lines,
            "comment_bytes": comment_bytes,
        }
    out["size_delta_bytes"] = out["vendor"]["size_bytes"] - out["open"]["size_bytes"]
    out["comment_delta_bytes"] = (out["vendor"]["comment_bytes"]
                                  - out["open"]["comment_bytes"])
    out["unaccounted_bytes"] = out["size_delta_bytes"] - out["comment_delta_bytes"]
    out["justification"] = (
        "comment_delta_bytes: bitstream header comment block (tool version, "
        "device, date, checksum, user code) -- metadata, not configuration "
        "(spec-harness.md 5.3 row 1). unaccounted_bytes: command/preamble "
        "words one side emits and the other does not; enumerated by "
        "line_delta below and NOT masked at this stage (the mask is empty).")
    out["line_delta"] = _line_delta(vendor_fs, open_fs)
    return out


def _line_delta(vendor_fs, open_fs):
    """The non-comment lines one file has and the other does not, by length."""
    def data_lines(path):
        with open(path) as f:
            return [line.rstrip("\n") for line in f
                    if not line.startswith("//")]

    a, b = data_lines(vendor_fs), data_lines(open_fs)
    extra = []
    i = j = 0
    while i < len(a) and j < len(b):
        if a[i] == b[j]:
            i += 1
            j += 1
        elif len(a) - i > len(b) - j:
            extra.append({"side": "vendor", "line": i + 1, "bits": len(a[i]),
                          "prefix": a[i][:32]})
            i += 1
        elif len(b) - j > len(a) - i:
            extra.append({"side": "open", "line": j + 1, "bits": len(b[j]),
                          "prefix": b[j][:32]})
            j += 1
        else:
            i += 1
            j += 1
    for k in range(i, len(a)):
        extra.append({"side": "vendor", "line": k + 1, "bits": len(a[k]),
                      "prefix": a[k][:32]})
    for k in range(j, len(b)):
        extra.append({"side": "open", "line": k + 1, "bits": len(b[k]),
                      "prefix": b[k][:32]})
    return extra[:32]


# --------------------------------------------------------------------------
# 7. The comparison
# --------------------------------------------------------------------------
@dataclass
class E0Result:
    verdict: str = "EQUIV E0 ok"
    level: str = "E0"
    diff_count: dict = field(default_factory=lambda: {
        "cells": 0, "attrs": 0, "conns": 0, "pips": 0})
    first_diff: str = None
    log_path: str = None
    mask_sha256: str = ""
    mask_entries: tuple = ()
    residual: dict = field(default_factory=dict)
    per_tile: dict = field(default_factory=dict)
    notes: str = ""


def _describe(kind, item, vendor, open_):
    cell = item if isinstance(item, Cell) else item[0]
    if kind == "cell":
        return (f"tile ({cell.x},{cell.y}) bel {cell.z}: cell "
                f"vendor={vendor} open={open_}")
    return (f"tile ({cell.x},{cell.y}) bel {cell.z}: "
            f"{'attr' if kind == 'attr' else 'port'} vendor={vendor} open={open_}")


def _first_cell_diff(only_v, only_o):
    """The first differing cell, rendered as §5.2's line -- never a byte offset."""
    key = lambda c: (c.y, c.x, c.z, c.type)  # noqa: E731
    by_site_v = {(c.x, c.y, c.z): c for c in only_v}
    for cell in sorted(only_o, key=key):
        site = (cell.x, cell.y, cell.z)
        if site in by_site_v:
            return _describe("cell", cell, by_site_v[site].type, cell.type)
    for cell in sorted(only_v, key=key):
        return _describe("cell", cell, cell.type, "<absent>")
    for cell in sorted(only_o, key=key):
        return _describe("cell", cell, "<absent>", cell.type)
    return None


def compare_e0(vendor, open_, scope=None, mask=None, residual=None):
    """Diff two canonical netlists as the three `E0` sets.

    Routing is never a verdict term: `diff_count.pips` is filled and printed
    as a statistic (`D32`).  A non-empty, non-enumerated raw residual makes
    the verdict `DIFF` (`D35`) even when all three sets match -- that is the
    whole point of §5.1b.
    """
    mask = mask if mask is not None else load_mask(None)
    cells_v, attrs_v, conns_v = canonicalise(vendor, scope)
    cells_o, attrs_o, conns_o = canonicalise(open_, scope)

    only_cv, only_co = cells_v - cells_o, cells_o - cells_v
    only_av, only_ao = attrs_v - attrs_o, attrs_o - attrs_v
    only_nv, only_no = conns_v - conns_o, conns_o - conns_v

    result = E0Result(mask_sha256=mask.sha256, mask_entries=mask.ids)
    # Counted **by key, not by set element**: a cell whose type changed at one
    # site is ONE differing cell, not one missing plus one added.  The key of a
    # cell is its site `(x, y, z)`, of an attribute `(cell, attr_name)`, of a
    # connection `(cell, port)`.
    result.diff_count = {
        "cells": len({(c.x, c.y, c.z) for c in only_cv | only_co}),
        "attrs": len({(a[0], a[1]) for a in only_av | only_ao}),
        "conns": len({(n[0], n[1]) for n in only_nv | only_no}),
        "pips": abs(vendor.pip_count - open_.pip_count),
    }

    per_tile = collections.defaultdict(
        lambda: {"cells": 0, "attrs": 0, "conns": 0})
    for kind, items in (("cells", only_cv | only_co),
                        ("attrs", only_av | only_ao),
                        ("conns", only_nv | only_no)):
        for item in items:
            cell = item if isinstance(item, Cell) else item[0]
            per_tile[(cell.x, cell.y)][kind] += 1
    result.per_tile = {f"({x},{y})": counts
                       for (x, y), counts in sorted(per_tile.items())}

    result.first_diff = _first_cell_diff(only_cv, only_co)
    if result.first_diff is None and (only_av or only_ao):
        cell, name, value = sorted(
            only_av or only_ao,
            key=lambda a: (a[0].y, a[0].x, a[0].z, a[1]))[0]
        other = next((v for c, n, v in (only_ao if only_av else only_av)
                      if c == cell and n == name), "<absent>")
        result.first_diff = _describe(
            "attr", (cell,), f"{name}={value}" if only_av else f"{name}={other}",
            f"{name}={other}" if only_av else f"{name}={value}")
    if result.first_diff is None and (only_nv or only_no):
        cell, port, net = sorted(
            only_nv or only_no,
            key=lambda a: (a[0].y, a[0].x, a[0].z, a[1]))[0]
        other = next((n for c, p, n in (only_no if only_nv else only_nv)
                      if c == cell and p == port), "<absent>")
        result.first_diff = _describe(
            "port", (cell,), f"{port}->{net}" if only_nv else f"{port}->{other}",
            f"{port}->{other}" if only_nv else f"{port}->{net}")

    if residual is not None:
        result.residual = residual

    sets_differ = any(result.diff_count[k] for k in ("cells", "attrs", "conns"))
    if sets_differ:
        result.verdict = "DIFF"
    elif _residual_is_dirty(result.residual):
        result.verdict = "DIFF"
        result.notes = ("sets identical after the mask, but the raw residual "
                        "of spec-harness.md 5.1b is non-empty (D35)")
    else:
        result.verdict = "EQUIV E0 ok"
    return result


def _residual_is_dirty(residual):
    """`True` when §5.1b's residual is non-empty and not fully enumerated.

    At this stage the mask is empty, so *any* frame-bit delta is dirty, and an
    outside-the-bitmap delta is dirty unless every byte of it is attributed to
    an enumerated category.
    """
    if not residual:
        return False
    if residual.get("frame_bits"):
        return True
    if residual.get("bitmap_row_delta"):
        return True
    outside = residual.get("outside_bitmap") or {}
    return bool(outside.get("unaccounted_bytes"))


# --------------------------------------------------------------------------
# 8. Verdict printing (§5.2)
# --------------------------------------------------------------------------
def verdict_line(result):
    """The single verdict string; `DIFF` carries the first differing item."""
    if result.verdict == "ABORT":
        return f"ABORT build failed; log={result.log_path}"
    if result.verdict == "DIFF":
        head = "DIFF"
        if result.first_diff:
            head += f" {result.first_diff}"
        return head
    return f"EQUIV {result.level} ok"


def report(result):
    """The full human report: verdict, counts by category, per tile, residual.

    `pips` is printed on its own line and labelled a statistic, so it can
    never be read as a verdict term (`D32`).  The residual is printed
    unconditionally, including when it is empty (`D35`).
    """
    lines = [verdict_line(result)]
    if result.verdict == "ABORT":
        return lines
    dc = result.diff_count
    lines.append(f"DIFF_COUNT cells={dc['cells']} attrs={dc['attrs']} "
                 f"conns={dc['conns']}")
    lines.append(f"PIPS diff={dc['pips']} (statistic, never a verdict term)")
    if result.per_tile:
        for tile, counts in result.per_tile.items():
            lines.append(f"PER_TILE {tile} cells={counts['cells']} "
                         f"attrs={counts['attrs']} conns={counts['conns']}")
    else:
        lines.append("PER_TILE (none)")
    res = result.residual or {}
    lines.append(f"RESIDUAL frame_bits={res.get('frame_bits', 0)} "
                 f"bitmap_row_delta={res.get('bitmap_row_delta', 0)} "
                 f"rows={sorted((res.get('frame_rows') or {}).items())[:8]}")
    outside = res.get("outside_bitmap") or {}
    if outside:
        lines.append(
            f"RESIDUAL_OUTSIDE size_delta_bytes={outside.get('size_delta_bytes')} "
            f"comment_delta_bytes={outside.get('comment_delta_bytes')} "
            f"unaccounted_bytes={outside.get('unaccounted_bytes')}")
        for entry in outside.get("line_delta", []):
            lines.append(f"RESIDUAL_LINE side={entry['side']} "
                         f"line={entry['line']} bits={entry['bits']} "
                         f"prefix={entry['prefix']}")
    lines.append(f"MASK sha256={result.mask_sha256} "
                 f"entries={len(result.mask_entries)} "
                 f"[{','.join(result.mask_entries)}]")
    if result.notes:
        lines.append(f"NOTE {result.notes}")
    return lines


def evidence_rows(result, run_id="equiv", primitive=None, shape=None):
    """The evidence-row fragments this comparison contributes (§6 schema).

    An `ABORT` yields a row marked `aborted`; it is **never** silently retried
    into a clean-looking result (§5.2).
    """
    verdict = {"EQUIV E0 ok": "ok", "DIFF": "diff", "ABORT": "aborted"}[
        result.verdict]
    return [{
        "run_id": run_id,
        "primitive": primitive,
        "shape": shape,
        "level": result.level,
        "verdict": verdict,
        "diff_count": result.diff_count,
        "first_diff": result.first_diff,
        "unexplained_bits": result.residual,
        "mask_sha256": result.mask_sha256,
        "mask_entries": list(result.mask_entries),
        "oracle_log": result.log_path,
        "notes": result.notes,
    }]


# --------------------------------------------------------------------------
# 9. Driving a real design directory
# --------------------------------------------------------------------------
def find_log(design_dir):
    for name in LOG_CANDIDATES:
        path = os.path.join(design_dir, name)
        if os.path.isfile(path):
            return path
    return design_dir


def load_spec(shape, design_dir):
    """The `ShapeSpec` for this run: `--shape` if given, else inferred.

    The design directory *is* the shape's identity in this harness -- the
    oracle and the open flow both write into `$DATASTORE/<slug>` -- so
    `oracle-smoke` resolves to the shape `smoke`.  Inference is deliberate,
    not a convenience: an unscoped `E0` would silently become the whole-design
    comparison `S6` admits only as calibration (`D32`, F6), so the caller must
    end up with either a real scope or a refusal, never a quiet fallback.
    """
    from .gen import load_shape

    names = []
    if shape:
        names.append(shape)
    else:
        base = os.path.basename(design_dir.rstrip(os.sep))
        names.append(base)
        for prefix in ("oracle-", "open-", "equiv-"):
            if base.startswith(prefix):
                names.append(base[len(prefix):])
    for name in names:
        try:
            return load_shape(name)
        except ImportError:
            continue
    if shape:
        raise EquivError(f"no shape module fuzz.gw5ast138c.shapes.{shape}")
    return None


def compare_design(design_dir, shape=None, level="E0", mask_path=None,
                   calibration=False, device=DEVICE, vendor_fs=None,
                   open_fs=None):
    """Compare the two bitstreams of one design directory at `E0`.

    `ABORT` when either build is missing: the log path is printed and the row
    is marked `aborted` (§5.2).
    """
    design_dir = os.path.abspath(design_dir)
    vendor = vendor_fs or os.path.join(design_dir, VENDOR_FS)
    open_ = open_fs or os.path.join(design_dir, OPEN_FS)
    mask = load_mask(mask_path)

    missing = [p for p in (vendor, open_) if not os.path.isfile(p)]
    if missing:
        return E0Result(verdict="ABORT", level=level,
                        log_path=find_log(design_dir), mask_sha256=mask.sha256,
                        mask_entries=mask.ids,
                        notes="missing bitstream(s): " + ", ".join(missing))

    spec = load_spec(shape, design_dir)
    if spec is None:
        if not calibration:
            raise ScopeUndefinedError(
                f"no shape resolves for design dir {design_dir!r} and none was "
                "given with --shape: without a ShapeSpec there is no tile "
                "scope, and whole-design E0 is a --calibration path only "
                "(D32, F6, S6)")
        scope = None
    else:
        scope = scope_of(spec, calibration=calibration)

    db = load_db(device)
    nl_v = unpack_netlist(vendor, device=device, db=db)
    nl_o = unpack_netlist(open_, device=device, db=db)
    residual = raw_bit_delta(vendor, open_)
    result = compare_e0(nl_v, nl_o, scope=scope, mask=mask, residual=residual)
    result.level = level
    return result


# --------------------------------------------------------------------------
# 10. CLI
# --------------------------------------------------------------------------
def build_parser():
    """Return this module's argparse parser.

    Every harness module parser carries a required `--design-dir` so no
    harness command depends on the current working directory
    (`spec-harness.md` §1, `spec.md` V5/V6).  The remaining flags are the ones
    `V5` passes.
    """
    parser = argparse.ArgumentParser(prog="fuzz.gw5ast138c.harness.equiv")
    parser.add_argument(
        "--design-dir",
        required=True,
        help="Directory holding the test design for this run (never inferred from cwd).",
    )
    parser.add_argument("--design", default=None,
                        help="Design/base name; `top` for the open flow.")
    parser.add_argument("--board", default="tangmega138k")
    parser.add_argument("--makefile-recipe", default=None,
                        help="Makefile recipe that built the open-flow side, "
                             "recorded in the row; never invoked here.")
    parser.add_argument("--shape", default=None,
                        help="Shape name; its ScopeSpec restricts the compare.")
    parser.add_argument("--mask", default=None,
                        help="Path to dontcare.mask; default is the checked-in one.")
    parser.add_argument("--calibration", action="store_true",
                        help="Whole-design comparison (S6 calibration only).")
    parser.add_argument("--level", default="E0", choices=["E0", "E1", "E2"])
    parser.add_argument("--json", action="store_true")
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    if args.level != "E0":
        raise EquivError(
            f"--level {args.level} is P0.T26's (level_e1/level_e2); "
            "P0.T23 implements E0 only")
    result = compare_design(args.design_dir, shape=args.shape,
                            level=args.level, mask_path=args.mask,
                            calibration=args.calibration)
    for line in report(result):
        print(line)
    if args.json:
        print(json.dumps(evidence_rows(result), sort_keys=True, default=str))
    return 0 if result.verdict.startswith("EQUIV") else 1


if __name__ == "__main__":
    sys.exit(main())
