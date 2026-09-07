"""The `AE350_RAM` vehicle as a `ShapeSpec`.

The row's question is presence, not parameters (measured: 26 ports, 0
parameters), so the vehicle's job is to isolate one variable: an
`AE350_SOC` design the vendor already builds, plus one `AE350_RAM`.  These
tests hold that isolation in place -- the `"soc"` point must stay the
`AE350_SOC` vehicle byte for byte apart from the block being added.
"""
import pytest

from fuzz.gw5ast138c.harness import gen
from fuzz.gw5ast138c.shapes import ae350_ram


def _render(point):
    """The vehicle for one companion point, or a skip when no chipdb is built.

    `ae350_soc` reads its port map out of the chipdb, so a checkout that has
    not built one cannot render either vehicle. That is a missing artefact,
    not a failing property.
    """
    try:
        return ae350_ram.rtl(ae350_ram.SPEC, point)
    except Exception as exc:                       # noqa: BLE001 - reported
        if "msgpack" in str(exc) or "extra_func" in str(exc):
            pytest.skip(f"no built chipdb to read the AE350 port map: {exc}")
        raise


def _instance_ports(text, primitive, instance):
    head = text.index(f"{primitive} {instance} (")
    body = text[head:text.index("    );", head)]
    return dict(
        line.strip().lstrip(".").rstrip(",").split("(", 1)
        for line in body.splitlines()[1:] if line.strip().startswith("."))


def test_ae350_ram_soc_point_is_the_soc_vehicle_with_one_block_added():
    """Only the header, `dout` and additions may differ from the `AE350_SOC` vehicle."""
    from fuzz.gw5ast138c.shapes import ae350_soc
    soc = _render(ae350_ram.COMPANION_SOC)
    base = ae350_soc.rtl(ae350_soc.SPEC, None).splitlines()
    removed = [line for line in base if line not in soc.splitlines()]
    assert removed == base[:3] + ["    assign dout = cap[NO-1];"]


def test_ae350_ram_instance_carries_every_port_the_vendor_declares():
    ports = _instance_ports(_render(ae350_ram.COMPANION_SOC),
                            "AE350_RAM", ae350_ram.RAM_INSTANCE)
    declared = [name for name, _ in
                ae350_ram.AE350_RAM_INPUTS + ae350_ram.AE350_RAM_OUTPUTS]
    assert sorted(ports) == sorted(declared)


def test_ae350_ram_shares_every_input_net_except_the_slave_select():
    """MUG1031: two AHB slaves on one master bus differ only in `HSEL`."""
    text = _render(ae350_ram.COMPANION_SOC)
    ram = _instance_ports(text, "AE350_RAM", ae350_ram.RAM_INSTANCE)
    soc = _instance_ports(text, "AE350_SOC", "u_ae350")
    shared = [name for name, _ in ae350_ram.AE350_RAM_INPUTS
              if name != ae350_ram.RAM_SELECT_PORT]
    assert [ram[name] for name in shared] == [soc[name] for name in shared]
    assert ram[ae350_ram.RAM_SELECT_PORT] != soc[ae350_ram.RAM_SELECT_PORT]


def test_ae350_ram_solo_point_instantiates_no_ae350_soc():
    solo = _render(ae350_ram.COMPANION_SOLO)
    assert "AE350_RAM " + ae350_ram.RAM_INSTANCE in solo
    assert "AE350_SOC u_ae350 " not in solo


def test_ae350_ram_pins_two_witness_flops_clear_of_the_soc_sites():
    """`E1` needs one net into the block and one out, at sites both flows read."""
    for point in (ae350_ram.COMPANION_SOC, ae350_ram.COMPANION_SOLO):
        sites = ae350_ram.ins_loc(ae350_ram.SPEC, point)
        witnesses = [sites[name] for name, _cls, _half in
                     (ae350_ram.RAM_PINNED_DRIVER, ae350_ram.RAM_PINNED_CAPTURE)]
        others = [site for name, site in sites.items()
                  if name not in {ae350_ram.RAM_PINNED_DRIVER[0],
                                  ae350_ram.RAM_PINNED_CAPTURE[0]}]
        assert len(set(witnesses)) == 2
        assert not set(witnesses) & set(others)
        for site in witnesses:
            assert gen.open_flow_reads_ins_loc(site)
