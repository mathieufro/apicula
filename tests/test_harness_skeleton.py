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
    "oracle",
    "openflow",
    "equiv",
    "attribute",
    "evidence",
    "selftest",
]

# Modules whose owning task has landed. Their `main()` no longer raises
# NotImplementedError; it parses arguments, so `main([])` exits via argparse
# on the missing required `--design-dir`. Each owning task appends its own
# module name here as it lands (P0.T19: oracle; P0.T20: gen;
# P0.T21: openflow; P0.T22: __main__; P0.T23: equiv; P0.T27: attribute;
# P0.T28: evidence; P0.T29: selftest; ...).
IMPLEMENTED_MODULES = [
    "oracle",
    "openflow",
    "__main__",
    "equiv",
    "attribute",
    "evidence",
    "selftest",
]

STUB_MODULES = [m for m in HARNESS_MODULES if m not in IMPLEMENTED_MODULES]


@pytest.mark.parametrize("module_name", STUB_MODULES)
def test_harness_package_importable(module_name):
    mod = importlib.import_module("fuzz.gw5ast138c.harness." + module_name)
    assert hasattr(mod, "main")
    with pytest.raises(NotImplementedError):
        mod.main([])


@pytest.mark.parametrize("module_name", IMPLEMENTED_MODULES)
def test_harness_implemented_module_requires_design_dir(module_name):
    mod = importlib.import_module("fuzz.gw5ast138c.harness." + module_name)
    assert hasattr(mod, "main")
    with pytest.raises(SystemExit):
        mod.main([])


@pytest.mark.parametrize("module_name", HARNESS_MODULES)
def test_harness_no_cwd_dependency(module_name):
    mod = importlib.import_module("fuzz.gw5ast138c.harness." + module_name)
    parser = mod.build_parser()
    actions = {action.dest: action for action in parser._actions}
    assert "design_dir" in actions
    assert actions["design_dir"].required
