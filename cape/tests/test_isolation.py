"""Guests defined while libvirt itself isolated their port still carry `<port isolated='yes'/>`,
which libvirt cannot apply without a privileged container; adoption strips it (the qemu hook
isolates the port instead, see port_isolation.py)."""

import pytest
from fixtures.engine_lab import Lab
from test_engine_adoption import DOMAIN_XML, REGISTRATION

from guest_engine.isolation import strip_port_isolation

ISOLATED = "<port isolated='yes'/>"
NIC = "<interface type='network'><source network='tt-guest'/></interface>"
ISOLATED_NIC = f"<interface type='network'><source network='tt-guest'/>{ISOLATED}</interface>"
SNAPSHOT_XML = (
    f"<domainsnapshot><name>tartarus-clean</name><domain>{ISOLATED_NIC}</domain></domainsnapshot>"
)
ISOLATED_DOMAIN_XML = DOMAIN_XML.replace("</interface>", f"{ISOLATED}</interface>")


def test_an_isolated_port_element_is_removed():
    assert strip_port_isolation(f"<domain>{ISOLATED_NIC}</domain>") == f"<domain>{NIC}</domain>"


def test_an_interface_without_the_element_is_left_as_it_is():
    xml = f"<domain>{NIC}</domain>"
    assert strip_port_isolation(xml) == xml


def test_a_port_element_in_either_quote_style_and_any_value_is_removed():
    xml = '<domain><interface type="network"><port isolated="no"/></interface></domain>'
    assert strip_port_isolation(xml) == '<domain><interface type="network"></interface></domain>'


def test_every_interface_is_handled_separately():
    xml = f"<domain>{ISOLATED_NIC}{NIC}{ISOLATED_NIC}</domain>"
    assert strip_port_isolation(xml) == f"<domain>{NIC}{NIC}{NIC}</domain>"


def test_a_port_element_outside_an_interface_is_left_alone():
    xml = f"<domain><devices>{ISOLATED}</devices></domain>"
    assert strip_port_isolation(xml) == xml


def test_a_domain_without_an_interface_is_unchanged():
    xml = "<domain><devices><disk/></devices></domain>"
    assert strip_port_isolation(xml) == xml


def test_the_domains_other_markup_survives_byte_for_byte():
    xml = (
        "<domain type='kvm' xmlns:qemu='http://libvirt.org/schemas/domain/qemu/1.0'>\n"
        f"  <devices>\n    {NIC}\n  </devices>\n  <qemu:commandline/>\n</domain>\n"
    )
    isolated = xml.replace("</interface>", f"{ISOLATED}</interface>")
    assert strip_port_isolation(isolated) == xml


def test_stripping_twice_is_the_same_as_once():
    once = strip_port_isolation(f"<domain>{ISOLATED_NIC}</domain>")
    assert strip_port_isolation(once) == once


# --- the migration at service start, on a fake libvirt -----------------------------------------


@pytest.fixture
def lab(tmp_path):
    return Lab(tmp_path)


def existing_guest(lab, domain_xml=ISOLATED_DOMAIN_XML):
    (lab.registration_dir / "win.conf").write_text(REGISTRATION)
    lab.host.define_elsewhere("win", domain_xml)
    return lab.restarted()


def test_an_existing_guests_domain_loses_the_element_at_start(lab):
    existing_guest(lab)

    assert "<port" not in lab.host.extra_domains["win"]
    assert lab.host.defines == ["win"]


def test_a_domain_that_never_had_the_element_is_not_redefined(lab):
    existing_guest(lab, DOMAIN_XML)

    assert lab.host.defines == []


def test_a_second_start_changes_nothing(lab):
    existing_guest(lab)
    lab.host.defines.clear()

    lab.restarted()

    assert lab.host.defines == []


def test_the_snapshots_copy_of_the_domain_loses_it_too_because_a_revert_restores_that_copy(lab):
    lab.host.snapshot_xmls["win"] = {"tartarus-clean": SNAPSHOT_XML}
    existing_guest(lab)

    assert "<port" not in lab.host.snapshot_xmls["win"]["tartarus-clean"]
    assert lab.host.redefined_snapshots == [("win", "tartarus-clean", True)]


def test_a_second_start_redefines_no_snapshot(lab):
    lab.host.snapshot_xmls["win"] = {"tartarus-clean": SNAPSHOT_XML}
    existing_guest(lab)
    lab.host.redefined_snapshots.clear()

    lab.restarted()

    assert lab.host.redefined_snapshots == []


def test_a_guest_without_a_network_interface_is_skipped(lab):
    existing_guest(lab, "<domain><name>win</name><devices/></domain>")

    assert lab.host.defines == []


def test_a_running_guest_is_left_alone_and_migrated_at_a_later_start(lab):
    lab.host.running.add("win")
    existing_guest(lab)
    assert lab.host.defines == []

    lab.host.running.clear()
    lab.restarted()

    assert lab.host.defines == ["win"]


def test_a_define_that_fails_does_not_stop_the_service_starting(lab):
    lab.host.define_fails = True

    engine = existing_guest(lab)

    assert [guest["name"] for guest in engine.guests()] == ["win"]
    assert ISOLATED in lab.host.extra_domains["win"]
