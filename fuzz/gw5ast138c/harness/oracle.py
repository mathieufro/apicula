"""`gw_sh` driver: writes run.tcl, runs it, collects artefacts (P0.T19).

Module rooting is fixed: this module is always addressed as
`fuzz.gw5ast138c.harness.oracle` and run from `$FL/apicula`; it never depends
on cwd -- the design directory is always passed explicitly via `--design-dir`.

The Tcl this module renders is `spec-harness.md` §3 verbatim (`D37`); that
file is its sole owner and this module states no Tcl of its own beyond
substituting the file list, the top module and the option block.

Binding behaviours implemented here:

* `create_project -name run` creates **and chdirs into** `run/`, so every
  artefact is resolved under `<design-dir>/run/impl/...` (F58).
* Artefacts are discovered by **glob on the extension**, never by an assumed
  basename (F12): the vendor names them after the design's top module.
* `gw_sh` prints `unknown option:` as a warning and still exits **zero**
  (F59), so the pre-flight fails the batch on that string; exit status alone
  proves nothing.
* Every invocation sets both `DYLD_LIBRARY_PATH` and `DYLD_FRAMEWORK_PATH` to
  `$GOWINHOME/IDE/lib` (`D17`, F65). No `LD_PRELOAD`, no binary patch.
"""
import argparse
import glob
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone

from . import evidence
from .evidence import git_sha, sha256

DEVICE = "GW5AST-138C"
PART = "GW5AST-LV138PG484AC1/I0"
DEVICE_VERSION = "C"

#: `gw_sh` warns with this string and still exits zero (F59).
UNKNOWN_OPTION_MARKER = "unknown option:"
#: Substrings that identify a licence refusal (F64, `D52`/`EC16`).
LICENCE_MARKERS = (
    "License verification failed",
    "Licence verification failed",
    "license check failed",
)

#: The four post-PnR artefact classes, all rooted at `run/impl/pnr/`.
ARTIFACT_CLASSES = ("fs", "tr", "sdf", "vo")
#: GowinSynthesis netlist, collected separately from `run/impl/gwsynthesis/`.
SYNTH_CLASS = "vg"

DATASTORE = "/Users/alex/fine-line-data/open-toolchain-gw5ast"
SMOKE_DIR = os.path.join(DATASTORE, "oracle-smoke")

DEFAULT_TIMEOUT_S = 600
PREFLIGHT_TIMEOUT_S = 60


class OracleError(Exception):
    """Anything the oracle driver refuses to proceed on."""


class ArtifactCollectionError(OracleError):
    """A class of artefact is missing, or ambiguous (more than one match)."""


class CstDefaultError(OracleError):
    """The `.cst` violates one of the three unconditional default rules."""


# --------------------------------------------------------------------------
# 1. The Tcl template (`spec-harness.md` §3, verbatim)
# --------------------------------------------------------------------------

def render_tcl(files, top_module="top", extra_options=()):
    """Render `run.tcl` for one design.

    `files` is an iterable of `(type, name)` pairs where type is
    `verilog` | `cst` | `sdc`; `extra_options` is an iterable of extra
    `set_option` argument strings (e.g. `"-use_sspi_as_gpio 1"`), used by the
    AE350 shape and never by the smoke design.
    """
    lines = [
        "# --- fixed header ---",
        f"create_project -name run -pn {PART} "
        f"-device_version {DEVICE_VERSION} -force",
        f"set_device -name {DEVICE} {PART}",
        "# --- design ---",
    ]
    for kind, name in files:
        # `create_project` has already chdir'd into `run/` (F58), so a source
        # in the design directory is one level up.
        lines.append(f"add_file -type {kind:<8} ../{name}")
    lines += [
        "# --- options ---",
        f"set_option -top_module {top_module}",
        "set_option -timing_driven 1",
        "set_option -gen_text_timing_rpt 1",
        "set_option -gen_sdf 1",
        "set_option -gen_verilog_sim_netlist 1",
        "set_option -use_cpu_as_gpio 1",
    ]
    for opt in extra_options:
        lines.append(f"set_option {opt}")
    lines += [
        "# --- run ---",
        "run all",
    ]
    return "\n".join(lines) + "\n"


def write_tcl(design_dir, files, top_module="top", extra_options=()):
    """Write `run.tcl` into `design_dir` and return its absolute path."""
    path = os.path.join(os.path.abspath(design_dir), "run.tcl")
    with open(path, "w") as fh:
        fh.write(render_tcl(files, top_module, extra_options))
    return path


def discover_design_files(design_dir):
    """Return the `(type, name)` list for `top.v` / `top.cst` / `top.sdc`.

    Discovery is by extension, so a design whose top module is not `top`
    still resolves (F12).
    """
    design_dir = os.path.abspath(design_dir)
    out = []
    for kind, pattern in (("verilog", "*.v"), ("cst", "*.cst"), ("sdc", "*.sdc")):
        hits = sorted(
            os.path.basename(p) for p in glob.glob(os.path.join(design_dir, pattern))
        )
        if not hits:
            raise OracleError(f"no {kind} source ({pattern}) in {design_dir}")
        out.extend((kind, name) for name in hits)
    return out


# --------------------------------------------------------------------------
# 2. Pre-flight (F59, binding) and the install check (F64)
# --------------------------------------------------------------------------

@dataclass
class Preflight:
    ok: bool
    returncode: int
    reason: str
    unknown_option_lines: list = field(default_factory=list)
    error_lines: list = field(default_factory=list)
    licence_lines: list = field(default_factory=list)


def preflight(log_text, returncode):
    """Assert a `gw_sh` log is trustworthy.

    Fails on any `unknown option:` line **even when `returncode == 0`** — the
    measured behaviour is warn-and-exit-zero (F59), so exit status alone
    proves nothing.
    """
    lines = log_text.splitlines()
    unknown = [ln.strip() for ln in lines if UNKNOWN_OPTION_MARKER in ln]
    licence = [
        ln.strip() for ln in lines
        if any(m.lower() in ln.lower() for m in LICENCE_MARKERS)
    ]
    errors = [ln.strip() for ln in lines if "Error" in ln]

    reasons = []
    if unknown:
        reasons.append(
            f"{len(unknown)} '{UNKNOWN_OPTION_MARKER}' line(s) in the gw_sh log "
            f"(gw_sh exits zero on these, F59)"
        )
    if licence:
        reasons.append(f"{len(licence)} licence-failure line(s) in the gw_sh log")
    if errors:
        reasons.append(f"{len(errors)} 'Error' line(s) in the gw_sh log")
    if returncode != 0:
        reasons.append(f"gw_sh exited {returncode}")

    return Preflight(
        ok=not reasons,
        returncode=returncode,
        reason="; ".join(reasons) if reasons else "ok",
        unknown_option_lines=unknown,
        error_lines=errors,
        licence_lines=licence,
    )


def selected_gowinhome():
    """The oracle-of-record install recorded by `P0.T05` (`gowinhome.selected`,
    now at `$OTC/evidence/_runs/gowinhome.selected`, `C10`/`D80`)."""
    try:
        root = evidence.evidence_root()
    except evidence.EvidenceSchemaError:
        return None
    path = os.path.join(root, "_runs", "gowinhome.selected")
    if os.path.isfile(path):
        with open(path) as fh:
            home = fh.read().strip()
        if home:
            return home
    return None


#: Installs known to this box, tried last so a stale `gowinhome.selected` (the
#: Education tree was removed from the Desktop on 2026-09-04) does not strand
#: a run that has a usable install sitting right there.
KNOWN_INSTALLS = (
    "/Applications/GowinIDE.app/Contents/Resources/Gowin_EDA",
    "/Users/alex/Desktop/GowinIDE.app/Contents/Resources/Gowin_EDA",
)


def resolve_gowinhome(gowinhome=None):
    """Resolution order: explicit argument, `$GOWINHOME`, `gowinhome.selected`,
    then any known install that still exists.

    An explicit argument or `$GOWINHOME` that does not exist is an error, never
    a silent fallback: the caller asked for that install by name.
    """
    for named in (gowinhome, os.environ.get("GOWINHOME")):
        if named:
            if not os.path.isdir(named):
                raise OracleError(f"GOWINHOME {named!r} is not a directory")
            return named
    for candidate in (selected_gowinhome(),) + KNOWN_INSTALLS:
        if candidate and os.path.isdir(candidate):
            return candidate
    raise OracleError(
        "no Gowin install: pass --gowinhome, export GOWINHOME, or record "
        "evidence/_runs/gowinhome.selected"
    )


def gwsh_path(gowinhome):
    return os.path.join(gowinhome, "IDE", "bin", "gw_sh")


def gwsh_env(gowinhome, base=None):
    """The environment of record (`D17`, F65).

    Both `DYLD_LIBRARY_PATH` and `DYLD_FRAMEWORK_PATH` are required: without
    the latter `gw_sh` looks for `/Library/Frameworks/Tcl.framework` and
    fails. No `LD_PRELOAD` is ever injected (the Linux `libfontconfig`
    preload of `legacy/codegen.py:270` is dropped, not ported).
    """
    env = dict(os.environ if base is None else base)
    lib = os.path.join(gowinhome, "IDE", "lib")
    env["GOWINHOME"] = gowinhome
    env["DYLD_LIBRARY_PATH"] = lib
    env["DYLD_FRAMEWORK_PATH"] = lib
    env.pop("LD_PRELOAD", None)
    return env


def ide_version(gowinhome):
    """The install's version string, via apicula's own detector."""
    try:
        from apycula import fse_parser
        return fse_parser.detect_ide_version(gowinhome)
    except Exception:
        m = re.search(r"(\d+\.\d+\.\d+(?:\.\d+)?)", gowinhome)
        return m.group(1) if m else "unknown"


def is_education(gowinhome):
    return "Education" in gowinhome or gowinhome.startswith(
        "/Users/alex/Desktop/GowinIDE.app"
    )


def check_install(gowinhome, timeout=PREFLIGHT_TIMEOUT_S):
    """Run a trivial Tcl script and classify the install.

    Returns a dict with `verdict` in
    `ok` | `licence-failed` | `timeout` | `missing` | `error`. The timeout is
    what keeps a licence-server lookup from hanging the batch (F64): the
    Standard install at `/Applications/GowinIDE.app` prints
    `License verification failed  Connection timeout.` and exits before
    executing any Tcl.
    """
    binary = gwsh_path(gowinhome)
    if not os.path.isfile(binary):
        return {"gowinhome": gowinhome, "verdict": "missing",
                "detail": f"no gw_sh at {binary}", "returncode": None}
    with tempfile.TemporaryDirectory() as tmp:
        script = os.path.join(tmp, "alive.tcl")
        with open(script, "w") as fh:
            fh.write('puts "TCL_ALIVE $tcl_version"\nexit 0\n')
        started = time.time()
        try:
            proc = subprocess.run(
                [binary, script], cwd=tmp, env=gwsh_env(gowinhome),
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                timeout=timeout,
            )
        except subprocess.TimeoutExpired:
            return {"gowinhome": gowinhome, "verdict": "timeout",
                    "detail": f"gw_sh did not exit within {timeout}s",
                    "returncode": None,
                    "wall_clock_s": round(time.time() - started, 3)}
        out = proc.stdout.decode(errors="replace")
    wall = round(time.time() - started, 3)
    licence = [ln.strip() for ln in out.splitlines()
               if any(m.lower() in ln.lower() for m in LICENCE_MARKERS)]
    if licence:
        return {"gowinhome": gowinhome, "verdict": "licence-failed",
                "detail": licence[0], "returncode": proc.returncode,
                "wall_clock_s": wall}
    if "TCL_ALIVE" in out:
        return {"gowinhome": gowinhome, "verdict": "ok",
                "detail": next(ln.strip() for ln in out.splitlines()
                               if "TCL_ALIVE" in ln),
                "returncode": proc.returncode, "wall_clock_s": wall}
    return {"gowinhome": gowinhome, "verdict": "error",
            "detail": out.strip().splitlines()[-1] if out.strip() else "no output",
            "returncode": proc.returncode, "wall_clock_s": wall}


# --------------------------------------------------------------------------
# 3. Artefact collection (F12, F58)
# --------------------------------------------------------------------------

def collect_artifacts(design_dir, require=True):
    """Resolve every artefact class under `<design-dir>/run/`.

    Discovery is by glob on the extension only — the vendor names artefacts
    after the design's **top module**, so `attosoc` yields `attosoc.sdf`
    (F12). More than one match for a class is a failure naming all matches,
    never a silent `head -1`.
    """
    root = os.path.join(os.path.abspath(design_dir), "run")
    pnr = os.path.join(root, "impl", "pnr")
    gws = os.path.join(root, "impl", "gwsynthesis")
    out = {}
    problems = []
    for cls, where in [(c, pnr) for c in ARTIFACT_CLASSES] + [(SYNTH_CLASS, gws)]:
        hits = sorted(glob.glob(os.path.join(where, f"*.{cls}")))
        out[cls] = hits
        if len(hits) > 1:
            problems.append(f"{cls}: {len(hits)} matches {hits}")
        elif not hits and require and cls in ARTIFACT_CLASSES:
            problems.append(f"{cls}: no match under {where}")
    if problems:
        raise ArtifactCollectionError("; ".join(problems))
    return out


# --------------------------------------------------------------------------
# 4. The `.cst` default assertion (F21, F73, `D20a`-`D20c`)
# --------------------------------------------------------------------------

@dataclass
class CstPort:
    port: str
    pin: str
    attrs: dict = field(default_factory=dict)


_IO_LOC_RE = re.compile(r'^\s*IO_LOC\s+"([^"]+)"\s+(\S+?)\s*;', re.M)
_IO_PORT_RE = re.compile(r'^\s*IO_PORT\s+"([^"]+)"\s+([^;]+);', re.M)


def parse_cst(text):
    """Return `{port: CstPort}` for every pin-assigned port in a `.cst`."""
    ports = {}
    for name, pin in _IO_LOC_RE.findall(text):
        ports[name] = CstPort(port=name, pin=pin)
    for name, body in _IO_PORT_RE.findall(text):
        port = ports.setdefault(name, CstPort(port=name, pin=""))
        for token in body.split():
            if "=" in token:
                key, _, value = token.partition("=")
                port.attrs[key.strip().upper()] = value.strip()
    return ports


def load_pin_banks(gowinhome=None, device=DEVICE, package="PBGA484A"):
    """`{pin_index: bank}` from the install's own package description.

    Read-only use of the shipped device data; no binary is patched or copied.
    """
    home = resolve_gowinhome(gowinhome)
    path = os.path.join(home, "IDE", "data", "device", device, f"{package}.json")
    with open(path) as fh:
        data = json.load(fh)
    return {e["INDEX"]: e.get("BANK") for e in data["PIN_DATA"]}


def check_cst_defaults(text, pin_banks):
    """The three unconditional rules `P0.T20` makes generation-time (F21).

    1. every used pin carries `IO_TYPE`;
    2. every bank named carries a `BANK_VCCIO`;
    3. no `LVCMOS*` on any bank 6 or 7 pin — the PR #423 thermal-hazard
       class (F73). A bank/pull change on this silicon is a live thermal
       hazard, not a cosmetic one.

    Returns a list of error strings; empty means the `.cst` is admissible.
    """
    errors = []
    ports = parse_cst(text)
    banks_seen = {}
    for port in ports.values():
        if not port.pin:
            errors.append(f'port "{port.port}" has IO_PORT attributes but no IO_LOC')
            continue
        if "IO_TYPE" not in port.attrs:
            errors.append(f'port "{port.port}" (pin {port.pin}) has no IO_TYPE')
        bank = pin_banks.get(port.pin)
        if bank is None:
            errors.append(
                f'pin {port.pin} of port "{port.port}" is not an I/O pin of this package'
            )
            continue
        banks_seen.setdefault(bank, False)
        if "BANK_VCCIO" in port.attrs:
            banks_seen[bank] = True
        io_type = str(port.attrs.get("IO_TYPE", "")).upper()
        if bank in (6, 7) and io_type.startswith("LVCMOS"):
            errors.append(
                f'port "{port.port}" (pin {port.pin}) sets {io_type} on bank {bank} '
                f"- LVCMOS* on banks 6/7 is the PR #423 thermal-hazard class (F73)"
            )
    for bank, ok in sorted(banks_seen.items()):
        if not ok:
            errors.append(f"bank {bank} is used but no BANK_VCCIO is set on it")
    return errors


def assert_cst_defaults(cst_path, gowinhome=None):
    """Raise `CstDefaultError` naming every violation in `cst_path`."""
    with open(cst_path) as fh:
        text = fh.read()
    errors = check_cst_defaults(text, load_pin_banks(gowinhome))
    if errors:
        raise CstDefaultError(f"{cst_path}: " + "; ".join(errors))
    return True


# --------------------------------------------------------------------------
# 5. The run itself
# --------------------------------------------------------------------------

def run_gwsh(design_dir, gowinhome=None, timeout=DEFAULT_TIMEOUT_S,
             log_name="gw_sh.log", tcl_name="run.tcl"):
    """Run `gw_sh run.tcl` in `design_dir`, logging to a FILE.

    Foreground with an explicit timeout: `impl/LOOP-BRIEF.md` §4 puts a single
    `gw_sh` run in the foreground-with-timeout class (the detach-and-watchdog
    rule covers fuzz campaigns and batches). The log is a real file, never a
    filter pipe.
    """
    design_dir = os.path.abspath(design_dir)
    home = resolve_gowinhome(gowinhome)
    binary = gwsh_path(home)
    if not os.path.isfile(binary):
        raise OracleError(f"no gw_sh at {binary}")
    log_path = os.path.join(design_dir, log_name)
    started = time.time()
    with open(log_path, "wb") as log:
        try:
            proc = subprocess.run(
                [binary, tcl_name], cwd=design_dir, env=gwsh_env(home),
                stdout=log, stderr=subprocess.STDOUT, timeout=timeout,
            )
            returncode = proc.returncode
            timed_out = False
        except subprocess.TimeoutExpired:
            returncode = None
            timed_out = True
    wall = round(time.time() - started, 3)
    with open(log_path, errors="replace") as fh:
        log_text = fh.read()
    if timed_out:
        raise OracleError(
            f"gw_sh did not exit within {timeout}s; log at {log_path}"
        )
    return {"log_path": log_path, "log_text": log_text,
            "returncode": returncode, "wall_clock_s": wall,
            "gowinhome": home}


def run_oracle(design_dir, gowinhome=None, timeout=DEFAULT_TIMEOUT_S,
               top_module="top", extra_options=(), write_tcl_file=True):
    """Full oracle run: assert the `.cst`, write the Tcl, run, pre-flight, collect."""
    design_dir = os.path.abspath(design_dir)
    home = resolve_gowinhome(gowinhome)
    files = discover_design_files(design_dir)
    for kind, name in files:
        if kind == "cst":
            assert_cst_defaults(os.path.join(design_dir, name), home)
    if write_tcl_file:
        write_tcl(design_dir, files, top_module, extra_options)
    run = run_gwsh(design_dir, home, timeout=timeout)
    pf = preflight(run["log_text"], run["returncode"])
    artefacts = collect_artifacts(design_dir, require=pf.ok)
    return {"design_dir": design_dir, "gowinhome": home, "files": files,
            "preflight": pf, "artefacts": artefacts,
            "log_path": run["log_path"], "returncode": run["returncode"],
            "wall_clock_s": run["wall_clock_s"]}


# --------------------------------------------------------------------------
# 6. Evidence row
# --------------------------------------------------------------------------

def evidence_row(result, run_id, primitive="DFF", shape="smoke",
                 standard_preflight=None):
    home = result["gowinhome"]
    version = ide_version(home)
    edition = "Education" if is_education(home) else "Standard"
    artefacts = result["artefacts"]

    def paths(cls):
        return [{"path": p, "sha256": sha256(p), "bytes": os.path.getsize(p)}
                for p in artefacts.get(cls, [])]

    repo = os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.dirname(os.path.abspath(__file__)))))
    pf = result["preflight"]
    # `evidence.py` (P0.T28) owns the one and only row schema
    # (`spec-harness.md` §6, `evidence.REQUIRED_FIELDS`); `adapt` normalises
    # this fragment onto it and folds the oracle-only measurements
    # (pre-flight detail, the .vo/.vg artefacts) into `notes` rather than
    # inventing extra columns.
    return evidence.adapt({
        "run_id": run_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "primitive": primitive,
        "shape": shape,
        "sweep": {},
        "device": DEVICE,
        "part": PART,
        "device_version": DEVICE_VERSION,
        "ide_version": f"{version} {edition}",
        "edu-provisional": edition == "Education",
        "apicula_sha": git_sha(repo),
        "level": "E0",
        "verdict": "ok" if pf.ok else "aborted",
        "preflight": {
            "ok": pf.ok, "reason": pf.reason, "returncode": pf.returncode,
            "unknown_option_lines": pf.unknown_option_lines,
            "error_lines": pf.error_lines,
        },
        "standard_preflight": standard_preflight,
        "oracle_log": result["log_path"],
        "vendor_fs": paths("fs"),
        "tr": paths("tr"),
        "sdf": paths("sdf"),
        "vo": paths("vo"),
        "vg": paths(SYNTH_CLASS),
        "wall_clock_s": {"oracle": result["wall_clock_s"]},
        "notes": "E0: P0.T19 oracle smoke; no open-flow side at this task id",
    })


def append_evidence(row, slug="oracle-smoke"):
    # Evidence is appended to the *live* pipeline directory (the main
    # checkout), which is the source the worktree copy is rsynced from.
    # The writer, the validation and the append-only guarantee all live in
    # `evidence.py` (P0.T28) -- this is one call site of one writer.
    try:
        return evidence.append_row(evidence.adapt(row), slug)
    except evidence.EvidenceSchemaError as exc:
        raise OracleError(str(exc)) from exc


# --------------------------------------------------------------------------
# 7. CLI
# --------------------------------------------------------------------------

def build_parser():
    """Return this module's argparse parser.

    Every harness module parser carries a required `--design-dir` so no
    harness command depends on the current working directory
    (`spec-harness.md` §1, `spec.md` V5/V6).
    """
    parser = argparse.ArgumentParser(prog="fuzz.gw5ast138c.harness.oracle")
    parser.add_argument(
        "--design-dir",
        required=True,
        help="Directory holding the test design for this run (never inferred from cwd).",
    )
    parser.add_argument("--gowinhome", default=None,
                        help="Gowin install to use; default $GOWINHOME then "
                             "evidence/_runs/gowinhome.selected.")
    parser.add_argument("--top-module", default="top")
    parser.add_argument("--extra-option", action="append", default=[],
                        help="Extra `set_option` argument string, repeatable.")
    parser.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT_S)
    parser.add_argument("--run-id", default=None)
    parser.add_argument("--check-install", action="append", default=[],
                        metavar="GOWINHOME",
                        help="Pre-flight one install (licence/Tcl liveness) and "
                             "report; repeatable. With --preflight-only, no build runs.")
    parser.add_argument("--preflight-only", action="store_true")
    parser.add_argument("--no-evidence", action="store_true")
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)

    install_reports = []
    for home in args.check_install:
        report = check_install(home, timeout=PREFLIGHT_TIMEOUT_S)
        install_reports.append(report)
        print(f"PREFLIGHT install={report['gowinhome']} "
              f"verdict={report['verdict']} detail={report['detail']!r}")
    if args.preflight_only:
        return 0 if all(r["verdict"] == "ok" for r in install_reports) else 1

    result = run_oracle(args.design_dir, args.gowinhome, timeout=args.timeout,
                        top_module=args.top_module,
                        extra_options=args.extra_option)
    pf = result["preflight"]
    print(f"PREFLIGHT run ok={pf.ok} returncode={pf.returncode} reason={pf.reason}")
    for cls in ARTIFACT_CLASSES + (SYNTH_CLASS,):
        for path in result["artefacts"].get(cls, []):
            print(f"ARTEFACT {cls} {path} {os.path.getsize(path)} {sha256(path)}")
    if not args.no_evidence:
        run_id = args.run_id or f"oracle-smoke-smoke-{int(time.time())}"
        standard = next((r for r in install_reports
                         if r["gowinhome"] != result["gowinhome"]), None)
        path = append_evidence(evidence_row(result, run_id,
                                            standard_preflight=standard))
        print(f"EVIDENCE {path}")
    return 0 if pf.ok else 1


if __name__ == "__main__":
    sys.exit(main())
