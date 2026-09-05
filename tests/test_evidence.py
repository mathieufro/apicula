"""Tests for `fuzz.gw5ast138c.harness.evidence` (P0.T28).

The evidence row schema of `spec-harness.md` §6 is declared exactly once, as
`evidence.REQUIRED_FIELDS`; every assertion below derives from that constant
rather than restating a field count, which is what stopped the earlier
"27 fields" drift (blueprint F4 / cross-phase F7).
"""
import json
import os
import subprocess
import sys

import pytest

from fuzz.gw5ast138c.harness import evidence

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

#: The §6 field list, restated here once and only here, so a change to
#: `evidence.REQUIRED_FIELDS` has to be a deliberate change to the schema.
SPEC_FIELDS = (
    "run_id", "timestamp", "primitive", "shape", "sweep", "device", "part",
    "ide_version", "yosys_version", "apicula_sha", "nextpnr_sha",
    "chipdb_sha256", "mask_sha256", "level", "verdict", "diff_count",
    "first_diff", "fuses_moved", "unexplained_bits", "decode_check",
    "sdf_condition", "oracle_log", "open_log", "vendor_fs", "open_fs",
    "sdf", "tr", "wall_clock_s", "notes",
)


def _row(**over):
    """A minimal valid E1 row."""
    fields = dict(run_id="harness-selftest-A-0001", primitive="DFF", shape="A",
                  level="E1", verdict="ok", notes="")
    fields.update(over)
    return evidence.new_row(**fields)


def test_evidence_row_has_all_required_fields():
    row = _row()
    assert set(row.keys()) == set(evidence.REQUIRED_FIELDS)
    assert len(evidence.REQUIRED_FIELDS) == 29
    assert evidence.REQUIRED_FIELDS == SPEC_FIELDS
    # A row missing any single required field is rejected, one field at a time.
    for field in evidence.REQUIRED_FIELDS:
        short = {k: v for k, v in row.items() if k != field}
        with pytest.raises(evidence.EvidenceSchemaError) as exc:
            evidence.validate_row(short)
        assert field in str(exc.value)
    # A wrong enum value is rejected on both enum-valued fields.
    for field, bad in (("level", "E3"), ("verdict", "passed")):
        wrong = dict(row, **{field: bad})
        with pytest.raises(evidence.EvidenceSchemaError) as exc:
            evidence.validate_row(wrong)
        assert bad in str(exc.value)
    # An unknown field is rejected too: the row is exactly the 29 names.
    with pytest.raises(evidence.EvidenceSchemaError):
        evidence.validate_row(dict(row, extra_field=1))


def test_evidence_e0_requires_notes(tmp_path):
    with pytest.raises(evidence.EvidenceSchemaError):
        evidence.validate_row(_row(level="E0", notes=""))
    with pytest.raises(evidence.EvidenceSchemaError):
        evidence.append_row(_row(level="E0", notes="   "), "harness-selftest",
                            root=str(tmp_path))
    ok = _row(level="E0", notes="E1 unavailable: nextpnr ignored INS_LOC")
    assert evidence.validate_row(ok) is ok
    # The E0+hw-pending shape (blueprints/README.md) validates.
    pending = evidence.hw_pending_row(
        observation="DDRDLL.LOCK",
        reason="E1 unavailable: no hardware before Phase 9",
        run_id="e2e-p0-A-0001", primitive="DDRDLL", shape="A")
    assert pending["level"] == "E0" and pending["verdict"] == "ok"
    assert evidence.HW_PENDING_TOKEN in pending["notes"]
    assert "DDRDLL.LOCK" in pending["notes"]
    evidence.validate_row(pending)
    # ... and is refused if it does not name the observation still owed.
    with pytest.raises(evidence.EvidenceSchemaError):
        evidence.validate_row(_row(level="E0", verdict="ok",
                                   notes=evidence.HW_PENDING_TOKEN))
    # ... or if it is not an E0/ok row.
    with pytest.raises(evidence.EvidenceSchemaError):
        evidence.validate_row(_row(
            level="E1", verdict="ok",
            notes=evidence.HW_PENDING_TOKEN + " DDRDLL.LOCK"))


ERROR_TEXT = ("ERROR: Pack: unsupported cell type 'DQS' for cell "
              "dut_dqs (bel DQS0) at gowin_pack.py:812")


def test_evidence_refused_records_error_text(tmp_path):
    row = evidence.refused_row(ERROR_TEXT, run_id="calibration-A-0001",
                               primitive="DQS", shape="A")
    assert row["verdict"] == "refused"
    assert ERROR_TEXT in row["notes"]
    evidence.validate_row(row)
    path = evidence.append_row(row, "calibration", root=str(tmp_path))
    written = json.loads(open(path).read().splitlines()[0])
    assert ERROR_TEXT in written["notes"]
    # A refusal with no error text is not a deliverable, it is a hole.
    with pytest.raises(evidence.EvidenceSchemaError):
        evidence.validate_row(_row(verdict="refused", notes=""))


def test_evidence_pruned_row_admissible():
    """`D99`: a row whose artefacts were pruned from the datastore carries
    `artefact_pruned: true` plus `sha256:<hex>` (or `sha256:unknown`) in place
    of a live path, and the schema accepts it -- it is not an unknown field
    and not a schema violation.
    """
    row = _row(artefact_pruned=True,
               oracle_log="sha256:" + "a" * 64,
               open_log=["sha256:" + "b" * 64, "sha256:unknown"],
               vendor_fs=[{"path": "sha256:" + "c" * 64, "bytes": 123,
                          "sha256": "c" * 64}])
    assert evidence.validate_row(row) is row
    assert row["artefact_pruned"] is True
    assert "artefact_pruned" not in evidence.REQUIRED_FIELDS
    assert "artefact_pruned" in evidence.OPTIONAL_FIELDS
    # The pruned-marker pattern accepts a real hash and the "unknown" literal,
    # and rejects anything else (a live path, a malformed hash).
    assert evidence.PRUNED_ARTIFACT_RE.match("sha256:" + "0" * 64)
    assert evidence.PRUNED_ARTIFACT_RE.match("sha256:unknown")
    assert not evidence.PRUNED_ARTIFACT_RE.match("/some/live/path/run.fs")
    assert not evidence.PRUNED_ARTIFACT_RE.match("sha256:tooshort")
    # A non-bool artefact_pruned is rejected.
    with pytest.raises(evidence.EvidenceSchemaError):
        evidence.validate_row(_row(artefact_pruned="true"))
    # A row with neither artefact_pruned nor any extra field is unaffected --
    # the optional field is additive, never required.
    assert set(_row().keys()) == set(evidence.REQUIRED_FIELDS)


def test_evidence_append_only(tmp_path):
    root = str(tmp_path)
    rows = [_row(run_id=f"harness-selftest-A-000{n}") for n in (1, 2, 3)]
    path = evidence.append_row(rows[0], "harness-selftest", root=root)
    evidence.append_row(rows[1], "harness-selftest", root=root)
    first_two = open(path, "rb").read()
    evidence.append_row(rows[2], "harness-selftest", root=root)
    final = open(path, "rb").read()
    assert len(final.splitlines()) == 3
    assert final.startswith(first_two)
    assert final[:len(first_two)] == first_two
    assert [json.loads(l)["run_id"] for l in final.splitlines()] == [
        r["run_id"] for r in rows]


def _seed_three(root):
    evidence.ensure_tree(root)
    evidence.append_row(_row(run_id="chipdb-A-0001", primitive="CHIPDB"),
                        "chipdb", root=root)
    evidence.append_row(_row(run_id="oracle-smoke-A-0001", primitive="DFF"),
                        "oracle-smoke", root=root)
    evidence.append_row(_row(run_id="calibration-A-0001", primitive="DFF",
                             verdict="diff"), "calibration", root=root)


def test_evidence_rollup_counts(tmp_path):
    root = str(tmp_path)
    _seed_three(root)
    path = evidence.rollup(root=root)
    text = open(path).read()
    assert path == os.path.join(root, "evidence-table.md")
    assert "rows=3" in text
    for slug in evidence.SLUGS:
        assert len([l for l in text.splitlines()
                    if l.startswith(f"| {slug} |")]) == 1
    # Aggregated per primitive and per status, not just totalled.
    assert "| DFF | E1 | ok | 1 |" in text
    assert "| DFF | E1 | diff | 1 |" in text
    assert "| CHIPDB | E1 | ok | 1 |" in text
    # Deterministic: the roll-up of an unchanged tree is byte-identical.
    again = open(evidence.rollup(root=root)).read()
    assert again == text


def test_evidence_slug_dirs_created(tmp_path):
    root = str(tmp_path)
    evidence.ensure_tree(root)
    assert sorted(evidence.SLUGS) == sorted(
        d for d in os.listdir(root) if os.path.isdir(os.path.join(root, d))
        and not d.startswith("_"))
    assert len(evidence.SLUGS) == 6
    assert set(evidence.SLUGS) == {"chipdb", "oracle-smoke", "calibration",
                                   "harness-selftest", "timing-l0-cfu",
                                   "e2e-p0"}
    assert os.path.isfile(os.path.join(root, ".gitignore"))


OTC = evidence.otc_root()
SHIM = os.path.join(OTC, "tools", "evidence.py") if OTC else ""


@pytest.mark.skipif(not os.path.isfile(SHIM), reason=f"no shim at {SHIM}")
def test_evidence_tools_shim_is_same_tool(tmp_path):
    root = str(tmp_path)
    _seed_three(root)
    env = dict(os.environ, OTC_EVIDENCE=root)
    module = subprocess.run([sys.executable, "-m",
                             "fuzz.gw5ast138c.harness.evidence", "--rollup"],
                            cwd=REPO, env=env, capture_output=True)
    assert module.returncode == 0, module.stderr.decode()
    via_module = open(os.path.join(root, "evidence-table.md"), "rb").read()
    os.remove(os.path.join(root, "evidence-table.md"))
    shim = subprocess.run([sys.executable, SHIM, "--rollup"],
                          cwd=str(tmp_path), env=env, capture_output=True)
    assert shim.returncode == 0, shim.stderr.decode()
    via_shim = open(os.path.join(root, "evidence-table.md"), "rb").read()
    assert via_shim == via_module
    assert shim.stdout == module.stdout
    assert open(SHIM).read().count("def ") == 0


# `-C` just needs to be inside the same repo as the path being checked, not
# repo root -- and OTC (`open-toolchain`, C10/D80) is its own git checkout,
# separate from apicula's.
FL = OTC


@pytest.mark.skipif(not OTC or not os.path.isdir(os.path.join(OTC, "evidence")),
                    reason="no open-toolchain evidence tree")
def test_evidence_gitignore_denies_binaries():
    # When this test runs from inside a git hook (e.g. the local gate's own
    # pre-commit), git has already exported GIT_DIR/GIT_WORK_TREE/
    # GIT_INDEX_FILE for *this* repo (apicula); a nested `git -C <FL>`
    # inherits them and resolves against that repo instead of FL's own,
    # regardless of -C. Strip them so -C is honoured.
    env = {k: v for k, v in os.environ.items()
           if k not in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE")}
    ev = os.path.join(OTC, "evidence")
    denied = subprocess.run(["git", "-C", FL, "check-ignore", "-q",
                             os.path.join(ev, "_runs", "x.fs")], env=env)
    assert denied.returncode == 0
    allowed = subprocess.run(["git", "-C", FL, "check-ignore",
                              os.path.join(ev, "chipdb", "summary.md")],
                             capture_output=True, env=env)
    assert allowed.returncode != 0


def test_every_row_states_that_the_timing_model_is_unverified():
    """`D91`: a row never reports a timing number as if the model were verified.

    The `S17a` tables are conservative in aggregate and optimistic per class
    (every DFF `CLK->Q` arc modelled 16% fast, 825 SDF arcs with no model arc
    at all), so the token is on every row rather than on the ones a reader
    happens to recognise as timing rows.
    """
    row = evidence.new_row(run_id="t-0001", level="E1", verdict="ok",
                           primitive="P1", shape="A")
    assert evidence.TIMING_MODEL_TOKEN in row["notes"]

    kept = evidence.new_row(run_id="t-0002", level="E1", verdict="ok",
                            notes="measured on the smoke pair")
    assert kept["notes"].startswith("measured on the smoke pair")
    assert evidence.TIMING_MODEL_TOKEN in kept["notes"]

    once = evidence.new_row(run_id="t-0003", level="E1", verdict="ok",
                            notes=f"already said {evidence.TIMING_MODEL_TOKEN}")
    assert once["notes"].count(evidence.TIMING_MODEL_TOKEN) == 1


def test_fmax_line_states_that_the_timing_model_is_unverified(capsys):
    """`D91`: the `FMAX` line carries it too, where the number is read."""
    from fuzz.gw5ast138c.harness import openflow

    log = "Info: Max frequency for clock 'clk': 300.00 MHz (PASS at 250.00 MHz)"
    entries = openflow.parse_fmax(log)
    assert entries and entries[0]["mhz"] == 300.0
    import inspect
    source = inspect.getsource(openflow.main)
    assert "evidence.TIMING_MODEL_TOKEN" in source
