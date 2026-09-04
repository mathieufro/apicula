"""`P0.T21` -- the open flow: yosys -> nextpnr-himbaechel -> gowin_pack.

The command-shape and provenance tests are pure (no tool runs). The smoke test
runs the three real tools on the `smoke` design directory and is skipped, with
a named reason, when a tool or the design is absent.
"""
import os
import shutil

import pytest

from fuzz.gw5ast138c.harness import openflow


# --------------------------------------------------------------------------
# Command shapes -- the two things that are easy to get wrong and fatal
# --------------------------------------------------------------------------

def test_openflow_command_shapes():
    nextpnr_cmd = openflow.nextpnr_command(
        "/opt/nextpnr-himbaechel",
        "/data/chipdb/std/chipdb-GW5AST-138C.bin",
    )
    rendered = " ".join(nextpnr_cmd)
    # There is exactly one database and it is named after the *device* (F47).
    assert rendered.count("chipdb-GW5AST-138C.bin") == 1
    assert rendered.count("chipdb-gw5a.bin") == 0
    assert "--device GW5AST-LV138PG484AC1/I0" in rendered
    assert "--vopt cst=top.cst" in rendered
    assert "--timing-allow-fail" in rendered

    pack_cmd = openflow.pack_command(["/opt/gowin_pack"])
    packed = " ".join(pack_cmd)
    # The packer namespace, never the gw_sh Tcl namespace.
    assert packed.count("--cpu_as_gpio") == 1
    assert packed.count("-use_cpu_as_gpio") == 0
    assert "-d GW5AST-138C" in packed

    yosys_cmd = openflow.yosys_command("/opt/yosys")
    assert "synth_gowin -family gw5a -setundef -json top.json" in yosys_cmd[-1]


def test_openflow_rejects_a_family_named_chipdb(tmp_path):
    bogus = tmp_path / "chipdb-gw5a.bin"
    bogus.write_bytes(b"\0")
    with pytest.raises(openflow.OpenFlowError):
        openflow.resolve_chipdb(str(bogus))


def test_openflow_top_module_is_a_shape_parameter():
    rendered = " ".join(openflow.nextpnr_command(
        "npnr", "/x/chipdb-GW5AST-138C.bin", top_module="attosoc"))
    assert "--top attosoc" in rendered


# --------------------------------------------------------------------------
# Provenance
# --------------------------------------------------------------------------

def _tool_or_skip():
    try:
        yosys = openflow.resolve_yosys()
        nextpnr = openflow.resolve_nextpnr()
        chipdb = openflow.resolve_chipdb()
    except openflow.OpenFlowError as exc:
        pytest.skip(str(exc))
    return yosys, nextpnr, chipdb


def test_openflow_records_provenance():
    yosys, nextpnr, chipdb = _tool_or_skip()
    prov = openflow.provenance(yosys, nextpnr, chipdb, nextpnr_log="")
    assert set(prov) == set(openflow.PROVENANCE_KEYS)
    assert len(prov) == 5
    assert prov["yosys_version"].startswith("Yosys")
    assert len(prov["chipdb_sha256"]) == 64
    assert len(prov["apicula_sha"]) == 40
    assert len(prov["nextpnr_sha"]) == 40
    assert prov["timing_allow_fail_needed"] is False

    failing = ("Info: Max frequency for clock 'clk': 12.00 MHz "
               "(FAIL at 50.00 MHz)\n")
    assert openflow.timing_allow_fail_needed(failing) is True
    passing = ("Info: Max frequency for clock 'clk': 300.00 MHz "
               "(PASS at 50.00 MHz)\n")
    assert openflow.timing_allow_fail_needed(passing) is False
    assert openflow.parse_fmax(passing)[0]["mhz"] == 300.0

    line = openflow.provenance_line(prov)
    assert line.startswith("PROVENANCE ")
    parsed = openflow.parse_provenance_line(line)
    assert len(parsed) == 5
    assert set(parsed) == set(openflow.PROVENANCE_KEYS)


# --------------------------------------------------------------------------
# The real flow
# --------------------------------------------------------------------------

def test_openflow_smoke_produces_fs(tmp_path):
    yosys, nextpnr, chipdb = _tool_or_skip()
    for name in ("top.v", "top.cst"):
        src = os.path.join(openflow.SMOKE_DIR, name)
        if not os.path.isfile(src):
            pytest.skip(f"smoke design absent: no {src}")
        shutil.copyfile(src, tmp_path / name)

    result = openflow.run_openflow(str(tmp_path), yosys=yosys,
                                   nextpnr=nextpnr, chipdb=chipdb)
    assert result["returncodes"] == {"yosys": 0, "nextpnr": 0, "gowin_pack": 0}
    assert result["ok"] is True
    assert result["fs_path"] is not None
    assert result["fs_bytes"] > 0

    from apycula import bslib
    loaded = bslib.read_bitstream(result["fs_path"])
    assert loaded is not None

    assert len(result["provenance"]) == 5
    assert result["fmax"], "nextpnr reported no Fmax line"
