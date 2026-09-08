"""`S3`: nothing this device learns may quietly move another device.

Every builder these rows exercise is shared with `GW5A-25A` and `GW5AT-60B`,
and the cheapest complete statement of "unchanged" is the chipdb's sha256 --
one number that covers every bel, portmap, table and fuse offset at once.  The
two baselines are the values the previous phase closed on.

The builds themselves are not run here: they take a device install and about a
minute each, and the phase runs them once at close.  These read what that run
produced, and skip rather than pass when it has not run.
"""
import hashlib
import os

import pytest

DATASTORE = os.environ.get(
    "OPEN_TOOLCHAIN_DATASTORE",
    "/Users/alex/fine-line-data/open-toolchain-gw5ast")
REGRESS = os.path.join(DATASTORE, "p3")

#: The sha256 each device's chipdb closed the previous phase with.
BASELINES = {
    "GW5A-25A":
        "60f1ba427f964feab3048f5dca82dc075acf9374a456476919202626d1335564",
    "GW5AT-60B":
        "615d4d0349ba238c1760d9685c4893fb132e39ea253aed0af6021e5da20082d8",
}


def _built(device):
    path = os.path.join(REGRESS, f"regress-{device}.msgpack.xz")
    if not os.path.isfile(path):
        pytest.skip(f"no {device} regression build in {REGRESS}")
    return path


def _sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load(path):
    from apycula import chipdb
    return chipdb.load_chipdb(path)


def _bel_histogram(db):
    from collections import Counter
    return Counter(name
                   for row in range(db.rows) for col in range(db.cols)
                   for name in db[row, col].bels)


@pytest.mark.parametrize("device", sorted(BASELINES))
def test_regression_chipdb_byte_identical(device):
    assert _sha256(_built(device)) == BASELINES[device]


@pytest.mark.parametrize("device", sorted(BASELINES))
def test_regression_bel_histogram_unchanged(device):
    """Named separately from the sha so a failure says *what* moved."""
    histogram = _bel_histogram(_load(_built(device)))
    assert histogram["OSER16"] == 0 and histogram["IDES16"] == 0, (
        "the 16-bit gearbox extent is measured on the GW5AST-138C only")


def test_regression_25a_diff_io_types_unchanged():
    """`TLVDS_IOBUF` was restored for one device, not for the family."""
    assert "TLVDS_IOBUF" in _load(_built("GW5A-25A")).diff_io_types


def test_regression_iologicb_fuse_offset_is_not_displaced_off_138c():
    """The `B`-half displacement is a 138C measurement and stays there."""
    db = _load(_built("GW5A-25A"))
    displaced = [(row, col)
                 for row in range(db.rows) for col in range(db.cols)
                 if (db[row, col].bels.get("IOLOGICB") is not None
                     and db[row, col].bels["IOLOGICB"].fuse_cell_offset)]
    assert displaced == []
