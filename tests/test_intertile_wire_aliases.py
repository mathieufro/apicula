"""A length-1 inter-tile wire has two spellings and must have one node.

`EW10` of a tile is the same piece of metal its eastern neighbour calls `E111`
and its western neighbour calls `W111`; `SN10` is the same for the vertical
pair, and `..20` for the second wire of each axis.  Both spellings are pip
endpoints in the shipped tile tables -- on the GW5AST-138C an `IOLOGIC` output
leaves the pad tile on `EW10` and is picked up next door on `W111` -- so a
`wire2global` that gave them different roots split one net into two, and every
net routed over such a wire decoded as two unrelated halves.

`tracing.source_intertile_wire` already carried the correspondence; this makes
`wire2global` agree with it.
"""
import pytest

from apycula import chipdb, tracing


class _Grid:
    """The only two things `wire2global` asks a device."""

    rows = 60
    cols = 92


DEVICE = _Grid()

#: (tile of the two-sided wire, neighbour, the neighbour's spelling)
PAIRS = (
    ("EW10", (0, -1), "W111"),
    ("EW10", (0, 1), "E111"),
    ("EW20", (0, -1), "W121"),
    ("SN10", (-1, 0), "N111"),
    ("SN20", (1, 0), "S121"),
)


@pytest.mark.parametrize("wire,offset,neighbour_wire", PAIRS)
def test_both_spellings_reach_the_same_node(wire, offset, neighbour_wire):
    row, col = 30, 46
    here = chipdb.wire2global(row, col, DEVICE, wire)
    there = chipdb.wire2global(row + offset[0], col + offset[1], DEVICE,
                               neighbour_wire)
    assert here == there


def test_the_alias_agrees_with_the_tracing_table():
    """One correspondence, not two: `tracing` is where it was measured."""
    for segment0, target in (("E110", "EW10"), ("W110", "EW10"),
                             ("E120", "EW20"), ("W120", "EW20"),
                             ("S110", "SN10"), ("N110", "SN10"),
                             ("S120", "SN20"), ("N120", "SN20")):
        assert chipdb.intertile_aliases[segment0[:-1]] == target


def test_an_ordinary_inter_tile_wire_is_left_alone():
    """Only the length-1 pairs alias; `E200` and friends keep their names."""
    assert chipdb.wire2global(30, 46, DEVICE, "E200") == "R30C46_E20"
    assert chipdb.wire2global(30, 46, DEVICE, "N130") == "R30C46_N13"


def test_a_local_wire_is_still_local():
    assert chipdb.wire2global(30, 46, DEVICE, "F7") == "R30C46_F7"


def test_tracing_and_wire2global_agree_on_every_length_1_wire():
    """The two models of the same metal, checked against each other."""
    for wire, offset, neighbour_wire in PAIRS:
        row, col = 30, 46
        source = tracing.source_intertile_wire(
            DEVICE, (row + offset[0], col + offset[1], neighbour_wire))
        assert source == (row, col, wire)
