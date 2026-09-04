"""`P0.T24` -- `dontcare.mask`: the six base entries and the policy (§5.3).

Six tests, named by the blueprint.  None of them needs a bitstream: what is
under test is the mask file itself and the policy `load_mask()` enforces on
it, which is exactly what makes a mask entry reviewable as a claim about the
hardware.
"""
import hashlib
import subprocess

import pytest

from fuzz.gw5ast138c.harness import equiv
from fuzz.gw5ast138c.harness.equiv import MaskPolicyError


REQUIRED = ("id", "levels", "justification", "citation", "initials")


@pytest.fixture
def mask():
    return equiv.load_mask(None)


def test_mask_has_exactly_six_base_entries(mask):
    """Phase 0 ships exactly the base set §5.3 admits without new evidence."""
    assert len(mask.entries) == 6, mask.ids
    assert mask.ids == equiv.BASE_MASK_ENTRY_IDS
    for entry in mask.entries:
        for key in REQUIRED:
            assert getattr(entry, key), f"{entry.id}: {key} missing or empty"
        assert entry.justification.strip()
        assert entry.citation.strip()


def test_mask_io_default_entry_carries_sixth_key(mask):
    """1 positive assertion, 5 negative ones -- the sixth key is IO-only."""
    io = mask.entry(equiv.IO_DEFAULT_ENTRY_ID)
    assert io is not None
    assert io.disabled_for_shape_classes == equiv.IO_SHAPE_CLASSES
    others = [e for e in mask.entries if e.id != equiv.IO_DEFAULT_ENTRY_ID]
    assert len(others) == 5
    for entry in others:
        assert entry.disabled_for_shape_classes is None, entry.id


def test_mask_rejects_primitive_scoped_entry(tmp_path):
    """§5.3 rule 2: a mask entry may never be scoped to a primitive row."""
    bad = tmp_path / "bad.mask"
    bad.write_text(
        "[entry]\n"
        "id: dsp_only\n"
        "levels: E0\n"
        "justification: only ever seen on the MULT18X18\n"
        "citation: none\n"
        "initials: ws_00\n"
        "primitive: MULT18X18\n")
    with pytest.raises(MaskPolicyError) as exc:
        equiv.load_mask(str(bad))
    assert "primitive" in str(exc.value)


def test_mask_placement_entry_disabled_at_e1(mask):
    """Free placement is an E0-only don't-care; a route is E0+E1, never E2."""
    placement = mask.entry("free_placement")
    assert placement.levels == ("E0",)
    assert placement.applies_at("E0")
    assert not placement.applies_at("E1")
    assert not placement.applies_at("E2")

    route = mask.entry("net_route")
    assert route.levels == ("E0", "E1")
    assert route.applies_at("E0") and route.applies_at("E1")
    assert not route.applies_at("E2")


def test_mask_io_default_disabled_for_io_shapes(mask):
    """4 shape classes, 4 skips -- there the default IS the thing under test."""
    io = mask.entry(equiv.IO_DEFAULT_ENTRY_ID)
    for shape_class in ("iob", "lvds", "iodelay", "iologic_mem"):
        assert not io.active_for("E0", shape_class=shape_class), shape_class
        assert not mask.explains(equiv.IO_DEFAULT_ENTRY_ID, "E0", shape_class)
        assert io.id not in [e.id for e in mask.active("E0", shape_class)]
    # ... and it IS in force for a shape whose subject is not the IO default.
    assert io.active_for("E0", shape_class="dff")
    assert mask.explains(equiv.IO_DEFAULT_ENTRY_ID, "E0", "dff")


def test_mask_sha256_recorded(mask):
    """§5.3, last rule: the sha256 rides in every evidence row."""
    digest = hashlib.sha256(open(equiv.DEFAULT_MASK_PATH, "rb").read()).hexdigest()
    assert mask.sha256 == digest

    shasum = subprocess.run(["shasum", "-a", "256", equiv.DEFAULT_MASK_PATH],
                            capture_output=True, text=True, check=True)
    assert shasum.stdout.split()[0] == digest

    result = equiv.compare_e0(equiv.Netlist(), equiv.Netlist(), mask=mask)
    assert result.mask_sha256 == digest
    row = equiv.evidence_rows(result)[0]
    assert row["mask_sha256"] == digest
    assert row["mask_entries"] == list(equiv.BASE_MASK_ENTRY_IDS)
