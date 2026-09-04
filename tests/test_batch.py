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
