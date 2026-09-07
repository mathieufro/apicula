"""The symmetric half of the raw residual: fuses the open flow over-emits.

`spec-harness.md` §5.1b guards one direction -- a fuse the vendor sets that
apicula does not model.  Its mirror image, a fuse apicula emits that the
vendor does not set, is not caught by the same subtraction: apicula modelling
the bit is exactly why the residual drops it.  These tests drive the
direction-aware split and the verdict term that acts on it, so they say what
they mean without a 34 MB bitstream.
"""
from fuzz.gw5ast138c.harness import equiv
from fuzz.gw5ast138c.harness.equiv import Cell, Netlist


def one_tile_netlist(x=2, y=1, typ="DFF", attrs=(("FF_TYPE", "DFF"),)):
    return Netlist(cells={Cell(x, y, 0, typ): frozenset(attrs)})


def test_directed_delta_names_only_the_bits_the_open_side_sets():
    vendor = {(1, 2): [[1, 0], [0, 0]]}
    open_ = {(1, 2): [[1, 1], [0, 0]]}
    assert equiv.open_only_from_tiles(vendor, open_) == {(1, 2): {(0, 1)}}
    # The vendor-only direction is not this function's business.
    assert equiv.open_only_from_tiles(open_, vendor) == {}


def test_over_emitted_bit_is_a_diff_even_when_every_set_matches():
    """A bit only the open flow sets is a DIFF, whatever the sets say."""
    nl = one_tile_netlist()
    residual = {"unexplained_bits": [],
                "fuses_over_emitted": [
                    {"category": "open_only_fill", "bits": 2, "tiles": 1}]}
    assert equiv._residual_is_dirty(residual)
    result = equiv.compare_e0(nl, nl, residual=residual)
    assert result.verdict == "DIFF"
    assert "the vendor does not" in result.notes
    assert equiv.evidence_rows(result)[0]["fuses_over_emitted"]


def test_no_over_emission_leaves_the_verdict_alone():
    nl = one_tile_netlist()
    residual = {"unexplained_bits": [], "fuses_over_emitted": []}
    assert not equiv._residual_is_dirty(residual)
    assert equiv.compare_e0(nl, nl, residual=residual).verdict == "EQUIV E0 ok"
