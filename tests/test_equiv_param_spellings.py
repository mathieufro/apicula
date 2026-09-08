"""One parameter, two spellings: the netlist's and the bitstream's.

A parameter that came from a Verilog vector reaches the netlist as the bit
string yosys wrote, while `gowin_unpack` recovers the attribute's own value.
Comparing them as text made every enumerated attribute wider than one bit --
`C_STATIC_DLY` is the whole 0..255 static delay step -- look like a decode-check
mismatch when the two sides agree.
"""
import pytest

from fuzz.gw5ast138c.harness import equiv


@pytest.mark.parametrize("expected,recovered", [
    ("0" * 31 + "1", "1"),
    ("0" * 32, "0"),
    ("0" * 24 + "10011000", "152"),
    ('"1"', "1 "),
    ("8", "8"),
])
def test_the_same_value_in_two_spellings_agrees(expected, recovered):
    assert equiv._params_agree(expected, recovered)


@pytest.mark.parametrize("expected,recovered", [
    ("0" * 31 + "1", "2"),
    ("0" * 24 + "10011000", "151"),
    ("MODDRX1", "MODDRX21"),
])
def test_different_values_still_disagree(expected, recovered):
    assert not equiv._params_agree(expected, recovered)


def test_a_name_is_compared_as_text_not_as_a_number():
    """`ENABLE` is not a number, so it must match only itself."""
    assert equiv._param_values("ENABLE") == set()
    assert equiv._params_agree("ENABLE", "ENABLE")
