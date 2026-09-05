"""`P0.T43` / `S23b` -- prove the local gate's push-time behaviour.

Owner ruling (C12/D94/D95, 2026-09-05): there is no pre-commit hook any
more, and `.githooks/pre-push` never refuses a push -- it always exits 0.
The old premise of this file (a blocking pre-commit and a blocking
pre-push that refuse a real commit/push) is gone, and with it the old
heavyweight machinery: `FAST_MUTATION_FILE`/`HEAVY_MUTATION_FILE` mutating
real test files, a real yosys/nextpnr/gowin_pack build via `make all`,
copying built chipdbs and symlinking a real `nextpnr` checkout into the
scratch clone, and 1800 s subprocess timeouts sized for that real build.

What actually needs proving now is much smaller, and is proven cheaply
against a real scratch git clone + local bare "remote" with `make` stubbed
on `PATH` (no real chipdb/nextpnr/yosys involved at all):

  (a) pushing a task branch runs the gate ZERO times and the push succeeds
      immediately (the ref moves) -- "task-branch push runs no gate".
  (b) pushing a ref matching main/dev/integration/*/epic/* still lets the
      push succeed immediately (pre-push always exits 0) AND spawns a
      detached process that -- after a short poll, since the hook returns
      before the background job necessarily finishes -- writes a
      `<repo>-<branch>-<sha>.result` file under
      `open-toolchain/evidence/_gates/` containing `PASS` -- "epic-branch
      push spawns a detached gate that writes a marker".

The stubbed `make` is a pure no-op that exits 0; per the real hook body
(`.githooks/pre-push`), the *hook itself* -- not `make` -- redirects the
outcome of `make -C "$root" gate GATE_SCOPE=branch` into the `.result`
marker (`PASS` on a zero exit, `FAIL` otherwise), so a no-op stub is
sufficient to prove the marker gets written.

The old module-level `GATE_BLOCKS_NESTED` guard existed because a real
`make gate` recursively re-ran `pytest tests`, including this file --
unbounded recursion into the same scratch clone. With `make` stubbed to a
no-op, nothing here ever re-invokes pytest, so that recursion hazard does
not exist any more; the guard is dropped rather than carried forward as
dead weight.
"""
import os
import shutil
import subprocess
import time

import pytest

from fuzz.gw5ast138c.harness import paths

pytestmark = [
    # Excluded from fast/full/all (gate.mk filters `gate_proof` out of every
    # scope): each test here does a real `git push` through the real
    # pre-push hook against a scratch clone -- not something an automatic
    # scope should be doing on every run. Run explicitly:
    # `pytest tests/test_gate_blocks.py -q -m gate_proof`.
    pytest.mark.gate_proof,
]

DATASTORE = paths.datastore()
SCRATCH_ROOT = os.path.join(DATASTORE, "gate-blocks")
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Env any nested `git` call in this module should use: if this pytest run
# is itself happening inside a git hook (GIT_DIR/GIT_WORK_TREE/GIT_INDEX_FILE
# exported by the outer git process), those must not leak into the git
# subprocesses this module spawns against the *scratch* clone.
_GIT_ENV = {k: v for k, v in os.environ.items()
            if k not in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE")}


def _run(cmd, cwd, env=None):
    return subprocess.run(cmd, cwd=cwd, env=(env or _GIT_ENV),
                           capture_output=True, text=True, timeout=60)


def _rev_parse(repo, ref="HEAD"):
    proc = _run(["git", "rev-parse", ref], repo)
    assert proc.returncode == 0, proc.stderr
    return proc.stdout.strip()


def _rev_parse_or_none(repo, ref):
    """Like `_rev_parse`, but `None` if `ref` does not exist yet in `repo`
    (a brand-new bare remote has no branches at all)."""
    proc = _run(["git", "rev-parse", "--verify", ref], repo)
    return proc.stdout.strip() if proc.returncode == 0 else None


def _wait_for(predicate, timeout=5, tick=0.1):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(tick)
    return predicate()


@pytest.fixture
def scratch_clone():
    """A fresh clone of this repo's current branch, plus a local bare
    "remote" and a stubbed `make` on `PATH` -- never a real remote, never a
    real `make gate` invocation."""
    if os.path.isdir(SCRATCH_ROOT):
        shutil.rmtree(SCRATCH_ROOT)
    os.makedirs(SCRATCH_ROOT, exist_ok=True)

    branch = _run(["git", "rev-parse", "--abbrev-ref", "HEAD"],
                   REPO_ROOT).stdout.strip()

    bare = os.path.join(SCRATCH_ROOT, "bare.git")
    _run(["git", "init", "--bare", "--quiet", bare], SCRATCH_ROOT)

    clone = os.path.join(SCRATCH_ROOT, "clone")
    proc = _run(["git", "clone", "--quiet", "--branch", branch, REPO_ROOT,
                 clone], SCRATCH_ROOT)
    assert proc.returncode == 0, proc.stderr

    _run(["git", "config", "user.email", "gate-blocks@example.invalid"], clone)
    _run(["git", "config", "user.name", "gate-blocks"], clone)
    proc = _run(["git", "config", "core.hooksPath", ".githooks"], clone)
    assert proc.returncode == 0, proc.stderr

    # `git clone` clones committed history, not the working tree -- this
    # module means to prove the hook file as it stands on disk right now
    # (which may be an uncommitted edit, per the standing convention of
    # landing hook changes in the same commit as the code they gate), so
    # the clone's `.githooks/` is replaced with the real working tree's
    # copy rather than whatever the last commit carried.
    real_hooks = os.path.join(REPO_ROOT, ".githooks")
    clone_hooks = os.path.join(clone, ".githooks")
    shutil.rmtree(clone_hooks, ignore_errors=True)
    shutil.copytree(real_hooks, clone_hooks)

    # `git clone <REPO_ROOT> <clone>` already points `origin` at REPO_ROOT;
    # repoint it at the scratch bare remote, the only "remote" this module
    # ever pushes to.
    _run(["git", "remote", "set-url", "origin", bare], clone)

    # A stubbed `make` that never builds or re-runs pytest: `git gate` (via
    # the hook) is a no-op that exits 0 and logs its argv, so the hook's own
    # `.result` marker logic gets exercised without any real toolchain work.
    stub_dir = os.path.join(SCRATCH_ROOT, "bin")
    os.makedirs(stub_dir, exist_ok=True)
    calls_log = os.path.join(SCRATCH_ROOT, "make-calls.log")
    stub_make = os.path.join(stub_dir, "make")
    with open(stub_make, "w") as fh:
        fh.write(f'#!/bin/sh\necho "$@" >> {calls_log}\nexit 0\n')
    os.chmod(stub_make, 0o755)

    env = dict(_GIT_ENV)
    env["PATH"] = f"{stub_dir}:{env['PATH']}"

    yield {"clone": clone, "bare": bare, "branch": branch, "env": env,
           "calls_log": calls_log}

    shutil.rmtree(SCRATCH_ROOT, ignore_errors=True)


def _gate_evidence_dir(clone):
    """Mirrors the hook's own OTC resolution: `$root/../open-toolchain` if
    it exists, else `$root/open-toolchain`. The scratch clone's parent
    (a throwaway tmp dir) never has an `open-toolchain` sibling, so this
    always resolves to the fallback, entirely inside the scratch clone."""
    return os.path.join(clone, "open-toolchain", "evidence", "_gates")


def test_task_branch_push_runs_no_gate(scratch_clone):
    """A task-branch push -- a ref that matches none of
    main/dev/integration/*/epic/* -- never invokes `make` and the push
    succeeds immediately.

    Deliberately NOT `scratch_clone["branch"]` (the real ambient branch this
    suite happens to run from): when this module itself runs from a
    checkout of `epic/gw5ast138c` (e.g. right after landing this change on
    the epic tip), that ambient branch name matches `epic/*` and would
    make this "task branch" case gate for real -- exactly the false
    negative a hardcoded, always-task-shaped ref name avoids."""
    clone = scratch_clone["clone"]
    bare = scratch_clone["bare"]
    branch = "clocking/gate-blocks-task-proof"
    env = scratch_clone["env"]
    calls_log = scratch_clone["calls_log"]

    before_remote = _rev_parse_or_none(bare, branch)

    marker = os.path.join(clone, "GATE_BLOCKS_TASK_PROOF.md")
    with open(marker, "w") as fh:
        fh.write("task-branch push proof\n")
    _run(["git", "add", "GATE_BLOCKS_TASK_PROOF.md"], clone)
    commit_proc = _run(["git", "commit", "-m", "gate-blocks: task push"],
                        clone, env=env)
    assert commit_proc.returncode == 0, commit_proc.stderr

    push_proc = _run(["git", "push", "origin", f"HEAD:refs/heads/{branch}"], clone,
                      env=env)
    assert push_proc.returncode == 0, (
        f"stdout={push_proc.stdout!r} stderr={push_proc.stderr!r}")

    after_remote = _rev_parse(bare, branch)
    assert after_remote != before_remote, "the ref did not move on a task-branch push"

    # No gate was ever spawned: give a slow/backgrounded invocation a brief
    # window to appear, then assert it never did.
    appeared = _wait_for(lambda: os.path.isfile(calls_log), timeout=2)
    assert not appeared, (
        "make was invoked for a task-branch push: "
        + (open(calls_log).read() if os.path.isfile(calls_log) else ""))


def test_epic_branch_push_spawns_detached_gate(scratch_clone):
    """A push to an `epic/*` ref succeeds immediately (pre-push always
    exits 0) and spawns a detached gate that writes a PASS marker."""
    clone = scratch_clone["clone"]
    bare = scratch_clone["bare"]
    env = scratch_clone["env"]
    epic_ref = "epic/gate-blocks-proof"

    before_remote = _rev_parse_or_none(bare, epic_ref)

    marker = os.path.join(clone, "GATE_BLOCKS_EPIC_PROOF.md")
    with open(marker, "w") as fh:
        fh.write("epic-branch push proof\n")
    _run(["git", "add", "GATE_BLOCKS_EPIC_PROOF.md"], clone)
    commit_proc = _run(["git", "commit", "-m", "gate-blocks: epic push"],
                        clone, env=env)
    assert commit_proc.returncode == 0, commit_proc.stderr
    # The hook computes `git rev-parse --short HEAD` itself, inside the
    # pushed repo, at push time -- match its exact abbreviation length
    # rather than assuming 7 (git widens it under sha collisions).
    short_sha = _run(["git", "rev-parse", "--short", "HEAD"], clone).stdout.strip()

    push_proc = _run(["git", "push", "origin", f"HEAD:refs/heads/{epic_ref}"],
                      clone, env=env)
    assert push_proc.returncode == 0, (
        f"stdout={push_proc.stdout!r} stderr={push_proc.stderr!r}")

    after_remote = _rev_parse(bare, epic_ref)
    assert after_remote != before_remote, "the ref did not move on an epic-branch push"

    repo = os.path.basename(clone)
    safe_ref = epic_ref.replace("/", "-")
    result_path = os.path.join(
        _gate_evidence_dir(clone), f"{repo}-{safe_ref}-{short_sha}.result")

    got = _wait_for(lambda: os.path.isfile(result_path), timeout=5)
    assert got, f"no .result marker appeared at {result_path}"
    assert open(result_path).read().strip() == "PASS", open(result_path).read()
