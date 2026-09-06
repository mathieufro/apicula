"""Tests for the GW5AST-138C PLL parameter header (P1.T39).

`examples/gw5a/pll/GW5AST-138C.vh` is a Phase-1-owned stub: Phases 4 and 7
`include it for a single reference PLL operating point. These tests assert
the header is well-formed and that its parameter set is admitted by the
packer's own datasheet checks (`GW5AST_138C.get_permitted_pll_freqs` /
`check_pll_fvco`), rather than trusting the header's own arithmetic.
"""

import json
import re
from pathlib import Path
from types import SimpleNamespace

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
HEADER_PATH = REPO_ROOT / "examples" / "gw5a" / "pll" / "GW5AST-138C.vh"
RUNS_JSONL = (
    REPO_ROOT.parent
    / "open-toolchain"
    / "evidence"
    / "plla"
    / "runs.jsonl"
)

DEFINE_RE = re.compile(r"^`define[ \t]+(\S+)[ \t]+(\S+)", re.MULTILINE)


def _read_header() -> str:
    return HEADER_PATH.read_text()


def _defines(text: str) -> dict[str, str]:
    return dict(DEFINE_RE.findall(text))


def _run_ids(runs_jsonl: Path) -> set[str]:
    ids = set()
    with runs_jsonl.open() as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            ids.add(json.loads(line)["run_id"])
    return ids


def test_plla_header_stub_wellformed():
    assert HEADER_PATH.exists(), f"missing {HEADER_PATH}"
    text = _read_header()
    assert text.strip(), "header must not be empty"

    # Guard triple, exactly once each.
    assert text.count("`ifndef GW5AST_138C_PLL_VH") == 1
    assert text.count("`define GW5AST_138C_PLL_VH") == 1
    assert text.count("`endif") == 1

    defines = _defines(text)
    pll_param_names = {
        "GW5AST_138C_PLL_IDIV_SEL",
        "GW5AST_138C_PLL_FBDIV_SEL",
        "GW5AST_138C_PLL_MDIV_SEL",
        "GW5AST_138C_PLL_ODIV0_SEL",
    }
    present_pll_params = pll_param_names & defines.keys()
    assert len(present_pll_params) >= 4, (
        f"expected >= 4 PLL parameters, found {present_pll_params}"
    )

    assert "GW5AST_138C_PLL_FVCO_MHZ" in defines
    fvco = float(defines["GW5AST_138C_PLL_FVCO_MHZ"])
    assert 650.0 <= fvco <= 1300.0

    # Header comment names a run id present in runs.jsonl.
    assert RUNS_JSONL.exists(), f"missing {RUNS_JSONL}"
    known_run_ids = _run_ids(RUNS_JSONL)
    cited_run_ids = set(re.findall(r"[\w-]+-clocking_\w+-\d{4}", text))
    unmatched = {r for r in cited_run_ids if r not in known_run_ids}
    assert unmatched == set(), f"run ids not present in runs.jsonl: {unmatched}"
    assert cited_run_ids, "header must name at least one run id"

    # It is a header, not a design.
    assert text.count("module ") == 0


def test_plla_header_matches_packer():
    import sys

    sys.path.insert(0, str(REPO_ROOT))
    from apycula.gowin_pack import GW5AST_138C
    from apycula.gowin_pll import plla_freqs

    text = _read_header()
    defines = _defines(text)

    fclkin = float(defines["GW5AST_138C_PLL_FCLKIN_MHZ"])
    idiv = int(defines["GW5AST_138C_PLL_IDIV_SEL"])
    fbdiv = int(defines["GW5AST_138C_PLL_FBDIV_SEL"])
    mdiv = int(defines["GW5AST_138C_PLL_MDIV_SEL"])
    odiv0 = int(defines["GW5AST_138C_PLL_ODIV0_SEL"])
    header_fvco = float(defines["GW5AST_138C_PLL_FVCO_MHZ"])
    header_clkout0 = float(defines["GW5AST_138C_PLL_CLKOUT0_MHZ"])

    pfd, fclkfb, fvco, clkout0 = plla_freqs(fclkin, idiv, fbdiv, mdiv, odiv0)
    assert fvco == pytest.approx(header_fvco, abs=1e-6)
    assert clkout0 == pytest.approx(header_clkout0, abs=1e-6)

    # Fed through the P1.T20 get_permitted_pll_freqs() / P1.T21
    # check_pll_fvco() band check: this must raise 0 exceptions.
    fake_self = SimpleNamespace(
        get_permitted_pll_freqs=GW5AST_138C.get_permitted_pll_freqs.__get__(
            SimpleNamespace()
        )
    )
    max_in, max_out, min_out, max_vco, min_vco = fake_self.get_permitted_pll_freqs()
    assert fclkin <= max_in
    assert min_out <= clkout0 <= max_out

    GW5AST_138C.check_pll_fvco(fake_self, fvco)
