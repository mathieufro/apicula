"""The §5.4 decode check is a verdict term, and a batch pins one chipdb.

Two defects, both found on the `clkdiv`/`clkdiv2` rows of `P1.T14`/`P1.T15`:

* `equiv.evidence_fields` computed `verdict` from the set-level diff and the
  raw residual only, so a row whose `decode_check` said `mismatch` was
  published as `verdict: ok` while its own notes said the decode check had
  failed.  §5.4 states c1 and c2 are **both required**, which makes a
  mismatch a `diff` like any other.
* `run_batch` let each run hash the chipdb for itself, so a chipdb rebuilt
  while a batch was running produced rows of one batch carrying two different
  `chipdb_sha256` values -- rows that cannot be compared with each other.
"""
import hashlib

from fuzz.gw5ast138c.harness import __main__ as batch
from fuzz.gw5ast138c.harness import equiv, evidence, openflow


CLEAN = {"cells": 0, "attrs": 0, "conns": 0, "pips": 0}


def test_decode_diff_makes_verdict_diff():
    """A `decode_check` mismatch is a `diff`, never an `ok` with a sad note."""
    ok = equiv.E0Result(diff_count=dict(CLEAN),
                        decode_check={"c1": "ok", "c2": "ok"})
    assert equiv.evidence_fields(ok)["verdict"] == "ok"

    for failing in ({"c1": "mismatch", "c2": "ok"},
                    {"c1": "ok", "c2": "mismatch"},
                    {"c1": "mismatch", "c2": "mismatch"}):
        result = equiv.E0Result(diff_count=dict(CLEAN), decode_check=failing)
        fragment = equiv.evidence_fields(result)
        assert fragment["verdict"] == "diff", failing
        assert "decode check" in fragment["notes"], fragment["notes"]
        row = evidence.adapt({"run_id": "b-dc-0000", "primitive": "DFF",
                              "shape": "smoke", "level": "E1"}, **fragment)
        evidence.validate_row(row)
        assert row["verdict"] == "diff"


def _chipdb(tmp_path, payload=b"chipdb-v1"):
    path = tmp_path / openflow.CHIPDB_BASENAME
    path.write_bytes(payload)
    return path


def test_batch_refuses_chipdb_change(tmp_path, monkeypatch):
    """A chipdb rebuilt mid-batch stops the batch; it never poisons the rows."""
    chipdb = _chipdb(tmp_path)
    monkeypatch.setenv("GOWIN_CHIPDB", str(chipdb))
    paths = batch.batch_paths("chipdb-001", base=str(tmp_path))

    executed = []

    def runner(run_id, design_dir, shape, sweep_value, level):
        executed.append(run_id)
        if len(executed) == 2:                 # a rebuild lands mid-batch
            chipdb.write_bytes(b"chipdb-v2-rebuilt")
        return {"run_id": run_id, "verdict": "ok", "shape": shape,
                "level": level,
                "chipdb_sha256": evidence.sha256(str(chipdb))}

    result = batch.run_batch("chipdb-001", "fake", str(tmp_path / "designs"),
                             sweep_points=4, level="E1", runner=runner,
                             fake=True, paths=paths, echo=False)

    assert result["chipdb_changed"] is True
    assert len(executed) == 2, executed        # run 3 is never started
    rows = batch.load_rows(paths["rows"])
    assert len(rows) == 1                      # the poisoned row is not kept
    assert {row["chipdb_sha256"] for row in rows} == {
        hashlib.sha256(b"chipdb-v1").hexdigest()}
    log = open(paths["log"]).read()
    assert "BATCH_CHIPDB " in log
    assert "BATCH_CHIPDB_CHANGED" in log
    assert log.strip().splitlines()[-1].startswith("BATCH_COMPLETE chipdb-001")
