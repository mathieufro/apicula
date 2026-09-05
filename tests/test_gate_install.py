"""`P0.T41` / `P0.T42` -- the local blocking gate is installed and wired up
identically in all three working repos (`C8`, `D76`, `D77`).

These are structural/wiring tests (hook files present, executable,
foreground, `core.hooksPath` configured, scope selection correct); the
end-to-end proof that a failing check actually refuses a commit/push is
`test_gate_blocks.py` (`P0.T43`).
"""
import os
import shutil
import subprocess

import pytest

from fuzz.gw5ast138c.harness import paths

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
def test_hooks_are_executable_and_foreground(name, repo):
    for hook in ("pre-commit", "pre-push"):
        path = os.path.join(repo, ".githooks", hook)
        assert os.path.isfile(path), f"{name}: missing {path}"
        assert os.access(path, os.X_OK), f"{name}: {path} is not executable"
        body = open(path).read()
        assert "nohup" not in body, f"{name}: {hook} backgrounds via nohup"
        assert "--no-verify" not in body, f"{name}: {hook} bypasses itself"
        # a backgrounding "&" operator (not "&&") would defeat the whole
        # point of a foreground, blocking gate.
        for line in body.splitlines():
            stripped = line.split("#", 1)[0].rstrip()
            if not stripped.endswith("&"):
                continue
            assert stripped.endswith("&&"), (
                f"{name}: {hook} backgrounds a command: {line!r}")


@pytest.mark.parametrize("name,repo", sorted(REPOS.items()))
def test_hookspath_configured(name, repo):
    proc = _run(["git", "config", "--get", "core.hooksPath"], repo)
    assert proc.returncode == 0, f"{name}: core.hooksPath is not set"
    assert proc.stdout.strip() == ".githooks", (
        f"{name}: core.hooksPath={proc.stdout.strip()!r}, expected '.githooks'")


def test_pre_push_scope_selection(tmp_path):
    """Feed the apicula pre-push hook the real git stdin protocol for three
    remote refs, with `make` stubbed on PATH, and assert the recorded
    GATE_SCOPE is all/all/full -- the discriminating case: a hook that
    always runs `full` silently under-gates `main`."""
    repo = REPOS["apicula"]
    hook = os.path.join(repo, ".githooks", "pre-push")

    stub_dir = tmp_path / "bin"
    stub_dir.mkdir()
    log_path = tmp_path / "make-calls.log"
    stub_make = stub_dir / "make"
    stub_make.write_text(
        "#!/bin/sh\n"
        f"echo \"$@\" >> {log_path}\n"
        "exit 0\n")
    stub_make.chmod(0o755)

    env = dict(os.environ)
    env["PATH"] = f"{stub_dir}:{env['PATH']}"

    stdin = (
        "refs/heads/task refs/heads/task-sha "
        "refs/heads/main remote-sha\n"
        "refs/heads/task refs/heads/task-sha "
        "refs/heads/integration remote-sha\n"
        "refs/heads/task refs/heads/task-sha "
        "refs/heads/epic/gw5ast138c remote-sha\n"
    )
    proc = subprocess.run(["sh", hook], cwd=repo, input=stdin,
                           capture_output=True, text=True, env=env)
    assert proc.returncode == 0, proc.stderr

    calls = log_path.read_text().splitlines()
    scopes = []
    for call in calls:
        for tok in call.split():
            if tok.startswith("GATE_SCOPE="):
                scopes.append(tok.split("=", 1)[1])
    assert scopes == ["all", "all", "full"], scopes
