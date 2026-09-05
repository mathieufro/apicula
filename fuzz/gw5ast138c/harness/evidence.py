"""The evidence row schema, the append-only writer and the roll-up (`P0.T28`).

`spec-harness.md` §6 fixes **one JSON Lines row per (primitive, shape, sweep
point)**, appended to `$OTC/evidence/<slug>/runs.jsonl`, with `summary.md`
beside it and `$OTC/evidence/evidence-table.md` as the roll-up that
`spec-primitives.md`'s status column is filled from (`DEL-b`, `S25`).

The field list is declared **once**, as `REQUIRED_FIELDS` -- the writer's key
check, every validation and every test derive from it, and no literal field
count appears anywhere else.  (An earlier "27" in one blueprint contradicted
the 29-name list in §6; one constant is what stops that drifting again.)

Artefact **paths** in a row are absolute paths into the data store
the data store `harness.paths.datastore()` names, each with a recorded
sha256; the committed `$OTC/evidence/` tree carries text only (`D41`), which
`.gitignore` (written by `ensure_tree`) enforces deny-by-default.

Module rooting is fixed: this module is always addressed as
`fuzz.gw5ast138c.harness.evidence` and never depends on cwd -- the evidence
tree is `--evidence-root` or `$OTC_EVIDENCE` or `$OTC/evidence` (`$OTC` is the
`open-toolchain` submodule checked out beside this apicula checkout, `C10`/
`D80`), and a recording run's design directory is passed as
`--design-dir`.  `$OTC/tools/evidence.py` is a shim onto `main()`, so
`python $OTC/tools/evidence.py --rollup` and
`python -m fuzz.gw5ast138c.harness.evidence --rollup` are the same tool with
the same flags.  The roll-up flag is spelled `--rollup` at every site.
"""
import argparse
import hashlib
import json
import os
import subprocess
import sys

# --------------------------------------------------------------------------
# 1. The schema (`spec-harness.md` §6)
# --------------------------------------------------------------------------

#: The evidence row, in §6 source order.  The single declaration of the field
#: list: derive counts and validations from it, never restate them.
REQUIRED_FIELDS: tuple = (
    "run_id",            # <slug>-<shape>-<nnnn>, also the scratch dir name
    "timestamp",         # ISO 8601, run start
    "primitive",         # the spec-primitives.md row id
    "shape",             # A..G or the row-specific shape name
    "sweep",             # the parameter map for this point
    "device",            # GW5AST-138C
    "part",              # GW5AST-LV138PG484AC1/I0, device_version C
    "ide_version",       # e.g. "1.9.12.03 Standard"; edu-provisional if Edu
    "yosys_version",
    "apicula_sha",
    "nextpnr_sha",
    "chipdb_sha256",
    "mask_sha256",
    "level",             # E0 | E1 | E2
    "verdict",           # ok | diff | aborted | refused
    "diff_count",        # {cells, attrs, conns, pips}; pips is a statistic
    "first_diff",
    "fuses_moved",       # [(tile_x, tile_y, table, bit)]
    "unexplained_bits",  # [] or an enumerated justified list (D35)
    "decode_check",      # {c1: ok|mismatch, c2: ok|mismatch}
    "sdf_condition",     # the vendor SDF operating-condition line (D49f)
    "oracle_log",
    "open_log",
    "vendor_fs",
    "open_fs",
    "sdf",
    "tr",
    "wall_clock_s",      # {oracle: s, open: s}
    "notes",             # required when level == E0
)

LEVELS = ("E0", "E1", "E2")
VERDICTS = ("ok", "diff", "aborted", "refused")
DIFF_COUNT_KEYS = ("cells", "attrs", "conns", "pips")
DECODE_KEYS = ("c1", "c2")
#: `n/a` is the recorded truth for a row the decode check was never run for
#: -- the `D26` budget-measurement calibration rows -- and is spelled here,
#: once, because this tuple is the single owner of the vocabulary the gate's
#: `check_evidence.py` validates against.  It is not a pass: a row carrying it
#: claims no decode check, and `S6b` cannot be closed from one.
DECODE_VALUES = ("ok", "mismatch", "n/a")

DEVICE = "GW5AST-138C"
PART = "GW5AST-LV138PG484AC1/I0, device_version C"

#: `blueprints/README.md`: an E0 row whose remaining proof is a hardware
#: observation Phase 9 has not made yet.  `level: E0`, `verdict: ok`, and
#: `notes` carrying this literal token plus the observation still owed.
#: Phase 0 writes no such row; the writer supports and validates the shape
#: because Phases 2-5b do.
HW_PENDING_TOKEN = "E0+hw-pending"

#: Every row carries this, because the `S17a` timing tables are not a
#: conservative bound: they are conservative in aggregate (median ratio 0.787)
#: and **optimistic per class** -- every DFF `CLK->Q` arc is 0.289 ns modelled
#: against 0.344 ns measured, with zero spread, and 825 SDF arcs (LUT1-3, IO,
#: OBUF) have no model arc at all, contributing zero.  A path is the sum of
#: its arcs, so aggregate pessimism does not compose.  Until Phase 6 / `S17b`
#: re-identifies the grade against the SDF medians, no Fmax number produced
#: anywhere in this harness is a verified one, and the row says so rather than
#: leaving a reader to infer it (`D1`, `D91`).
TIMING_MODEL_TOKEN = "timing_model=unverified"

#: The evidence tree's slug directories, fixed for Phase 0.
SLUGS = ("calibration", "chipdb", "e2e-p0", "harness-selftest",
         "oracle-smoke", "timing-l0-cfu")

#: Environment override for the evidence tree root (used by tests and by any
#: caller that must not write into the checked-out `open-toolchain` tree).
EVIDENCE_ROOT_ENV = "OTC_EVIDENCE"

ROLLUP_NAME = "evidence-table.md"
ROWS_NAME = "runs.jsonl"


class EvidenceSchemaError(Exception):
    """A row that does not satisfy the §6 schema. Never written."""


# --------------------------------------------------------------------------
# 2. Paths
# --------------------------------------------------------------------------
def otc_root():
    """`$OTC`, the `open-toolchain` submodule checked out as a sibling of
    this apicula checkout in the umbrella worktree (`C10`/`D80`), or None
    when it is not present there.

    This module's own path is `<apicula>/fuzz/gw5ast138c/harness/evidence.py`
    -- three `dirname()`s up is the apicula checkout root, and `open-toolchain`
    is that root's sibling.
    """
    apicula_root = os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.dirname(os.path.abspath(__file__)))))
    candidate = os.path.join(os.path.dirname(apicula_root), "open-toolchain")
    return candidate if os.path.isdir(candidate) else None


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def git_sha(repo):
    """`HEAD` of the checkout at `repo`, or None if it is not readable."""
    try:
        return subprocess.run(
            ["git", "-C", repo, "rev-parse", "HEAD"],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=20,
        ).stdout.decode().strip() or None
    except Exception:
        return None


def evidence_root(root=None):
    """The evidence tree root: explicit > `$OTC_EVIDENCE` > `$OTC/evidence`.

    Fails loudly (`EvidenceSchemaError`) rather than silently falling back to
    the pipeline directory, which no longer carries evidence (`C10`/`D80`).
    """
    if root:
        return root
    env = os.environ.get(EVIDENCE_ROOT_ENV)
    if env:
        return env
    otc = otc_root()
    if otc:
        path = os.path.join(otc, "evidence")
        if os.path.isdir(path):
            return path
    raise EvidenceSchemaError(
        "no open-toolchain evidence directory found; pass --evidence-root, "
        f"set {EVIDENCE_ROOT_ENV}, or check out the open-toolchain submodule "
        "beside this apicula checkout")


def rows_path(slug, root=None):
    """`<root>/<slug>/runs.jsonl` -- the append-only file for one slug."""
    return os.path.join(evidence_root(root), slug, ROWS_NAME)


# --------------------------------------------------------------------------
# 3. Building rows
# --------------------------------------------------------------------------
def _default(field):
    if field in ("sweep", "diff_count", "decode_check", "wall_clock_s"):
        return {}
    if field in ("fuses_moved", "unexplained_bits", "vendor_fs", "open_fs",
                 "sdf", "tr"):
        return []
    if field == "device":
        return DEVICE
    if field == "part":
        return PART
    if field == "notes":
        return ""
    return None


def _with_timing_model(fields):
    """`notes` always states that the timing model is unverified (`D91`)."""
    notes = str(fields.get("notes") or "")
    if TIMING_MODEL_TOKEN in notes:
        return fields
    out = dict(fields)
    out["notes"] = f"{notes} | {TIMING_MODEL_TOKEN}".strip(" |")
    return out


def new_row(**fields):
    """A row carrying exactly `REQUIRED_FIELDS`, defaults where unset.

    Unknown keys are a programming error, not a silent extra column: the row
    is exactly the 29 names or it is not a row.
    """
    fields = _with_timing_model(fields)
    unknown = sorted(set(fields) - set(REQUIRED_FIELDS))
    if unknown:
        raise EvidenceSchemaError(
            f"not evidence-row fields: {', '.join(unknown)}")
    row = {name: _default(name) for name in REQUIRED_FIELDS}
    row.update(fields)
    if row["timestamp"] is None:
        from datetime import datetime, timezone
        row["timestamp"] = datetime.now(timezone.utc).isoformat()
    return row


def refused_row(error_text, **fields):
    """A `verdict: refused` row recording the packer's **exact** error text.

    A refusal is a deliverable (`D30`), not a hole: the error text is copied
    into `notes` byte for byte.
    """
    if not error_text or not error_text.strip():
        raise EvidenceSchemaError(
            "verdict 'refused' needs the exact packer error text")
    notes = fields.pop("notes", "")
    fields["notes"] = f"{notes}\n{error_text}".strip() if notes else error_text
    fields["verdict"] = "refused"
    fields.setdefault("level", "E0")
    return validate_row(new_row(**fields))


def hw_pending_row(observation, reason, **fields):
    """The `E0+hw-pending` shape (`blueprints/README.md`, `D33`).

    `observation` names the hardware observation Phase 9 still owes (e.g.
    `DDRDLL.LOCK`, `DQS.RVALID`, `memtest`); `reason` says why E1 was
    unavailable.  Phase 9 flips such a row to `E0+hw` by appending the gate
    artefacts and re-running the roll-up.
    """
    if not observation or not observation.strip():
        raise EvidenceSchemaError(
            f"{HW_PENDING_TOKEN} must name the hardware observation owed")
    fields["level"] = "E0"
    fields["verdict"] = "ok"
    fields["notes"] = f"{reason.strip()} {HW_PENDING_TOKEN} {observation.strip()}"
    return validate_row(new_row(**fields))


def adapt(*fragments, **overrides):
    """Fold partial rows from `oracle`/`openflow`/`equiv` into one §6 row.

    Each producer module builds the part of the row it can measure; this is
    the single place they are merged and normalised, so there is exactly one
    schema in the harness.  Keys that are not §6 fields are not dropped
    silently -- they are appended to `notes` as a compact JSON tail, because a
    measurement that was made is never thrown away.
    """
    merged, extra = {}, {}
    for fragment in list(fragments) + [overrides]:
        for key, value in (fragment or {}).items():
            if value is None:
                continue
            (merged if key in REQUIRED_FIELDS else extra)[key] = value
    if extra:
        tail = "extra=" + json.dumps(extra, sort_keys=True, default=str)
        notes = merged.get("notes", "")
        merged["notes"] = f"{notes} | {tail}".strip(" |") if notes else tail
    return new_row(**merged)


# --------------------------------------------------------------------------
# 4. Validation
# --------------------------------------------------------------------------
def validate_row(row):
    """Return `row` if it satisfies §6, else raise `EvidenceSchemaError`."""
    if not isinstance(row, dict):
        raise EvidenceSchemaError(f"evidence row must be a dict, got {type(row)}")
    missing = [name for name in REQUIRED_FIELDS if name not in row]
    if missing:
        raise EvidenceSchemaError(
            f"evidence row missing required field(s): {', '.join(missing)}")
    unknown = sorted(set(row) - set(REQUIRED_FIELDS))
    if unknown:
        raise EvidenceSchemaError(
            f"evidence row has non-schema field(s): {', '.join(unknown)}")

    if not str(row["run_id"] or "").strip():
        raise EvidenceSchemaError("run_id is required and must be non-empty")
    if row["level"] not in LEVELS:
        raise EvidenceSchemaError(
            f"level {row['level']!r} is not one of {'|'.join(LEVELS)}")
    if row["verdict"] not in VERDICTS:
        raise EvidenceSchemaError(
            f"verdict {row['verdict']!r} is not one of {'|'.join(VERDICTS)}")

    diff = row["diff_count"]
    if diff:
        bad = sorted(set(diff) - set(DIFF_COUNT_KEYS))
        if bad:
            raise EvidenceSchemaError(
                f"diff_count has non-schema key(s): {', '.join(bad)}")
    decode = row["decode_check"]
    if decode:
        bad = sorted(set(decode) - set(DECODE_KEYS))
        if bad:
            raise EvidenceSchemaError(
                f"decode_check has non-schema key(s): {', '.join(bad)}")
        for key, value in decode.items():
            if value not in DECODE_VALUES:
                raise EvidenceSchemaError(
                    f"decode_check.{key} {value!r} is not one of "
                    f"{'|'.join(DECODE_VALUES)}")
    if not isinstance(row["unexplained_bits"], (list, dict)):
        raise EvidenceSchemaError(
            "unexplained_bits must be a list (empty, or the enumerated "
            "justified residual) or the raw residual map (D35)")

    notes = str(row["notes"] or "")
    # Tokens every row carries say nothing about *this* row, so they never
    # satisfy a requirement that the row say something.
    said = notes.replace(TIMING_MODEL_TOKEN, "").strip(" |").strip()
    if row["level"] == "E0" and not said:
        raise EvidenceSchemaError(
            "notes is required when level == 'E0' (say why E1 was "
            "unavailable)")
    if row["verdict"] == "refused" and not said:
        raise EvidenceSchemaError(
            "verdict 'refused' must record the exact packer error text in "
            "notes (D30)")
    if HW_PENDING_TOKEN in notes:
        if row["level"] != "E0" or row["verdict"] != "ok":
            raise EvidenceSchemaError(
                f"{HW_PENDING_TOKEN} requires level 'E0' and verdict 'ok', "
                f"got {row['level']!r}/{row['verdict']!r}")
        if not said.replace(HW_PENDING_TOKEN, "").strip():
            raise EvidenceSchemaError(
                f"{HW_PENDING_TOKEN} must name the hardware observation still "
                "owed, plus the reason E1 was unavailable")
    return row


# --------------------------------------------------------------------------
# 5. The append-only writer
# --------------------------------------------------------------------------
def append_row(row, slug, root=None):
    """Validate and append one row to `<root>/<slug>/runs.jsonl`.

    Append-only, by construction: the file is opened `"a"` and an existing row
    is never rewritten or reordered (`P0.T28` Must-NOT).
    """
    validate_row(row)
    path = rows_path(slug, root)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    line = json.dumps(row, sort_keys=True, default=str) + "\n"
    with open(path, "a") as fh:
        fh.write(line)
        fh.flush()
        os.fsync(fh.fileno())
    return path


def read_rows(path):
    """Every JSON row in one `runs.jsonl`, skipping blank lines.

    Tolerant on purpose: rows written by `P0.T19`/`P0.T23` before this schema
    landed are still counted by the roll-up rather than crashing it.
    """
    if not os.path.isfile(path):
        return []
    rows = []
    with open(path) as fh:
        for line in fh:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


# --------------------------------------------------------------------------
# 6. The evidence tree
# --------------------------------------------------------------------------
#: Deny-by-default with a short justified allowlist (`D41`): the committed
#: tree carries text only, binaries live in the data store with a sha256 in
#: the row.  Later patterns win in git, so the explicit binary denials sit
#: last and cannot be re-allowed by an earlier negation.
GITIGNORE = """\
# Evidence tree: deny by default, allow text only (`D41`, P0.T28).
# Binaries live in the data store (`harness.paths.datastore()`) and are
# referenced from a row by absolute path plus sha256 -- never committed here.
# git takes the WHOLE line as the pattern, so every justification is its own
# comment line, never a trailing one.
*
# Descend into slug directories so the allowlist below can be reached.
!*/
!.gitignore
# summary.md, evidence-table.md and any prose beside a runs.jsonl
!*.md
# the JSON Lines rows themselves (`spec-harness.md` §6)
!runs.jsonl
# text diffs quoted by summaries and PR bodies, at any depth
!**/diff/**
# the S22/V8 parity exception file
!parity-exceptions.tsv
# batch, watchdog and tool logs (`spec-harness.md` §8)
!_runs/*.log
# provenance stamps: sha256 lists, tool versions, gowinhome.selected
!_runs/*.txt
!_runs/*.selected
# Explicitly denied, even under an allowed directory (last match wins):
*.fs
*.vo
*.tr
*.sdf
*.fse
*.dat
*.tm
"""


def ensure_tree(root=None):
    """Create the evidence tree: the six slug directories and `.gitignore`."""
    root = evidence_root(root)
    os.makedirs(root, exist_ok=True)
    for slug in SLUGS:
        os.makedirs(os.path.join(root, slug), exist_ok=True)
    path = os.path.join(root, ".gitignore")
    if not os.path.isfile(path) or open(path).read() != GITIGNORE:
        with open(path, "w") as fh:
            fh.write(GITIGNORE)
    return root


# --------------------------------------------------------------------------
# 7. The roll-up (`spec.md` §5: end of every batch, and at validate time)
# --------------------------------------------------------------------------
def rollup(root=None, out=None):
    """Regenerate `<root>/evidence-table.md` from every `runs.jsonl`.

    Deterministic: no timestamp, no cwd, sorted keys -- two roll-ups of an
    unchanged tree are byte-identical, which is what makes the shim and the
    module provably the same tool.
    """
    root = evidence_root(root)
    slugs = sorted(set(SLUGS) | {
        name for name in (os.listdir(root) if os.path.isdir(root) else [])
        if os.path.isfile(os.path.join(root, name, ROWS_NAME))})

    per_slug, per_primitive, total = [], {}, 0
    for slug in slugs:
        rows = read_rows(os.path.join(root, slug, ROWS_NAME))
        total += len(rows)
        counts = {v: 0 for v in VERDICTS}
        other = 0
        for row in rows:
            verdict = row.get("verdict")
            if verdict in counts:
                counts[verdict] += 1
            else:
                other += 1
            key = (str(row.get("primitive")), str(row.get("level")),
                   str(verdict))
            per_primitive[key] = per_primitive.get(key, 0) + 1
        per_slug.append((slug, len(rows), counts, other))

    lines = [
        "# Evidence table (roll-up)",
        "",
        "Generated by `fuzz.gw5ast138c.harness.evidence --rollup` "
        "(`spec-harness.md` §6). One row per (primitive, shape, sweep point) "
        "lives in `<slug>/runs.jsonl`; this file is the aggregate "
        "`spec-primitives.md`'s status column is filled from (`DEL-b`, `S25`).",
        "",
        f"rows={total}",
        "",
        "## Per slug",
        "",
        "| slug | rows | " + " | ".join(VERDICTS) + " | other |",
        "|---|---|" + "---|" * (len(VERDICTS) + 1),
    ]
    for slug, count, counts, other in per_slug:
        lines.append(f"| {slug} | {count} | "
                     + " | ".join(str(counts[v]) for v in VERDICTS)
                     + f" | {other} |")
    lines += [
        "",
        "## Per primitive",
        "",
        "| primitive | level | verdict | rows |",
        "|---|---|---|---|",
    ]
    for (primitive, level, verdict), count in sorted(per_primitive.items()):
        lines.append(f"| {primitive} | {level} | {verdict} | {count} |")
    if not per_primitive:
        lines.append("| (none) | - | - | 0 |")
    lines.append("")

    path = out or os.path.join(root, ROLLUP_NAME)
    with open(path, "w") as fh:
        fh.write("\n".join(lines))
    return path


# --------------------------------------------------------------------------
# 8. CLI
# --------------------------------------------------------------------------
def build_parser():
    """Return this module's *recording* parser.

    Every harness module parser carries a required `--design-dir` so no
    harness command depends on the current working directory
    (`spec-harness.md` §1, `spec.md` V5/V6).  The maintenance modes
    (`--rollup`, `--ensure-tree`) act on the evidence tree, not on a design,
    and get their own parser below; they name the tree explicitly, so they are
    cwd-independent too.
    """
    parser = argparse.ArgumentParser(prog="fuzz.gw5ast138c.harness.evidence")
    parser.add_argument(
        "--design-dir",
        required=True,
        help="Directory holding the test design for this run (never inferred from cwd).")
    parser.add_argument("--slug", default="harness-selftest",
                        help="Evidence slug directory to append to.")
    parser.add_argument("--evidence-root", default=None,
                        help=f"Evidence tree root (default: ${EVIDENCE_ROOT_ENV} "
                             "or $OTC/evidence).")
    parser.add_argument("--row", default=None,
                        help="A JSON object to validate and append as a row.")
    parser.add_argument("--validate-only", action="store_true",
                        help="Validate --row against the schema, write nothing.")
    return parser


def build_tree_parser():
    """The `--rollup` / `--ensure-tree` parser (no design directory)."""
    parser = argparse.ArgumentParser(
        prog="fuzz.gw5ast138c.harness.evidence")
    parser.add_argument("--rollup", action="store_true",
                        help=f"Regenerate <root>/{ROLLUP_NAME} from every runs.jsonl.")
    parser.add_argument("--ensure-tree", action="store_true",
                        help="Create the slug directories and .gitignore.")
    parser.add_argument("--evidence-root", default=None,
                        help=f"Evidence tree root (default: ${EVIDENCE_ROOT_ENV} "
                             "or $OTC/evidence).")
    return parser


_TREE_FLAGS = ("--rollup", "--ensure-tree")


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if any(arg in _TREE_FLAGS for arg in argv):
        args = build_tree_parser().parse_args(argv)
        root = args.evidence_root
        if args.ensure_tree:
            root = ensure_tree(root)
            print(f"EVIDENCE_TREE {root} slugs={len(SLUGS)}")
        if args.rollup:
            path = rollup(root)
            print(f"ROLLUP {os.path.basename(path)}")
        return 0

    args = build_parser().parse_args(argv)
    if not args.row:
        print(f"FIELDS {len(REQUIRED_FIELDS)} {' '.join(REQUIRED_FIELDS)}")
        return 0
    row = validate_row(new_row(**json.loads(args.row)))
    if args.validate_only:
        print(f"VALID {row['run_id']}")
        return 0
    path = append_row(row, args.slug, args.evidence_root)
    print(f"EVIDENCE {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
