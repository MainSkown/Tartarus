"""Guests on the shared bridge must not reach each other: the isolated port flag, and the
migration that gives it to guests defined before the template carried it (M9 task 3.0)."""

import pytest
from fixtures.engine_lab import Lab
from test_engine_adoption import DOMAIN_XML, REGISTRATION

from guest_engine.isolation import isolate_interfaces

ISOLATED = "<port isolated='yes'/>"
NIC = "<interface type='network'><source network='tt-guest'/></interface>"
SNAPSHOT_XML = f"<domainsnapshot><name>tartarus-clean</name><domain>{NIC}</domain></domainsnapshot>"


def test_an_interface_without_the_flag_gets_it():
    assert isolate_interfaces(f"<domain>{NIC}</domain>") == (
        f"<domain><interface type='network'><source network='tt-guest'/>{ISOLATED}"
        "</interface></domain>"
    )


def test_an_isolated_interface_is_left_as_it_is():
    xml = f"<domain><interface type='network'>{ISOLATED}</interface></domain>"
    assert isolate_interfaces(xml) == xml


def test_a_port_that_is_explicitly_not_isolated_is_switched_on():
    xml = "<domain><interface type='network'><port isolated='no'/></interface></domain>"
    assert (
        isolate_interfaces(xml)
        == f"<domain><interface type='network'>{ISOLATED}</interface></domain>"
    )


def test_every_interface_is_handled_separately():
    xml = f"<domain>{NIC}<interface type='network'>{ISOLATED}</interface>{NIC}</domain>"
    assert isolate_interfaces(xml).count(ISOLATED) == 3


def test_a_domain_without_an_interface_is_unchanged():
    xml = "<domain><devices><disk/></devices></domain>"
    assert isolate_interfaces(xml) == xml


def test_the_domains_other_markup_survives_byte_for_byte():
    xml = (
        "<domain type='kvm' xmlns:qemu='http://libvirt.org/schemas/domain/qemu/1.0'>\n"
        f"  <devices>\n    {NIC}\n  </devices>\n  <qemu:commandline/>\n</domain>\n"
    )
    assert isolate_interfaces(xml).replace(ISOLATED, "") == xml


def test_isolating_twice_is_the_same_as_once():
    once = isolate_interfaces(f"<domain>{NIC}</domain>")
    assert isolate_interfaces(once) == once


# --- the migration at service start, on a fake libvirt -----------------------------------------


@pytest.fixture
def lab(tmp_path):
    return Lab(tmp_path)


def existing_guest(lab, domain_xml=DOMAIN_XML):
    (lab.registration_dir / "win.conf").write_text(REGISTRATION)
    lab.host.define_elsewhere("win", domain_xml)
    return lab.restarted()


def test_an_existing_guests_domain_gets_the_flag_at_start(lab):
    existing_guest(lab)

    assert ISOLATED in lab.host.extra_domains["win"]
    assert lab.host.defines == ["win"]


def test_a_second_start_changes_nothing(lab):
    existing_guest(lab)
    lab.host.defines.clear()

    lab.restarted()

    assert lab.host.defines == []
    assert lab.host.extra_domains["win"].count(ISOLATED) == 1


def test_the_snapshots_copy_of_the_domain_gets_it_too_because_a_revert_restores_that_copy(lab):
    lab.host.snapshot_xmls["win"] = {"tartarus-clean": SNAPSHOT_XML}
    existing_guest(lab)

    assert ISOLATED in lab.host.snapshot_xmls["win"]["tartarus-clean"]
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
    assert ISOLATED not in lab.host.extra_domains["win"]
