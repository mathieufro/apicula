"""Tests for the `fuzz.gw5ast138c.harness` package skeleton (P0.T18).

Every harness module is an importable stub until its owning task (P0.T19+)
fills it in: it exposes a `main()` that raises NotImplementedError naming the
owning task id, and an argparse parser with a required `--design-dir` option
(`spec-harness.md` §1 — no harness command depends on cwd).
"""
import importlib

import pytest

HARNESS_MODULES = [
    "__main__",
    "gen",
    "oracle",
    "openflow",
    "equiv",
    "attribute",
    "evidence",
    "selftest",
]


@pytest.mark.parametrize("module_name", HARNESS_MODULES)
def test_harness_package_importable(module_name):
    mod = importlib.import_module("fuzz.gw5ast138c.harness." + module_name)
    assert hasattr(mod, "main")
    with pytest.raises(NotImplementedError):
        mod.main([])


@pytest.mark.parametrize("module_name", HARNESS_MODULES)
def test_harness_no_cwd_dependency(module_name):
    mod = importlib.import_module("fuzz.gw5ast138c.harness." + module_name)
    parser = mod.build_parser()
    actions = {action.dest: action for action in parser._actions}
    assert "design_dir" in actions
    assert actions["design_dir"].required
