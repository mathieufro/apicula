"""`P0.T43` / `S23b` -- prove the local blocking gate actually blocks.

A gate that runs and is ignored is indistinguishable in a log from a gate
that blocks; these tests prove the difference. Everything happens against a
throwaway clone under `$DATASTORE/gate-blocks/` and a local bare "remote"
(`git init --bare`) -- never a `mathieufro` remote, never the real working
repos. Real golden fixtures and hooks are never touched; only files inside
the scratch clone are mutated, and every mutation is reverted in a
`finally`.

Exit status alone is not sufficient to prove a hook blocks (a hook whose
failure is swallowed by a wrapper still returns non-zero while the ref
moves anyway), so every assertion below also checks that the ref
(`HEAD` for the commit case, the bare remote's branch tip for the push
case) did **not** move on the red run, and **did** move on the green
control.
"""
import os
import shutil
import subprocess

import pytest

DATASTORE = "/Users/alex/fine-line-data/open-toolchain-gw5ast"
SCRATCH_ROOT = os.path.join(DATASTORE, "gate-blocks")
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Every commit/push this module makes in the scratch clone re-invokes the
# gate hooks, which re-run `pytest tests` -- including this file. Without a
# guard that is unbounded recursion into the *same* $DATASTORE/gate-blocks
# scratch directory. `_HOOK_ENV` marks a subprocess as "already inside a
# gate-blocks proof run" so the nested pytest collection skips this module
# instead of recursing.
_NESTED_MARKER = "GATE_BLOCKS_NESTED"
pytestmark = [
    # Excluded from fast/full/all (gate.mk filters `gate_proof` out of every
    # scope) -- each test here does a real commit/push through the real
    # gate, which recursively re-runs the gate; run explicitly instead.
    pytest.mark.gate_proof,
    pytest.mark.skipif(
        os.environ.get(_NESTED_MARKER) == "1",
        reason="nested invocation from inside a gate-blocks proof commit/push"),
]

# tests/test_calibration.py has a pre-existing failure unrelated to the gate
# mechanism (evidence/calibration/runs.jsonl currently carries extra rows
# from concurrent work on this branch, missing the keys those tests expect
# -- not touched here, per the standing rule against fixing another task's
# in-flight work). Excluded only inside this module's own disposable
# scratch clone so the gate-blocks proof exercises the *mechanism*, not
# today's unrelated flakiness elsewhere in the suite.
_KNOWN_UNRELATED_RED = ("tests/test_calibration.py",)

FAST_MUTATION_FILE = "tests/test_mask.py"
FAST_MUTATION_OLD = "assert len(mask.entries) == 6, mask.ids"
FAST_MUTATION_NEW = "assert len(mask.entries) == 999999, mask.ids"

HEAVY_MUTATION_FILE = "tests/test_residual_decode.py"
HEAVY_MUTATION_OLD = "def test_decode_check_c2_bitmap_roundtrip(tmp_path):"
HEAVY_MUTATION_NEW = (
    "def test_decode_check_c2_bitmap_roundtrip(tmp_path):\n"
    "    assert False, 'P0.T43 deliberate mutation'"
)


# When this module runs from inside a git hook (its own real use case: the
# pre-push that gates GATE_SCOPE=full), git has already exported
# GIT_DIR/GIT_WORK_TREE/GIT_INDEX_FILE for the repo performing that push
# (the real apicula checkout). Every nested `git` call here inherits those
# and resolves against the real repo instead of `cwd`, regardless of `-C`
# or the cwd argument -- stripped unconditionally so every git subprocess
# in this module is scoped to the directory it was actually given.
_GIT_ENV = {k: v for k, v in os.environ.items()
            if k not in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE")}
# Every commit/push this module makes carries the nested marker (see
# _NESTED_MARKER above) on top of the cleaned git env.
_HOOK_ENV = dict(_GIT_ENV, **{_NESTED_MARKER: "1"})


def _run(cmd, cwd, env=None, timeout=1800):
    # A push/commit here can trigger a real full-scope gate run (fast +
    # heavy: a real yosys/nextpnr/gowin_pack build, several 34 MB bitstream
    # reads) on a machine that may have other agents' gate runs competing
    # for CPU at the same time -- generous on purpose, not tuned to the
    # gate's own ~90 s design budget.
    return subprocess.run(cmd, cwd=cwd, env=(env or _GIT_ENV),
                           capture_output=True, text=True, timeout=timeout)


def _rev_parse(repo, ref="HEAD"):
    proc = _run(["git", "rev-parse", ref], repo)
    if proc.returncode != 0:
        return None
    return proc.stdout.strip()


def _log_shas(repo, ref="HEAD"):
    proc = _run(["git", "log", "--format=%H", ref], repo)
    return set(proc.stdout.split()) if proc.returncode == 0 else set()


def _mutate(path, old, new):
    text = open(path).read()
    assert old in text, f"expected literal not found in {path}: {old!r}"
    open(path, "w").write(text.replace(old, new, 1))


def _restore(path, new, old):
    text = open(path).read()
    assert new in text, f"mutation to revert not found in {path}: {new!r}"
    open(path, "w").write(text.replace(new, old, 1))


@pytest.fixture
def scratch_clone():
    """A fresh clone of this repo's current branch, plus a local bare
    "remote" -- never a mathieufro remote, never the working repos."""
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

    # The built chipdbs (apycula/*.msgpack.xz) are gitignored build products
    # (Makefile's `all:`), not tracked content -- a handful of fast tests
    # resolve one from disk (openflow.resolve_chipdb() et al.) and fail on
    # any repo checkout that lacks it, cloned or not. Copying the ones
    # already built in REPO_ROOT is the fast-scope equivalent of running
    # `make all` once; it reads REPO_ROOT, never writes to it.
    src_chipdbs = os.path.join(REPO_ROOT, "apycula")
    dst_chipdbs = os.path.join(clone, "apycula")
    for name in os.listdir(src_chipdbs):
        if name.endswith(".msgpack.xz"):
            shutil.copyfile(os.path.join(src_chipdbs, name),
                             os.path.join(dst_chipdbs, name))

    # openflow.provenance()'s nextpnr_sha walks up from the apicula repo to
    # a *sibling* `nextpnr` checkout (the real worktree layout); a symlink
    # to the real one gives the clone the same layout without copying a
    # second git repo.
    real_nextpnr = os.path.join(os.path.dirname(REPO_ROOT), "nextpnr")
    if os.path.isdir(real_nextpnr):
        os.symlink(real_nextpnr, os.path.join(SCRATCH_ROOT, "nextpnr"))

    proc = _run(["git", "config", "user.email", "gate-blocks@example.invalid"], clone)
    proc = _run(["git", "config", "user.name", "gate-blocks"], clone)

    # Drop the one file with a pre-existing, unrelated red (see module
    # docstring/_KNOWN_UNRELATED_RED) from the clone *before* hooks are
    # even configured, so this housekeeping commit is unaffected by the
    # gate and the clone's baseline is genuinely green from here on.
    for rel in _KNOWN_UNRELATED_RED:
        path = os.path.join(clone, rel)
        if os.path.exists(path):
            os.remove(path)
            _run(["git", "add", rel], clone)
    status = _run(["git", "status", "--porcelain"], clone).stdout
    if status.strip():
        _run(["git", "commit", "-m", "gate-blocks scratch: drop known-unrelated-red file"],
             clone)

    proc = _run(["git", "config", "core.hooksPath", ".githooks"], clone)
    assert proc.returncode == 0, proc.stderr

    # `git clone <REPO_ROOT> <clone>` already points `origin` at REPO_ROOT
    # (the real, checked-out working repo) -- `remote add` would no-op
    # against an existing name, silently leaving pushes aimed at the real
    # repo. `set-url` repoints the existing `origin` at the scratch bare
    # remote instead, which is the only "remote" this module ever pushes to.
    _run(["git", "remote", "set-url", "origin", bare], clone)
    # Baseline push: already gated (core.hooksPath is set above), so this
    # also exercises the gate for real, but it must carry the nested marker
    # like every other commit/push below -- otherwise it recurses into a
    # full pytest run that re-collects this very module.
    proc = _run(["git", "push", "--quiet", "origin", f"HEAD:{branch}"], clone,
                 env=_HOOK_ENV)
    assert proc.returncode == 0, proc.stderr

    yield {"clone": clone, "bare": bare, "branch": branch}

    shutil.rmtree(SCRATCH_ROOT, ignore_errors=True)


def test_gate_blocks_a_failing_commit(scratch_clone):
    """A fast-scope failure refuses `git commit`; HEAD does not move."""
    clone = scratch_clone["clone"]
    path = os.path.join(clone, FAST_MUTATION_FILE)
    before = _rev_parse(clone)
    before_log = _log_shas(clone)

    _mutate(path, FAST_MUTATION_OLD, FAST_MUTATION_NEW)
    try:
        _run(["git", "add", FAST_MUTATION_FILE], clone)
        proc = _run(["git", "commit", "-m", "P0.T43 deliberate red commit"],
                     clone, env=_HOOK_ENV)

        assert proc.returncode != 0, (
            f"commit should have been refused; stdout={proc.stdout!r} "
            f"stderr={proc.stderr!r}")
        combined = proc.stdout + proc.stderr
        assert "GATE" in combined and "FAILED" in combined, combined

        after = _rev_parse(clone)
        after_log = _log_shas(clone)
        assert after == before, "HEAD moved on a refused commit"
        assert after_log == before_log, (
            "a new commit object landed on HEAD despite the refusal")
    finally:
        _restore(path, FAST_MUTATION_NEW, FAST_MUTATION_OLD)
        _run(["git", "checkout", "--", FAST_MUTATION_FILE], clone)


def test_gate_allows_a_green_commit(scratch_clone):
    """Negative control: an unmutated commit succeeds and HEAD moves."""
    clone = scratch_clone["clone"]
    before = _rev_parse(clone)

    marker = os.path.join(clone, "GATE_BLOCKS_PROOF.md")
    with open(marker, "w") as fh:
        fh.write("P0.T43 green commit control\n")
    _run(["git", "add", "GATE_BLOCKS_PROOF.md"], clone)
    proc = _run(["git", "commit", "-m", "P0.T43 deliberate green commit"],
                 clone, env=_HOOK_ENV)

    assert proc.returncode == 0, f"stdout={proc.stdout!r} stderr={proc.stderr!r}"
    after = _rev_parse(clone)
    assert after != before, "HEAD did not move on a green commit"


def test_gate_blocks_would_fail_without_hooks(scratch_clone):
    """Meta-assertion: with core.hooksPath unset, the same red commit lands.

    Proves `test_gate_blocks_a_failing_commit` is sensitive to the hook,
    not to some other failure (e.g. a syntax error aborting `git commit`
    itself regardless of hooks).
    """
    clone = scratch_clone["clone"]
    path = os.path.join(clone, FAST_MUTATION_FILE)
    _run(["git", "config", "--unset", "core.hooksPath"], clone)
    before = _rev_parse(clone)

    _mutate(path, FAST_MUTATION_OLD, FAST_MUTATION_NEW)
    try:
        _run(["git", "add", FAST_MUTATION_FILE], clone)
        proc = _run(["git", "commit", "-m", "P0.T43 hookless red commit"],
                     clone, env=_HOOK_ENV)

        assert proc.returncode == 0, (
            "commit should have landed with no hook installed: "
            f"stdout={proc.stdout!r} stderr={proc.stderr!r}")
        after = _rev_parse(clone)
        assert after != before, "HEAD should have moved with no hook installed"
    finally:
        _run(["git", "config", "core.hooksPath", ".githooks"], clone)


def test_gate_blocks_a_failing_push(scratch_clone):
    """A full-scope failure refuses `git push`; the remote ref does not move.

    The mutation is heavy-scope-only, so the fast-scope pre-commit hook
    does not catch it -- the commit lands locally, exactly demonstrating
    why pre-push exists.
    """
    clone = scratch_clone["clone"]
    bare = scratch_clone["bare"]
    branch = scratch_clone["branch"]
    path = os.path.join(clone, HEAVY_MUTATION_FILE)

    before_remote = _rev_parse(bare, branch)

    _mutate(path, HEAVY_MUTATION_OLD, HEAVY_MUTATION_NEW)
    committed = False
    try:
        _run(["git", "add", HEAVY_MUTATION_FILE], clone)
        commit_proc = _run(
            ["git", "commit", "-m", "P0.T43 deliberate heavy-red commit"],
            clone, env=_HOOK_ENV)
        assert commit_proc.returncode == 0, (
            "the heavy-only mutation should pass the fast-scope pre-commit "
            f"hook: stdout={commit_proc.stdout!r} stderr={commit_proc.stderr!r}")
        committed = True

        push_proc = _run(["git", "push", "origin", f"HEAD:{branch}"], clone,
                          env=_HOOK_ENV)

        assert push_proc.returncode != 0, (
            f"push should have been refused; stdout={push_proc.stdout!r} "
            f"stderr={push_proc.stderr!r}")
        combined = push_proc.stdout + push_proc.stderr
        assert "GATE" in combined and "FAILED" in combined, combined

        after_remote = _rev_parse(bare, branch)
        assert after_remote == before_remote, "the bare remote's ref moved on a refused push"
    finally:
        if committed:
            _run(["git", "reset", "--hard", "HEAD~1"], clone)
        if os.path.exists(path) and HEAVY_MUTATION_NEW in open(path).read():
            _restore(path, HEAVY_MUTATION_NEW, HEAVY_MUTATION_OLD)
        _run(["git", "checkout", "--", HEAVY_MUTATION_FILE], clone)


def test_gate_allows_a_green_push(scratch_clone):
    """Negative control: an unmutated push succeeds and the ref moves."""
    clone = scratch_clone["clone"]
    bare = scratch_clone["bare"]
    branch = scratch_clone["branch"]
    before_remote = _rev_parse(bare, branch)

    marker = os.path.join(clone, "GATE_BLOCKS_PUSH_PROOF.md")
    with open(marker, "w") as fh:
        fh.write("P0.T43 green push control\n")
    _run(["git", "add", "GATE_BLOCKS_PUSH_PROOF.md"], clone)
    commit_proc = _run(
        ["git", "commit", "-m", "P0.T43 deliberate green push"], clone,
        env=_HOOK_ENV)
    assert commit_proc.returncode == 0, commit_proc.stderr

    push_proc = _run(["git", "push", "origin", f"HEAD:{branch}"], clone,
                      env=_HOOK_ENV)
    assert push_proc.returncode == 0, (
        f"stdout={push_proc.stdout!r} stderr={push_proc.stderr!r}")

    after_remote = _rev_parse(bare, branch)
    assert after_remote != before_remote, "the bare remote's ref did not move on a green push"
