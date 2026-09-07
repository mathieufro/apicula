"""A named packer refusal is a measurement with its own verdict.

`D30` says the packer refuses by name rather than emitting a fuse it has never
measured, and `spec-harness.md` §6 gives that outcome the verdict `refused`
carrying the packer's exact words.  Before these guards the refusal left
`gowin_pack` as an ordinary traceback with exit status 1, indistinguishable
from a crash, and the harness recorded it as `aborted` with only a returncode
map -- the deliverable was thrown away.
"""
import pytest

from apycula import gowin_pack
from fuzz.gw5ast138c.harness import openflow


REFUSAL = ("DCS CLKSEL0, SELFORCE is driven on a device whose DCS control "
           "wires have never been traced.")


def test_a_refusal_exits_with_its_own_status_and_prints_its_text(capsys, monkeypatch):
    def refuse(_cli_args):
        raise gowin_pack.PackRefused(REFUSAL)

    monkeypatch.setattr(gowin_pack, "_pack", refuse)
    monkeypatch.setattr(gowin_pack, "CliArgs", lambda: None)

    assert gowin_pack.main() == gowin_pack.REFUSED_EXIT
    assert gowin_pack.REFUSED_EXIT != 1
    assert capsys.readouterr().err.strip() == f"REFUSED: {REFUSAL}"


def test_a_crash_is_not_reported_as_a_refusal(monkeypatch):
    def crash(_cli_args):
        raise KeyError("some device table")

    monkeypatch.setattr(gowin_pack, "_pack", crash)
    monkeypatch.setattr(gowin_pack, "CliArgs", lambda: None)

    with pytest.raises(KeyError):
        gowin_pack.main()


def test_named_refusal_recovers_the_packers_exact_words():
    steps = [{"step": "gowin_pack", "returncode": gowin_pack.REFUSED_EXIT,
              "log_text": f"some chatter\nREFUSED: {REFUSAL}\n"}]
    assert openflow.named_refusal(steps) == REFUSAL


def test_a_nonrefusal_failure_yields_no_refusal_text():
    steps = [{"step": "gowin_pack", "returncode": 1,
              "log_text": "Traceback (most recent call last):\nKeyError: 3\n"}]
    assert openflow.named_refusal(steps) is None
