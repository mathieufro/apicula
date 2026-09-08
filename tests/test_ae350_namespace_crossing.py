"""`AE350_SOC` taps must never alias a fabric wire of the same name elsewhere.

`fse_create_ae350()` builds one Himbaechel node per tap: an anchor-tile entry
`(0, 159, 'AE350_SOC<port>')` joined to a fabric-tile entry
`(row, col, '<wire>')` outside the anchor cell (`evidence/ae350/portmap-138c.md`
"The 138C delta"). Both halves of that pair are tile-qualified tuples, but the
short fabric-side wire names (`CE0`-`CE3`, `CLK0`-`CLK2`, `A0`-`D7`, ...) recur
in many unrelated tiles across the die. If node construction ever dropped the
tile qualifier and merged on the bare wire name instead, two independent
AE350 ports would collapse onto one physical wire, or an AE350 tap would
silently fuse into a pre-existing, unrelated global node -- a namespace
crossing that routes two logically distinct signals onto one net without
either failing to build or looking wrong in a diff.

This is a regression test, not a discovery task: it locks in the injectivity
already measured (`portmap-138c.md` "+698 Himbaechel nodes,
all `X145Y0/AE350_SOC*` aliases") against the *installed* chipdb, sha256
`7f3c64c94fcf6ae8f4cfbe4e8a90bf38af83251d4bc0f818fd347636580f506e` -- the
`d6e00bdc...` build plus the dedicated `CLKOUT1 -> CORE_CLK` edge, which adds
no node whose members cross two ports.
"""

from pathlib import Path

import pytest

from apycula import chipdb as chipdb_mod

DEVICE = "GW5AST-138C"
ANCHOR_NODE_PREFIX = "X159Y0/AE350_SOC"
ANCHOR_TILE = (0, 159)
#: The chipdb this test is a regression lock for (`portmap-138c.md`).
#: Re-measured at the Phase-3 close: the IO/IOLOGIC work moved the
#: database (IOLOGIC bels, the HCLK-to-FCLK edge, the 16-bit gearboxes,
#: both ADC bels and their configuration attribution), and the AE350
#: facts below were re-checked against the new value rather than the
#: lock being widened.
EXPECTED_SHA256 = (
    "f2f92b0448b7218b969237f150c694039bad9e0d4f0f17dfdbfde5108d0efd6c")


def find_ae350_namespace_crossings(nodes, anchor_prefix=ANCHOR_NODE_PREFIX,
                                    anchor_tile=ANCHOR_TILE):
    """Return the two ways an AE350 tap can alias the wrong fabric wire.

    `nodes` is the `Device.nodes` mapping: node name -> (kind, set of
    `(row, col, wire)` tuples). Returns `(duplicates, foreign_collisions)`:

    - `duplicates`: fabric-side tuples claimed by more than one AE350 node
      (two AE350 ports collapsed onto the same physical wire);
    - `foreign_collisions`: fabric-side tuples that also belong to some
      *other*, non-AE350 node (an AE350 tap fused into an unrelated global
      net of a different tile).

    Both are empty on a correctly namespaced chipdb.
    """
    ae350_fabric_tuples = []
    non_ae350_tuples = set()

    for name, (_kind, wires) in nodes.items():
        is_ae350 = name.startswith(anchor_prefix)
        if is_ae350:
            fabric_side = [
                w for w in wires
                if not (w[0] == anchor_tile[0] and w[1] == anchor_tile[1]
                        and w[2].startswith("AE350_SOC"))
            ]
            ae350_fabric_tuples.extend(fabric_side)
        else:
            non_ae350_tuples.update(wires)

    counts = {}
    for t in ae350_fabric_tuples:
        counts[t] = counts.get(t, 0) + 1
    duplicates = {t for t, n in counts.items() if n > 1}

    foreign_collisions = {t for t in ae350_fabric_tuples if t in non_ae350_tuples}

    return duplicates, foreign_collisions


def _load_installed_chipdb():
    path = (Path(__file__).resolve().parent.parent / "apycula"
             / f"{DEVICE}.msgpack.xz")
    if not path.is_file():
        pytest.skip(f"{path} is absent; run `make apycula/{DEVICE}.msgpack.xz`")
    return chipdb_mod.load_chipdb(str(path))


def test_installed_chipdb_matches_the_locked_sha256():
    """The chipdb this regression is measured against has not silently moved."""
    import hashlib
    path = (Path(__file__).resolve().parent.parent / "apycula"
             / f"{DEVICE}.msgpack.xz")
    if not path.is_file():
        pytest.skip(f"{path} is absent; run `make apycula/{DEVICE}.msgpack.xz`")
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    assert digest == EXPECTED_SHA256, (
        f"{path} is sha256 {digest}, not the locked {EXPECTED_SHA256} -- "
        "re-measure this test against the new chipdb before trusting it"
    )


def test_ae350_taps_never_alias_a_fabric_wire_of_the_same_name_elsewhere():
    db = _load_installed_chipdb()
    duplicates, foreign_collisions = find_ae350_namespace_crossings(db.nodes)
    assert duplicates == set(), (
        f"{len(duplicates)} fabric wire(s) claimed by more than one AE350 "
        f"tap: {sorted(duplicates)[:5]}"
    )
    assert foreign_collisions == set(), (
        f"{len(foreign_collisions)} AE350 tap(s) alias a wire already owned "
        f"by an unrelated node: {sorted(foreign_collisions)[:5]}"
    )


def test_ae350_namespace_crossing_check_actually_detects_a_duplicate():
    """Proof the checker can fail: two AE350 nodes sharing one fabric wire."""
    nodes = {
        "X159Y0/AE350_SOCPORT_A": (
            "AE350_IN", {(0, 159, "AE350_SOCPORT_A"), (0, 170, "CE0")}
        ),
        "X159Y0/AE350_SOCPORT_B": (
            "AE350_IN", {(0, 159, "AE350_SOCPORT_B"), (0, 170, "CE0")}
        ),
    }
    duplicates, foreign_collisions = find_ae350_namespace_crossings(nodes)
    assert duplicates == {(0, 170, "CE0")}
    assert foreign_collisions == set()


def test_ae350_namespace_crossing_check_actually_detects_a_foreign_fusion():
    """Proof the checker can fail: an AE350 tap fuses into an unrelated node."""
    nodes = {
        "X159Y0/AE350_SOCPORT_A": (
            "AE350_IN", {(0, 159, "AE350_SOCPORT_A"), (12, 40, "CE0")}
        ),
        "SOME_UNRELATED_GLOBAL_NET": (
            "GLOBAL_CLK", {(12, 40, "CE0"), (12, 41, "CE0")}
        ),
    }
    duplicates, foreign_collisions = find_ae350_namespace_crossings(nodes)
    assert duplicates == set()
    assert foreign_collisions == {(12, 40, "CE0")}


def test_ae350_namespace_crossing_check_is_clean_on_disjoint_fixtures():
    """The checker does not false-positive when nothing actually collides."""
    nodes = {
        "X159Y0/AE350_SOCPORT_A": (
            "AE350_IN", {(0, 159, "AE350_SOCPORT_A"), (0, 170, "CE0")}
        ),
        "X159Y0/AE350_SOCPORT_B": (
            "AE350_IN", {(0, 159, "AE350_SOCPORT_B"), (0, 171, "CE0")}
        ),
        "SOME_UNRELATED_GLOBAL_NET": (
            "GLOBAL_CLK", {(12, 40, "CE0"), (12, 41, "CE0")}
        ),
    }
    duplicates, foreign_collisions = find_ae350_namespace_crossings(nodes)
    assert duplicates == set()
    assert foreign_collisions == set()
