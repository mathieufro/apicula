"""yosys -> nextpnr-himbaechel -> gowin_pack for the same inputs (`P0.T21`).

The open-flow half of a differential run: it consumes exactly the `top.v` /
`top.cst` / `top.sdc` the oracle (`oracle.py`) hands to `gw_sh` and produces a
`top.fs` for the same design directory.

Module rooting is fixed: this module is always addressed as
`fuzz.gw5ast138c.harness.openflow` and run from `$FL/apicula`; it never depends
on cwd -- the design directory is always passed explicitly via `--design-dir`
(`spec-harness.md` §1, `spec.md` V5/V6).

The three commands are `spec-harness.md` §4 verbatim:

    yosys -p 'read_verilog top.v; synth_gowin -family gw5a -setundef -json top.json'
    nextpnr-himbaechel --device GW5AST-LV138PG484AC1/I0 \\
        --chipdb <path>/chipdb-GW5AST-138C.bin --vopt cst=top.cst \\
        --json top.json --write top_pnr.json --top <module> --timing-allow-fail
    gowin_pack -d GW5AST-138C --cpu_as_gpio -o top.fs top_pnr.json

Binding behaviours implemented here:

* **The chipdb is `chipdb-GW5AST-138C.bin`, never `chipdb-gw5a.bin`** -- there
  is no per-family database (F47). `--chipdb` is always passed explicitly: the
  harness pins the artefact whose sha256 goes into the evidence row and never
  relies on the install prefix (the same bytes are also installed under
  `$DATASTORE/toolchains/nextpnr/share/himbaechel/gowin/` so that unmodified
  recipes resolve it without a flag -- that path is not this module's
  mechanism).
* The two option namespaces are never crossed: `gowin_pack` takes
  `--cpu_as_gpio`; `-use_cpu_as_gpio` is the `gw_sh` Tcl spelling and belongs
  to `oracle.py` alone.
* `--top <module>` is a parameter of the shape, required whenever the top
  module is not `top`.
* `--timing-allow-fail` stays until W-TIMING's L0 and L1a pass (`D24`, `D49e`);
  every run records whether it was actually *needed* -- itself an L2 datapoint.
* `yosys` performs **zero DSP inference for `gw5a`**; DSP shapes hand-
  instantiate. Nothing here compensates for that.
"""
import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time

DEVICE = "GW5AST-138C"
PART = "GW5AST-LV138PG484AC1/I0"
FAMILY = "gw5a"

#: The one chipdb name (F47). There is no per-family `chipdb-gw5a.bin`.
CHIPDB_BASENAME = f"chipdb-{DEVICE}.bin"

DATASTORE = "/Users/alex/fine-line-data/open-toolchain-gw5ast"
#: The harness-only explicit `--chipdb` pin recorded by `P0.T16b`.
DEFAULT_CHIPDB = os.path.join(DATASTORE, "chipdb", "std", CHIPDB_BASENAME)
DEFAULT_NEXTPNR = os.path.join(DATASTORE, "toolchains", "nextpnr", "bin",
                               "nextpnr-himbaechel")
DEFAULT_YOSYS = "/opt/homebrew/bin/yosys"
SMOKE_DIR = os.path.join(DATASTORE, "oracle-smoke")

DEFAULT_TIMEOUT_S = 1800

#: `nextpnr` reports one line per clock; a violated constraint reads `FAIL at`.
_FMAX_RE = re.compile(
    r"^Info: Max frequency for clock\s+'([^']+)':\s+([\d.]+)\s+MHz\s+"
    r"\((PASS|FAIL) at ([\d.]+) MHz\)", re.M)
#: Any timing failure nextpnr would have made fatal without the flag.
_TIMING_FAIL_MARKERS = ("FAIL at", "Max delay ", "Timing failure")


class OpenFlowError(Exception):
    """Anything the open flow refuses to proceed on."""


# --------------------------------------------------------------------------
# 1. Tool resolution
# --------------------------------------------------------------------------

def resolve_yosys(path=None):
    for candidate in (path, os.environ.get("YOSYS"), DEFAULT_YOSYS):
        if candidate and os.path.isfile(candidate):
            return candidate
    found = shutil.which("yosys")
    if found:
        return found
    raise OpenFlowError("no yosys: pass --yosys, export YOSYS, or install one")


def resolve_nextpnr(path=None):
    for candidate in (path, os.environ.get("NEXTPNR_HIMBAECHEL"),
                      DEFAULT_NEXTPNR):
        if candidate and os.path.isfile(candidate):
            return candidate
    found = shutil.which("nextpnr-himbaechel")
    if found:
        return found
    raise OpenFlowError(
        "no nextpnr-himbaechel: pass --nextpnr or export NEXTPNR_HIMBAECHEL")


def resolve_gowin_pack(path=None):
    """`gowin_pack` as an argv **prefix**.

    The console script is preferred; the module form keeps a venv whose
    scripts are not on `PATH` working. `apycula/gowin_pack.py` is frozen and
    is only ever called, never edited.
    """
    for candidate in (path, os.environ.get("GOWIN_PACK")):
        if candidate and os.path.isfile(candidate):
            return [candidate]
    found = shutil.which("gowin_pack")
    if found:
        return [found]
    return [sys.executable, "-m", "apycula.gowin_pack"]


def resolve_chipdb(path=None):
    """The explicit `--chipdb` artefact, asserted to be the device database."""
    chipdb = path or os.environ.get("GOWIN_CHIPDB") or DEFAULT_CHIPDB
    if os.path.basename(chipdb) != CHIPDB_BASENAME:
        raise OpenFlowError(
            f"chipdb {chipdb!r} is not {CHIPDB_BASENAME}: there is no "
            f"per-family database (F47)")
    if not os.path.isfile(chipdb):
        raise OpenFlowError(f"no chipdb at {chipdb}")
    return chipdb


# --------------------------------------------------------------------------
# 2. The three commands (`spec-harness.md` §4, verbatim)
# --------------------------------------------------------------------------

def yosys_script(verilog="top.v", json_out="top.json", family=FAMILY):
    return (f"read_verilog {verilog}; "
            f"synth_gowin -family {family} -setundef -json {json_out}")


def yosys_command(yosys, verilog="top.v", json_out="top.json", family=FAMILY):
    return [yosys, "-p", yosys_script(verilog, json_out, family)]


def nextpnr_command(nextpnr, chipdb, cst="top.cst", json_in="top.json",
                    json_out="top_pnr.json", top_module="top",
                    timing_allow_fail=True, report=None):
    cmd = [
        nextpnr,
        "--device", PART,
        "--chipdb", chipdb,
        "--vopt", f"cst={cst}",
        "--json", json_in,
        "--write", json_out,
        "--top", top_module,
    ]
    if timing_allow_fail:
        cmd.append("--timing-allow-fail")
    if report:
        cmd += ["--report", report]
    return cmd


def pack_command(gowin_pack, json_in="top_pnr.json", fs_out="top.fs",
                 device=DEVICE, extra_gpio=()):
    """`gowin_pack -d <device> --cpu_as_gpio -o top.fs top_pnr.json`.

    `--cpu_as_gpio` is the **packer** namespace (`gowin_pack.py:36`); the
    `gw_sh` Tcl spelling `-use_cpu_as_gpio` is never emitted here.
    `extra_gpio` carries a shape's additional dual-purpose-pin flags (the
    AE350 shape passes `sspi_as_gpio` and `mspi_as_gpio`).
    """
    cmd = list(gowin_pack) + ["-d", device, "--cpu_as_gpio"]
    for flag in extra_gpio:
        cmd.append(flag if flag.startswith("--") else f"--{flag}")
    cmd += ["-o", fs_out, json_in]
    return cmd


# --------------------------------------------------------------------------
# 3. Running one step
# --------------------------------------------------------------------------

def run_step(name, cmd, design_dir, timeout=DEFAULT_TIMEOUT_S, env=None):
    """Run one tool in `design_dir`, logging to a FILE (never a filter pipe).

    Foreground with an explicit timeout: `impl/LOOP-BRIEF.md` §4 puts a single
    tool invocation in the foreground-with-timeout class.
    """
    log_path = os.path.join(design_dir, f"{name}.log")
    started = time.time()
    with open(log_path, "wb") as log:
        try:
            proc = subprocess.run(cmd, cwd=design_dir, stdout=log,
                                  stderr=subprocess.STDOUT, timeout=timeout,
                                  env=env)
            returncode = proc.returncode
        except subprocess.TimeoutExpired:
            raise OpenFlowError(
                f"{name} did not exit within {timeout}s; log at {log_path}")
    with open(log_path, errors="replace") as fh:
        text = fh.read()
    return {"step": name, "cmd": cmd, "returncode": returncode,
            "log_path": log_path, "log_text": text,
            "wall_clock_s": round(time.time() - started, 3)}


# --------------------------------------------------------------------------
# 4. Timing report and provenance
# --------------------------------------------------------------------------

def parse_fmax(log_text):
    """`[{clock, mhz, verdict, target_mhz}]` from a nextpnr log."""
    return [{"clock": clock, "mhz": float(mhz), "verdict": verdict,
             "target_mhz": float(target)}
            for clock, mhz, verdict, target in _FMAX_RE.findall(log_text)]


def timing_allow_fail_needed(log_text):
    """Whether `--timing-allow-fail` actually rescued this run.

    True when nextpnr reported a violated constraint -- without the flag that
    run would have been fatal. Recorded per run: it is itself an L2 datapoint
    (`D24`, `D49e`).
    """
    if any(marker in log_text for marker in _TIMING_FAIL_MARKERS):
        return True
    return any(entry["verdict"] == "FAIL" for entry in parse_fmax(log_text))


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _git_sha(repo):
    try:
        out = subprocess.run(["git", "-C", repo, "rev-parse", "HEAD"],
                             stdout=subprocess.PIPE,
                             stderr=subprocess.DEVNULL, timeout=20)
        return out.stdout.decode().strip() or None
    except Exception:
        return None


def _apicula_repo():
    return os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.dirname(os.path.abspath(__file__)))))


def _nextpnr_repo(nextpnr_binary):
    """The nextpnr submodule checkout, not the install prefix."""
    sibling = os.path.join(os.path.dirname(_apicula_repo()), "nextpnr")
    # A submodule's `.git` is a *file* pointing at the real git dir.
    if os.path.exists(os.path.join(sibling, ".git")):
        return sibling
    return os.path.dirname(os.path.dirname(os.path.abspath(nextpnr_binary)))


def yosys_version(yosys):
    try:
        out = subprocess.run([yosys, "--version"], stdout=subprocess.PIPE,
                             stderr=subprocess.STDOUT, timeout=60)
        return out.stdout.decode(errors="replace").strip().splitlines()[0]
    except Exception:
        return "unknown"


#: The five keys `spec.md` §7.1 requires of every open-flow evidence row.
PROVENANCE_KEYS = ("yosys_version", "apicula_sha", "nextpnr_sha",
                   "chipdb_sha256", "timing_allow_fail_needed")


def provenance(yosys, nextpnr, chipdb, nextpnr_log=""):
    """The five-field provenance dict of `spec.md` §7.1."""
    return {
        "yosys_version": yosys_version(yosys),
        "apicula_sha": _git_sha(_apicula_repo()),
        "nextpnr_sha": _git_sha(_nextpnr_repo(nextpnr)),
        "chipdb_sha256": sha256(chipdb),
        "timing_allow_fail_needed": timing_allow_fail_needed(nextpnr_log),
    }


#: The §6 evidence-row fields the open flow supplies (`evidence.py`, P0.T28).
#: `timing_allow_fail_needed` is a flow fact, not a row column: it reaches the
#: row through `evidence.adapt`, which folds it into `notes`.
EVIDENCE_PROVENANCE_KEYS = ("yosys_version", "apicula_sha", "nextpnr_sha",
                            "chipdb_sha256")


def evidence_fields(prov, open_log=None, open_fs=None, wall_clock_s=None):
    """This flow's fragment of the one §6 row schema.

    `evidence.adapt(oracle_fragment, openflow.evidence_fields(prov), ...)` is
    how a full row is assembled; no module here builds a row of its own shape.
    """
    fragment = {key: prov.get(key) for key in EVIDENCE_PROVENANCE_KEYS}
    fragment["timing_allow_fail_needed"] = prov.get("timing_allow_fail_needed")
    if open_log is not None:
        fragment["open_log"] = open_log
    if open_fs is not None:
        fragment["open_fs"] = open_fs
    if wall_clock_s is not None:
        fragment["wall_clock_s"] = wall_clock_s
    return fragment


#: Field separator of the provenance line. `yosys --version` is recorded
#: verbatim and contains spaces, so the five fields are separated by ` | `,
#: never by whitespace.
PROVENANCE_SEP = " | "


def provenance_line(prov):
    """One line, five `key=value` fields, in `PROVENANCE_KEYS` order."""
    return "PROVENANCE " + PROVENANCE_SEP.join(
        f"{key}={prov[key]}" for key in PROVENANCE_KEYS)


def parse_provenance_line(line):
    """The inverse of `provenance_line`, so the line is a real contract."""
    if not line.startswith("PROVENANCE "):
        raise OpenFlowError(f"not a provenance line: {line!r}")
    fields = line[len("PROVENANCE "):].split(PROVENANCE_SEP)
    return dict(field.split("=", 1) for field in fields)


# --------------------------------------------------------------------------
# 5. The flow
# --------------------------------------------------------------------------

def run_openflow(design_dir, top_module="top", verilog="top.v", cst="top.cst",
                 json_name="top.json", pnr_json="top_pnr.json",
                 fs_out="top.fs", yosys=None, nextpnr=None, chipdb=None,
                 gowin_pack=None, extra_gpio=(), timing_allow_fail=True,
                 report="top_report.json", timeout=DEFAULT_TIMEOUT_S):
    """Run the three tools on one design directory and return the result.

    Every step's log is a real file inside `design_dir`; the first non-zero
    exit stops the flow and is returned, never swallowed.
    """
    design_dir = os.path.abspath(design_dir)
    if not os.path.isdir(design_dir):
        raise OpenFlowError(f"no design directory {design_dir}")
    for name in (verilog, cst):
        if not os.path.isfile(os.path.join(design_dir, name)):
            raise OpenFlowError(f"{design_dir}: no {name}")

    yosys_bin = resolve_yosys(yosys)
    nextpnr_bin = resolve_nextpnr(nextpnr)
    chipdb_path = resolve_chipdb(chipdb)
    pack_prefix = resolve_gowin_pack(gowin_pack)

    steps = []
    steps.append(run_step(
        "yosys", yosys_command(yosys_bin, verilog, json_name), design_dir,
        timeout))
    if steps[-1]["returncode"] == 0:
        steps.append(run_step(
            "nextpnr", nextpnr_command(
                nextpnr_bin, chipdb_path, cst, json_name, pnr_json,
                top_module, timing_allow_fail, report),
            design_dir, timeout))
    if steps[-1]["returncode"] == 0:
        steps.append(run_step(
            "gowin_pack", pack_command(
                pack_prefix, pnr_json, fs_out, DEVICE, extra_gpio),
            design_dir, timeout))

    nextpnr_log = next((s["log_text"] for s in steps if s["step"] == "nextpnr"),
                       "")
    fs_path = os.path.join(design_dir, fs_out)
    ok = all(s["returncode"] == 0 for s in steps) and os.path.isfile(fs_path)
    return {
        "design_dir": design_dir,
        "ok": ok,
        "steps": [{k: v for k, v in s.items() if k != "log_text"}
                  for s in steps],
        "returncodes": {s["step"]: s["returncode"] for s in steps},
        "fs_path": fs_path if os.path.isfile(fs_path) else None,
        "fs_bytes": os.path.getsize(fs_path) if os.path.isfile(fs_path) else 0,
        "fmax": parse_fmax(nextpnr_log),
        "provenance": provenance(yosys_bin, nextpnr_bin, chipdb_path,
                                 nextpnr_log),
        "tools": {"yosys": yosys_bin, "nextpnr": nextpnr_bin,
                  "chipdb": chipdb_path, "gowin_pack": pack_prefix},
    }


# --------------------------------------------------------------------------
# 6. CLI
# --------------------------------------------------------------------------

def build_parser():
    """Return this module's argparse parser.

    Every harness module parser carries a required `--design-dir` so no
    harness command depends on the current working directory
    (`spec-harness.md` §1, `spec.md` V5/V6).
    """
    parser = argparse.ArgumentParser(prog="fuzz.gw5ast138c.harness.openflow")
    parser.add_argument(
        "--design-dir",
        required=True,
        help="Directory holding the test design for this run (never inferred from cwd).",
    )
    parser.add_argument("--shape", default="smoke",
                        help="Shape name; used for the top module and the "
                             "extra dual-purpose-pin flags.")
    parser.add_argument("--top-module", default=None,
                        help="Top module; default: the shape's own top module.")
    parser.add_argument("--yosys", default=None)
    parser.add_argument("--nextpnr", default=None)
    parser.add_argument("--gowin-pack", default=None)
    parser.add_argument("--chipdb", default=None,
                        help=f"Explicit {CHIPDB_BASENAME} to pin; default "
                             f"{DEFAULT_CHIPDB}.")
    parser.add_argument("--extra-gpio", action="append", default=[],
                        metavar="FLAG",
                        help="Extra gowin_pack dual-purpose-pin flag "
                             "(e.g. sspi_as_gpio), repeatable.")
    parser.add_argument("--no-timing-allow-fail", action="store_true",
                        help="Drop --timing-allow-fail (W-TIMING L0/L1a only).")
    parser.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT_S)
    parser.add_argument("--json", action="store_true",
                        help="Also print the full result as one JSON line.")
    return parser


def _shape_top_module(shape):
    """The shape's own top module, without importing a shape that is absent."""
    try:
        module = __import__(f"fuzz.gw5ast138c.shapes.{shape}",
                            fromlist=["SPEC"])
    except Exception:
        return "top"
    return getattr(getattr(module, "SPEC", None), "top_module", "top")


def main(argv=None):
    args = build_parser().parse_args(argv)
    top_module = args.top_module or _shape_top_module(args.shape)
    result = run_openflow(
        args.design_dir, top_module=top_module, yosys=args.yosys,
        nextpnr=args.nextpnr, chipdb=args.chipdb, gowin_pack=args.gowin_pack,
        extra_gpio=args.extra_gpio,
        timing_allow_fail=not args.no_timing_allow_fail,
        timeout=args.timeout)
    for step in result["steps"]:
        print(f"STEP {step['step']} returncode={step['returncode']} "
              f"wall_clock_s={step['wall_clock_s']} log={step['log_path']}")
    for entry in result["fmax"]:
        print(f"FMAX clock={entry['clock']} mhz={entry['mhz']} "
              f"verdict={entry['verdict']} target_mhz={entry['target_mhz']}")
    if result["fs_path"]:
        print(f"BITSTREAM {result['fs_path']} {result['fs_bytes']} "
              f"{sha256(result['fs_path'])}")
    print(provenance_line(result["provenance"]))
    if args.json:
        print(json.dumps(result, sort_keys=True))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
