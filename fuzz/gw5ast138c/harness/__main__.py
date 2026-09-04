"""Entry point: one shape, one sweep, one batch (`P0.T22`).

The **published CLI** of this module is the single contract every later phase
quotes (`F11`, cross-phase `F29`); it is written out verbatim in
`fuzz/gw5ast138c/harness/README.md` and guarded by
`tests/test_batch.py::test_batch_cli_readme_matches_parser`.

Canonical spellings, binding on every later phase:

* the batch entry point is ``python -m fuzz.gw5ast138c.harness`` (the package,
  never ``...harness.__main__``),
* the design flag is ``--design-dir`` (never ``--design``, which belongs to
  ``equiv.py``),
* the batch flag is ``--batch-id`` (never ``--batch``),
* the stall watchdog ships at ``fuzz/gw5ast138c/harness/watchdog.sh`` (never
  ``$PIPE/tools/watchdog.sh``, cross-phase `F30`).

Module rooting is fixed: this module is always addressed as
``fuzz.gw5ast138c.harness`` and run from ``$FL/apicula``; it never depends on
cwd -- the design directory is always passed explicitly via ``--design-dir``.

Long-running discipline (`spec-harness.md` §8, inherited from the fine-line
CLAUDE.md rule -- restated here as *what this code does*, never as an
alternative to it):

* the batch writes to ``$PIPE/evidence/_runs/<batch_id>.log``, a **FILE**, and
  never through a filter pipe (a dead filter deadlocks the producer's write),
* an **out-of-process** watchdog (``watchdog.sh``) is armed *before* the batch
  starts and fires on stall, death **and** completion, judging liveness only
  from the batch pid and log-file mtimes,
* the batch's last act is exactly one line
  ``BATCH_COMPLETE <batch_id> runs=<n> ok=<n> diff=<n> aborted=<n>``; the
  watchdog's clean-exit verdict is the presence of that line, not the process
  having exited.
"""
import argparse
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
WATCHDOG = os.path.join(HERE, "watchdog.sh")

#: Where the batch log, the watchdog log, the pidfile and the batch's evidence
#: rows live (`D41`; this phase owns `$PIPE/evidence/_runs/**`).  The pipeline
#: directory exists in two places during this epic -- the umbrella worktree
#: (day-to-day code work) and the main checkout -- and the same resolution
#: order `oracle.py` and `tests/conftest.py` use is repeated here.
_PIPE_CANDIDATES = (
    "/Users/alex/fine-line/.atelier/worktrees/"
    "2026-09-03-open-toolchain-gw5ast-7e84/.atelier/pipelines/"
    "2026-09-03-open-toolchain-gw5ast-7e84",
    "/Users/alex/fine-line/.atelier/pipelines/"
    "2026-09-03-open-toolchain-gw5ast-7e84",
)

#: Test-only overrides.  They are environment variables rather than CLI flags
#: precisely so the published seven-option surface stays exactly seven options.
RUNS_DIR_ENV = "FUZZ_HARNESS_RUNS_DIR"
FAKE_RUN_ENV = "FUZZ_HARNESS_FAKE_RUN_SECONDS"

#: `spec.md` §8.2 ASSUMED per-run total, used only until `P0.T34` measures it.
ASSUMED_PER_RUN_TOTAL_S = 35 * 60
BATCH_WALL_CLOCK_S = 10 * 3600

#: A run whose evidence row already carries one of these is never re-run
#: (`spec-harness.md` §8 resumability, §6 verdict vocabulary).
TERMINAL_VERDICTS = ("ok", "diff", "aborted", "refused")

COMPLETE_RE = re.compile(
    r"^BATCH_COMPLETE (\S+) runs=(\d+) ok=(\d+) diff=(\d+) aborted=(\d+)$")


class BatchError(Exception):
    """A batch could not be set up or run."""


# --------------------------------------------------------------------------
# 1. Paths
# --------------------------------------------------------------------------
def runs_dir():
    """`$PIPE/evidence/_runs`, created on demand."""
    override = os.environ.get(RUNS_DIR_ENV)
    if override:
        os.makedirs(override, exist_ok=True)
        return override
    for pipe in _PIPE_CANDIDATES:
        if os.path.isdir(os.path.join(pipe, "evidence")):
            path = os.path.join(pipe, "evidence", "_runs")
            os.makedirs(path, exist_ok=True)
            return path
    raise BatchError("no pipeline evidence directory found; set "
                     f"{RUNS_DIR_ENV} to name one")


def batch_paths(batch_id, base=None):
    """Every file one batch owns, all under `$PIPE/evidence/_runs/`."""
    base = base or runs_dir()
    return {
        "log": os.path.join(base, f"{batch_id}.log"),
        "watchdog_log": os.path.join(base, f"{batch_id}.watchdog.log"),
        "pidfile": os.path.join(base, f"{batch_id}.pid"),
        "stdout": os.path.join(base, f"{batch_id}.stdout.log"),
        "rows": os.path.join(base, f"{batch_id}.rows.jsonl"),
    }


# --------------------------------------------------------------------------
# 2. Watchdog intervals and batch sizing (`spec-harness.md` §8)
# --------------------------------------------------------------------------
def watchdog_intervals(expected_seconds):
    """`(stall_minutes, poll_seconds)` for an expected duration.

    stall = expected/10, floored at 5 min and capped at 90 min;
    poll = `min(300 s, stall/3)`.
    """
    stall_min = int(expected_seconds / 10 // 60)
    stall_min = max(5, min(90, stall_min))
    poll_s = max(1, min(300, (stall_min * 60) // 3))
    return stall_min, poll_s


def measured_per_run_total(stream=None):
    """Per-run cost in seconds: `P0.T34`'s measurement, or the ASSUMED value.

    Returns `(seconds, source)`.  When `P0.T34`'s
    `$PIPE/evidence/calibration/measured-budget.md` does not exist yet, the
    ASSUMED number is used and a warning is **printed**, never swallowed.
    """
    for pipe in _PIPE_CANDIDATES:
        path = os.path.join(pipe, "evidence", "calibration",
                            "measured-budget.md")
        if not os.path.isfile(path):
            continue
        with open(path) as fh:
            text = fh.read()
        match = re.search(
            r"measured_per_run_total\D{0,40}?([0-9]+(?:\.[0-9]+)?)\s*(s|sec|seconds|min|minutes)",
            text, re.I)
        if match:
            value = float(match.group(1))
            if match.group(2).lower().startswith("min"):
                value *= 60
            return int(value), path
    print(f"WARNING: no P0.T34 measured-budget.md found; falling back to the "
          f"ASSUMED per-run total of {ASSUMED_PER_RUN_TOTAL_S}s "
          f"(spec.md §8.2 ASSUMED, D51)", file=stream or sys.stdout)
    return ASSUMED_PER_RUN_TOTAL_S, "ASSUMED"


def batch_size(parallelism=1, stream=None):
    """`floor(10 h * parallelism / measured_per_run_total)` (`D51`)."""
    per_run, source = measured_per_run_total(stream)
    return max(1, int(BATCH_WALL_CLOCK_S * parallelism // per_run)), source


# --------------------------------------------------------------------------
# 3. Run ids, evidence rows and resumability
# --------------------------------------------------------------------------
def run_ids(batch_id, shape, count):
    """A batch is a list of run ids -- deterministic, so a resume matches."""
    return [f"{batch_id}-{shape}-{i:04d}" for i in range(count)]


def load_rows(rows_path):
    """Every row written for this batch so far (missing file -> `[]`)."""
    if not os.path.isfile(rows_path):
        return []
    rows = []
    with open(rows_path) as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except ValueError:
                continue
    return rows


def terminal_run_ids(rows):
    """Run ids already carrying a terminal verdict -- the resume skip set."""
    return {r.get("run_id") for r in rows
            if r.get("verdict") in TERMINAL_VERDICTS}


def append_row(rows_path, row):
    os.makedirs(os.path.dirname(rows_path), exist_ok=True)
    with open(rows_path, "a") as fh:
        fh.write(json.dumps(row, sort_keys=True) + "\n")
        fh.flush()
        os.fsync(fh.fileno())
    return rows_path


# --------------------------------------------------------------------------
# 4. The log: a FILE, never a filter pipe
# --------------------------------------------------------------------------
class BatchLog:
    """Append-only line writer over the batch log file.

    Every line is flushed and fsync'd, because the watchdog's only evidence of
    liveness is this file's mtime.
    """

    def __init__(self, path, echo=True):
        self.path = path
        self.echo = echo
        os.makedirs(os.path.dirname(path), exist_ok=True)
        self._fh = open(path, "a")

    def line(self, text):
        stamp = datetime.now(timezone.utc).strftime("%H:%M:%S")
        self._fh.write(f"{stamp} {text}\n")
        self._fh.flush()
        os.fsync(self._fh.fileno())
        if self.echo:
            print(text, flush=True)

    def raw(self, text):
        """A line written verbatim -- the completion marker must be exact."""
        self._fh.write(text + "\n")
        self._fh.flush()
        os.fsync(self._fh.fileno())
        if self.echo:
            print(text, flush=True)

    def close(self):
        self._fh.close()


# --------------------------------------------------------------------------
# 5. The batch head (`roadmap.md` §5.1c / §9)
# --------------------------------------------------------------------------
def _selftest_gate(flag):
    def gate():
        from . import selftest
        return selftest.main(["--design-dir", os.getcwd(), flag])
    return gate


def _preflight_gate():
    def gate():
        from . import oracle
        result = oracle.check_install(oracle.resolve_gowinhome(None))
        if result.get("verdict") != "ok":
            raise BatchError(
                f"gw_sh pre-flight {result.get('verdict')}: "
                f"{result.get('detail')}")
        return 0
    return gate


#: In this order and unconditionally, before any row the batch would produce.
HEAD_GATES = (
    ("selftest --inject-one-fuse", _selftest_gate("--inject-one-fuse")),
    ("selftest --unpacker-completeness",
     _selftest_gate("--unpacker-completeness")),
    ("gw_sh pre-flight", _preflight_gate()),
)


def run_head_gates(log, gates=HEAD_GATES, skip=False):
    """Run the batch head. Returns `(ok, statuses)`.

    A gate that **fails** blocks every row the batch would produce.  A gate
    whose owning task has not landed yet raises `NotImplementedError` from its
    `P0.T18` stub; that is recorded as `unavailable` with a printed warning and
    does not block, because the gate cannot have an opinion before it exists.
    """
    statuses = []
    ok = True
    for name, gate in gates:
        if skip:
            statuses.append({"gate": name, "status": "skipped"})
            log.line(f"BATCH_HEAD {name}: skipped (fake batch)")
            continue
        try:
            rc = gate()
        except NotImplementedError as exc:
            statuses.append({"gate": name, "status": "unavailable",
                             "detail": str(exc)})
            log.line(f"BATCH_HEAD {name}: UNAVAILABLE (stub not yet landed) — "
                     f"{exc}")
            continue
        except Exception as exc:                       # noqa: BLE001
            statuses.append({"gate": name, "status": "failed",
                             "detail": repr(exc)})
            log.line(f"BATCH_HEAD {name}: FAILED — {exc!r}")
            ok = False
            continue
        if rc not in (0, None):
            statuses.append({"gate": name, "status": "failed",
                             "detail": f"exit {rc}"})
            log.line(f"BATCH_HEAD {name}: FAILED — exit {rc}")
            ok = False
        else:
            statuses.append({"gate": name, "status": "ok"})
            log.line(f"BATCH_HEAD {name}: ok")
    return ok, statuses


# --------------------------------------------------------------------------
# 6. One run
# --------------------------------------------------------------------------
def real_runner(run_id, design_dir, shape, sweep_value, level):
    """gen -> oracle -> open flow -> equiv, for one sweep point.

    Returns the evidence row.  `equiv.py` is authored by `P0.T23`-`P0.T26`; a
    stub `equiv` yields a row with the two bitstreams and `verdict: aborted`
    plus a note, never a silent `ok`.
    """
    from . import gen, oracle, openflow

    row = {
        "run_id": run_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "shape": shape,
        "sweep": {},
        "level": level,
        "verdict": "aborted",
        "notes": "",
    }
    spec = gen.load_shape(shape)
    row["primitive"] = spec.primitive
    row["sweep"] = {spec.sweep_axis: sweep_value}
    gen.run(spec, design_dir, sweep_value)

    started = time.time()
    oracle_result = oracle.run_oracle(design_dir, top_module=spec.top_module,
                                      extra_options=spec.extra_gwsh_options)
    row["oracle_log"] = oracle_result["log_path"]
    if not oracle_result["preflight"].ok:
        row["notes"] = f"oracle pre-flight: {oracle_result['preflight'].reason}"
        row["wall_clock_s"] = {"oracle": time.time() - started}
        return row

    open_result = openflow.run_openflow(design_dir, top_module=spec.top_module,
                                        extra_gpio=spec.extra_pack_flags)
    row["wall_clock_s"] = {"total": time.time() - started}
    row["open_fs"] = open_result["fs_path"]
    if not open_result["ok"]:
        row["notes"] = f"open flow failed: {open_result['returncodes']}"
        return row

    try:
        from . import equiv
        # `equiv.py` is authored by P0.T23-P0.T26; `compare_e0` is P0.T23's
        # named entry, `compare` the level-dispatching one P0.T26 adds.
        compare = getattr(equiv, "compare", None) or equiv.compare_e0
        verdict = compare(design_dir, spec, level=level)
    except (ImportError, AttributeError, NotImplementedError, TypeError) as exc:
        row["notes"] = (f"equiv not available at this task id ({exc}); both "
                        f"bitstreams built, comparison deferred")
        return row
    row.update(verdict)
    return row


def fake_runner(seconds):
    """A runner that only burns wall clock -- the fake-batch driver.

    It exists so the watchdog, the completion marker and resumability can be
    exercised end to end without a 35-minute real run (`Done when`: "a fake
    10-second batch").
    """
    def _run(run_id, design_dir, shape, sweep_value, level):
        time.sleep(seconds)
        return {
            "run_id": run_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "shape": shape,
            "sweep": {"fake": sweep_value},
            "level": level,
            "verdict": "ok",
            "notes": f"fake run ({seconds}s), no oracle and no open flow",
        }
    return _run


def resolve_runner():
    fake = os.environ.get(FAKE_RUN_ENV)
    if fake:
        return fake_runner(float(fake)), True
    return real_runner, False


# --------------------------------------------------------------------------
# 7. The batch
# --------------------------------------------------------------------------
def run_batch(batch_id, shape, design_dir, sweep_points=None, level="E1",
              runner=None, fake=None, paths=None, gates=HEAD_GATES,
              echo=True):
    """Run one shape, one sweep, as one resumable batch.

    A batch is a **list of run ids**; a run whose evidence row already exists
    with a terminal verdict is skipped, so a killed batch is restarted with the
    identical command (`spec-harness.md` §8).
    """
    paths = paths or batch_paths(batch_id)
    if runner is None:
        runner, auto_fake = resolve_runner()
        fake = auto_fake if fake is None else fake
    fake = bool(fake)

    log = BatchLog(paths["log"], echo=echo)
    counts = {"ok": 0, "diff": 0, "aborted": 0}
    refused = 0
    try:
        log.line(f"BATCH_START batch={batch_id} shape={shape} level={level} "
                 f"pid={os.getpid()} design_dir={design_dir}")

        head_ok, statuses = run_head_gates(log, gates=gates, skip=fake)
        if not head_ok:
            log.line(f"BATCH_HEAD_BLOCKED batch={batch_id} — no row is "
                     f"produced by this batch")
            log.raw(f"BATCH_COMPLETE {batch_id} runs=0 ok=0 diff=0 aborted=0")
            return {"batch_id": batch_id, "executed": 0, "counts": counts,
                    "skipped": 0, "head": statuses, "head_ok": False,
                    "rows_path": paths["rows"]}

        sweep_values = _sweep_values(shape, sweep_points, fake)
        ids = run_ids(batch_id, shape, len(sweep_values))
        already = terminal_run_ids(load_rows(paths["rows"]))
        sized, source = batch_size(stream=sys.stdout if echo else None)
        log.line(f"BATCH_SIZE batch_runs={sized} source={source} "
                 f"parallelism=1 (this batch: {len(ids)} run ids)")
        log.line(f"BATCH_RESUME batch={batch_id} planned={len(ids)} "
                 f"already_terminal={len(already)}")

        executed = 0
        for run_id, sweep_value in zip(ids, sweep_values):
            if run_id in already:
                log.line(f"RUN_SKIP {run_id} (terminal row already present)")
                continue
            log.line(f"RUN_START {run_id} sweep={sweep_value!r}")
            try:
                row = runner(run_id, os.path.join(design_dir, run_id), shape,
                             sweep_value, level)
            except Exception as exc:                   # noqa: BLE001
                row = {"run_id": run_id,
                       "timestamp": datetime.now(timezone.utc).isoformat(),
                       "shape": shape, "level": level, "verdict": "aborted",
                       "notes": f"runner raised {exc!r}"}
            row.setdefault("run_id", run_id)
            row.setdefault("verdict", "aborted")
            append_row(paths["rows"], row)
            executed += 1
            verdict = row["verdict"]
            if verdict == "refused":
                refused += 1
                counts["aborted"] += 1
            else:
                counts[verdict if verdict in counts else "aborted"] += 1
            log.line(f"RUN_DONE {run_id} verdict={verdict}")

        log.line(f"BATCH_SKIPPED batch={batch_id} n={len(already)} "
                 f"refused={refused} rows={paths['rows']}")
        # The batch's LAST act, exactly one line, exact format.
        log.raw(f"BATCH_COMPLETE {batch_id} runs={executed} "
                f"ok={counts['ok']} diff={counts['diff']} "
                f"aborted={counts['aborted']}")
        return {"batch_id": batch_id, "executed": executed, "counts": counts,
                "skipped": len(already), "head": statuses, "head_ok": True,
                "rows_path": paths["rows"]}
    finally:
        log.close()


def _sweep_values(shape, sweep_points, fake):
    """The sweep points of this batch; default = the shape's full sweep."""
    if fake:
        return list(range(sweep_points if sweep_points else 1))
    from . import gen
    spec = gen.load_shape(shape)
    values = list(gen.sweep_order(spec))
    if sweep_points is not None:
        values = values[:sweep_points]
    return values


# --------------------------------------------------------------------------
# 8. Detach: arm the watchdog FIRST, then start the batch
# --------------------------------------------------------------------------
def detach(argv, batch_id, expected_minutes, paths=None):
    """Arm `watchdog.sh`, then start this same command detached.

    The watchdog is given a *pidfile*, not a pid, so it is genuinely armed
    before the batch process exists.
    """
    paths = paths or batch_paths(batch_id)
    for key in ("pidfile", "log", "watchdog_log"):
        if os.path.exists(paths[key]):
            os.remove(paths[key])
    stall_min, poll_s = watchdog_intervals(expected_minutes * 60)

    watchdog = subprocess.Popen(
        ["bash", WATCHDOG, batch_id, paths["log"], paths["watchdog_log"],
         paths["pidfile"], str(stall_min), str(poll_s)],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        start_new_session=True)
    # The watchdog writes WATCHDOG_ARMED as its first act; wait for the
    # artefact, never assume it.
    deadline = time.time() + 30
    while time.time() < deadline:
        if os.path.isfile(paths["watchdog_log"]):
            with open(paths["watchdog_log"]) as fh:
                if "WATCHDOG_ARMED" in fh.read():
                    break
        time.sleep(0.1)
    else:
        watchdog.kill()
        raise BatchError("watchdog did not arm within 30s")

    child_argv = [a for a in argv if a != "--detach"]
    # A FILE, never a pipe: a dead reader on a pipe deadlocks the producer.
    out = open(paths["stdout"], "ab")
    batch = subprocess.Popen(
        [sys.executable, "-m", "fuzz.gw5ast138c.harness"] + child_argv,
        stdout=out, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
        start_new_session=True, cwd=_apicula_root())
    with open(paths["pidfile"], "w") as fh:
        fh.write(f"{batch.pid}\n")
    print(f"BATCH_DETACHED batch={batch_id} pid={batch.pid} "
          f"watchdog_pid={watchdog.pid} stall={stall_min}min poll={poll_s}s")
    print(f"  batch log:    {paths['log']}")
    print(f"  watchdog log: {paths['watchdog_log']}")
    print(f"  evidence:     {paths['rows']}")
    return {"batch_pid": batch.pid, "watchdog_pid": watchdog.pid,
            "stall_min": stall_min, "poll_s": poll_s, "paths": paths}


def _apicula_root():
    return os.path.dirname(os.path.dirname(os.path.dirname(HERE)))


# --------------------------------------------------------------------------
# 9. The published CLI -- exactly seven options, no synonyms (`F11`, `F29`)
# --------------------------------------------------------------------------
def build_parser():
    """Return this module's argparse parser.

    Every harness module parser carries a required `--design-dir` so no
    harness command depends on the current working directory
    (`spec-harness.md` §1, `spec.md` V5/V6).
    """
    parser = argparse.ArgumentParser(
        prog="fuzz.gw5ast138c.harness",
        description="Run one shape, one sweep, as one resumable batch.")
    parser.add_argument(
        "--design-dir", required=True,
        help="Directory holding the test design for this run (never inferred from cwd).")
    parser.add_argument(
        "--shape", required=True,
        help="A module name under fuzz/gw5ast138c/shapes/.")
    parser.add_argument(
        "--sweep-points", type=int, default=None,
        help="Number of sweep points; default = the shape's full sweep_values length.")
    parser.add_argument(
        "--level", choices=("E0", "E1", "E2"), default="E1",
        help="Comparison level; default E1.")
    parser.add_argument(
        "--batch-id", required=True,
        help="Batch id; also names $PIPE/evidence/_runs/<batch_id>.log.")
    parser.add_argument(
        "--detach", action="store_true",
        help="Run detached with the out-of-process watchdog armed first.")
    parser.add_argument(
        "--expected-minutes", type=int, default=None,
        help="Expected wall clock; sets the watchdog's stall = D/10. Required with --detach.")
    return parser


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.detach and args.expected_minutes is None:
        parser.error("--detach requires --expected-minutes: the watchdog's "
                     "stall threshold is expected duration / 10 and cannot be "
                     "derived without it")

    if args.detach:
        detach(argv, args.batch_id, args.expected_minutes)
        return 0

    result = run_batch(args.batch_id, args.shape, args.design_dir,
                       sweep_points=args.sweep_points, level=args.level)
    return 0 if result["head_ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
