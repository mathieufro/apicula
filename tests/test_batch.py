"""`P0.T22` — the batch runner, the out-of-process watchdog and resumability.

The watchdog tests deliberately observe `WATCHDOG_ARMED` / `WATCHDOG_DEAD` /
the clean-exit line produced by an **independent process** watching a fake
batch, because the fine-line long-running rule is precisely that a watcher
living inside the process it watches proves nothing.
"""
import json
import os
import re
import signal
import subprocess
import sys
import time

import pytest

from fuzz.gw5ast138c.harness import __main__ as batch

HARNESS_DIR = os.path.dirname(
    os.path.abspath(batch.__file__))
WATCHDOG = os.path.join(HARNESS_DIR, "watchdog.sh")
README = os.path.join(HARNESS_DIR, "README.md")
APICULA_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(HARNESS_DIR)))

COMPLETE_RE = re.compile(
    r"^BATCH_COMPLETE \S+ runs=\d+ ok=\d+ diff=\d+ aborted=\d+$")


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------
def _wait_for(predicate, timeout=60, tick=0.2):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(tick)
    return False


def _read(path):
    if not os.path.isfile(path):
        return ""
    with open(path) as fh:
        return fh.read()


def _arm_watchdog(tmp_path, batch_id, stall_min, poll_s):
    """Start `watchdog.sh` as an independent process. Returns (proc, paths)."""
    paths = batch.batch_paths(batch_id, base=str(tmp_path))
    proc = subprocess.Popen(
        ["bash", WATCHDOG, batch_id, paths["log"], paths["watchdog_log"],
         paths["pidfile"], str(stall_min), str(poll_s)],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        start_new_session=True)
    assert _wait_for(
        lambda: "WATCHDOG_ARMED" in _read(paths["watchdog_log"]), timeout=30), \
        "watchdog never wrote WATCHDOG_ARMED"
    return proc, paths


def _fake_batch(paths, seconds, complete=True):
    """A fake batch process: sleeps, touches its log, then marks completion."""
    batch_id = os.path.basename(paths["log"])[:-len(".log")]
    marker = (f"BATCH_COMPLETE {batch_id} runs=1 ok=1 diff=0 aborted=0"
              if complete else "")
    script = (
        f'for i in $(seq 1 {seconds}); do '
        f'  echo "tick $i" >> "{paths["log"]}"; sleep 1; '
        f'done; '
        + (f'echo "{marker}" >> "{paths["log"]}"' if complete else 'true')
    )
    proc = subprocess.Popen(["bash", "-c", script], start_new_session=True)
    with open(paths["pidfile"], "w") as fh:
        fh.write(f"{proc.pid}\n")
    return proc


def _terminal_lines(text):
    return [ln for ln in text.splitlines()
            if "WATCHDOG_DEAD" in ln or "WATCHDOG_COMPLETE" in ln]


def _seed_row(rows_path, run_id, verdict="ok"):
    os.makedirs(os.path.dirname(rows_path), exist_ok=True)
    with open(rows_path, "a") as fh:
        fh.write(json.dumps({"run_id": run_id, "verdict": verdict,
                             "shape": "fake", "level": "E1"}) + "\n")


# --------------------------------------------------------------------------
# 1. watchdog: armed + one terminal line, and the interval floor
# --------------------------------------------------------------------------
@pytest.mark.heavy  # slow: real sleeping subprocess + watchdog poll interval, not toolchain
def test_batch_watchdog_emits_armed_and_terminal(tmp_path):
    # A 10-second expected duration: stall = 10s/10 = 1s -> floored at 5 min.
    stall_min, poll_s = batch.watchdog_intervals(10)
    assert stall_min == 5
    assert poll_s == 100

    proc, paths = _arm_watchdog(tmp_path, "wd-clean", stall_min, poll_s)
    fake = _fake_batch(paths, seconds=10, complete=True)
    try:
        assert _wait_for(
            lambda: _terminal_lines(_read(paths["watchdog_log"])), timeout=90), \
            f"watchdog log had no terminal line:\n{_read(paths['watchdog_log'])}"
        text = _read(paths["watchdog_log"])
        armed = [ln for ln in text.splitlines() if "WATCHDOG_ARMED" in ln]
        assert len(armed) == 1, text
        assert f"stall={stall_min}min" in armed[0]
        assert "stall=5min" in armed[0]
        assert len(_terminal_lines(text)) == 1, text
        assert "WATCHDOG_COMPLETE" in _terminal_lines(text)[0], text
    finally:
        for p in (fake, proc):
            if p.poll() is None:
                p.kill()
        fake.wait()
        proc.wait()


# --------------------------------------------------------------------------
# 2. the completion marker's format
# --------------------------------------------------------------------------
def test_batch_complete_marker_format(tmp_path):
    paths = batch.batch_paths("fmt-001", base=str(tmp_path))
    result = batch.run_batch("fmt-001", "fake", str(tmp_path / "designs"),
                             sweep_points=3, level="E1",
                             runner=batch.fake_runner(0.0), fake=True,
                             paths=paths, echo=False)
    lines = [ln for ln in _read(paths["log"]).splitlines() if ln.strip()]
    last = lines[-1]
    assert COMPLETE_RE.match(last), last
    fields = dict(part.split("=") for part in last.split()[2:])
    runs = int(fields["runs"])
    assert runs == int(fields["ok"]) + int(fields["diff"]) + \
        int(fields["aborted"])
    assert runs == 3
    assert result["executed"] == 3


# --------------------------------------------------------------------------
# 3. resumability: a terminal row is never re-run
# --------------------------------------------------------------------------
def test_batch_resume_skips_terminal_rows(tmp_path):
    paths = batch.batch_paths("resume-001", base=str(tmp_path))
    ids = batch.run_ids("resume-001", "fake", 5)
    for run_id in ids[:3]:
        _seed_row(paths["rows"], run_id)

    executed = []

    def runner(run_id, design_dir, shape, sweep_value, level):
        executed.append(run_id)
        return {"run_id": run_id, "verdict": "ok", "shape": shape,
                "level": level}

    batch.run_batch("resume-001", "fake", str(tmp_path / "designs"),
                    sweep_points=5, level="E1", runner=runner, fake=True,
                    paths=paths, echo=False)
    assert executed == ids[3:], executed
    assert len(executed) == 2
    assert len(batch.load_rows(paths["rows"])) == 5


@pytest.mark.heavy  # slow: real sleeping subprocess + kill/resume timing, not toolchain
def test_batch_resume_after_kill_midway(tmp_path):
    """Kill a real detached batch mid-way, then resume with the SAME command.

    This is the fine-line resumability rule as an experiment rather than a
    fixture: the first invocation is killed while it still has runs left, and
    the identical command finishes the job without redoing anything.
    """
    runs_dir = tmp_path / "_runs"
    runs_dir.mkdir()
    designs = tmp_path / "designs"
    env = dict(os.environ)
    env[batch.RUNS_DIR_ENV] = str(runs_dir)
    env[batch.FAKE_RUN_ENV] = "1.5"
    env["PYTHONPATH"] = APICULA_ROOT
    argv = [sys.executable, "-m", "fuzz.gw5ast138c.harness",
            "--design-dir", str(designs), "--shape", "fake",
            "--sweep-points", "5", "--batch-id", "kill-001"]
    paths = batch.batch_paths("kill-001", base=str(runs_dir))

    proc = subprocess.Popen(argv, cwd=APICULA_ROOT, env=env,
                            stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL,
                            start_new_session=True)
    try:
        assert _wait_for(lambda: len(batch.load_rows(paths["rows"])) >= 2,
                         timeout=60), "batch never produced 2 rows"
    finally:
        os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        proc.wait()
    killed_after = len(batch.load_rows(paths["rows"]))
    assert 2 <= killed_after < 5, killed_after
    assert "BATCH_COMPLETE" not in _read(paths["log"])

    # The identical command, resumed.
    done = subprocess.run(argv, cwd=APICULA_ROOT, env=env,
                          stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                          timeout=180)
    assert done.returncode == 0, done.stdout.decode()
    rows = batch.load_rows(paths["rows"])
    assert len(rows) == 5, rows
    assert len({r["run_id"] for r in rows}) == 5
    last = [ln for ln in _read(paths["log"]).splitlines() if ln.strip()][-1]
    assert COMPLETE_RE.match(last), last
    assert f"runs={5 - killed_after}" in last, last


# --------------------------------------------------------------------------
# 4. watchdog: a death without the marker
# --------------------------------------------------------------------------
@pytest.mark.heavy  # slow: real sleeping subprocess + watchdog poll interval, not toolchain
def test_batch_watchdog_detects_death(tmp_path):
    proc, paths = _arm_watchdog(tmp_path, "wd-dead", 5, 100)
    fake = _fake_batch(paths, seconds=30, complete=False)
    try:
        assert _wait_for(lambda: "tick 1" in _read(paths["log"]), timeout=30)
        os.killpg(os.getpgid(fake.pid), signal.SIGKILL)
        fake.wait()
        assert _wait_for(
            lambda: _terminal_lines(_read(paths["watchdog_log"])), timeout=60), \
            f"watchdog log had no terminal line:\n{_read(paths['watchdog_log'])}"
        text = _read(paths["watchdog_log"])
        dead = [ln for ln in text.splitlines() if "WATCHDOG_DEAD" in ln]
        assert len(dead) == 1, text
        assert "exited WITHOUT BATCH_COMPLETE" in dead[0]
        assert len(_terminal_lines(text)) == 1, text
    finally:
        for p in (fake, proc):
            if p.poll() is None:
                p.kill()
        proc.wait()


# --------------------------------------------------------------------------
# 5/6. the published CLI surface and its README guard
# --------------------------------------------------------------------------
PUBLISHED = ("--design-dir", "--shape", "--sweep-points", "--level",
             "--batch-id", "--detach", "--expected-minutes")


def _parser_flags():
    flags = set()
    for action in batch.build_parser()._actions:
        for opt in action.option_strings:
            if opt != "-h" and opt != "--help":
                flags.add(opt)
    return flags


def test_batch_cli_surface_published(capsys):
    parser = batch.build_parser()
    args = parser.parse_args([
        "--design-dir", "/tmp/d", "--shape", "smoke", "--sweep-points", "3",
        "--level", "E0", "--batch-id", "b1", "--detach",
        "--expected-minutes", "60"])
    assert args.design_dir == "/tmp/d"
    assert args.shape == "smoke"
    assert args.sweep_points == 3
    assert args.level == "E0"
    assert args.batch_id == "b1"
    assert args.detach is True
    assert args.expected_minutes == 60

    assert _parser_flags() == set(PUBLISHED)

    with pytest.raises(SystemExit) as exc:
        parser.parse_args(["--design-dir", "/tmp/d", "--shape", "smoke",
                           "--batch-id", "b1", "--level", "E3"])
    assert exc.value.code != 0

    with pytest.raises(SystemExit) as exc:
        batch.main(["--design-dir", "/tmp/d", "--shape", "smoke",
                    "--batch-id", "b1", "--detach"])
    assert exc.value.code != 0
    err = capsys.readouterr().err
    assert "--detach requires --expected-minutes" in err

    # No synonyms: zero options named --design or --batch.
    assert len([f for f in _parser_flags() if f in ("--design", "--batch")]) == 0


def _readme_option_flags():
    text = _read(README)
    section = text.split("## The published CLI", 1)[1].split("\n## ", 1)[0]
    return set(re.findall(r"\|\s*`(--[a-z-]+)[^`]*`", section))


def test_batch_cli_readme_matches_parser():
    assert os.path.isfile(README), README
    assert _readme_option_flags() == _parser_flags() == set(PUBLISHED)


# --------------------------------------------------------------------------
# The batch head's self-tests need a REFERENCE design pair (P0.T39 defect).
#
# `_selftest_gate` used to pass `os.getcwd()` as `--design-dir`, i.e. the
# apicula checkout, which holds no vendor/open-flow pair at all.  The two head
# gates therefore failed on every real batch and `BATCH_HEAD_BLOCKED` was the
# only reachable outcome.  The guard below is what was missing: it asserts the
# gate is pointed at the smoke pair, not at the cwd and not at the batch's own
# (still empty) design directory.
# --------------------------------------------------------------------------
def test_selftest_gate_uses_the_smoke_pair_not_cwd(monkeypatch):
    from fuzz.gw5ast138c.harness import __main__ as batch
    from fuzz.gw5ast138c.harness import oracle

    monkeypatch.delenv(batch.SELFTEST_DIR_ENV, raising=False)
    assert batch.selftest_dir() == oracle.SMOKE_DIR
    assert batch.selftest_dir() != os.getcwd()


def test_selftest_gate_dir_is_overridable(monkeypatch, tmp_path):
    from fuzz.gw5ast138c.harness import __main__ as batch

    monkeypatch.setenv(batch.SELFTEST_DIR_ENV, str(tmp_path))
    assert batch.selftest_dir() == str(tmp_path)


def test_selftest_gate_passes_that_dir_to_selftest(monkeypatch, tmp_path):
    from fuzz.gw5ast138c.harness import __main__ as batch
    from fuzz.gw5ast138c.harness import selftest

    monkeypatch.setenv(batch.SELFTEST_DIR_ENV, str(tmp_path))
    seen = {}

    def fake_main(argv):
        seen["argv"] = list(argv)
        return 0

    monkeypatch.setattr(selftest, "main", fake_main)
    gate = batch._selftest_gate("--inject-one-fuse")
    assert gate() == 0
    assert seen["argv"] == ["--design-dir", str(tmp_path), "--inject-one-fuse"]


# --------------------------------------------------------------------------
# The batch runner must assemble a real §6 row (P0.T39 defect).
#
# `real_runner` used to hand-build a row and then `row.update(verdict)` the
# checker's `E0Result` dataclass into it, which raised
# `TypeError: 'E0Result' object is not iterable` on every real batch: the run
# always came back `verdict=aborted` and the phase's E2E slug stayed empty.
# The guards below pin the seam: the checker publishes a fragment, and the
# fragment folds into a row that satisfies `evidence.validate_row`.
# --------------------------------------------------------------------------
def test_equiv_publishes_a_schema_fragment():
    from fuzz.gw5ast138c.harness import equiv, evidence

    result = equiv.E0Result()
    fragment = equiv.evidence_fields(result)
    assert set(fragment) <= set(evidence.REQUIRED_FIELDS)
    assert fragment["verdict"] in evidence.VERDICTS


def test_equiv_fragment_verdict_is_the_schema_vocabulary():
    from fuzz.gw5ast138c.harness import equiv

    clean = equiv.E0Result(diff_count={"cells": 0, "attrs": 0, "conns": 0,
                                       "pips": 17})
    assert equiv.evidence_fields(clean)["verdict"] == "ok"

    dirty = equiv.E0Result(diff_count={"cells": 1, "attrs": 0, "conns": 0,
                                       "pips": 0})
    assert equiv.evidence_fields(dirty)["verdict"] == "diff"

    unexplained = equiv.E0Result(
        diff_count={"cells": 0, "attrs": 0, "conns": 0, "pips": 0},
        residual={"unexplained_bits": [[1, 2, "t", 3]]})
    assert equiv.evidence_fields(unexplained)["verdict"] == "diff"


def test_equiv_fragment_folds_into_a_valid_row():
    from fuzz.gw5ast138c.harness import equiv, evidence

    result = equiv.E0Result()
    row = evidence.adapt({"run_id": "b-smoke-0000", "primitive": "DFF",
                          "shape": "smoke", "level": "E0"},
                         **equiv.evidence_fields(result))
    evidence.validate_row(row)          # raises if the seam drifts again
    assert set(row) == set(evidence.REQUIRED_FIELDS)


# --------------------------------------------------------------------------
# `BATCH_SIZE source=` must be P0.T34's measurement, not the ASSUMED fallback
# (P0.T39 defect: the ledger stated the number only inside a three-addend
# worked derivation, which the reader's adjacency window could not reach, so
# every batch silently sized itself off spec.md §8.2's 35-minute ASSUMED row).
# --------------------------------------------------------------------------
def test_measured_budget_is_machine_readable(tmp_path, monkeypatch):
    from fuzz.gw5ast138c.harness import __main__ as batch
    from fuzz.gw5ast138c.harness import evidence

    root = tmp_path / "evidence"
    (root / "calibration").mkdir(parents=True)
    (root / "calibration" / "measured-budget.md").write_text(
        "# derivation\n"
        "measured_per_run_total = oracle + yosys + nextpnr\n"
        "                        = 23.144 + 5.064 + 13.273\n"
        "                        = 41.481 s\n\n"
        "```\nmeasured_per_run_total = 41.481 s\n```\n")
    monkeypatch.setenv(evidence.EVIDENCE_ROOT_ENV, str(root))

    seconds, source = batch.measured_per_run_total()
    assert source != "ASSUMED"
    assert abs(seconds - 41.481) < 1e-6      # not truncated to 41
    assert batch.batch_size()[0] == 867      # P0.T34's recorded number


def test_the_real_measured_budget_is_readable():
    """The checked-in ledger itself, not a fixture."""
    from fuzz.gw5ast138c.harness import __main__ as batch

    seconds, source = batch.measured_per_run_total()
    assert source != "ASSUMED", "P0.T34's measured-budget.md is unreadable again"
    assert seconds > 0


def test_equiv_fragment_decode_check_is_only_c1_c2():
    """`validate_row` rejects any other key; the diagnostics go to `notes`."""
    from fuzz.gw5ast138c.harness import equiv, evidence

    result = equiv.E0Result(decode_check={
        "c1": "ok", "c2": "ok", "c1_missing": [], "c2_differing_bytes": 0})
    fragment = equiv.evidence_fields(result)
    assert set(fragment["decode_check"]) == {"c1", "c2"}
    assert "c1_missing" in fragment["notes"]
    evidence.validate_row(evidence.adapt(
        {"run_id": "b-smoke-0000", "shape": "smoke", "level": "E0"},
        **fragment))
