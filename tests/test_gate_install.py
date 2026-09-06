"""`P0.T41` / `P0.T42` -- the local gate is installed and wired up
identically in all three working repos (`C8`, `D76`, `D77`).

Owner ruling (C12/D94/D95, 2026-09-05) reshaped the gate: there is no
pre-commit hook any more -- `.githooks/pre-push` is the only hook, and it
only gates a push to `main`/`dev`/`integration/*`/`epic/*`; every other
(task-branch) push gets zero gate. `pre-push` itself never blocks a push --
it spawns `make gate GATE_SCOPE=branch` **detached** and returns
immediately, so a `main`/`dev`/`integration/*`/`epic/*` push completes right
away while the gate runs in the background (watched by an out-of-process
watchdog per fine-line `CLAUDE.md` "Long-running work").

These are structural/wiring tests (hook file present, executable, no
pre-commit hook, never bypasses itself, `core.hooksPath` configured, scope
selection correct); the end-to-end proof that a real push through the real
hook succeeds immediately and spawns a real detached gate is
`test_gate_blocks.py` (`P0.T43`).
"""
import os
import shutil
import subprocess
import time

import pytest

from fuzz.gw5ast138c.harness import paths

pytestmark = [
    # Excluded from fast/full/all (gate.mk filters `gate_proof` out of every
    # scope): the scope-selection tests invoke the real pre-push hook
    # against the real repos and spawn real detached background jobs that
    # write into the real `open-toolchain/evidence/_gates/` -- not
    # something an automatic scope should be doing on every run. Run
    # explicitly: `pytest tests/test_gate_install.py -q -m gate_proof`.
    pytest.mark.gate_proof,
]

#: The umbrella worktree this apicula checkout sits in: its parent directory.
#: `S23b` is about the three checkouts being hooked, and which box they are on
#: is not part of the claim.
WORKTREE = os.path.dirname(paths.repo_root())
REPOS = {
    "apicula": os.path.join(WORKTREE, "apicula"),
    "nextpnr": os.path.join(WORKTREE, "nextpnr"),
    "pipe": WORKTREE,
}


def _run(cmd, cwd):
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)


@pytest.mark.parametrize("name,repo", sorted(REPOS.items()))
def test_no_pre_commit_hook(name, repo):
    """C12/D94: the blocking pre-commit shape is gone; nothing gates a
    commit any more, in any of the three repos."""
    path = os.path.join(repo, ".githooks", "pre-commit")
    assert not os.path.exists(path), (
        f"{name}: {path} exists -- pre-commit hooks were removed (D94)")


@pytest.mark.parametrize("name,repo", sorted(REPOS.items()))
def test_pre_push_is_present_executable_and_returns_promptly(name, repo):
    path = os.path.join(repo, ".githooks", "pre-push")
    assert os.path.isfile(path), f"{name}: missing {path}"
    assert os.access(path, os.X_OK), f"{name}: {path} is not executable"
    body = open(path).read()
    assert "--no-verify" not in body, f"{name}: pre-push bypasses itself"
    # pre-push is now EXPECTED to background the gate itself (a detached
    # `nohup ... &`) rather than block the push -- the opposite of the old
    # foreground-only rule -- but the hook process itself must still return
    # promptly: its last executed statement is an unconditional `exit 0`,
    # never something that waits on the backgrounded work.
    assert "nohup" in body, (
        f"{name}: pre-push does not background the gate via nohup")
    lines = [ln.split("#", 1)[0].rstrip() for ln in body.splitlines()]
    non_empty = [ln for ln in lines if ln.strip()]
    assert non_empty[-1].strip() == "exit 0", (
        f"{name}: pre-push's last statement is {non_empty[-1]!r}, "
        "not 'exit 0' -- it must return promptly")


@pytest.mark.parametrize("name,repo", sorted(REPOS.items()))
def test_hookspath_configured(name, repo):
    proc = _run(["git", "config", "--get", "core.hooksPath"], repo)
    assert proc.returncode == 0, f"{name}: core.hooksPath is not set"
    assert proc.stdout.strip() == ".githooks", (
        f"{name}: core.hooksPath={proc.stdout.strip()!r}, expected '.githooks'")


# --------------------------------------------------------------------------
# scope selection
# --------------------------------------------------------------------------

#: `$OTC/evidence/_gates` as the real pre-push hook resolves it: a sibling
#: `open-toolchain` checkout next to this worktree's repos (real here, per
#: the calling agent -- no need to fake it), else a fallback inside the repo.
_OTC = os.path.join(WORKTREE, "open-toolchain") if os.path.isdir(
    os.path.join(WORKTREE, "open-toolchain")) else os.path.join(
        REPOS["apicula"], "open-toolchain")
_EVIDENCE_DIR = os.path.join(_OTC, "evidence", "_gates")

#: (case name, pushed remote ref, expected GATE_SCOPE or None for "no gate")
SCOPE_CASES = [
    ("task-branch", "refs/heads/some-task-branch", None),
    ("main", "refs/heads/main", "branch"),
    ("dev", "refs/heads/dev", "branch"),
    ("integration", "refs/heads/integration/foo", "branch"),
    ("epic", "refs/heads/epic/gw5ast138c", "branch"),
]


def _stub_make(stub_dir):
    """A `make` on PATH that logs its argv to `$MAKE_CALLS_LOG` (so each
    case gets its own log file, including the one invoked from inside the
    hook's detached `nohup ... &` subshell, which inherits the parent
    process's environment) and exits 0 -- never a real build."""
    stub_make = stub_dir / "make"
    stub_make.write_text(
        "#!/bin/sh\n"
        'echo "$@" >> "${MAKE_CALLS_LOG:-/dev/null}"\n'
        "exit 0\n")
    stub_make.chmod(0o755)


def _wait_for(predicate, timeout=2.0, tick=0.05):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(tick)
    return predicate()


def _cleanup_evidence(id_):
    """Remove every marker file this test's `id_` could have produced.

    The watchdog is its own detached process (spawned by the hook
    alongside the backgrounded `make gate`) and can still be writing its
    `.watchdog.log` a moment after the hook -- and even after the polled
    `.result`/log files above already appeared -- so this sweeps twice
    with a short grace pause to avoid leaving a stray file behind in a
    real checkout."""
    def _sweep():
        for suffix in (".result", ".log", ".pid", ".watchdog.log"):
            path = os.path.join(_EVIDENCE_DIR, id_ + suffix)
            if os.path.exists(path):
                os.remove(path)
    _sweep()
    time.sleep(0.5)
    _sweep()


@pytest.mark.parametrize("case,remote_ref,expected_scope", SCOPE_CASES)
def test_pre_push_scope_selection_disabled_by_default(tmp_path, case, remote_ref, expected_scope):
    """D181 (owner, 2026-09-06): no push runs a gate any more -- landings are
    checked by targeted tests, full gates run once at phase close. Feed the
    real apicula pre-push hook the real git stdin protocol for one remote
    ref, with `make` stubbed on PATH and `LANDING_GATE` unset/`0`: every
    ref, including main/dev/integration/*/epic/*, now gets zero gate."""
    repo = REPOS["apicula"]
    hook = os.path.join(repo, ".githooks", "pre-push")

    stub_dir = tmp_path / "bin"
    stub_dir.mkdir()
    _stub_make(stub_dir)
    log_path = tmp_path / "make-calls.log"

    env = dict(os.environ)
    env["PATH"] = f"{stub_dir}:{env['PATH']}"
    env["MAKE_CALLS_LOG"] = str(log_path)
    env.pop("LANDING_GATE", None)

    stdin = f"refs/heads/task refs/heads/task-sha {remote_ref} remote-sha\n"

    proc = subprocess.run(["sh", hook], cwd=repo, input=stdin,
                           capture_output=True, text=True, env=env)
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout == "", proc.stdout
    time.sleep(0.3)  # generous: catch a stray background spawn
    assert not log_path.exists(), (
        f"{case}: make was invoked even though LANDING_GATE is unset: "
        f"{log_path.read_text() if log_path.exists() else ''}")


@pytest.mark.parametrize("case,remote_ref,expected_scope", SCOPE_CASES)
def test_pre_push_scope_selection_with_landing_gate(tmp_path, case, remote_ref, expected_scope):
    """With `LANDING_GATE=1` set for the push, the pre-D181 behaviour is
    restored verbatim: a task-branch push still gets zero gate, and a
    main/dev/integration/*/epic/* push spawns a detached
    `make gate GATE_SCOPE=branch` -- since the hook returns before that
    background job necessarily finishes, this polls briefly for the stub's
    log file rather than asserting on it right away."""
    repo = REPOS["apicula"]
    hook = os.path.join(repo, ".githooks", "pre-push")

    stub_dir = tmp_path / "bin"
    stub_dir.mkdir()
    _stub_make(stub_dir)
    log_path = tmp_path / "make-calls.log"

    env = dict(os.environ)
    env["PATH"] = f"{stub_dir}:{env['PATH']}"
    env["MAKE_CALLS_LOG"] = str(log_path)
    env["LANDING_GATE"] = "1"

    stdin = f"refs/heads/task refs/heads/task-sha {remote_ref} remote-sha\n"

    sha = _run(["git", "rev-parse", "--short", "HEAD"], repo).stdout.strip()
    safe_ref = remote_ref[len("refs/heads/"):].replace("/", "-")
    id_ = f"apicula-{safe_ref}-{sha}"

    try:
        proc = subprocess.run(["sh", hook], cwd=repo, input=stdin,
                               capture_output=True, text=True, env=env)
        assert proc.returncode == 0, proc.stderr

        if expected_scope is None:
            # A task-branch push gets zero gate: the hook exits immediately,
            # prints nothing, and never invokes `make` at all -- not even in
            # the background, so no brief poll is needed here.
            assert proc.stdout == "" and proc.stderr == "", (
                proc.stdout, proc.stderr)
            time.sleep(0.3)  # generous: catch a stray background spawn
            assert not log_path.exists(), (
                f"make was invoked for a task-branch push: "
                f"{log_path.read_text() if log_path.exists() else ''}")
        else:
            got = _wait_for(lambda: log_path.exists() and log_path.stat().st_size > 0)
            assert got, f"{case}: stub make was never invoked (log never appeared)"
            calls = log_path.read_text().splitlines()
            scopes = []
            for call in calls:
                for tok in call.split():
                    if tok.startswith("GATE_SCOPE="):
                        scopes.append(tok.split("=", 1)[1])
            assert scopes == [expected_scope], (case, scopes)
    finally:
        _cleanup_evidence(id_)
