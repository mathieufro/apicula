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
    #: `(row, col) -> {dest_global: src_global}`, kept because `E2`'s pip-set
    #: identity (`P0.T26`) needs a net's pips, not just their count.
    raw_pips: dict = field(default_factory=dict)
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
    for name in ("_pll_cells", "_bsram_cells", "_bank_fuse_tables",
                 "_lvds_out_alias_cache"):
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
        netlist.raw_pips[(row, col)] = merged
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
# 6b. `residual()` and `decode_check()` (`D35`, `D34`, `P0.T25`)
# --------------------------------------------------------------------------
#: Categories a differing frame bit can land in.  The first three are
#: **subtracted** by §5.1b ("every bit either unpacker accounted for is
#: subtracted"); the last three are not, and are what `unexplained_bits`
#: enumerates.
RESIDUAL_CATEGORIES = {
    "set_level_diff": (
        "both unpackers produced cells in this tile and their cell/attr sets "
        "differ: the difference is visible to the E0 set comparison, so the "
        "bits are accounted for (spec-harness.md 5.1b)"),
    "vendor_only_fill": (
        "the vendor unpacks cells here and the open side unpacks none: "
        "unused-tile fill, not configuration of any instantiated cell "
        "(spec-harness.md 5.3 row 3, mask entry unused_tile_fill)"),
    "open_only_fill": (
        "the open side unpacks cells here and the vendor unpacks none: the "
        "mirror image of unused-tile fill, same mask entry"),
    "unmodelled_fuse": (
        "BOTH unpackers produced the SAME cells and attributes in this tile "
        "and the raw bits still differ: a fuse apicula does not model at all, "
        "dropped on both sides during unpack. This is exactly the blind spot "
        "D35 exists to catch and it is NOT masked"),
    "unattributed_tile": (
        "bits differ in a tile in which NEITHER side unpacks any cell: no "
        "cell accounts for them (spec-harness.md 5.1c's named-error case)"),
    "outside_every_tile": (
        "differing bits in the fuse bitmap that fall outside every tile the "
        "chipdb grid describes -- inter-tile padding the unpacker never reads"),
    "extra_command_words": (
        "whole command/preamble words one side emits and the other does not, "
        "outside the fuse bitmap and outside the `//` comment block, so "
        "neither the header-words nor the CRC mask entry covers them"),
}

#: Bels a nextpnr post-PnR netlist can name that leave no **bel** fuse for
#: `gowin_unpack` to recover, so `c1` must not require them.  `VCC`/`GND` are
#: the packer's constant drivers and `GSR`/`PINCFG` are whole-device config
#: sites, none of which is a placed cell; `BUFG` is a clock-routing mux, and
#: apicula recovers it as a pip, not as a bel (`gowin_unpack.py` returns it in
#: `clock_pips`), so requiring it as a cell would assert something the decode
#: does not claim to produce.  Measured on the smoke pair, 2026-09-04.
NON_FUSE_BACKED_BELS = ("VCC", "GND", "GSR", "PINCFG", "BUFG")


def cells_by_tile(netlist):
    """`{(row, col): frozenset((z, type, attrs))}` -- one side, per tile."""
    out = {}
    for cell, attrs in netlist.cells.items():
        out.setdefault((cell.y, cell.x), set()).add((cell.z, cell.type, attrs))
    return {k: frozenset(v) for k, v in out.items()}


def tile_delta_from_tiles(tiles_v, tiles_o):
    """`({(row, col): differing_bits}, total)` for two already-split grids.

    Split out from `tile_bit_delta` so the classifier can be exercised on a
    hand-built grid: a bitstream compared with itself must produce `({}, 0)`.
    """
    per_tile = {}
    total = 0
    for key, a in tiles_v.items():
        b = tiles_o.get(key)
        if b is None:
            continue
        n = 0
        for ra, rb in zip(a, b):
            n += sum(1 for x, y in zip(ra, rb) if x != y)
        if n:
            per_tile[key] = n
            total += n
    return per_tile, total


def tile_bit_delta(bitmap_v, bitmap_o, db):
    """Differing fuse bits per `(row, col)` tile, plus the ones in no tile.

    `chipdb.tile_bitmap` is the same grid split `gowin_unpack` itself uses, so
    "which tile is this bit in" is answered exactly as the unpacker answers
    it, never by a byte offset (§5.2).
    """
    from apycula import chipdb as _chipdb

    return tile_delta_from_tiles(
        _chipdb.tile_bitmap(db, bitmap_v, empty=True),
        _chipdb.tile_bitmap(db, bitmap_o, empty=True))


def classify_residual(tile_delta, cells_v, cells_o, outside_every_tile=0,
                      outside=None, mask=None, level="E0", shape_class=None):
    """Split every differing bit into "accounted for" and `unexplained_bits`.

    §5.1b, literally: *"every bit either unpacker accounted for is subtracted;
    the residual must be empty or fully enumerated in the evidence row as
    `unexplained_bits`, each entry carrying a justification. A non-empty,
    non-enumerated residual is a `DIFF`. No row closes at E0, E1 or E2 with an
    unexplained residual."*

    A bit is **accounted for** when some cell either unpacker produced was
    decoded from it -- which is the case in every tile where at least one side
    unpacks a cell.  Unused-tile fill is such a case and is additionally named
    by §5.3 row 3's mask entry, so it is reported with that entry's id rather
    than silently dropped.  What is left over is what no cell explains, and it
    is enumerated by category with the justification each category carries.
    """
    mask = mask if mask is not None else load_mask(None)
    fill_entry = ("unused_tile_fill"
                  if mask.explains("unused_tile_fill", level, shape_class)
                  else None)

    buckets = collections.defaultdict(lambda: {"bits": 0, "tiles": []})
    for tile, bits in sorted(tile_delta.items()):
        v, o = cells_v.get(tile, frozenset()), cells_o.get(tile, frozenset())
        if v and o:
            cat = "set_level_diff" if v != o else "unmodelled_fuse"
        elif v:
            cat = "vendor_only_fill"
        elif o:
            cat = "open_only_fill"
        else:
            cat = "unattributed_tile"
        bucket = buckets[cat]
        bucket["bits"] += bits
        if len(bucket["tiles"]) < 16:
            bucket["tiles"].append(f"({tile[1]},{tile[0]})")

    if outside_every_tile:
        buckets["outside_every_tile"]["bits"] += outside_every_tile

    outside = outside or {}
    unaccounted = abs(outside.get("unaccounted_bytes", 0) or 0)
    header_masked = mask.explains("header_words", level, shape_class)

    explained, unexplained = [], []
    for cat, bucket in buckets.items():
        row = {"category": cat, "bits": bucket["bits"],
               "tiles": len([t for t in tile_delta
                             if _category_of(t, cells_v, cells_o) == cat]),
               "sample_tiles": bucket["tiles"],
               "justification": RESIDUAL_CATEGORIES[cat]}
        if cat in ("set_level_diff", "vendor_only_fill", "open_only_fill"):
            if cat != "set_level_diff" and fill_entry:
                row["mask_entry"] = fill_entry
            explained.append(row)
        else:
            unexplained.append(row)

    if outside.get("comment_delta_bytes"):
        explained.append({
            "category": "comment_header",
            "bytes": abs(outside["comment_delta_bytes"]),
            "mask_entry": "header_words" if header_masked else None,
            "justification": (
                "the `//` comment block bslib.read_bitstream discards before "
                "the fuse bitmap exists: tool version, device, date, checksum, "
                "user code -- metadata, not configuration "
                "(spec-harness.md 5.3 row 1)"),
        })
    if unaccounted:
        unexplained.append({
            "category": "extra_command_words",
            "bytes": unaccounted,
            "lines": outside.get("line_delta", [])[:8],
            "justification": RESIDUAL_CATEGORIES["extra_command_words"],
        })

    order = list(RESIDUAL_CATEGORIES)
    key = lambda r: order.index(r["category"]) if r["category"] in order else 99  # noqa: E731
    explained.sort(key=key)
    unexplained.sort(key=key)
    return {
        "unexplained_bits": unexplained,
        "explained": explained,
        "unexplained_total_bits": sum(r.get("bits", 0) for r in unexplained),
        "unexplained_total_bytes": sum(r.get("bytes", 0) for r in unexplained),
        "mask_sha256": mask.sha256,
    }


def _category_of(tile, cells_v, cells_o):
    v, o = cells_v.get(tile, frozenset()), cells_o.get(tile, frozenset())
    if v and o:
        return "set_level_diff" if v != o else "unmodelled_fuse"
    if v:
        return "vendor_only_fill"
    if o:
        return "open_only_fill"
    return "unattributed_tile"


def residual(vendor_fs, open_fs, db=None, nl_v=None, nl_o=None, mask=None,
             level="E0", shape_class=None, device=DEVICE):
    """§5.1b's mandatory raw residual, computed on the two real `.fs`.

    Returns `raw_bit_delta()`'s enumeration plus the `unexplained_bits` list
    the evidence row must carry.  It is **always** computed: the unpacked
    comparison is blind to any fuse apicula does not model, so a row that
    closed on the three sets alone could be reporting `ok` for two bitstreams
    that differ (`D35`).
    """
    from apycula.bslib import read_bitstream

    if db is None:
        db = load_db(device)
    bmv, _, _, _ = read_bitstream(vendor_fs)
    bmo, _, _, _ = read_bitstream(open_fs)

    rows = min(len(bmv), len(bmo))
    total = 0
    per_row = {}
    for r in range(rows):
        ra, rb = bmv[r], bmo[r]
        width = min(len(ra), len(rb))
        n = int(sum(1 for c in range(width) if ra[c] != rb[c]))
        n += abs(len(ra) - len(rb))
        if n:
            per_row[r] = n
            total += n

    tile_delta, in_tiles = tile_bit_delta(bmv, bmo, db)
    if nl_v is None:
        nl_v = unpack_netlist(vendor_fs, device=device, db=db)
    if nl_o is None:
        nl_o = unpack_netlist(open_fs, device=device, db=db)

    out = {
        "frame_bits": total,
        "frame_rows": per_row,
        "frame_bits_in_tiles": in_tiles,
        "bitmap_shape": [[len(bmv), len(bmv[0]) if len(bmv) else 0],
                         [len(bmo), len(bmo[0]) if len(bmo) else 0]],
        "bitmap_row_delta": abs(len(bmv) - len(bmo)),
        "outside_bitmap": _outside_bitmap(vendor_fs, open_fs),
        "cells": {"vendor": len(nl_v.cells), "open": len(nl_o.cells)},
    }
    out.update(classify_residual(
        tile_delta, cells_by_tile(nl_v), cells_by_tile(nl_o),
        outside_every_tile=total - in_tiles + out["bitmap_row_delta"],
        outside=out["outside_bitmap"], mask=mask, level=level,
        shape_class=shape_class))
    return out


# --- the two-part decode check (`D34`, §5.4) -------------------------------
def read_pnr_cells(pnr_path):
    """The placed cells of a nextpnr post-PnR JSON, as `(x, y, bel)` sites.

    A `.fs` -> `.fs` byte round-trip does not exist (§5.4: `gowin_unpack`
    emits Verilog, `gowin_pack` consumes this JSON), so this file -- not a
    repack -- is what `c1` checks the decode against.
    """
    with open(pnr_path) as f:
        design = json.load(f)
    cells = []
    for mod in design.get("modules", {}).values():
        for name, cell in mod.get("cells", {}).items():
            attrs = cell.get("attributes", {}) or {}
            bel = attrs.get("NEXTPNR_BEL")
            if not bel:
                cells.append({"name": name, "type": cell.get("type"),
                              "bel": None, "site": None, "attrs": attrs,
                              "params": cell.get("parameters", {}) or {}})
                continue
            site, belname = bel.split("/", 1)
            x = int(site[1:site.index("Y")])
            y = int(site[site.index("Y") + 1:])
            cells.append({"name": name, "type": cell.get("type"), "bel": belname,
                          "site": (x, y), "attrs": attrs,
                          "params": cell.get("parameters", {}) or {}})
    return cells


def _expected_attrs(cell):
    """`{name: value}` a placed cell asserts, from `&NAME=VALUE` and params."""
    want = {}
    for key, value in cell["attrs"].items():
        if key.startswith("&") and "=" in key:
            name, val = key[1:].split("=", 1)
            want[name] = val
    for key, value in cell["params"].items():
        if isinstance(value, str):
            want[key] = value
    return want


def decode_check_c1(pnr_cells, netlist):
    """`c1` -- does the decode recover every cell the placement contains?

    Required set = every placed cell whose bel is fuse-backed.  A packer
    pseudo-bel (`NON_FUSE_BACKED_BELS`) and a cell nextpnr never placed leave
    no fuse behind, so requiring them would make `c1` assert something the
    bitstream format cannot carry; both are listed, never silently dropped.
    """
    by_site = collections.defaultdict(dict)
    for cell, attrs in netlist.cells.items():
        by_site[(cell.x, cell.y)][(cell.type, cell.z)] = attrs

    required, skipped, missing, attr_mismatch = [], [], [], []
    for cell in pnr_cells:
        if cell["bel"] is None:
            skipped.append({"name": cell["name"], "type": cell["type"],
                            "why": "not placed on any bel"})
            continue
        base, z = split_bel_name(cell["bel"])
        if base in NON_FUSE_BACKED_BELS:
            skipped.append({"name": cell["name"], "type": cell["type"],
                            "bel": cell["bel"], "why": "pseudo-bel, no fuse"})
            continue
        required.append(cell)
        site = by_site.get(cell["site"], {})
        attrs = site.get((base, z))
        if attrs is None:
            missing.append({"name": cell["name"], "type": cell["type"],
                            "bel": cell["bel"], "site": list(cell["site"])})
            continue
        have = dict(canon_attr(f) for f in attrs)
        for name, value in _expected_attrs(cell).items():
            if name in have and str(have[name]) != str(value):
                attr_mismatch.append({
                    "name": cell["name"], "attr": name,
                    "expected": value, "recovered": str(have[name])})

    return {
        "c1": "ok" if not missing and not attr_mismatch else "mismatch",
        "required_cells": len(required),
        "recovered_cells": len(required) - len(missing),
        "missing": missing[:16],
        "attr_mismatch": attr_mismatch[:16],
        "skipped": skipped,
    }


def _bitmap_bytes(bitmap):
    """The fuse bitmap as bytes, so "byte-identical" is literally that."""
    from apycula import bitmatrix

    packed = bitmatrix.packbits(bitmap, axis=1)
    if hasattr(packed, "tobytes"):
        return packed.tobytes()
    return bytes(v for row in packed for v in row)


def decode_check_c2(fs_path, tmp_path=None):
    """`c2` -- read the packed `.fs`, re-emit it, assert the bitmap is identical.

    This is what "catches encode/decode asymmetry" can actually mean against
    the shipped tools (§5.4): there is no repack path, but `bslib` owns both
    directions of the *bitmap*, so a round-trip through it is runnable and is
    a real assertion about the encoder.
    """
    import tempfile

    from apycula import bitmatrix
    from apycula.bslib import read_bitstream, write_bitstream

    bs, hdr, ftr, slots = read_bitstream(fs_path)
    tmp = tmp_path or os.path.join(tempfile.mkdtemp(prefix="equiv-c2-"),
                                   "roundtrip.fs")
    # `read_bitstream` returns `transpose(fliplr(lines))` for the 5A series and
    # `write_bitstream` writes `fliplr(bs)` as its lines, so the inverse of the
    # read is a single transpose.  `write_bitstream` mutates `hdr`, so it gets
    # copies.
    write_bitstream(tmp, bitmatrix.transpose(bs),
                    [bytearray(x) for x in hdr], [bytearray(x) for x in ftr],
                    False, slots)
    again, _, _, _ = read_bitstream(tmp)

    a, b = _bitmap_bytes(bs), _bitmap_bytes(again)
    differing = sum(1 for x, y in zip(a, b) if x != y) + abs(len(a) - len(b))
    return {"c2": "ok" if a == b else "mismatch",
            "bitmap_bytes": len(a),
            "differing_bytes": differing,
            "roundtrip_path": tmp}


def decode_check(open_fs, pnr_path, netlist=None, db=None, device=DEVICE,
                 tmp_path=None):
    """§5.4's two runnable halves, both required: `{c1: ..., c2: ...}`."""
    if netlist is None:
        netlist = unpack_netlist(open_fs, device=device, db=db, noalu=True)
    c1 = decode_check_c1(read_pnr_cells(pnr_path), netlist)
    c2 = decode_check_c2(open_fs, tmp_path=tmp_path)
    out = {"c1": c1["c1"], "c2": c2["c2"]}
    out.update({f"c1_{k}": v for k, v in c1.items() if k != "c1"})
    out.update({f"c2_{k}": v for k, v in c2.items() if k != "c2"})
    return out


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
    decode_check: dict = field(default_factory=dict)
    per_tile: dict = field(default_factory=dict)
    #: `P0.T26`'s two level payloads: `level_e1()`'s placement report and
    #: `level_e2()`'s single-legal-path pip-set fraction.
    e1: dict = field(default_factory=dict)
    e2: dict = field(default_factory=dict)
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
    if "unexplained_bits" in residual:
        # `P0.T25`'s classified residual: what the two unpackers accounted for
        # has already been subtracted, so anything still listed is a bit no
        # cell explains -- "No row closes at E0, E1 or E2 with an unexplained
        # residual" (§5.1b).
        return bool(residual["unexplained_bits"])
    # `raw_bit_delta()`'s unclassified shape (`P0.T23`): nothing is subtracted,
    # so any delta at all is dirty.
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
    if "unexplained_bits" in res:
        unexplained = res["unexplained_bits"]
        lines.append(
            f"RESIDUAL_UNEXPLAINED entries={len(unexplained)} "
            f"bits={res.get('unexplained_total_bits', 0)} "
            f"bytes={res.get('unexplained_total_bytes', 0)}")
        for row in unexplained:
            lines.append(
                f"  UNEXPLAINED {row['category']} "
                f"bits={row.get('bits', 0)} bytes={row.get('bytes', 0)} "
                f"tiles={row.get('tiles', 0)} :: {row['justification']}")
        for row in res.get("explained", []):
            lines.append(
                f"  ACCOUNTED {row['category']} bits={row.get('bits', 0)} "
                f"bytes={row.get('bytes', 0)} tiles={row.get('tiles', 0)} "
                f"mask_entry={row.get('mask_entry')}")
    if result.e1:
        e1 = result.e1
        lines.append(
            f"E1 placement level={e1['level']} constrained={e1['checked']} "
            f"matched={len(e1['matched'])} mismatched={len(e1['mismatched'])} "
            f"unobserved={len(e1['unobserved'])}")
        for row in e1["mismatched"][:8]:
            lines.append(f"  E1_MISMATCH \"{row['name']}\" "
                         f"exported={row['exported']} "
                         f"realised={row['realised']}")
        for row in e1["unobserved"][:8]:
            lines.append(f"  E1_UNOBSERVED \"{row['name']}\" "
                         f"exported={row['exported']} "
                         f"in_scope={row['in_scope']} in_vo={row['in_vo']}")
    if result.e2:
        e2 = result.e2
        lines.append(
            f"E2 single_path_nets candidates={e2['candidates']} "
            f"identical={e2['identical']} fraction={e2['fraction']:.3f} "
            "(bonus, never a done criterion)")
        for row in e2["nets"][:8]:
            lines.append(f"  E2_NET class={row['class']} "
                         f"identical={row['identical']} "
                         f"vendor_pips={row['vendor_pips']} "
                         f"open_pips={row['open_pips']}")
        if e2["note"]:
            lines.append(f"  E2_NOTE {e2['note']}")
    if result.decode_check:
        dc = result.decode_check
        lines.append(f"DECODE_CHECK c1={dc.get('c1')} c2={dc.get('c2')} "
                     f"(c1 recovered {dc.get('c1_recovered_cells')}/"
                     f"{dc.get('c1_required_cells')} placed cells, "
                     f"{len(dc.get('c1_skipped') or [])} not fuse-backed; "
                     f"c2 {dc.get('c2_differing_bytes')} differing bytes of "
                     f"{dc.get('c2_bitmap_bytes')})")
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
    verdict = {"EQUIV E0 ok": "ok", "EQUIV E1 ok": "ok",
               "EQUIV E2 ok": "ok", "DIFF": "diff", "ABORT": "aborted"}[
        result.verdict]
    return [{
        "run_id": run_id,
        "primitive": primitive,
        "shape": shape,
        "level": result.level,
        "verdict": verdict,
        "diff_count": result.diff_count,
        "first_diff": result.first_diff,
        "unexplained_bits": (result.residual.get("unexplained_bits")
                             if "unexplained_bits" in result.residual
                             else result.residual),
        "residual": result.residual,
        "decode_check": result.decode_check,
        "e1": result.e1,
        "e2": result.e2,
        "mask_sha256": result.mask_sha256,
        "mask_entries": list(result.mask_entries),
        "oracle_log": result.log_path,
        "notes": result.notes,
    }]


# --------------------------------------------------------------------------
# 8b. Levels `E1` and `E2` (`P0.T26`, `D32`, `spec-harness.md` §3/§5.1)
# --------------------------------------------------------------------------
#: nextpnr's own `.cst` reader regex for the CLS spelling of `INS_LOC`
#: (`himbaechel/uarch/gowin/cst.cc:94-96`), transliterated to Python by
#: unescaping the C++ string escapes and nothing else.  Every line the
#: exporter writes is matched against this **before** it reaches a `.cst`, so
#: a line nextpnr could not read back can never be written.
INSLOC_RE = re.compile(
    r'INS_LOC +"([^"]+)" +R([0-9]+)C([0-9]+)\[([0-9])\]\[([AB])\] *;.*[\s\S]*')

#: The bels that live in a CLS and therefore have a `RxCy[cls][A|B]` address.
#: Everything else nextpnr places (IOB, BUFG, GSR, PINCFG, VCC/GND, ...) is
#: either constrained by `IO_LOC`/`CLOCK_LOC` or has no `.cst` spelling at
#: all; those are **listed as skipped**, never silently dropped.
_CLS_BEL_RE = re.compile(r"^(LUT|DFF)([0-7])$")

#: The block `export_insloc()` owns inside a `.cst`.  Re-exporting replaces
#: the block, so the exporter is idempotent and never accumulates stale
#: constraints from an earlier placement.
INSLOC_BLOCK_BEGIN = ("// --- BEGIN nextpnr placement export "
                      "(fuzz.gw5ast138c.harness.equiv.export_insloc) ---")
INSLOC_BLOCK_END = "// --- END nextpnr placement export ---"


def z_lut(cls, half):
    """`z` of the LUT of CLS `cls`, half `A`/`B` (`gowin_arch_gen.py:1330`).

    LUT `i` has `z = i*2` and `i = cls*2 + (half == "B")`, so
    `z_lut = cls*4 + 2*(half == "B")`.
    """
    if cls not in (0, 1, 2, 3):
        raise EquivError(f"CLS index {cls!r} outside 0..3")
    if half not in ("A", "B"):
        raise EquivError(f"CLS half {half!r} is neither 'A' nor 'B'")
    return cls * 4 + 2 * (half == "B")


def z_dff(cls, half):
    """`z` of the DFF of CLS `cls`, half `A`/`B` (`gowin_arch_gen.py:1342`)."""
    return z_lut(cls, half) + 1


def cls_half(index):
    """`LUT3`/`DFF3` -> `(cls, half)`, inverting `i = cls*2 + (half == "B")`."""
    if not 0 <= index <= 7:
        raise EquivError(f"CLS bel index {index!r} outside 0..7")
    return index // 2, "B" if index % 2 else "A"


def insloc_line(name, x, y, cls, half):
    """One `INS_LOC` line: `R` is `y+1` and `C` is `x+1` (`spec-harness.md` §3).

    The line is validated against nextpnr's own regex here, so an unwritable
    line raises rather than reaching a `.cst`.
    """
    line = f'INS_LOC "{name}" R{y + 1}C{x + 1}[{cls}][{half}];'
    if not INSLOC_RE.match(line):
        raise EquivError(
            f"generated INS_LOC line does not match nextpnr's reader regex "
            f"(cst.cc:94-96): {line!r}")
    return line


def insloc_lines(pnr_cells, known_instances=None):
    """`INS_LOC` lines for every placed CLS cell of a nextpnr placement.

    Returns `{"lines", "exported", "skipped"}`.  `exported` maps the cell name
    to `{"x", "y", "cls", "half", "z", "bel", "type", "line"}`; `skipped`
    lists every placed cell that gets no line, each with the reason -- an IOB
    is constrained by `IO_LOC`, a `BUFG` by `CLOCK_LOC`, and a packer
    pseudo-bel by nothing at all.

    `known_instances`, when given, is the set of instance names the **vendor's
    own** netlist carries, and a cell whose name is not in it is skipped.  It
    is not an optimisation: measured on the smoke design (`P0.T26`), a
    constraint naming an instance GowinSynthesis renamed makes `gw_sh` print
    `ERROR (CT1135) : Can't find object named ...` and abort the whole run, so
    exporting a name the vendor does not have destroys the comparison instead
    of tightening it.  Only names both flows agree on can be constrained, and
    that is a property of the two synthesisers, not of this exporter.
    """
    lines, exported, skipped = [], {}, []
    for cell in pnr_cells:
        name, bel, site = cell["name"], cell["bel"], cell["site"]
        if bel is None or site is None:
            skipped.append({"name": name, "type": cell["type"], "bel": bel,
                            "why": "not placed on any bel"})
            continue
        if known_instances is not None and name not in known_instances:
            skipped.append({"name": name, "type": cell["type"], "bel": bel,
                            "why": "not an instance of the vendor netlist "
                                   "(renamed by GowinSynthesis); constraining "
                                   "it aborts gw_sh with CT1135"})
            continue
        m = _CLS_BEL_RE.match(bel)
        if m is None:
            skipped.append({"name": name, "type": cell["type"], "bel": bel,
                            "why": "not a CLS bel: no RxCy[cls][A|B] address"})
            continue
        kind, index = m.group(1), int(m.group(2))
        cls, half = cls_half(index)
        x, y = site
        z = z_lut(cls, half) if kind == "LUT" else z_dff(cls, half)
        line = insloc_line(name, x, y, cls, half)
        lines.append(line)
        exported[name] = {"x": x, "y": y, "cls": cls, "half": half, "z": z,
                          "bel": bel, "type": cell["type"], "line": line}
    return {"lines": lines, "exported": exported, "skipped": skipped}


def export_insloc(pnr_json, cst_path, vendor_netlist=None):
    """Export a nextpnr placement into a vendor `.cst` as `INS_LOC` lines.

    **This is the named symbol** (`P0.T26`; `P2.T01` precondition (7), `P2.T22`
    call, cross-phase `F15`): no other phase writes an exporter.  It reads the
    post-PnR JSON, writes one `INS_LOC` line per placed CLS cell into an owned
    block at the end of `cst_path` (replacing any earlier block, so it is
    idempotent), and returns the same dict `insloc_lines()` does plus the
    `.cst` path and the count.

    The dataflow is the **export** direction only (nextpnr placement -> vendor
    `.cst`); it needs no nextpnr change (`spec-harness.md` §3).

    `vendor_netlist` is the vendor's own `.vg`/`.vo`; pass it and only
    instance names the vendor also has are constrained (see `insloc_lines()`
    for why that is mandatory rather than defensive).
    """
    known = (set(vendor_instances(vendor_netlist))
             if vendor_netlist else None)
    out = insloc_lines(read_pnr_cells(pnr_json), known_instances=known)
    text = ""
    if os.path.isfile(cst_path):
        with open(cst_path) as fh:
            text = fh.read()
    head = text.split(INSLOC_BLOCK_BEGIN)[0].rstrip("\n")
    block = "\n".join([INSLOC_BLOCK_BEGIN] + out["lines"] + [INSLOC_BLOCK_END])
    with open(cst_path, "w") as fh:
        fh.write((head + "\n\n" if head else "") + block + "\n")
    out["cst"] = os.path.abspath(cst_path)
    out["count"] = len(out["lines"])
    return out


# --- the vendor's realised placement (`run/impl/pnr/*.tr`, `*.vo`) ---------
#: A `.tr` timing-path row: the `LOC` column carries the CLS address and the
#: `NODE` column the instance and its port, e.g.
#: `  6.582   5.968   tNET   RR   1        R2C3[0][A]    dut_dff/CLK`.
_TR_LOC_RE = re.compile(
    r"\bR([0-9]+)C([0-9]+)\[([0-9])\]\[([AB])\]\s+(\S+)")

#: An instance header in a vendor Verilog netlist, `.vg` or `.vo`:
#: `DFFRE dut_dff (` (the `.vg` indents it, the `.vo` does not).
_VO_INST_RE = re.compile(r"^\s*([A-Z][A-Z0-9_]*)\s+(\S+)\s*\(\s*$")


def vendor_instances(path):
    """`{instance: cell_type}` of a vendor `.vg`/`.vo` netlist."""
    out = {}
    if not path or not os.path.isfile(path):
        return out
    with open(path, errors="replace") as fh:
        for row in fh:
            m = _VO_INST_RE.match(row.rstrip())
            if m is not None:
                out[m.group(2)] = m.group(1)
    return out


def parse_vendor_placement(tr_path=None, vo_path=None, design_dir=None):
    """The vendor's realised CLS placement, read from its own reports.

    `.tr` carries the coordinates (its timing rows name `LOC` and `NODE`);
    `.vo` carries the post-PnR instance list, which is what tells a *renamed*
    instance apart from a *moved* one.  Returns
    `{"placement": {inst: (x, y, cls, half)}, "instances": {...}, "tr", "vo"}`
    with `x = C-1`, `y = R-1`, so it is directly comparable with the exporter.
    """
    if design_dir is not None:
        pnr_dir = os.path.join(design_dir, "run", "impl", "pnr")
        if tr_path is None:
            tr_path = next(iter(sorted(
                _glob(os.path.join(pnr_dir, "*.tr")))), None)
        if vo_path is None:
            vo_path = next(iter(sorted(
                _glob(os.path.join(pnr_dir, "*.vo")))), None)

    placement, conflicts = {}, []
    if tr_path and os.path.isfile(tr_path):
        with open(tr_path, errors="replace") as fh:
            for row in fh:
                m = _TR_LOC_RE.search(row)
                if m is None:
                    continue
                r, c, cls, half, node = m.groups()
                inst = node.rsplit("/", 1)[0] if "/" in node else node
                site = (int(c) - 1, int(r) - 1, int(cls), half)
                if placement.setdefault(inst, site) != site:
                    conflicts.append({"instance": inst,
                                      "sites": [placement[inst], site]})

    instances = vendor_instances(vo_path)

    return {"placement": placement, "instances": instances,
            "conflicts": conflicts,
            "tr": os.path.abspath(tr_path) if tr_path else None,
            "vo": os.path.abspath(vo_path) if vo_path else None}


def _glob(pattern):
    import glob as _g
    return _g.glob(pattern)


def level_e1(exported, realised, scope=None):
    """`E1`: does the vendor place every constrained cell where we asked?

    Returns `{"level", "checked", "matched", "mismatched", "unobserved",
    "notes"}`.  `level` is `E1` when every constrained cell **that the vendor's
    own reports show** sits at its exported address and at least one such cell
    lies in the comparison scope; otherwise `E0`, and `notes` says why
    (`EC9`).  A constrained cell the vendor's reports never name is
    *unobserved*, not *moved*: GowinSynthesis renames instances, so absence is
    evidence about the report, not about the placement -- it is listed, and an
    unobserved **in-scope** cell is enough to withhold `E1`.
    """
    placed = realised.get("placement", {})
    instances = realised.get("instances", {})
    matched, mismatched, unobserved = [], [], []
    in_scope_seen = 0
    for name, want in sorted(exported.items()):
        inside = scope is None or (want["x"], want["y"]) in {
            tuple(t) for t in scope.tiles}
        got = placed.get(name)
        if got is None:
            unobserved.append({
                "name": name, "in_scope": inside,
                "exported": f"R{want['y'] + 1}C{want['x'] + 1}"
                            f"[{want['cls']}][{want['half']}]",
                "in_vo": name in instances})
            continue
        gx, gy, gcls, ghalf = got
        if (gx, gy, gcls, ghalf) == (want["x"], want["y"], want["cls"],
                                     want["half"]):
            matched.append({"name": name, "in_scope": inside,
                            "site": f"R{gy + 1}C{gx + 1}[{gcls}][{ghalf}]"})
            in_scope_seen += bool(inside)
        else:
            mismatched.append({
                "name": name, "in_scope": inside,
                "exported": f"R{want['y'] + 1}C{want['x'] + 1}"
                            f"[{want['cls']}][{want['half']}]",
                "realised": f"R{gy + 1}C{gx + 1}[{gcls}][{ghalf}]"})

    notes = ""
    level = "E1"
    if mismatched:
        level = "E0"
        first = mismatched[0]
        notes = (f"EC9: the vendor ignored {len(mismatched)} INS_LOC "
                 f"constraint(s); first is {first['name']!r} exported at "
                 f"{first['exported']} but realised at {first['realised']} -- "
                 "placement identity is not assertable, so the row closes at E0")
    else:
        blind = [u for u in unobserved if u["in_scope"]]
        if not exported:
            level = "E0"
            notes = ("EC9: the open placement exported no CLS constraint, so "
                     "there is nothing for E1 to assert")
        elif blind:
            level = "E0"
            notes = (f"EC9: {len(blind)} in-scope constrained cell(s) are not "
                     "named by the vendor's .tr/.vo (GowinSynthesis renames "
                     f"instances); first is {blind[0]['name']!r} exported at "
                     f"{blind[0]['exported']} -- placement identity cannot be "
                     "observed, so the row closes at E0")
        elif not in_scope_seen:
            level = "E0"
            notes = ("EC9: no constrained cell lies inside the comparison "
                     "scope, so E1 would assert nothing about the primitive "
                     "under test")
        elif unobserved:
            notes = (f"E1 holds in scope; {len(unobserved)} out-of-scope "
                     "constrained cell(s) are not named by the vendor's "
                     ".tr/.vo (renamed by GowinSynthesis), so their placement "
                     "is unobserved, not moved")
    return {"level": level, "checked": len(exported), "matched": matched,
            "mismatched": mismatched, "unobserved": unobserved, "notes": notes}


# --- `E2`: the pip-set bonus on single-legal-path nets ---------------------
#: The only net classes `spec-harness.md` §5.1 admits at `E2` -- nets with
#: exactly one legal path, so two independent routers *must* agree.  A net is
#: a candidate when one of its endpoints is a `(cell type prefix, port)` pair
#: below.  Nothing else is ever compared at `E2`, because for an ordinary
#: fabric net a pip difference is a routing choice, not a defect (`D32`).
SINGLE_PATH_NET_CLASSES = {
    "dqs_strobe": (("DQS",), ("DQSR90", "DQSW0", "DQSW270", "RCLKSEL",
                              "WSTEP", "READ")),
    "hclk_to_fclk": (("HCLKMUX", "CLKDIV", "DHCEN", "HCLK"), ("FCLK",)),
    "pll_to_core_clk": (("PLL", "PLLA", "RPLLA", "PLLVR"),
                        ("CLKOUT", "CLKOUTP", "CLKOUTD", "CLKOUTD3")),
}


def _net_class(endpoints):
    for label, (types, ports) in sorted(SINGLE_PATH_NET_CLASSES.items()):
        for cell, port in endpoints:
            if cell.type.startswith(tuple(types)) and port in ports:
                return label
    return None


def _pips_by_net(netlist):
    """`{net root: {(src, dest)}}` -- the pips of each connected component.

    Rebuilt from `Netlist.raw_pips` with the same union-find `_build_nets()`
    used, so a root here is the label `Netlist.nets` carries.
    """
    uf = _UnionFind()
    for tile_pips in netlist.raw_pips.values():
        for dest, src in tile_pips.items():
            uf.setdefault(dest, dest)
            uf.setdefault(src, src)
            uf.union(src, dest)
    out = collections.defaultdict(set)
    for tile_pips in netlist.raw_pips.values():
        for dest, src in tile_pips.items():
            out[uf.find(dest)].add((src, dest))
    return out


def level_e2(vendor, open_, scope=None):
    """`E2`: pip-set identity on the single-legal-path nets of the shape.

    Reported as an **achieved fraction**, never a done criterion (`D32`,
    §5.1): a fraction of 0.0 -- including the honest 0.0 of a shape with no
    such net -- leaves the verdict exactly where `E1` left it.  Nets are
    matched across the two sides by `net_id()`, i.e. by their endpoint sets,
    which is meaningful precisely because `E2` is only ever computed once
    `E1` has established that the cells sit at the same sites.
    """
    pips_v, pips_o = _pips_by_net(vendor), _pips_by_net(open_)
    sides = []
    for netlist, pips in ((vendor, pips_v), (open_, pips_o)):
        by_id = {}
        for label, endpoints in netlist.nets.items():
            eps = {(c, p) for c, p in endpoints if in_scope(c, scope)}
            if not eps:
                continue
            cls = _net_class(eps)
            if cls is None:
                continue
            by_id[net_id(endpoints)] = (cls, pips.get(label, set()))
        sides.append(by_id)
    by_v, by_o = sides

    nets, identical = [], 0
    for key in sorted(set(by_v) & set(by_o)):
        cls, pv = by_v[key]
        _cls_o, po = by_o[key]
        same = pv == po
        identical += bool(same)
        nets.append({"net": key, "class": cls, "identical": bool(same),
                     "vendor_pips": len(pv), "open_pips": len(po),
                     "only_vendor": len(pv - po), "only_open": len(po - pv)})
    candidates = len(nets)
    note = ""
    if not candidates:
        note = ("no single-legal-path net in scope (DQS strobe, HCLK->FCLK or "
                "PLL->CORE_CLK); E2 is a bonus and reports 0.0, which is never "
                "a verdict term")
    return {"candidates": candidates, "identical": identical,
            "fraction": (identical / candidates) if candidates else 0.0,
            "nets": nets, "note": note}


def apply_level(result, requested):
    """Fold `result.e1`/`result.e2` into the level and the verdict line.

    `E2` is reached only when `E1` holds **and** every single-legal-path net
    in scope has an identical pip set; a partial fraction leaves the row at
    `E1` (§5.2: `EQUIV E2 ok` is "a bonus line, never required").
    """
    level = "E0"
    if requested != "E0" and result.e1:
        level = result.e1["level"]
        if result.e1["notes"]:
            result.notes = ((result.notes + " " if result.notes else "")
                            + result.e1["notes"])
    if level == "E1" and requested == "E2" and result.e2:
        if result.e2["candidates"] and result.e2["fraction"] == 1.0:
            level = "E2"
    result.level = level
    if result.verdict.startswith("EQUIV"):
        result.verdict = f"EQUIV {level} ok"
    return result


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
                   open_fs=None, pnr_json=None, tr_path=None, vo_path=None):
    """Compare the two bitstreams of one design directory at `E0`/`E1`/`E2`.

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
    shape_class = getattr(spec, "shape_class", None)
    res = residual(vendor, open_, db=db, nl_v=nl_v, nl_o=nl_o, mask=mask,
                   level=level, shape_class=shape_class, device=device)
    result = compare_e0(nl_v, nl_o, scope=scope, mask=mask, residual=res)
    result.level = level

    # §5.4's decode check is required for the row to be admissible, so it runs
    # whenever the nextpnr post-PnR netlist `c1` needs is on disk beside the
    # open-flow bitstream.
    pnr = pnr_json or os.path.join(design_dir, "top_pnr.json")
    if os.path.isfile(pnr):
        nl_c1 = unpack_netlist(open_, device=device, db=db, noalu=True)
        result.decode_check = decode_check(open_, pnr, netlist=nl_c1, db=db,
                                           device=device)
        if result.decode_check["c1"] != "ok" or result.decode_check["c2"] != "ok":
            result.verdict = "DIFF"
            result.notes = (result.notes + " " if result.notes else "") + (
                "decode check failed (spec-harness.md 5.4, D34): "
                f"c1={result.decode_check['c1']} c2={result.decode_check['c2']}")
    else:
        result.decode_check = {"c1": "skipped", "c2": "skipped",
                               "why": f"no nextpnr post-PnR netlist at {pnr}"}

    # `E1`/`E2` (`P0.T26`).  `E1` needs the open placement (the post-PnR JSON
    # the exporter reads) and the vendor's own reports; when either is absent
    # the row stays at `E0` and says so, which is exactly `EC9`'s shape.
    if level != "E0":
        if os.path.isfile(pnr):
            realised = parse_vendor_placement(
                tr_path=tr_path, vo_path=vo_path, design_dir=design_dir)
            exported = insloc_lines(
                read_pnr_cells(pnr),
                known_instances=set(realised["instances"]) or None)["exported"]
            if realised["tr"] is None and realised["vo"] is None:
                result.e1 = {"level": "E0", "checked": len(exported),
                             "matched": [], "mismatched": [],
                             "unobserved": [],
                             "notes": ("EC9: no vendor .tr/.vo under "
                                       f"{design_dir}/run/impl/pnr, so the "
                                       "realised placement cannot be read")}
            else:
                result.e1 = level_e1(exported, realised, scope=scope)
        else:
            result.e1 = {"level": "E0", "checked": 0, "matched": [],
                         "mismatched": [], "unobserved": [],
                         "notes": ("EC9: no nextpnr post-PnR netlist at "
                                   f"{pnr}, so there is no placement to export")}
        if level == "E2" and result.e1["level"] == "E1":
            result.e2 = level_e2(nl_v, nl_o, scope=scope)
        apply_level(result, level)
    return result


def compare(design_dir, spec=None, level="E0", **kwargs):
    """The level-dispatching entry `__main__.real_runner` calls (`P0.T22`).

    `compare_e0()` is the set algebra; this is the whole comparison at the
    level a batch asked for.  A `ShapeSpec` is accepted directly because that
    is what the batch has in hand.
    """
    shape = getattr(spec, "name", spec) if spec is not None else None
    return compare_design(design_dir, shape=shape, level=level, **kwargs)


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
    parser.add_argument("--pnr-json", default=None,
                        help="nextpnr post-PnR netlist for the decode check's "
                             "c1; default is top_pnr.json in --design-dir.")
    parser.add_argument("--tr", default=None,
                        help="Vendor timing report holding the realised CLS "
                             "placement; default run/impl/pnr/*.tr under "
                             "--design-dir (E1).")
    parser.add_argument("--vo", default=None,
                        help="Vendor post-PnR netlist; default "
                             "run/impl/pnr/*.vo under --design-dir (E1).")
    parser.add_argument("--json", action="store_true")
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    result = compare_design(args.design_dir, shape=args.shape,
                            level=args.level, mask_path=args.mask,
                            calibration=args.calibration,
                            pnr_json=args.pnr_json, tr_path=args.tr,
                            vo_path=args.vo)
    for line in report(result):
        print(line)
    if args.json:
        print(json.dumps(evidence_rows(result), sort_keys=True, default=str))
    return 0 if result.verdict.startswith("EQUIV") else 1


if __name__ == "__main__":
    sys.exit(main())
